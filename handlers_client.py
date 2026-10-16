"""Mijoz bilan shaxsiy chat: AI suhbat, rasmlar, oldindan ko'rish, to'lov silkasi, chek."""
import asyncio
import json
import logging
from collections import defaultdict
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.filters import CommandStart
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, Message, ReplyKeyboardMarkup)

import ai
import db
import publisher
from config import (AD_PRICE, ADMIN_CONTACT, CHANNEL_TITLE, MAX_PHOTOS, PAYMENT_GROUP_ID,
                    PAYMENT_TTL_HOURS, UNIQUE_AMOUNT)
from formatting import fmt_sum
from payments import payme_link, pick_amount
from services import to_group

log = logging.getLogger(__name__)
router = Router()
router.message.filter(F.chat.type == "private")

BTN_NEW = "🆕 Yangi e'lon"
BTN_MY = "📋 Mening e'lonim"
BTN_HELP = "ℹ️ Narx va qoidalar"
BTN_CANCEL = "❌ Bekor qilish"

MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=BTN_NEW), KeyboardButton(text=BTN_MY)],
              [KeyboardButton(text=BTN_HELP), KeyboardButton(text=BTN_CANCEL)]],
    resize_keyboard=True,
    input_field_placeholder="Nima sotmoqchisiz? Yozing yoki rasm yuboring…",
)

REQUIRED = {"category": "kategoriya", "title": "sarlavha", "price": "narx",
            "location": "manzil", "phone": "telefon"}

RULES = (
    f"📌 <b>{escape(CHANNEL_TITLE)}</b> — e'lon berish qoidalari\n\n"
    f"💰 Narxi: <b>{fmt_sum(AD_PRICE)} so'm</b> — 1 ta e'lon, kanalga 1 marta joylanadi.\n"
    "💳 To'lov: faqat Payme orqali. To'lov tushishi bilan e'lon avtomatik joylanadi.\n\n"
    "✅ Qabul qilinadi: uy-joy, avtomobil, texnika, telefon, mebel, qurilish mollari, kiyim, chorva va boshqa "
    "<b>sotiladigan buyumlar</b>.\n"
    "⛔️ Qabul qilinmaydi: Telegram kanal/guruh/bot reklamalari, yangilik kanallari, xizmat va kurs reklamasi, "
    "kredit, stavka, 18+ va taqiqlangan narsalar.\n\n"
    "📸 3-4 ta sifatli rasm yuboring — albom qilib chiroyli joylab beramiz."
)

_ai_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
_photo_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
_album_timers: dict[int, asyncio.Task] = {}
_album_captions: dict[int, list[str]] = defaultdict(list)


def missing_fields(order: dict) -> list[str]:
    miss = [name for key, name in REQUIRED.items() if not order["data"].get(key)]
    if not order["photos"]:
        miss.append("kamida 1 ta rasm")
    return miss


# ---------------- buyruqlar va tugmalar ----------------
@router.message(CommandStart())
async def cmd_start(m: Message):
    await db.upsert_user(m.from_user.id, m.from_user.username, m.from_user.full_name)
    await m.answer(
        f"Assalomu alaykum, {escape(m.from_user.first_name or '')}! 👋\n"
        f"Men <b>{escape(CHANNEL_TITLE)}</b> kanalining e'lon yordamchisiman.\n\n"
        f"Nima sotmoqchisiz? Shunchaki yozing — masalan: <i>«Cobalt 2021 sotaman»</i> yoki "
        f"<i>«3 xonali kvartira sotiladi»</i>. Qolganini o'zim so'rab olaman.\n\n"
        f"💰 E'lon narxi: <b>{fmt_sum(AD_PRICE)} so'm</b>",
        reply_markup=MAIN_KB,
    )


@router.message(F.text == BTN_HELP)
async def btn_help(m: Message):
    extra = f"\n\n👤 Admin: {escape(ADMIN_CONTACT)}" if ADMIN_CONTACT else ""
    await m.answer(RULES + extra, reply_markup=MAIN_KB)


