"""Mijoz bilan yozishma: AI suhbat, rasmlar, oldindan ko'rish, to'lov silkasi, chek.

Ikki rejimda ishlaydi:
  • Business lichka — mijoz sizning shaxsiy akkauntingizga yozadi, bot siz nomingizdan javob beradi.
    Tugmalar ishlatilmaydi: mijoz "ha" deb tasdiqlaydi, Payme silkasi matnda yuboriladi.
  • To'g'ridan-to'g'ri bot chati — /start, pastki menyu va inline tugmalar bilan.
"""
import asyncio
import json
import logging
import time
from collections import defaultdict
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.filters import CommandStart
from aiogram.types import (BusinessConnection, CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, KeyboardButton, Message, ReplyKeyboardMarkup)

import ai
import db
import publisher
from config import (AD_PRICE, ADMIN_CONTACT, BUSINESS_PAUSE_HOURS, CHANNEL_TITLE, CLICK_ENABLED,
                    CLICK_SEARCH_NAME, MAX_PHOTOS,
                    PAYME_SEARCH_NAME, PAYMENT_GROUP_ID, PAYMENT_TTL_HOURS, UNIQUE_AMOUNT)
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


async def remember(m: Message) -> None:
    """Mijozni saqlaydi va u qayerdan yozganini (business lichka yoki bot) eslab qoladi."""
    u = m.from_user
    await db.upsert_user(u.id, u.username, u.full_name, m.business_connection_id)


async def reply_kb(uid: int):
    """Pastki menyu faqat bot chatida; business lichkada klaviatura yo'q."""
    return None if await db.bc_id(uid) else MAIN_KB


# ================= Business lichka: kim yozganini ajratish =================
async def business_gate(m: Message) -> bool:
    """True — bot bu xabarga javob berishi kerak."""
    if m.sender_business_bot:
        return False  # botning o'zi siz nomingizdan yuborgan xabar
    client_id = m.chat.id
    if m.from_user and m.from_user.id != client_id:
        # Bu xabarni SIZ (akkaunt egasi) o'zingiz yozdingiz
        cmd = (m.text or "").strip().lower()
        if cmd == "/ai":
            await db.set_pause(client_id, 0)  # botni shu chatda qayta yoqish
        else:
            await db.set_pause(client_id, int(time.time()) + BUSINESS_PAUSE_HOURS * 3600)
        return False
    return not await db.is_paused(client_id)


@router.business_connection()
async def on_business_connection(bc: BusinessConnection, bot: Bot):
    if bc.is_enabled:
        can = getattr(getattr(bc, "rights", None), "can_reply", None)
        if can is None:
            can = getattr(bc, "can_reply", True)
        warn = "" if can else "\n⚠️ Botga «javob berish» huquqi berilmagan — Telegram Business → Chatbots da yoqing!"
        await to_group(bot, f"🔗 Business akkaunt ulandi: {escape(bc.user.full_name)}{warn}")
    else:
        await to_group(bot, f"🔌 Business akkaunt uzildi: {escape(bc.user.full_name)}")


@router.business_message(F.photo)
async def biz_photo(m: Message, bot: Bot):
    if await business_gate(m):
        await on_photo(m, bot)


@router.business_message(F.text)
async def biz_text(m: Message, bot: Bot):
    if await business_gate(m):
        await on_text(m, bot)


@router.business_message()
async def biz_other(m: Message, bot: Bot):
    if await business_gate(m):
        await on_other(m, bot)


# ================= Bot chati: buyruqlar va tugmalar =================
@router.message(CommandStart())
async def cmd_start(m: Message):
    await remember(m)
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
    await remember(m)
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
    await remember(m)
    await m.answer(await cancel_active(m.from_user.id), reply_markup=MAIN_KB)


