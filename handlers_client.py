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
from config import (AD_PRICE, TARIFFS, ADMIN_CONTACT, BUSINESS_PAUSE_HOURS, CHANNEL_TITLE, CLICK_ENABLED,
                    EDIT_WINDOW_DAYS, MAX_EDITS, SOLD_WINDOW_DAYS,
                    CLICK_GROUP_ID, CLICK_SEARCH_NAME, MAX_PHOTOS,
                    PAYME_SEARCH_NAME, PAYMENT_GROUP_ID, PAYMENT_TTL_HOURS, UNIQUE_AMOUNT)
from formatting import fmt_sum, is_service, tariff_name
from texts import LANG_NAMES, detect_lang, t as tr
from payments import click_link, payme_link, pick_amount
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
    input_field_placeholder="Nima sotasiz yoki qanday xizmat? Yozing…",
)

REQUIRED = {"category": "kategoriya", "title": "sarlavha", "price": "narx",
            "location": "manzil", "phone": "telefon"}

RULES = (
    f"📌 <b>{escape(CHANNEL_TITLE)}</b> — e'lon berish qoidalari\n\n"
    f"💰 Narxi: <b>{fmt_sum(AD_PRICE)} so'm</b> — 1 ta e'lon, kanalga 1 marta joylanadi.\n"
    + ("💳 To'lov: Payme yoki Click (ikkalasi ham avtomatik).\n\n" if CLICK_GROUP_ID else
       "💳 To'lov: Payme (avtomatik) yoki Click (chek skrinshoti bilan).\n\n") +
    "✅ Qabul qilinadi:\n"
    "• <b>sotuv</b> — uy-joy, avtomobil, texnika, telefon, mebel, qurilish mollari, kiyim, chorva va boshqalar;\n"
    "• <b>xizmat ko'rsatish</b> — gilam yuvish, tozalash, santexnik, elektrik, ta'mirlash, yuk tashish, "
    "avtoservis, repetitor, to'y-tadbir xizmatlari va h.k.\n"
    "⛔️ Qabul qilinmaydi: Telegram kanal/guruh/bot reklamalari, yangilik kanallari, onlayn kurs va "
    "\"pul topish\" reklamalari, vakansiyalar, kredit, stavka, 18+ va taqiqlangan narsalar.\n\n"
    "📸 Sotuvda 3-4 ta sifatli rasm yoki video yuboring — albom qilib chiroyli joylab beramiz. Xizmatda rasm ixtiyoriy.\n"
    "📝 Tayyor reklamangiz bo'lsa (rasm/video + matn), shunchaki yuboring yoki forward qiling — o'zgartirmasdan joylaymiz."
)

_ai_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
_photo_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
_album_timers: dict[int, asyncio.Task] = {}
_album_captions: dict[int, list[str]] = defaultdict(list)


def order_days(order: dict) -> int:
    d = int(order["data"].get("_days") or 1)
    return d if d in TARIFFS else 1


def order_price(order: dict) -> int:
    return TARIFFS[order_days(order)]


def missing_fields(order: dict) -> list[str]:
    if order["data"].get("_ready"):  # tayyor reklama: faqat mazmuni bo'lsa yetarli
        return [] if (order["photos"] or order["data"].get("_ready_html")) else ["tayyor reklama mazmuni"]
    miss = [name for key, name in REQUIRED.items() if not order["data"].get(key)]
    if not order["photos"] and not is_service(order["data"]):  # xizmat e'lonida rasm ixtiyoriy
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


@router.business_message(F.photo | F.video)
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
        f"Nima sotmoqchisiz yoki qanday xizmat ko'rsatasiz? Shunchaki yozing — masalan: "
        f"<i>«Cobalt 2021 sotaman»</i> yoki <i>«gilam yuvish xizmati»</i>. Qolganini o'zim so'rab olaman.\n\n"
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
    await m.answer("Yangi e'lon boshladik ✍️\nNima sotasiz yoki qanday xizmat? Qisqacha yozing, sotuv bo'lsa 3-4 ta rasm yoki video ham yuboring. Tayyor reklamangiz bo'lsa — shunchaki tashlang.")


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


# ================= Rasm va videolar (ikkala rejim) =================
_album_plain: dict[int, list[str]] = defaultdict(list)
_album_fwd: dict[int, str] = {}
READY_MIN_LEN = 30  # shundan uzun izoh yoki forward — tayyor reklama bo'lishi mumkin