@router.message(F.text == BTN_NEW)
async def btn_new(m: Message):
    uid = m.from_user.id
    await db.upsert_user(uid, m.from_user.username, m.from_user.full_name)
    o = await db.active_order(uid)
    if o and o["status"] == "awaiting_payment":
        await m.answer(f"Sizda #{o['id']} e'lon to'lovni kutmoqda ({fmt_sum(o['amount'])} so'm). "
                       f"Avval uni to'lang yoki «{BTN_CANCEL}» ni bosing.")
        return
    if o and o["status"] == "paid":
        await m.answer("Oldingi e'loningiz hozir joylanmoqda, biroz kuting 🙏")
        return
    if o:
        await db.set_status(o["id"], "cancelled")
    await db.save_history(uid, [])
    await db.get_or_create_draft(uid)
    await m.answer("Yangi e'lon boshladik ✍️\nNima sotmoqchisiz? Qisqacha yozing va 3-4 ta rasm yuboring.")


@router.message(F.text == BTN_CANCEL)
async def btn_cancel(m: Message):
    uid = m.from_user.id
    o = await db.active_order(uid)
    if not o:
        await m.answer("Faol e'loningiz yo'q.", reply_markup=MAIN_KB)
        return
    if o["status"] == "paid":
        await m.answer("To'lov qabul qilingan, e'lon joylanmoqda — endi bekor qilib bo'lmaydi.")
        return
    await db.set_status(o["id"], "cancelled")
    await db.save_history(uid, [])
    await m.answer("E'lon bekor qilindi. Yangisini boshlash uchun «🆕 Yangi e'lon» ni bosing.", reply_markup=MAIN_KB)


@router.message(F.text == BTN_MY)
async def btn_my(m: Message, bot: Bot):
    o = await db.active_order(m.from_user.id)
    if not o:
        await m.answer("Faol e'loningiz yo'q. «🆕 Yangi e'lon» ni bosing.")
        return
    if o["status"] == "awaiting_payment":
        await send_payment_message(bot, m.chat.id, o)
        return
    miss = missing_fields(o)
    if miss:
        await m.answer("E'loningiz tayyorlanmoqda. Yetishmayapti: " + ", ".join(miss))
    else:
        await send_preview(bot, m.chat.id, o)


# ---------------- rasmlar ----------------
@router.message(F.photo)
async def on_photo(m: Message, bot: Bot):
    uid = m.from_user.id
    await db.upsert_user(uid, m.from_user.username, m.from_user.full_name)
    o = await db.active_order(uid)

    if o and o["status"] == "awaiting_payment":
        await forward_receipt(bot, m, o)
        return
    if o and o["status"] == "paid":
        await m.answer("To'lovingiz qabul qilingan, e'lon joylanmoqda 🙏")
        return

    file_id = m.photo[-1].file_id  # eng katta o'lcham
    async with _photo_locks[uid]:
        o = await db.get_or_create_draft(uid)
        photos = o["photos"]
        if len(photos) >= MAX_PHOTOS:
            if m.media_group_id is None or uid not in _album_timers:
                await m.answer(f"Ko'pi bilan {MAX_PHOTOS} ta rasm qabul qilinadi.")
            return
        photos.append(file_id)
        await db.set_photos(o["id"], photos)
    if m.caption:
        _album_captions[uid].append(m.caption)

    # Albom bir nechta alohida xabar bo'lib keladi — hammasi kelgach bitta javob beramiz
    if t := _album_timers.get(uid):
        t.cancel()
    _album_timers[uid] = asyncio.create_task(_flush_photos(bot, uid, m.chat.id))


async def _flush_photos(bot: Bot, uid: int, chat_id: int):
    try:
        await asyncio.sleep(2)
    except asyncio.CancelledError:
        return
    _album_timers.pop(uid, None)
    captions = _album_captions.pop(uid, [])
    o = await db.active_order(uid)
    if not o:
        return
    note = f"[Tizim: mijoz rasm yubordi. Jami rasmlar: {len(o['photos'])} ta, maksimum {MAX_PHOTOS}.]"
    if captions:
        note += "\nRasm izohi: " + " ".join(captions)
    await run_ai(bot, uid, chat_id, note)


# ---------------- matn -> AI ----------------
@router.message(F.text)
async def on_text(m: Message, bot: Bot):
    await db.upsert_user(m.from_user.id, m.from_user.username, m.from_user.full_name)
    await run_ai(bot, m.from_user.id, m.chat.id, m.text[:2000])


@router.message()
async def on_other(m: Message):
    await m.answer("Iltimos, ma'lumotni matn bilan yozing va rasmlarni rasm (photo) ko'rinishida yuboring 📸")