@router.message(F.text == BTN_MY)
async def btn_my(m: Message, bot: Bot):
    await remember(m)
    uid = m.from_user.id
    o = await db.active_order(uid)
    if not o:
        await m.answer("Faol e'loningiz yo'q. «🆕 Yangi e'lon» ni bosing.")
        return
    if o["status"] == "awaiting_payment":
        await send_payment_message(bot, uid, o)
        return
    miss = missing_fields(o)
    if miss:
        await m.answer("E'loningiz tayyorlanmoqda. Yetishmayapti: " + ", ".join(miss))
    else:
        await send_preview(bot, uid, o)


async def cancel_active(uid: int) -> str:
    o = await db.active_order(uid)
    if not o:
        return "Faol e'loningiz yo'q."
    if o["status"] == "paid":
        return "To'lov qabul qilingan, e'lon joylanmoqda — endi bekor qilib bo'lmaydi."
    await db.set_status(o["id"], "cancelled")
    await db.save_history(uid, [])
    return "E'lon bekor qilindi. Yangi e'lon bermoqchi bo'lsangiz, yozing."


# ================= Rasmlar (ikkala rejim) =================
@router.message(F.photo)
async def on_photo(m: Message, bot: Bot):
    uid = m.from_user.id
    await remember(m)
    kw = await db.send_kw(uid)
    o = await db.active_order(uid)

    if o and o["status"] == "awaiting_payment":
        await forward_receipt(bot, m, o)
        return
    if o and o["status"] == "paid":
        await bot.send_message(uid, "To'lovingiz qabul qilingan, e'lon joylanmoqda 🙏", **kw)
        return

    file_id = m.photo[-1].file_id  # eng katta o'lcham
    async with _photo_locks[uid]:
        o = await db.get_or_create_draft(uid)
        photos = o["photos"]
        if len(photos) >= MAX_PHOTOS:
            if m.media_group_id is None or uid not in _album_timers:
                await bot.send_message(uid, f"Ko'pi bilan {MAX_PHOTOS} ta rasm qabul qilinadi.", **kw)
            return
        photos.append(file_id)
        await db.set_photos(o["id"], photos)
        if o["data"].get("_preview"):
            await db.set_preview_shown(o["id"], False)  # rasm o'zgardi — qayta ko'rsatish kerak
    if m.caption:
        _album_captions[uid].append(m.caption)

    # Albom bir nechta alohida xabar bo'lib keladi — hammasi kelgach bitta javob beramiz
    if t := _album_timers.get(uid):
        t.cancel()
    _album_timers[uid] = asyncio.create_task(_flush_photos(bot, uid))


async def _flush_photos(bot: Bot, uid: int):
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
    await run_ai(bot, uid, note)


# ================= Matn -> AI (ikkala rejim) =================
@router.message(F.text)
async def on_text(m: Message, bot: Bot):
    await remember(m)
    await run_ai(bot, m.from_user.id, m.text[:2000])


@router.message()
async def on_other(m: Message, bot: Bot):
    await remember(m)
    if m.video or m.video_note or m.voice or m.document or m.sticker or m.audio:
        await bot.send_message(m.from_user.id,
                               "Iltimos, ma'lumotni matn bilan yozing va rasmlarni rasm (photo) ko'rinishida yuboring 📸",
                               **await db.send_kw(m.from_user.id))


