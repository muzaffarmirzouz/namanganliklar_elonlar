"""To'lov tasdiqlangach: kanalga joylash va hammaga xabar berish."""
import logging
from html import escape

from aiogram import Bot

import db
import publisher
from config import PAYMENT_GROUP_ID
from formatting import fmt_sum

log = logging.getLogger(__name__)


async def confirm_and_publish(bot: Bot, order_id: int, paid_by: str, manual: bool = False) -> str:
    """Qaytaradi: guruhga yoziladigan qisqa natija matni."""
    if not await db.mark_paid(order_id, paid_by, allow_expired=manual):
        o = await db.get_order(order_id)
        st = o["status"] if o else "yo'q"
        return f"⚠️ #{order_id} buyurtma tasdiqlanmadi (holati: {st})."

    order = await db.get_order(order_id)
    await notify_user(bot, order["user_id"],
                       "To'lov tushdi, rahmat! Hozir kanalga chiqaraman")
    try:
        link = await publisher.publish(bot, order)
    except Exception as e:
        log.exception("publish failed")
        await notify_user(bot, order["user_id"],
                           "To'lov tushdi, lekin kanalga chiqarishda biroz kechikish bo'ldi. Tez orada chiqarib qo'yaman 🙏")
        return (f"❗️ #{order_id} to'langan, lekin kanalga joylanmadi: {escape(str(e))}\n"
                f"Qayta urinish: /joyla {order_id}")

    await notify_user(bot, order["user_id"],
                       f"Tayyor, e'loningiz kanalda 👇\n{link}\n\n"
                       "Xaridor chiqishini tilayman! Yana biror narsa sotmoqchi bo'lsangiz, yozavering")
    await db.save_history(order["user_id"], [])  # keyingi e'lon toza suhbatdan boshlansin
    return f"✅ #{order_id} — {fmt_sum(order['amount'])} so'm tasdiqlandi va joylandi: {link}"


async def republish(bot: Bot, order_id: int) -> str:
    order = await db.get_order(order_id)
    if not order or order["status"] != "paid":
        return "Faqat to'langan, lekin joylanmagan buyurtmani qayta joylash mumkin."
    link = await publisher.publish(bot, order)
    await notify_user(bot, order["user_id"], f"Tayyor, e'loningiz kanalda 👇\n{link}")
    return f"✅ #{order_id} joylandi: {link}"


async def notify_user(bot: Bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text, parse_mode=None, disable_web_page_preview=True,
                               **await db.send_kw(user_id))
    except Exception:
        log.warning("user %s ga yozib bo'lmadi", user_id)


async def to_group(bot: Bot, text: str, **kw) -> None:
    try:
        await bot.send_message(PAYMENT_GROUP_ID, text, disable_web_page_preview=True, **kw)
    except Exception:
        log.exception("guruhga yozib bo'lmadi")
