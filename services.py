"""To'lov tasdiqlangach: kanalga joylash va hammaga xabar berish."""
import asyncio
import logging
from html import escape

from aiogram import Bot

import db
import publisher
from config import PAYMENT_GROUP_ID
from formatting import fmt_sum, is_service
from texts import t

log = logging.getLogger(__name__)


async def confirm_and_publish(bot: Bot, order_id: int, paid_by: str, manual: bool = False) -> str:
    """Qaytaradi: guruhga yoziladigan qisqa natija matni."""
    if not await db.mark_paid(order_id, paid_by, allow_expired=manual):
        o = await db.get_order(order_id)
        st = o["status"] if o else "yo'q"
        return f"⚠️ #{order_id} buyurtma tasdiqlanmadi (holati: {st})."

    order = await db.get_order(order_id)
    await notify_user(bot, order["user_id"], "paid")
    try:
        link, pending = await publisher.publish(bot, order)
    except Exception as e:
        log.exception("publish failed")
        await notify_user(bot, order["user_id"], "publish_delay")
        return (f"❗️ #{order_id} to'langan, lekin kanalga joylanmadi: {escape(str(e))}\n"
                f"Qayta urinish: /joyla {order_id}")

    await notify_user(bot, order["user_id"], "published_service" if is_service(order["data"]) else "published", link=link)
    if pending:
        asyncio.create_task(resolve_post_link(bot, order_id))
    # Suhbatni tozalamaymiz — AI e'lon joylanganini bilsin ("rahmat"ga to'g'ri javob bersin)
    await db.add_history_note(order["user_id"],
                              f"[Tizim: #{order_id} e'lon to'landi va kanalga joylandi: {link}. Mijozga xabar berildi.]")
    return (f"✅ #{order_id} — {fmt_sum(order['amount'])} so'm tasdiqlandi va joylandi: {link}"
            + ("\n⏳ Telegram postni navbatga qo'ydi (video), aniq silka chiqqach mijozga yuboriladi" if pending else ""))


async def republish(bot: Bot, order_id: int) -> str:
    order = await db.get_order(order_id)
    if not order or order["status"] != "paid":
        return "Faqat to'langan, lekin joylanmagan buyurtmani qayta joylash mumkin."
    link, pending = await publisher.publish(bot, order)
    await notify_user(bot, order["user_id"], "published_service" if is_service(order["data"]) else "published", link=link)
    if pending:
        asyncio.create_task(resolve_post_link(bot, order_id))
    await db.add_history_note(order["user_id"], f"[Tizim: #{order_id} e'lon kanalga joylandi: {link}.]")
    return f"✅ #{order_id} joylandi: {link}"


async def notify_user(bot: Bot, user_id: int, key: str, **fmt) -> None:
    """Mijozga tayyor xabar — u oxirgi marta qaysi tilda yozgan bo'lsa, o'sha tilda."""
    text = t(key, await db.get_lang(user_id), **fmt)
    kw = await db.send_kw(user_id)
    try:
        await bot.send_message(user_id, text, parse_mode=None, disable_web_page_preview=True, **kw)
        return
    except Exception as e:
        log.warning("user %s ga yozib bo'lmadi (%s)", user_id, e)
    if kw:  # business ulanishi uzilgan bo'lishi mumkin — mijoz botni ochgan bo'lsa, bot chatiga yozamiz
        try:
            await bot.send_message(user_id, text, parse_mode=None, disable_web_page_preview=True)
            return
        except Exception:
            pass
    await to_group(bot, f"📵 Mijozga xabar yetmadi (<a href=\"tg://user?id={user_id}\">{user_id}</a>): "
                        f"{escape(text[:300])}\nUnga o'zingiz yozib qo'ying.")


async def to_group(bot: Bot, text: str, **kw) -> None:
    try:
        await bot.send_message(PAYMENT_GROUP_ID, text, disable_web_page_preview=True, **kw)
    except Exception:
        log.exception("guruhga yozib bo'lmadi")


async def resolve_post_link(bot: Bot, order_id: int, tries: int = 60, every: int = 30) -> None:
    """Telegram videoli postni navbatga qo'yganda (message_id=0) haqiqiy post raqamini topadi:
    kanal posti kelganda (channel_post) yoki userbot orqali kanalni o'qib. Topilgach mijozga aniq silkani yuboradi."""
    import userbot
    order = await db.get_order(order_id)
    expected = publisher.expected_text(order)
    for _ in range(tries):
        await asyncio.sleep(every)
        o = await db.get_order(order_id)
        ids = o["channel_msgs"] if o["channel_msgs"] and o["channel_msgs"][0] != 0 else None
        if not ids:
            ids = await userbot.find_post(publisher.CHANNEL_ID, expected, publisher.norm_text)
            if ids:
                await db.set_channel_msgs(order_id, ids)
        if ids:
            link = publisher.post_link(ids[0])
            await notify_user(bot, o["user_id"], "published_link", link=link)
            await db.add_history_note(o["user_id"], f"[Tizim: #{order_id} e'lonning aniq silkasi: {link}]")
            await to_group(bot, f"🔗 #{order_id} post silkasi aniqlandi: {link}")
            return
    await to_group(bot, f"⚠️ #{order_id} postining aniq silkasini topib bo'lmadi (Telegram videoni kech joyladi). "
                        "Mijozga silkani o'zingiz yuboring; «sotildi»/«tuzatish» bu e'lon uchun ishlamaydi.")