async def run_ai(bot: Bot, uid: int, text: str):
    async with _ai_locks[uid]:
        kw = await db.send_kw(uid)
        business = bool(kw)
        await db.get_or_create_draft(uid)
        history = await db.get_history(uid)
        want_preview = False
        want_payment = False

        async def state() -> str:
            o = await db.active_order(uid)
            if not o:
                return "Faol e'lon yo'q."
            data = {k: v for k, v in o["data"].items() if not k.startswith("_")}
            lines = [
                "Kanal: " + ("Telegram lichka (siz kanal egasi nomidan yozyapsiz, tugmalar YO'Q — "
                             "mijoz hammasini yozib javob beradi)" if business else "bot chati (tugmalar bor)"),
                f"Buyurtma #{o['id']}, holati: {o['status']}",
                "Qoralama: " + json.dumps(data, ensure_ascii=False),
                f"Rasmlar soni: {len(o['photos'])}",
                "Tayyor e'lon mijozga ko'rsatilganmi: " + ("ha" if o["data"].get("_preview") else "yo'q"),
            ]
            miss = missing_fields(o)
            lines.append("Yetishmayapti: " + (", ".join(miss) if miss else "hech narsa — show_preview chaqirsa bo'ladi"))
            if o["status"] == "awaiting_payment":
                lines.append(f"Mijoz e'lonni tasdiqlagan va {fmt_sum(o['amount'])} so'm to'lashi kerak (aynan shu summa). "
                             "Qoralamani endi o'zgartirib bo'lmaydi. To'lov tushgach e'lon avtomatik joylanadi. "
                             "To'lagan bo'lsa-yu joylanmagan bo'lsa — to'lov chekining skrinshotini shu chatga yuborishini ayt. "
                             "Silkani qayta so'rasa go_to_payment chaqir. "
                             f"Silka ochilmayapti/ishlamayapti desa: Payme ilovasiga kirib qidiruvga «{PAYME_SEARCH_NAME}» "
                             "deb yozib, o'sha yerdan aynan shu summani to'lashini ayt. "
                             + (f"Click'dan to'lamoqchi bo'lsa: Click ilovasida «{CLICK_SEARCH_NAME}» deb qidirib to'lashini ayt. "
                                "Mijoz Click'dan to'laganini aytsa yoki 'to'ladim' deb yozsa-yu e'lon chiqmagan bo'lsa — "
                                "CHEK SKRINSHOTINI so'ra; skrinshotsiz tasdiqlab bo'lmaydi, 'tasdiqlandi' dema. "
                                "Chek kelgach admin tekshiradi." if CLICK_ENABLED else ""))
            return "\n".join(lines)

        async def on_tool(name: str, args: dict) -> str:
            nonlocal want_preview, want_payment
            o = await db.active_order(uid)
            if name == "cancel_order":
                return await cancel_active(uid)
            if name == "go_to_payment":
                if o and o["status"] == "awaiting_payment":
                    want_payment = True
                    return "Bot to'lov ma'lumotini qayta yuboradi."
                if not o or o["status"] != "draft":
                    return "To'lovga o'tib bo'lmaydi: faol qoralama yo'q."
                if miss := missing_fields(o):
                    return "Hali to'lovga o'tib bo'lmaydi. Yetishmayapti: " + ", ".join(miss)
                if not o["data"].get("_preview"):
                    return "Avval show_preview chaqirib, mijozga tayyor e'lonni ko'rsat."
                want_payment = True
                return ("Bot javobingdan keyin to'lov summasi va Payme silkasini o'zi yuboradi. "
                        "Sen silka yoki summa yozma — faqat juda qisqa yoz, masalan: 'Zo'r 👍'.")
            if name == "reset_ad":
                # Yangi e'lon: joriy qoralama yoki TO'LANMAGAN e'lon yopiladi, to'langani tegilmaydi
                if o and o["status"] == "paid":
                    return "Oldingi e'lon to'langan va hozir joylanmoqda — u tugagach yangisini boshlash mumkin."
                old = ""
                if o:
                    old = f" (#{o['id']} {'to‘lanmagan e‘lon' if o['status'] == 'awaiting_payment' else 'qoralama'} yopildi)"
                    await db.set_status(o["id"], "cancelled")
                await db.get_or_create_draft(uid)
                return "Yangi bo'sh qoralama ochildi" + old + ". Endi update_ad bilan ma'lumotlarni saqla."
            if not o:
                o = await db.get_or_create_draft(uid)  # e'lon yo'q bo'lsa — yangisini ochamiz
            if o["status"] == "awaiting_payment":
                return ("Mijozning #{0} e'loni to'lov kutmoqda, uni o'zgartirib bo'lmaydi. Agar mijoz YANGI e'lon "
                        "bermoqchi bo'lsa: eski to'lanmagan e'lon bekor bo'lishini aytib, rozi bo'lsa reset_ad chaqir, "
                        "keyin update_ad.").format(o["id"])
            if o["status"] != "draft":
                return "Hozir qoralamani o'zgartirib bo'lmaydi."
            if name == "update_ad":
                await db.update_data(o["id"], args)
                await db.set_preview_shown(o["id"], False)
                o = await db.get_order(o["id"])
                miss = missing_fields(o)
                return "Saqlandi. " + ("Yetishmayapti: " + ", ".join(miss) if miss else "Hammasi to'liq.")
            if name == "show_preview":
                if miss := missing_fields(o):
                    return "Hali ko'rsatib bo'lmaydi. Yetishmayapti: " + ", ".join(miss)
                want_preview = True
                return ("Bot javobingdan keyin tayyor e'lonni yuboradi va 'hammasi to'g'rimi?' deb o'zi so'raydi. "
                        "Sen faqat juda qisqa yoz, masalan: 'Bo'ldi, hozir tayyor e'lonni tashlayman'.")
            return "Noma'lum asbob."

        try:
            await bot.send_chat_action(uid, ChatAction.TYPING, **kw)
        except Exception:
            pass
        try:
            reply = await ai.agent_turn(history, text, state, on_tool)
        except Exception as e:
            log.exception("AI xatosi")
            await to_group(bot, f"⚠️ AI xatosi (mijoz <code>{uid}</code>):\n<code>{escape(type(e).__name__)}: "
                                f"{escape(str(e))[:700]}</code>")
            await bot.send_message(uid, "Kechirasiz, hozir texnik nosozlik bor. Bir daqiqadan keyin qayta yozing 🙏",
                                   parse_mode=None, **kw)
            return

        history += [{"role": "user", "content": text},
                    {"role": "assistant", "content": reply or "(tayyor e'lon ko'rsatildi)"}]
        await db.save_history(uid, history)

        if reply:
            await send_human(bot, uid, reply, kw, await reply_kb(uid))
        o = await db.active_order(uid)
        if want_preview and o:
            await send_preview(bot, uid, o)
        if want_payment and o:
            await start_payment(bot, uid, o)


