"""E'lonni kanalga (yoki mijozga oldindan ko'rish uchun) albom qilib yuborish."""
import os
from aiogram import Bot
from aiogram.types import InputMediaPhoto

import db
from config import CHANNEL_ID, CHANNEL_TITLE, CHANNEL_USERNAME
from formatting import TEXT_LIMIT, build_caption, build_footer

BOT_USERNAME = ""  # main.py ishga tushganda to'ldiradi


def footer() -> str:
    # "E'lon berish:" qatorida ko'rinadigan username (ELON_CONTACT bo'lmasa — botning o'zi)
    contact = os.getenv("ELON_CONTACT", "").strip().lstrip("@") or BOT_USERNAME
    return build_footer(CHANNEL_USERNAME, CHANNEL_TITLE, contact)


async def send_ad(bot: Bot, chat_id: int, order: dict, **kw) -> list[int]:
    """Rasmlar albom bo'lib, birinchi rasm tagida bezatilgan matn. Rasm bo'lmasa — oddiy matn.
    kw — business lichka uchun business_connection_id."""
    photos = order["photos"][:10]
    if not photos:
        caption = build_caption(order["data"], footer(), limit=TEXT_LIMIT)
        msg = await bot.send_message(chat_id, caption, disable_web_page_preview=True, **kw)
        return [msg.message_id]

    caption = build_caption(order["data"], footer())
    if len(photos) == 1:
        msg = await bot.send_photo(chat_id, photos[0], caption=caption, **kw)
        return [msg.message_id]

    media = [InputMediaPhoto(media=fid) for fid in photos]
    media[0] = InputMediaPhoto(media=photos[0], caption=caption, parse_mode="HTML")
    msgs = await bot.send_media_group(chat_id, media, **kw)
    return [m.message_id for m in msgs]


def post_link(msg_id: int) -> str:
    if CHANNEL_USERNAME:
        return f"https://t.me/{CHANNEL_USERNAME}/{msg_id}"
    # yopiq kanal: -1001234567890 -> c/1234567890
    return f"https://t.me/c/{str(CHANNEL_ID).removeprefix('-100')}/{msg_id}"


async def publish(bot: Bot, order: dict) -> str:
    ids = await send_ad(bot, CHANNEL_ID, order)
    await db.mark_published(order["id"], ids)
    return post_link(ids[0])


async def edit_post(bot: Bot, order: dict) -> str:
    """Kanaldagi postning matnini yangilaydi (rasmlar o'zgarmaydi). Qaytaradi: post silkasi."""
    msg_id = order["channel_msgs"][0]  # albomda izoh birinchi rasmda turadi
    try:
        if order["photos"]:
            await bot.edit_message_caption(chat_id=CHANNEL_ID, message_id=msg_id,
                                           caption=build_caption(order["data"], footer()))
        else:
            await bot.edit_message_text(build_caption(order["data"], footer(), limit=TEXT_LIMIT),
                                        chat_id=CHANNEL_ID, message_id=msg_id, disable_web_page_preview=True)
    except Exception as e:
        if "not modified" not in str(e).lower():  # matn o'zgarmagan bo'lsa — xato emas
            raise
    return post_link(msg_id)
