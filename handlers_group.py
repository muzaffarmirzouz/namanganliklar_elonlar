"""To'lov guruhi: Payme bot xabarini o'qib, mos buyurtmani topib, avtomatik tasdiqlash."""
import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.types import Message

import ai
import db
from config import ADMIN_IDS, PAYMENT_GROUP_ID, PAYMENT_SOURCE_IDS
from formatting import fmt_sum
from payments import match_order
from services import confirm_and_publish

log = logging.getLogger(__name__)
router = Router()
router.message.filter(F.chat.id == PAYMENT_GROUP_ID)


@router.message()
async def on_payment_message(m: Message, bot: Bot):
    if m.from_user and m.from_user.id == bot.id:
        return
    sender = m.from_user.id if m.from_user else (m.sender_chat.id if m.sender_chat else 0)
    if PAYMENT_SOURCE_IDS and sender not in (PAYMENT_SOURCE_IDS | ADMIN_IDS):
        return  # begona odamning xabari to'lov deb hisoblanmaydi

    text = (m.text or m.caption or "").strip()
    if not text or text.startswith("/"):
        return
    key = f"{m.chat.id}:{m.message_id}"
    if await db.payment_seen(key):
        return

    info = await ai.parse_payment_text(text)
    if info is not None and (not info.get("is_payment") or info.get("incoming") is False):
        return  # oddiy yozishma yoki chiqim

    ai_amount = info.get("amount") if info else None
    awaiting = await db.awaiting_orders()
    order, why = match_order(text, ai_amount, awaiting)
    await db.log_payment(key, text, int(ai_amount) if ai_amount else None, order["id"] if order else None)

    if order:
        log.info("To'lov %s -> #%s (%s)", key, order["id"], why)
        await m.reply(await confirm_and_publish(bot, order["id"], f"auto:{key}"))
        return

    if info is None and not ai_amount:
        return  # AI ishlamadi va summa ham topilmadi — shovqin qilmaymiz
    pending = "\n".join(f"#{o['id']} — {fmt_sum(o['amount'])} so'm" for o in awaiting[:15]) or "yo'q"
    amount_txt = f"{fmt_sum(int(ai_amount))} so'm" if ai_amount else "Summa"
    await m.reply(f"⚠️ {amount_txt} tushdi — {escape(why)}.\n"
                  f"Qo'lda tasdiqlash: /tasdiq ID\n\n⏳ Kutilayotganlar:\n{pending}")