async def run_ai(bot: Bot, uid: int, chat_id: int, text: str):
    async with _ai_locks[uid]:
        await db.get_or_create_draft(uid)
        history = await db.get_history(uid)
        want_preview = False

        async def state() -> str:
            o = await db.active_order(uid)
            if not o:
                return "Faol e'lon yo'q."
            lines = [f"Buyurtma #{o['id']}, holati: {o['status']}",
                     "Qoralama: " + json.dumps(o["data"], ensure_ascii=False),
                     f"Rasmlar soni: {len(o['photos'])}"]
            miss = missing_fields(o)
            lines.append("Yetishmayapti: " + (", ".join(miss) if miss else "hech narsa — show_preview chaqirsa bo'ladi"))
            if o["status"] == "awaiting_payment":
                lines.append(f"Mijoz oldindan ko'rishni tasdiqlagan va {fmt_sum(o['amount'])} so'm to'lashi kerak. "
                             "Qoralamani endi o'zgartirib bo'lmaydi. To'lov tushgach e'lon avtomatik joylanadi. "
                             "To'lagan bo'lsa-yu joylanmagan bo'lsa — to'lov chekining skrinshotini shu chatga rasm qilib yuborishini ayt. "
                             f"Payme silkasini qayta olish uchun «{BTN_MY}» tugmasi.")
            return "\n".join(lines)

        async def on_tool(name: str, args: dict) -> str:
            nonlocal want_preview
            o = await db.active_order(uid)
            if not o or o["status"] != "draft":
                return "Hozir qoralamani o'zgartirib bo'lmaydi (to'lov bosqichida yoki e'lon yo'q)."
            if name == "update_ad":
                await db.update_data(o["id"], args)
                o = await db.get_order(o["id"])
                miss = missing_fields(o)
                return "Saqlandi. " + ("Yetishmayapti: " + ", ".join(miss) if miss else "Hammasi to'liq.")
            if name == "show_preview":
                miss = missing_fields(o)
                if miss:
                    return "Hali ko'rsatib bo'lmaydi. Yetishmayapti: " + ", ".join(miss)
                want_preview = True
                return ("Bot javobingdan keyin tayyor e'lonni va tasdiqlash tugmalarini yuboradi. "
                        "Mijozga qisqa qilib: tekshirib, to'g'ri bo'lsa tugmani bosishini ayt.")
            if name == "reset_ad":
                await db.set_status(o["id"], "cancelled")
                await db.get_or_create_draft(uid)
                return "Eski qoralama o'chirildi, yangi bo'sh qoralama ochildi."
            return "Noma'lum asbob."

        await bot.send_chat_action(chat_id, ChatAction.TYPING)
        try:
            reply = await ai.agent_turn(history, text, state, on_tool)
        except Exception:
            log.exception("AI xatosi")
            await bot.send_message(chat_id, "Kechirasiz, hozir texnik nosozlik bor. Bir daqiqadan keyin qayta yozing 🙏",
                                   parse_mode=None)
            return

        history += [{"role": "user", "content": text},
                    {"role": "assistant", "content": reply or "(tayyor e'lon ko'rsatildi)"}]
        await db.save_history(uid, history)

        if reply:
            await bot.send_message(chat_id, reply, parse_mode=None, reply_markup=MAIN_KB)
        if want_preview:
            o = await db.active_order(uid)
            if o:
                await send_preview(bot, chat_id, o)


# ---------------- oldindan ko'rish va to'lov ----------------
async def send_preview(bot: Bot, chat_id: int, order: dict):
    await bot.send_message(chat_id, "👇 E'loningiz kanalda shunday ko'rinadi:")
    await publisher.send_ad(bot, chat_id, order)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Hammasi to'g'ri — to'lovga o'tish", callback_data=f"ok:{order['id']}")],
        [InlineKeyboardButton(text="✏️ O'zgartirish", callback_data=f"edit:{order['id']}")],
    ])
    await bot.send_message(chat_id, f"Tekshirib chiqing. E'lon narxi: <b>{fmt_sum(AD_PRICE)} so'm</b>.", reply_markup=kb)