async def send_human(bot: Bot, uid: int, text: str, kw: dict, markup=None):
    """Odamdek yuborish: avval 'yozmoqda...' turadi, uzun javob 2-3 ta qisqa xabarga bo'linadi."""
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(parts) > 3:  # juda ko'p bo'lak bo'lmasin
        parts = parts[:2] + ["\n\n".join(parts[2:])]
    for i, part in enumerate(parts):
        # taxminan odam yozish tezligi: ~25 belgi/soniya, 1.2–5 soniya oralig'ida
        delay = min(5.0, max(1.2, len(part) / 25))
        try:
            await bot.send_chat_action(uid, ChatAction.TYPING, **kw)
        except Exception:
            pass
        await asyncio.sleep(delay)
        last = i == len(parts) - 1
        await bot.send_message(uid, part, parse_mode=None, reply_markup=markup if last else None, **kw)


# ================= Oldindan ko'rish va to'lov =================
async def send_preview(bot: Bot, uid: int, order: dict):
    kw = await db.send_kw(uid)
    if kw:
        await asyncio.sleep(1.5)
    else:
        await bot.send_message(uid, "👇 E'loningiz kanalda shunday ko'rinadi:")
    await publisher.send_ad(bot, uid, order, **kw)
    await db.set_preview_shown(order["id"], True)
    if kw:  # business lichka — tugmasiz, odamdek
        await send_human(bot, uid, f"Kanalda shunaqa chiqadi. Hammasi to'g'rimi? To'g'ri bo'lsa «ha» deb yozing, "
                                   f"to'g'irlash kerak bo'lsa ayting\n\nE'lon narxi {fmt_sum(AD_PRICE)} so'm", kw)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Hammasi to'g'ri — to'lovga o'tish", callback_data=f"ok:{order['id']}")],
        [InlineKeyboardButton(text="✏️ O'zgartirish", callback_data=f"edit:{order['id']}")],
    ])
    await bot.send_message(uid, f"Tekshirib chiqing. E'lon narxi: <b>{fmt_sum(AD_PRICE)} so'm</b>.", reply_markup=kb)


