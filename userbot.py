"""Userbot: sizning Telegram akkauntingiz orqali Payme guruhini FAQAT O'QIYDI.

Nega kerak: Payme ochgan guruhda botga adminlik berib bo'lmaydi, admin bo'lmagan bot esa
boshqa botning (PaymeBusinessNotifier) xabarlarini Telegram qoidasiga ko'ra ko'rmaydi.
Siz guruh a'zosisiz — userbot sizning ko'zingiz bilan o'qiydi va to'lovni botga uzatadi.
Userbot hech narsa yozmaydi; guruhga javoblarni bot o'zi yozadi.

Kerakli o'zgaruvchilar: TG_API_ID, TG_API_HASH (my.telegram.org), TG_SESSION (gen_session.py).
"""
import logging

from aiogram import Bot

from config import CLICK_GROUP_ID, PAYMENT_GROUP_ID, TG_API_HASH, TG_API_ID, TG_SESSION
from handlers_group import process_payment

log = logging.getLogger(__name__)


async def start(bot: Bot):
    if not (TG_API_ID and TG_API_HASH and TG_SESSION):
        log.info("Userbot o'chiq (TG_API_ID / TG_API_HASH / TG_SESSION berilmagan)")
        return None
    from telethon import TelegramClient, events
    from telethon.sessions import StringSession

    client = TelegramClient(StringSession(TG_SESSION), TG_API_ID, TG_API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        log.error("Userbot: TG_SESSION yaroqsiz — gen_session.py ni qayta ishga tushiring")
        await client.disconnect()
        return None

    @client.on(events.NewMessage())
    async def on_new(event):
        click = bool(CLICK_GROUP_ID) and event.chat_id == CLICK_GROUP_ID
        if event.chat_id != PAYMENT_GROUP_ID and not click:
            return
        msg = event.message
        is_bot = None
        if click:
            try:
                sender = await event.get_sender()
                is_bot = bool(getattr(sender, "bot", False))
            except Exception:
                is_bot = None
        try:
            await process_payment(bot, msg.message or "", f"{event.chat_id}:{msg.id}",
                                  {event.sender_id} if event.sender_id else set(),
                                  # oddiy guruhda xabar raqamlari akkauntlarda farq qiladi — reply qilmaymiz
                                  msg.id if str(event.chat_id).startswith("-100") else None,
                                  "userbot", click=click, sender_is_bot=is_bot)
        except Exception:
            log.exception("Userbot: to'lovni qayta ishlashda xato")

    me = await client.get_me()
    log.info("Userbot ulandi: %s (id=%s), guruh %s kuzatilmoqda", me.first_name, me.id, PAYMENT_GROUP_ID)
    return client