def forward_source(m: Message) -> str:
    """Forward qilingan bo'lsa — qayerdan (AI va admin uchun qisqa izoh), aks holda bo'sh."""
    o = m.forward_origin
    if not o:
        return ""
    chat = getattr(o, "chat", None) or getattr(o, "sender_chat", None)
    if chat:
        return f"«{chat.title or ''}»" + (f" @{chat.username}" if getattr(chat, "username", None) else "")
    user = getattr(o, "sender_user", None)
    if user:
        return user.full_name or "foydalanuvchi"
    return getattr(o, "sender_user_name", "") or "noma'lum manba"


@router.message(F.photo | F.video)
async def on_photo(m: Message, bot: Bot):
    uid = m.from_user.id
    await remember(m)
    kw = await db.send_kw(uid)
    o = await db.active_order(uid)

    if o and o["status"] == "awaiting_payment":
        if m.photo:
            await forward_receipt(bot, m, o)
        else:
            await run_ai(bot, uid, "[Tizim: to'lov kutilayotganda mijoz video yubordi.]")
        return
    if not o and m.photo:
        # To'lov muddati o'tgan e'lon bormi? Bot "chekni shu yerga tashlang" degan — rasm chek bo'lsa, adminga
        expired = await db.recent_expired(uid)
        if expired and await forward_receipt(bot, m, expired, strict=False):
            return
    if o and o["status"] == "paid":
        await bot.send_message(uid, tr("paid_wait", await db.get_lang(uid)), **kw)
        return

    item = m.photo[-1].file_id if m.photo else {"t": "video", "id": m.video.file_id}
    async with _photo_locks[uid]:
        o = await db.get_or_create_draft(uid)
        photos = o["photos"]
        if len(photos) >= MAX_PHOTOS:
            if m.media_group_id is None or uid not in _album_timers:
                await bot.send_message(uid, tr("too_many_photos", await db.get_lang(uid), n=MAX_PHOTOS), **kw)
            return
        photos.append(item)
        await db.set_photos(o["id"], photos)
        if o["data"].get("_preview"):
            await db.set_preview_shown(o["id"], False)  # media o'zgardi — qayta ko'rsatish kerak
    if m.caption:
        _album_captions[uid].append(m.html_text)   # formatlash (qalin, silka) saqlanadi
        _album_plain[uid].append(m.caption)
    if src := forward_source(m):
        _album_fwd[uid] = src

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
    plain = " ".join(_album_plain.pop(uid, [])).strip()
    fwd = _album_fwd.pop(uid, "")
    o = await db.active_order(uid)
    if not o:
        return
    n_video = sum(1 for x in o["photos"] if isinstance(x, dict) and x.get("t") == "video")
    n_photo = len(o["photos"]) - n_video
    note = (f"[Tizim: mijoz media yubordi. Qoralamada jami: {n_photo} ta rasm, {n_video} ta video "
            f"(maksimum {MAX_PHOTOS}).")
    if fwd:
        note += f" Bu boshqa joydan FORWARD qilingan: {fwd}."
    note += "]"
    if plain:
        note += f"\nMedia ostidagi matn: «{plain[:1500]}»"
        await db.set_lang(uid, detect_lang(plain, await db.get_lang(uid)))
    if captions and (len(plain) >= READY_MIN_LEN or fwd):
        await db.update_data(o["id"], {"_ready_candidate": "\n\n".join(captions)})
        note += ("\n[Tizim: bu TAYYOR REKLAMA bo'lishi mumkin. Agar shunday bo'lsa — mazmuni qoidaga mosligini tekshir, "
                 "use_ready_ad chaqir va keyin show_preview.]")
    await run_ai(bot, uid, note)


# ================= Matn -> AI (ikkala rejim) =================
@router.message(F.text)
async def on_text(m: Message, bot: Bot):
    await remember(m)
    uid = m.from_user.id
    await db.set_lang(uid, detect_lang(m.text, await db.get_lang(uid)))
    text = m.text[:2000]
    fwd = forward_source(m)
    if fwd or len(m.text) >= 80:
        o = await db.active_order(uid)
        if not o or o["status"] == "draft":
            o = o or await db.get_or_create_draft(uid)
            await db.update_data(o["id"], {"_ready_candidate": m.html_text})
            if fwd:
                text = f"[Tizim: mijoz boshqa joydan matnli post FORWARD qildi: {fwd}. Bu TAYYOR REKLAMA bo'lishi mumkin.]\n{text}"
    await run_ai(bot, uid, text)


