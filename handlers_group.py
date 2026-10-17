"""To'lov guruhi: Payme xabarini o'qib, mos buyurtmani topib, avtomatik tasdiqlash.

Payme xabari ikki yo'l bilan kelishi mumkin:
  • bot o'zi ko'rsa (bot guruhda admin bo'lsa) — quyidagi router;
  • userbot orqali (userbot.py) — bot admin bo'lmagan, Payme ochgan guruhlar uchun.
Ikkalasi ham process_payment() ga tushadi; bir xabar ikki marta hisoblanmaydi.
"""
import asyncio
import hashlib
import re
import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.types import Message, ReplyParameters

import ai
import db
from config import AD_PRICE, ADMIN_IDS, PAYMENT_GROUP_ID, PAYMENT_SOURCE_IDS, UNIQUE_MAX_OFFSET
from formatting import fmt_sum
from payments import extract_amounts, match_order
from services import confirm_and_publish

log = logging.getLogger(__name__)
router = Router()
router.message.filter(F.chat.id == PAYMENT_GROUP_ID)
_seen_lock = asyncio.Lock()


def _to_int(v) -> int | None:
    """AI summani son, matn ("50 976") yoki kasr ko'rinishida qaytarishi mumkin — butun so'mga keltiramiz."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(round(v)) or None
    digits = re.sub(r"[^\d.,]", "", str(v)).replace(",", ".")
    if digits.count(".") > 1 or re.search(r"\.\d{3}$", digits):  # 50.976 yoki 1.250.000 — minglik ajratkich
        digits = digits.replace(".", "")
    try:
        return int(round(float(digits))) or None
    except ValueError:
        return None


async def reply_in_group(bot: Bot, text: str, reply_to: int | None) -> None:
    kw = {}
    if reply_to:
        kw["reply_parameters"] = ReplyParameters(message_id=reply_to, allow_sending_without_reply=True)
    try:
        await bot.send_message(PAYMENT_GROUP_ID, text, disable_web_page_preview=True, **kw)
    except Exception:
        log.exception("guruhga javob yozib bo'lmadi")


async def process_payment(bot: Bot, text: str, key: str, senders: set[int], reply_to: int | None,
                          source: str) -> None:
    text = (text or "").strip()
    if bot.id in senders:
        return  # botning o'z xabari
    log.info("Guruh xabari [%s]: senders=%s | %r", source, senders, text[:80])
    if PAYMENT_SOURCE_IDS and not (senders & (PAYMENT_SOURCE_IDS | ADMIN_IDS)):
        log.info("  -> o'tkazib yuborildi: yuboruvchi %s PAYMENT_SOURCE_IDS da yo'q", senders)
        return
    if not text or text.startswith("/"):
        return
    # Bir xabar ham userbot, ham bot orqali kelishi mumkin; oddiy guruhda ularning xabar raqamlari farq qiladi.
    # Shuning uchun matn bo'yicha tekshiramiz (Payme xabarida har to'lovning noyob ID si bor).
    key = "txt:" + hashlib.sha1(" ".join(text.split()).encode()).hexdigest()
    async with _seen_lock:  # tekshirish va band qilish bitta qadamda — ikki yo'l bir vaqtda kirmasin
        if await db.payment_seen(key):
            return
        await db.log_payment(key, text, None, None)

    info = await ai.parse_payment_text(text)
    if info is not None and (not info.get("is_payment") or info.get("incoming") is False):
        return  # oddiy yozishma yoki chiqim

    ai_amount = _to_int(info.get("amount")) if info else None
    awaiting = await db.matchable_orders()  # kutilayotganlar + muddati yaqinda o'tganlar
    order, why = match_order(text, ai_amount, awaiting)
    await db.update_payment(key, ai_amount, order["id"] if order else None)

    if order:
        log.info("To'lov %s -> #%s (%s)", key, order["id"], why)
        late = order["status"] == "expired"
        res = await confirm_and_publish(bot, order["id"], f"{source}:{key}", manual=late)
        await reply_in_group(bot, res + ("\n⏰ (to'lov muddatidan keyin keldi)" if late else ""), reply_to)
        return

    if info is None and not ai_amount:
        # AI ishlamadi. Matnda e'lon narxiga yaqin summa bo'lsa — to'lov bo'lishi mumkin, jim qolmaymiz
        near = sorted(a for a in extract_amounts(text) if AD_PRICE <= a <= AD_PRICE + UNIQUE_MAX_OFFSET)
        if not near:
            return
        ai_amount = near[0]
        why = "AI xabarni o'qiy olmadi, summa matndan topildi, lekin mos buyurtma yo'q"
    pending = "\n".join(f"#{o['id']} — {fmt_sum(o['amount'])} so'm" + (" (muddati o'tgan)" if o["status"] == "expired" else "")
                        for o in awaiting[:15]) or "yo'q"
    amount_txt = f"{fmt_sum(ai_amount)} so'm" if ai_amount else "Summa"
    await reply_in_group(bot, f"⚠️ {amount_txt} tushdi — {escape(why)}.\n"
                              f"Qo'lda tasdiqlash: /tasdiq ID\n\n⏳ Kutilayotganlar:\n{pending}", reply_to)


@router.message()
async def on_payment_message(m: Message, bot: Bot):
    senders = {x for x in (
        m.from_user.id if m.from_user else None,
        m.sender_chat.id if m.sender_chat else None,
        m.via_bot.id if m.via_bot else None,
    ) if x}
    await process_payment(bot, m.text or m.caption or "", f"{m.chat.id}:{m.message_id}",
                          senders, m.message_id, "bot")
