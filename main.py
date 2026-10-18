"""Namanganliklar E'lonlari — AI agent bot. Ishga tushirish: python main.py"""
import asyncio
import logging
import os
import time

os.environ.setdefault("TZ", "Asia/Tashkent")
time.tzset()

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.default import DefaultBotProperties  # noqa: E402
from aiogram.enums import ParseMode  # noqa: E402

import config  # noqa: E402
import db  # noqa: E402
import handlers_admin  # noqa: E402
import handlers_client  # noqa: E402
import handlers_group  # noqa: E402
import publisher  # noqa: E402
import userbot  # noqa: E402
from formatting import fmt_sum  # noqa: E402
from services import notify_user, to_group  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")


def check_config():
    need = {"BOT_TOKEN": config.BOT_TOKEN, "ANTHROPIC_API_KEY": config.ANTHROPIC_API_KEY,
            "CHANNEL_ID": config.CHANNEL_ID, "PAYMENT_GROUP_ID": config.PAYMENT_GROUP_ID,
            "ADMIN_IDS": config.ADMIN_IDS}
    missing = [k for k, v in need.items() if not v]
    if missing:
        raise SystemExit("Sozlanmagan: " + ", ".join(missing) + " (.env.example ga qarang)")
    if not (config.PAYME_LINK or config.PAYME_MERCHANT_ID):
        log.warning("PAYME_LINK ham, PAYME_MERCHANT_ID ham yo'q — mijozga to'lov tugmasi chiqmaydi!")


async def housekeeping(bot: Bot):
    """Har 5 daqiqada: muddati o'tgan to'lovlarni yopish, kerak bo'lsa eski e'lonlarni o'chirish."""
    while True:
        try:
            for o in await db.expired_awaiting(config.PAYMENT_TTL_HOURS * 3600):
                await db.set_status(o["id"], "expired")
                await notify_user(bot, o["user_id"], "expired", id=o["id"], amount=fmt_sum(o["amount"]))
            if config.AUTO_DELETE_HOURS > 0:
                for o in await db.to_autodelete(config.AUTO_DELETE_HOURS * 3600):
                    try:
                        await bot.delete_messages(config.CHANNEL_ID, o["channel_msgs"])
                    except Exception as e:
                        log.warning("#%s o'chirilmadi: %s", o["id"], e)
                    await db.mark_deleted(o["id"])
        except Exception:
            log.exception("housekeeping xatosi")
        await asyncio.sleep(300)


async def main():
    check_config()
    await db.init()
    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    me = await bot.get_me()
    publisher.BOT_USERNAME = me.username
    log.info("Bot: @%s", me.username)

    # Post silkasi to'g'ri bo'lishi uchun kanal username'ini Telegram'ning o'zidan olamiz (Railway'dagi qiymatga ishonmaymiz)
    link_note = ""
    try:
        ch = await bot.get_chat(config.CHANNEL_ID)
        real = (ch.username or "").lstrip("@")
        if real.lower() != config.CHANNEL_USERNAME.lower():
            log.warning("CHANNEL_USERNAME=%r noto'g'ri, kanalning haqiqiy username'i: %r", config.CHANNEL_USERNAME, real)
            link_note = (f"\n⚠️ Railway'da CHANNEL_USERNAME=<code>{config.CHANNEL_USERNAME or '(bo‘sh)'}</code>, lekin kanalning "
                         f"haqiqiy username'i <code>{real or '(yo‘q — yopiq kanal)'}</code>. Silkalar endi haqiqiysi bilan yasaladi.")
        publisher.CHANNEL_USERNAME = real
        if not real:
            link_note += "\n⚠️ Kanal yopiq (username yo'q): post silkalari faqat kanal a'zolarida ochiladi."
        log.info("Kanal: %s (@%s)", ch.title, real or "-")
    except Exception as e:
        log.exception("Kanalni tekshirib bo'lmadi")
        link_note = f"\n❗️ Kanalga ulanib bo'lmadi (CHANNEL_ID to'g'rimi, bot kanalda adminmi?): <code>{e}</code>"

    dp = Dispatcher()
    # Tartib muhim: admin buyruqlari -> to'lov guruhi -> mijoz chati
    # Click guruhi birinchi: u yerdagi har qanday xabar jim qayta ishlanadi va boshqa joyga o'tmaydi
    dp.include_routers(handlers_group.click_router, handlers_admin.router, handlers_group.router,
                       handlers_client.router, handlers_group.silent_router, handlers_group.channel_router)

    try:
        ub = await userbot.start(bot)  # bo'lmasa None — bot o'zi ishlayveradi
    except Exception:
        log.exception("Userbot ishga tushmadi")
        ub = None
    asyncio.create_task(housekeeping(bot))
    ub_txt = "\n👁 Userbot: to'lovlar kuzatilmoqda" if ub else "\n⚠️ Userbot ulanmagan — to'lovlar avtomatik tanilmaydi"
    if config.CLICK_GROUP_ID:
        ub_txt += "\n🔵 Click guruhi jim kuzatilmoqda" + ("" if config.CLICK_SOURCE_IDS else
                                                          " (⚠️ CLICK_SOURCE_IDS berilmagan)")
    sample = publisher.post_link(1).removesuffix("/1")
    await to_group(bot, f"🤖 @{me.username} ishga tushdi. E'lon narxi: {fmt_sum(config.AD_PRICE)} so'm.{ub_txt}"
                        f"\n🔗 Post silkalari: {sample}/…{link_note}")
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