@router.callback_query(F.data.startswith("ok:"))
async def cb_ok(cb: CallbackQuery, bot: Bot):
    order_id = int(cb.data.split(":")[1])
    o = await db.get_order(order_id)
    if not o or o["user_id"] != cb.from_user.id:
        await cb.answer("Bu e'lon topilmadi", show_alert=True)
        return
    if o["status"] == "awaiting_payment":
        await cb.answer()
        await send_payment_message(bot, cb.from_user.id, o)
        return
    if o["status"] != "draft":
        await cb.answer("Bu e'lon allaqachon yopilgan", show_alert=True)
        return
    if miss := missing_fields(o):
        await cb.answer("Yetishmayapti: " + ", ".join(miss), show_alert=True)
        return

    amount = pick_amount(await db.reserved_amounts())
    await db.request_payment(order_id, amount)
    o = await db.get_order(order_id)
    await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await send_payment_message(bot, cb.from_user.id, o)
    user = cb.from_user
    await to_group(bot, f"🆕 #{order_id} to'lov kutilmoqda: <b>{fmt_sum(amount)} so'm</b>\n"
                        f"👤 <a href=\"tg://user?id={user.id}\">{escape(user.full_name)}</a>"
                        + (f" (@{user.username})" if user.username else "")
                        + f"\n📦 {escape(o['data'].get('title', ''))}")


async def send_payment_message(bot: Bot, chat_id: int, o: dict):
    link = payme_link(o["amount"], o["id"])
    exact = ("❗️ <b>Aynan shu summani</b> to'lang (so'mi bilan) — tizim to'lovingizni summa orqali avtomatik taniydi.\n"
             if UNIQUE_AMOUNT else "")
    text = (f"💳 <b>To'lov</b> — e'lon #{o['id']}\n\n"
            f"Summa: <b>{fmt_sum(o['amount'])} so'm</b>\n{exact}\n"
            "To'lov tushishi bilan e'loningiz avtomatik kanalga joylanadi (odatda 1-2 daqiqa).\n"
            "10 daqiqada joylanmasa — to'lov chekining skrinshotini shu yerga rasm qilib yuboring.\n\n"
            f"⏳ To'lov {PAYMENT_TTL_HOURS} soat ichida qilinishi kerak.")
    rows = []
    if link:
        rows.append([InlineKeyboardButton(text="💳 Payme orqali to'lash", url=link)])
    else:
        text += "\n\n⚠️ To'lov silkasi sozlanmagan, admin bilan bog'laning."
    rows.append([InlineKeyboardButton(text="❌ E'lonni bekor qilish", callback_data=f"cancel:{o['id']}")])
    await bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("edit:"))
async def cb_edit(cb: CallbackQuery):
    await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await cb.message.answer("Nimani o'zgartiramiz? Yozing (masalan: «narxi 11 800 $» yoki «rasmlarni almashtiraman»).")


@router.callback_query(F.data.startswith("cancel:"))
async def cb_cancel(cb: CallbackQuery):
    order_id = int(cb.data.split(":")[1])
    o = await db.get_order(order_id)
    if not o or o["user_id"] != cb.from_user.id or o["status"] not in ("draft", "awaiting_payment"):
        await cb.answer("Bu e'lonni bekor qilib bo'lmaydi", show_alert=True)
        return
    await db.set_status(order_id, "cancelled")
    await db.save_history(cb.from_user.id, [])
    await cb.answer("Bekor qilindi")
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await cb.message.answer("E'lon bekor qilindi. Agar to'lov qilgan bo'lsangiz, admin bilan bog'laning.",
                            reply_markup=MAIN_KB)


# ---------------- chek (qo'lda tekshirish) ----------------
async def forward_receipt(bot: Bot, m: Message, o: dict):
    user = m.from_user
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"adm_ok:{o['id']}"),
        InlineKeyboardButton(text="❌ Rad etish", callback_data=f"adm_no:{o['id']}"),
    ]])
    caption = (f"🧾 <b>Chek</b> — e'lon #{o['id']}\n"
               f"Kutilgan summa: <b>{fmt_sum(o['amount'])} so'm</b>\n"
               f"👤 <a href=\"tg://user?id={user.id}\">{escape(user.full_name)}</a>"
               + (f" (@{user.username})" if user.username else ""))
    await bot.send_photo(PAYMENT_GROUP_ID, m.photo[-1].file_id, caption=caption, reply_markup=kb)
    await m.answer("🧾 Chekingiz adminga yuborildi. Tekshirilgach e'loningiz joylanadi.")