@router.message()
async def on_other(m: Message, bot: Bot):
    await remember(m)
    uid = m.from_user.id
    if m.contact:  # "Kontaktni yuborish" — telefon raqamini AI ga beramiz
        phone = m.contact.phone_number or ""
        if phone and not phone.startswith("+"):
            phone = "+" + phone
        await run_ai(bot, uid, f"[Tizim: mijoz kontakt yubordi. Telefon: {phone}]")
        return
    if m.sticker:
        return  # stiker (👍 va h.k.) — javob shart emas
    if m.video or m.video_note or m.voice or m.document or m.audio:
        uid = m.from_user.id
        await bot.send_message(uid, tr("other_media", await db.get_lang(uid)), **await db.send_kw(uid))


async def run_ai(bot: Bot, uid: int, text: str):
    async with _ai_locks[uid]:
        kw = await db.send_kw(uid)
        business = bool(kw)
        lang = await db.get_lang(uid)
        history = await db.get_history(uid)
        want_preview = False
        want_payment = False

        async def state() -> str:
            lang_line = (f"MIJOZ TILI: {LANG_NAMES.get(lang, lang)}. Javobni FAQAT shu tilda va shu yozuvda yoz "
                         "(mijozning oxirgi xabariga qarab aniqlangan).")
            o = await db.active_order(uid)
            ed = await db.editable_published(uid, EDIT_WINDOW_DAYS * 86400)
            ed_line = ""
            if ed:
                left = MAX_EDITS - (ed.get("edits") or 0)
                ed_data = {k: v for k, v in ed["data"].items() if not k.startswith("_")}
                ed_line = (f"KANALDAGI E'LON #{ed['id']} (tuzatish mumkin, qolgan bepul tuzatishlar: {max(left, 0)}): "
                           + json.dumps(ed_data, ensure_ascii=False)
                           + ". Mijoz undagi xatoni aytsa — edit_published chaqir, yangi e'lon ochma.")
            camp = await db.user_campaign(uid)
            if camp:
                cd = camp["data"]
                nxt = time.strftime("%d.%m %H:%M", time.localtime(int(cd.get("_camp_next") or 0)))
                ed_line = (ed_line + "\n" if ed_line else "") + (
                    f"FAOL TARIF: #{camp['id']} «{cd.get('title', '')}», {cd.get('_camp_days')} kunlik, "
                    f"{cd.get('_camp_posted')}/{cd.get('_camp_days')} kun chiqdi, keyingisi taxminan {nxt}. "
                    "Mijoz yangi rasm/video (yoki tayyor reklama matnini) yuborsa — bu YANGI E'LON EMAS: "
                    "apply_to_campaign chaqir, to'lov so'rama.")
            live = await db.recent_published(uid, SOLD_WINDOW_DAYS * 86400)
            if live:
                items = "; ".join(f"#{x['id']} «{x['data'].get('title', '')}»"
                                  + (" — xizmat" if is_service(x["data"]) else "")
                                  + (" — SOTILDI belgisi bor" if x["data"].get("_sold") else "")
                                  + (" — TO'XTATILDI belgisi bor" if x["data"].get("_stopped") else "") for x in live)
                ed_line = (ed_line + "\n" if ed_line else "") + "Mijozning kanaldagi e'lonlari (mark_sold / mark_stopped uchun): " + items
            if not o:
                last = await db.last_published(uid)
                lines = [lang_line, "Faol e'lon yo'q (hozircha qoralama ochilmagan)."]
                if last:
                    mins = int((time.time() - (last["published_at"] or 0)) // 60)
                    lines.append(f"Mijozning oxirgi e'loni #{last['id']} «{last['data'].get('title', '')}» "
                                 f"{mins} daqiqa oldin to'langan va kanalga joylangan.")
                if ed_line:
                    lines.append(ed_line)
                lines.append("Agar mijoz shunchaki rahmat/xayr/ok desa — qisqa samimiy javob ber "
                             "(masalan 'Arzimaydi, xaridor tez chiqsin!') va SUHBATNI SHU YERDA TUGAT: "
                             "yangi e'lon taklif qilma, 'yana nima sotasiz' deb so'rama. "
                             "Faqat mijoz o'zi yangi narsa sotmoqchi bo'lsa yoki savol bersa — davom et.")
                return "\n".join(lines)
            data = {k: v for k, v in o["data"].items() if not k.startswith("_")}
            lines = [
                lang_line,
                "Kanal: " + ("Telegram lichka (siz kanal egasi nomidan yozyapsiz, tugmalar YO'Q — "
                             "mijoz hammasini yozib javob beradi)" if business else "bot chati (tugmalar bor)"),
                f"Buyurtma #{o['id']}, holati: {o['status']}",
                "Qoralama: " + json.dumps(data, ensure_ascii=False),
                f"Tanlangan tarif: {tariff_name(order_days(o))} — {fmt_sum(order_price(o))} so'm",
                f"Media soni (rasm+video): {len(o['photos'])}",
                ("TAYYOR REKLAMA rejimi: ha — mijoz matni o'zgartirilmasdan joylanadi" if o["data"].get("_ready") else
                 "Tayyor reklama nomzodi bor (use_ready_ad bilan qabul qilish mumkin): «"
                 + str(o["data"].get("_ready_candidate", ""))[:400] + "»" if o["data"].get("_ready_candidate") else
                 "Tayyor reklama: yo'q"),
                "Tayyor e'lon mijozga ko'rsatilganmi: " + ("ha" if o["data"].get("_preview") else "yo'q"),
            ]
            miss = missing_fields(o)
            lines.append("Yetishmayapti: " + (", ".join(miss) if miss else "hech narsa — show_preview chaqirsa bo'ladi"))
            if ed_line:
                lines.append(ed_line + " (Joriy qoralama — bu boshqa, yangi e'lon.)")
            lines.append("E'lon turi: " + ("XIZMAT (rasm ixtiyoriy)" if is_service(o["data"]) else
                                           "SOTUV" if o["data"].get("category") else "hali aniqlanmagan"))
            if o["status"] == "paid":
                lines.append("To'lov qabul qilingan, e'lon kanalga joylanmoqda (kechiksa admin joylaydi). "
                             "Hech narsani o'zgartirma, mijozni biroz kutishga chaqir.")
            if o["status"] == "awaiting_payment":
                lines.append(f"Mijoz e'lonni tasdiqlagan va {fmt_sum(o['amount'])} so'm to'lashi kerak (aynan shu summa). "
                             "Qoralamani endi o'zgartirib bo'lmaydi. To'lov tushgach e'lon avtomatik joylanadi. "
                             "To'lagan bo'lsa-yu joylanmagan bo'lsa — to'lov chekining skrinshotini shu chatga yuborishini ayt. "
                             "Silkani (Payme yoki Click) qayta so'rasa go_to_payment chaqir — bot ikkalasini ham yuboradi. "
                             f"Silka ochilmayapti/ishlamayapti desa: Payme ilovasiga kirib qidiruvga «{PAYME_SEARCH_NAME}» "
                             "deb yozib, o'sha yerdan aynan shu summani to'lashini ayt. "
                             + (f"Click'dan to'lamoqchi bo'lsa: Click ilovasida «{CLICK_SEARCH_NAME}» deb qidirib, aynan shu "
                                "summani to'lashini ayt. "
                                + ("Click to'lovi ham avtomatik tanib olinadi. Mijoz 'to'ladim' deb yozsa-yu e'lon 10 daqiqada "
                                   "chiqmagan bo'lsa — chek skrinshotini so'ra. 'Tasdiqlandi' deb o'zing aytma."
                                   if CLICK_GROUP_ID else
                                   "Mijoz Click'dan to'laganini aytsa yoki 'to'ladim' deb yozsa-yu e'lon chiqmagan bo'lsa — "
                                   "CHEK SKRINSHOTINI so'ra; skrinshotsiz tasdiqlab bo'lmaydi, 'tasdiqlandi' dema. "
                                   "Chek kelgach admin tekshiradi.") if CLICK_ENABLED else ""))
            return "\n".join(lines)

        async def on_tool(name: str, args: dict) -> str:
            nonlocal want_preview, want_payment
            o = await db.active_order(uid)
            if name == "apply_to_campaign":
                camp = await db.user_campaign(uid)
                if not camp:
                    return "Mijozda faol tarif yo'q. Bu yangi e'lon bo'lsa — odatdagidek davom et."
                if not o or o["status"] != "draft" or not (o["photos"] or o["data"].get("_ready_candidate")):
                    return "Yangi rasm/video hali kelmagan — mijozdan yuborishini so'ra."
                upd = {"_camp_refreshed": int(time.time())}
                if o["photos"]:
                    await db.set_photos(camp["id"], o["photos"][:10])
                if o["data"].get("_ready_candidate") and camp["data"].get("_ready"):
                    upd["_ready_html"] = o["data"]["_ready_candidate"]
                await db.update_data(camp["id"], upd)
                await db.set_status(o["id"], "cancelled")  # vaqtinchalik qoralama kerak emas
                nxt = time.strftime("%d.%m %H:%M", time.localtime(int(camp["data"].get("_camp_next") or 0)))
                await to_group(bot, f"🔄 #{camp['id']} «{escape(camp['data'].get('title', ''))}» — mijoz reklamani yangiladi "
                                    f"({len(o['photos'])} ta media), keyingi post shu bilan chiqadi")
                return f"Yangilandi. Keyingi post (taxminan {nxt}) yangi material bilan chiqadi. Mijozga qisqa ayt."
            if name == "edit_published":
                return await edit_published(bot, uid, args)
            if name == "mark_sold":
                return await close_ad(bot, uid, args.get("order_id"), "sold")
            if name == "mark_stopped":
                return await close_ad(bot, uid, args.get("order_id"), "stopped")
            if name == "notify_admin":
                u = await db.get_user(uid) or {}
                ed = await db.editable_published(uid, EDIT_WINDOW_DAYS * 86400)
                await to_group(bot, f"🙋 Mijoz yordam so'radi: {escape(str(args.get('reason', '')))[:500]}\n"
                                    f"👤 <a href=\"tg://user?id={uid}\">{escape(u.get('full_name') or str(uid))}</a>"
                                    + (f" (@{u['username']})" if u.get("username") else "")
                                    + (f"\n📌 E'lon: {publisher.post_link(ed['channel_msgs'][0])}" if ed and ed["channel_msgs"] and ed["channel_msgs"][0] else ""))
                return "Adminga yuborildi. Mijozga admin tez orada o'zi hal qilishini ayt."
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
            if name == "choose_tariff":
                try:
                    days = int(args.get("days") or 1)
                except (TypeError, ValueError):
                    days = 0
                if days not in TARIFFS:
                    return "Bunday tarif yo'q. Mavjud: " + ", ".join(f"{d} kun — {fmt_sum(p)} so'm" for d, p in sorted(TARIFFS.items()))
                await db.update_data(o["id"], {"_days": days})
                await db.set_preview_shown(o["id"], False)
                return (f"Tarif tanlandi: {tariff_name(days)}, {fmt_sum(TARIFFS[days])} so'm. "
                        + ("Agar e'lon tayyor bo'lsa — show_preview chaqir (narx yangilanadi)." ))
            if name == "use_ready_ad":
                cand = o["data"].get("_ready_candidate") or o["data"].get("_ready_html")
                if not cand and not o["photos"]:
                    return "Tayyor reklama topilmadi — mijozdan rasm/video va matnni yuborishini so'ra."
                await db.update_data(o["id"], {"_ready": True, "_ready_html": cand or "",
                                                "category": args.get("category"), "title": args.get("title")})
                await db.set_preview_shown(o["id"], False)
                return ("Tayyor reklama sifatida qabul qilindi (matni o'zgartirilmaydi). Endi show_preview chaqir — "
                        "bot kanalda qanday chiqishini ko'rsatib, tasdiqlashni so'raydi.")
            if name == "update_ad":
                if o["data"].get("_ready"):
                    await db.update_data(o["id"], {"_ready": False})  # oddiy tartibga qaytdi
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
            await bot.send_message(uid, tr("tech_error", lang), parse_mode=None, **kw)
            return

        if not reply and not want_preview and not want_payment:
            reply = tr("ack", lang)  # AI matn yozmay qolsa ham mijoz javobsiz qolmasin
        note = reply or ("(tayyor e'lon ko'rsatildi)" if want_preview else "(to'lov ma'lumoti yuborildi)")
        history += [{"role": "user", "content": text}, {"role": "assistant", "content": note}]
        await db.save_history(uid, history)

        if reply:
            await send_human(bot, uid, reply, kw, await reply_kb(uid))
        o = await db.active_order(uid)
        if want_preview and o:
            await send_preview(bot, uid, o)
        if want_payment and o:
            await start_payment(bot, uid, o)


EDITABLE = ("title", "price", "location", "phone", "telegram", "condition", "details", "description")
FIELD_NAMES = {"title": "sarlavha", "price": "narx", "location": "manzil", "phone": "telefon", "telegram": "telegram",
               "condition": "holati", "details": "xususiyatlar", "description": "tavsif"}


async def edit_published(bot: Bot, uid: int, args: dict) -> str:
    """Kanaldagi e'lonni tuzatish: bazada yangilaydi, kanal postini tahrirlaydi, guruhga hisobot beradi."""
    cands = [x for x in await db.recent_published(uid, EDIT_WINDOW_DAYS * 86400) if x["channel_msgs"] and x["channel_msgs"][0] != 0]
    if args.get("order_id"):
        o = next((x for x in cands if x["id"] == int(args["order_id"])), None)
    elif len(cands) > 1:
        return ("Mijozning bir nechta e'loni bor: " + ", ".join(f"#{x['id']} «{x['data'].get('title', '')}»" for x in cands)
                + ". Qaysi birini tuzatish kerakligini so'ra, keyin order_id bilan chaqir.")
    else:
        o = cands[0] if cands else None
    if not o:
        return (f"Tuzatsa bo'ladigan e'lon topilmadi (oxirgi {EDIT_WINDOW_DAYS} kunda joylangan e'lon yo'q yoki "
                "kanaldan o'chirilgan). Kerak bo'lsa notify_admin chaqir.")
    if o["data"].get("_ready"):
        return ("Bu mijozning tayyor reklamasi — matnini bot tahrirlay olmaydi. notify_admin chaqirib, nimani "
                "o'zgartirish kerakligini yoz; mijozga admin tez orada tuzatishini ayt.")
    if (o.get("edits") or 0) >= MAX_EDITS:
        return f"Bepul tuzatishlar soni ({MAX_EDITS} ta) tugagan. notify_admin chaqirib, adminga yubor."
    changes = {k: v for k, v in args.items() if k in EDITABLE and v not in (None, "", [])}
    if not changes:
        return "Nima o'zgarishi aniq emas — mijozdan so'ra."
    old_data = dict(o["data"])
    new_data = {**old_data, **changes}
    diff = [(k, old_data.get(k), v) for k, v in changes.items() if old_data.get(k) != v]
    if not diff:
        return "Bu ma'lumotlar e'londa allaqachon shunday turibdi."
    o["data"] = new_data
    try:
        link = await publisher.edit_post(bot, o)
    except Exception as e:
        log.exception("kanal postini tahrirlab bo'lmadi")
        await to_group(bot, f"❗️ #{o['id']} postini tahrirlab bo'lmadi: <code>{escape(str(e))[:300]}</code>\n"
                            "Botda kanalda «Xabarlarni tahrirlash» huquqi bormi?")
        return "Kanal postini hozir tahrirlab bo'lmadi, adminga xabar berildi. Mijozga admin tez orada tuzatishini ayt."
    await db.save_published_edit(o["id"], new_data)

    def short(v):
        v = ", ".join(v) if isinstance(v, list) else str(v or "—")
        return escape(v if len(v) <= 80 else v[:77] + "…")
    lines = "\n".join(f"• {FIELD_NAMES.get(k, k)}: {short(a)} → <b>{short(b)}</b>" for k, a, b in diff)
    left = MAX_EDITS - (o.get("edits") or 0) - 1
    await to_group(bot, f"✏️ #{o['id']} e'lon mijoz so'rovi bilan tuzatildi ({left} ta bepul tuzatish qoldi):\n"
                        f"{lines}\n{link}")
    return f"Kanaldagi e'lon yangilandi: {link}. Qolgan bepul tuzatishlar: {left}."


async def mark_sold(bot: Bot, uid: int, order_id: int | None) -> str:
    return await close_ad(bot, uid, order_id, "sold")


async def close_ad(bot: Bot, uid: int, order_id: int | None, kind: str) -> str:
    """kind="sold" — SOTILDI, kind="stopped" — E'LON TO'XTATILDI. Ikkalasida ham telefon raqami olib tashlanadi."""
    flag, label = ("_sold", "SOTILDI") if kind == "sold" else ("_stopped", "E'LON TO'XTATILDI")
    live = await db.recent_published(uid, SOLD_WINDOW_DAYS * 86400)
    live = [x for x in live if x["channel_msgs"] and x["channel_msgs"][0] != 0]
    if not live:
        return "Mijozning kanalda turgan e'loni topilmadi (o'chirilgan yoki juda eski). Kerak bo'lsa notify_admin chaqir."
    if order_id:
        o = next((x for x in live if x["id"] == int(order_id)), None)
        if not o:
            return "Bu raqamli e'lon mijozniki emas yoki kanalda yo'q. Ro'yxatdan to'g'risini tanla."
    else:
        open_ads = [x for x in live if not x["data"].get("_sold") and not x["data"].get("_stopped")
                    and not (kind == "sold" and is_service(x["data"]))]
        if len(open_ads) > 1:
            return ("Mijozning bir nechta e'loni bor: " + ", ".join(f"#{x['id']} «{x['data'].get('title', '')}»" for x in open_ads)
                    + ". Qaysi biri ekanini so'ra, keyin order_id bilan chaqir.")
        o = open_ads[0] if open_ads else live[0]
    if kind == "sold" and is_service(o["data"]):
        return "Bu xizmat e'loni — unga SOTILDI qo'yilmaydi. Mijoz xizmatni to'xtatgan bo'lsa mark_stopped chaqir."
    if o["data"].get("_sold") or o["data"].get("_stopped"):
        return "Bu e'lon allaqachon yopilgan (SOTILDI yoki TO'XTATILDI belgisi bor)."
    o["data"][flag] = True
    try:
        link = await publisher.edit_post(bot, o)
    except Exception as e:
        log.exception("e'lonni yopib bo'lmadi")
        await to_group(bot, f"❗️ #{o['id']} ga «{label}» qo'yib bo'lmadi: <code>{escape(str(e))[:300]}</code>")
        return "Kanal postini hozir o'zgartirib bo'lmadi, adminga xabar berildi. Mijozga admin tez orada belgilashini ayt."
    await db.update_data(o["id"], {flag: True})
    # Tarifli e'lonning oldingi kunlardagi postlariga ham belgi qo'yamiz (telefon hamma joydan olinsin)
    latest = o["channel_msgs"][0] if o["channel_msgs"] else 0
    for old_id in [x for x in o["data"].get("_all_posts") or [] if x and x != latest]:
        try:
            await publisher.edit_post(bot, {**o, "channel_msgs": [old_id]})
        except Exception as e:
            log.warning("#%s eski post %s ni yopib bo'lmadi: %s", o["id"], old_id, e)
    await to_group(bot, f"{'🏷' if kind == 'sold' else '⛔️'} #{o['id']} «{escape(o['data'].get('title', ''))}» — "
                        f"mijoz so'rovi bilan «{label}» qo'yildi, telefon raqami olib tashlandi\n{link}")
    return f"Kanalda «{label}» deb belgilandi va telefon raqami olib tashlandi: {link}"


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
        price = fmt_sum(order_price(order)) + (f" ({tariff_name(order_days(order))})" if order_days(order) > 1 else "")
        await send_human(bot, uid, tr("preview_ask", await db.get_lang(uid), price=price), kw)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Hammasi to'g'ri — to'lovga o'tish", callback_data=f"ok:{order['id']}")],
        [InlineKeyboardButton(text="✏️ O'zgartirish", callback_data=f"edit:{order['id']}")],
    ])
    tname = f" ({tariff_name(order_days(order))})" if order_days(order) > 1 else ""
    await bot.send_message(uid, f"Tekshirib chiqing. E'lon narxi: <b>{fmt_sum(order_price(order))} so'm</b>{tname}.",
                           reply_markup=kb)