async def start_payment(bot: Bot, uid: int, o: dict):
    """Qoralamani to'lov kutish holatiga o'tkazib, mijozga summa va Payme silkasini yuboradi."""
    if o["status"] == "draft":
        amount = pick_amount(await db.reserved_amounts())
        await db.request_payment(o["id"], amount)
        o = await db.get_order(o["id"])
        user = await db.get_user(uid) or {}
        name = escape(user.get("full_name") or str(uid))
        source = "💬 lichka" if await db.bc_id(uid) else "🤖 bot"
        await to_group(bot, f"🆕 #{o['id']} to'lov kutilmoqda: <b>{fmt_sum(amount)} so'm</b> ({source})\n"
                            f"👤 <a href=\"tg://user?id={uid}\">{name}</a>"
                            + (f" (@{user['username']})" if user.get("username") else "")
                            + f"\n📦 {escape(o['data'].get('title', ''))}")
    if o["status"] == "awaiting_payment":
        await send_payment_message(bot, uid, o)


async def send_payment_message(bot: Bot, uid: int, o: dict):
    kw = await db.send_kw(uid)
    link = payme_link(o["amount"], o["id"])
    exact = ("❗️ <b>Aynan shu summani</b> to'lang (so'mi bilan) — tizim to'lovingizni summa orqali avtomatik taniydi.\n"
             if UNIQUE_AMOUNT else "")
    text = (f"💳 <b>To'lov</b> — e'lon #{o['id']}\n\n"
            f"Summa: <b>{fmt_sum(o['amount'])} so'm</b>\n{exact}")
    if kw and link:
        text += f"\n👉 Payme orqali to'lash: {link}\n"
    text += (f"\n📱 Silka ochilmasa: Payme ilovasida qidiruvga <b>«{escape(PAYME_SEARCH_NAME)}»</b> deb yozing "
             "va o'sha yerdan to'lang.\n")
    if CLICK_ENABLED:
        text += (f"\n🔵 <b>Click orqali:</b> Click ilovasida <b>«{escape(CLICK_SEARCH_NAME)}»</b> deb qidiring, shu summani "
                 "to'lang va <b>chek skrinshotini albatta shu yerga yuboring</b> — Click to'lovi faqat chek bilan tasdiqlanadi.\n")
    text += ("\nTo'lov tushishi bilan e'loningiz avtomatik kanalga joylanadi (odatda 1-2 daqiqa).\n"
             "10 daqiqada joylanmasa — to'lov chekining skrinshotini shu yerga yuboring.\n\n"
             f"⏳ To'lov {PAYMENT_TTL_HOURS} soat ichida qilinishi kerak.")
    if not link:
        text += "\n\n⚠️ To'lov silkasi sozlanmagan, admin bilan bog'laning."
    if kw:  # business lichka — odamdek, bo'lib-bo'lib
        exact_h = "Aynan shu summani tashlang, so'migacha, shunda to'lovingiz avtomatik taniladi. " if UNIQUE_AMOUNT else ""
        msg1 = f"Unda to'lovni qilib qo'ying: {fmt_sum(o['amount'])} so'm. {exact_h}"
        msg2 = (f"Payme orqali: {link}\n\nAgar silka ochilmasa, Payme ilovasiga kirib qidiruvga "
                f"«{PAYME_SEARCH_NAME}» deb yozing, o'sha yerdan to'lasangiz ham bo'ladi") if link else \
               f"Payme ilovasiga kirib qidiruvga «{PAYME_SEARCH_NAME}» deb yozing va o'sha yerdan to'lang"
        msg3 = ("To'lov tushishi bilan e'loningizni kanalga chiqarib yuboraman. "
                "Agar 10 daqiqada chiqmasa, to'lov chekining skrinshotini shu yerga tashlab qo'ying")
        await send_human(bot, uid, msg1, kw)
        await send_human(bot, uid, msg2, kw)
        if CLICK_ENABLED:
            await send_human(bot, uid, f"Click'dan ham bo'ladi: Click ilovasida «{CLICK_SEARCH_NAME}» deb qidiring, "
                                       f"shu summani tashlang. Faqat Click'dan to'lasangiz, chekining skrinshotini "
                                       f"albatta shu yerga yuboring, cheksiz tasdiqlay olmayman", kw)
        await send_human(bot, uid, msg3, kw)
        return
    rows = []
    if link:
        rows.append([InlineKeyboardButton(text="💳 Payme orqali to'lash", url=link)])
    rows.append([InlineKeyboardButton(text="❌ E'lonni bekor qilish", callback_data=f"cancel:{o['id']}")])
    await bot.send_message(uid, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("ok:"))
