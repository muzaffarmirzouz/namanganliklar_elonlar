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
from formatting import fmt_sum  # noqa: E402
from services import to_group  # noqa: E402

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
                try:
                    await bot.send_message(
                        o["user_id"],
                        f"⌛️ #{o['id']} e'lon uchun to'lov muddati tugadi ({fmt_sum(o['amount'])} so'm). "
                        "Agar to'lagan bo'lsangiz, chekni adminga yuboring. Yangi e'lon uchun «🆕 Yangi e'lon».",
                        parse_mode=None)
                except Exception:
                    pass
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

    dp = Dispatcher()
    # Tartib muhim: admin buyruqlari -> to'lov guruhi -> mijoz chati
    dp.include_routers(handlers_admin.router, handlers_group.router, handlers_client.router)

    asyncio.create_task(housekeeping(bot))
    await to_group(bot, f"🤖 @{me.username} ishga tushdi. E'lon narxi: {fmt_sum(config.AD_PRICE)} so'm.")
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