async def start_payment(bot: Bot, uid: int, o: dict):
    """Qoralamani to'lov kutish holatiga o'tkazib, mijozga summa va Payme silkasini yuboradi."""
    if o["status"] == "draft":
        amount = pick_amount(await db.reserved_amounts(), order_price(o))
        await db.request_payment(o["id"], amount)
        o = await db.get_order(o["id"])
        user = await db.get_user(uid) or {}
        name = escape(user.get("full_name") or str(uid))
        source = "💬 lichka" if await db.bc_id(uid) else "🤖 bot"
        await to_group(bot, f"🆕 #{o['id']} to'lov kutilmoqda: <b>{fmt_sum(amount)} so'm</b> ({source})\n"
                            f"👤 <a href=\"tg://user?id={uid}\">{name}</a>"
                            + (f" (@{user['username']})" if user.get("username") else "")
                            + f"\n📦 {escape(o['data'].get('title', ''))}"
                            + (f"\n📅 Tarif: {tariff_name(order_days(o))}" if order_days(o) > 1 else ""))
    if o["status"] == "awaiting_payment":
        await send_payment_message(bot, uid, o)


async def send_payment_message(bot: Bot, uid: int, o: dict):
    """To'lov ma'lumoti mijoz tilida. Lichkada — bo'lib-bo'lib, odamdek; bot chatida — bitta xabar + tugmalar."""
    kw = await db.send_kw(uid)
    lang = await db.get_lang(uid)
    link = payme_link(o["amount"], o["id"])
    amount = fmt_sum(o["amount"])
    msgs = [tr("pay_amount", lang, amount=amount) + (tr("pay_exact", lang) if UNIQUE_AMOUNT else "")]
    msgs.append(tr("pay_link", lang, link=link, payme=PAYME_SEARCH_NAME) if link
                else tr("pay_nolink", lang, payme=PAYME_SEARCH_NAME))
    clink = click_link(o["amount"], o["id"]) if CLICK_ENABLED else ""
    if CLICK_ENABLED:
        if clink:
            msgs.append(tr("pay_click_link" if CLICK_GROUP_ID else "pay_click_link_receipt", lang,
                           link=clink, click=CLICK_SEARCH_NAME))
        else:
            msgs.append(tr("pay_click_auto" if CLICK_GROUP_ID else "pay_click", lang, click=CLICK_SEARCH_NAME))
    msgs.append(tr("pay_after", lang))

    if kw:  # business lichka
        for msg in msgs:
            await send_human(bot, uid, msg, kw)
        return
    rows = []
    if link:
        rows.append([InlineKeyboardButton(text=tr("btn_pay", lang), url=link)])
    if clink:
        rows.append([InlineKeyboardButton(text=tr("btn_click", lang), url=clink)])
    rows.append([InlineKeyboardButton(text=tr("btn_cancel", lang), callback_data=f"cancel:{o['id']}")])
    await bot.send_message(uid, "💳 " + "\n\n".join(msgs), parse_mode=None, disable_web_page_preview=True,
                           reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


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
async def forward_receipt(bot: Bot, m: Message, o: dict, strict: bool = True) -> bool:
    """Chekni AI bilan o'qib, guruhga tasdiqlash tugmalari bilan yuboradi.
    strict=False — rasm chek bo'lmasa hech narsa qilmaydi va False qaytaradi (oddiy rasm sifatida davom etiladi)."""
    user = m.from_user
    try:
        buf = await bot.download(m.photo[-1])
        info = await ai.read_receipt(buf.read())
    except Exception:
        log.exception("chekni yuklab bo'lmadi")
        info = None
    if not (info and info.get("is_receipt")):
        if not strict:
            return False
        if info is not None:  # AI aniq "chek emas" dedi — guruhni band qilmaymiz
            await send_human(bot, user.id, tr("receipt_bad", await db.get_lang(user.id)), await db.send_kw(user.id))
            return True
        # AI ishlamadi — ehtiyot uchun baribir adminga yuboramiz

    ai_line = ""
    if info and info.get("is_receipt"):
        amt = info.get("amount")
        try:
            amt = int(amt) if amt is not None else None
        except (TypeError, ValueError):
            amt = None
        svc = escape(str(info.get("service") or "?").capitalize()[:20])
        match = ("✅ summa mos" if amt == o["amount"]
                 else f"⚠️ summa MOS EMAS (kutilgan {fmt_sum(o['amount'])})" if amt else "❓ summa o'qilmadi")
        ai_line = (f"\n\n🤖 Chekdan: <b>{svc}</b> · {fmt_sum(amt) + ' so‘m' if amt else '?'} · {match}"
                   + (f"\nQabul qiluvchi: {escape(str(info['recipient'])[:80])}" if info.get("recipient") else "")
                   + (f"\nVaqt: {escape(str(info['datetime'])[:40])}" if info.get("datetime") else "")
                   + ("" if info.get("success", True) else "\n⚠️ Chekda 'muvaffaqiyatli' belgisi ko'rinmadi")
                   + ("\n👉 Click ilovangizdan tushganini tekshiring" if "click" in svc.lower() else ""))
    late = "\n⏰ To'lov muddati o'tgan e'lon" if o["status"] == "expired" else ""
    # Har bir bo'lak qisqa — HTML kesilmasdan 1024 belgiga sig'adi
    caption = (f"🧾 <b>Chek</b> — e'lon #{o['id']}\n"
               f"Kutilgan summa: <b>{fmt_sum(o['amount'])} so'm</b>\n"
               f"👤 <a href=\"tg://user?id={user.id}\">{escape(user.full_name[:60])}</a>"
               + (f" (@{user.username})" if user.username else "")
               + ("\n💬 Business lichka orqali" if m.business_connection_id else "")
               + late + ai_line)
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"adm_ok:{o['id']}"),
        InlineKeyboardButton(text="❌ Rad etish", callback_data=f"adm_no:{o['id']}"),
    ]])
    try:
        await bot.send_photo(PAYMENT_GROUP_ID, m.photo[-1].file_id, caption=caption, reply_markup=kb)
    except Exception:
        log.exception("chekni guruhga yuborib bo'lmadi")
        await to_group(bot, f"🧾 #{o['id']} cheki keldi, lekin rasmni yuborib bo'lmadi. "
                            f"Mijoz: <a href=\"tg://user?id={user.id}\">{escape(user.full_name[:60])}</a>\n"
                            f"Tasdiqlash: /tasdiq {o['id']}")
    await bot.send_message(user.id, tr("receipt_got", await db.get_lang(user.id)), **await db.send_kw(user.id))
    return True