async def cb_ok(cb: CallbackQuery, bot: Bot):
    order_id = int(cb.data.split(":")[1])
    o = await db.get_order(order_id)
    if not o or o["user_id"] != cb.from_user.id:
        await cb.answer("Bu e'lon topilmadi", show_alert=True)
        return
    if o["status"] not in ("draft", "awaiting_payment"):
        await cb.answer("Bu e'lon allaqachon yopilgan", show_alert=True)
        return
    if miss := missing_fields(o):
        await cb.answer("Yetishmayapti: " + ", ".join(miss), show_alert=True)
        return
    await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await start_payment(bot, cb.from_user.id, o)


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


# ================= Chek (qo'lda tekshirish) =================
async def forward_receipt(bot: Bot, m: Message, o: dict):
    user = m.from_user
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"adm_ok:{o['id']}"),
        InlineKeyboardButton(text="❌ Rad etish", callback_data=f"adm_no:{o['id']}"),
    ]])
    # Chekni AI o'qib, adminga yordamchi ma'lumot beradi (qaror baribir adminniki)
    ai_line = ""
    try:
        buf = await bot.download(m.photo[-1])
        info = await ai.read_receipt(buf.read())
    except Exception:
        log.exception("chekni yuklab bo'lmadi")
        info = None
    if info and info.get("is_receipt"):
        amt = info.get("amount")
        svc = (info.get("service") or "?").capitalize()
        match = ("✅ summa mos" if amt and int(amt) == o["amount"]
                 else f"⚠️ summa MOS EMAS (kutilgan {fmt_sum(o['amount'])})" if amt else "❓ summa o'qilmadi")
        ok = "" if info.get("success", True) else "\n⚠️ Chekda 'muvaffaqiyatli' belgisi ko'rinmadi"
        ai_line = (f"\n\n🤖 Chekdan: <b>{svc}</b> · {fmt_sum(int(amt)) + ' so‘m' if amt else '?'} · {match}"
                   + (f"\nQabul qiluvchi: {escape(str(info['recipient']))}" if info.get("recipient") else "")
                   + (f"\nVaqt: {escape(str(info['datetime']))}" if info.get("datetime") else "") + ok
                   + ("\n👉 Click ilovangizdan tushganini tekshiring" if svc.lower() == "click" else ""))
    elif info is not None:
        # Aniq chek emas — guruhni band qilmaymiz, mijozdan qayta so'raymiz
        await send_human(bot, user.id, "Bu rasm to'lov chekiga o'xshamadi. To'lov qilgan bo'lsangiz, "
                                       "Payme yoki Click'dagi chekning skrinshotini tashlang", await db.send_kw(user.id))
        return
    caption = (f"🧾 <b>Chek</b> — e'lon #{o['id']}\n"
               f"Kutilgan summa: <b>{fmt_sum(o['amount'])} so'm</b>\n"
               f"👤 <a href=\"tg://user?id={user.id}\">{escape(user.full_name)}</a>"
               + (f" (@{user.username})" if user.username else "")
               + ("\n💬 Business lichka orqali" if m.business_connection_id else "")
               + ai_line)[:1024]
    await bot.send_photo(PAYMENT_GROUP_ID, m.photo[-1].file_id, caption=caption, reply_markup=kb)
    await bot.send_message(user.id, "Chekni oldim, tekshirib e'loningizni chiqarib yuboraman 👍",
                           **await db.send_kw(user.id))
