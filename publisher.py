"""E'lonni kanalga (yoki mijozga oldindan ko'rish uchun) albom qilib yuborish."""
import os
import re
from html import unescape
from aiogram import Bot
from aiogram.types import InputMediaPhoto, InputMediaVideo

import db
from config import CHANNEL_ID, CHANNEL_TITLE, CHANNEL_USERNAME
from formatting import TEXT_LIMIT, build_caption, build_footer

BOT_USERNAME = ""  # main.py ishga tushganda to'ldiradi


def footer() -> str:
    # "E'lon berish:" qatorida ko'rinadigan username (ELON_CONTACT bo'lmasa — botning o'zi)
    contact = os.getenv("ELON_CONTACT", "").strip().lstrip("@") or BOT_USERNAME
    return build_footer(CHANNEL_USERNAME, CHANNEL_TITLE, contact)


def media_item(x) -> tuple[str, str]:
    """photos ro'yxatidagi element: eski format — oddiy file_id (rasm), yangi — {"t": "video", "id": ...}."""
    if isinstance(x, dict):
        return x.get("t", "photo"), x["id"]
    return "photo", x


async def send_ad(bot: Bot, chat_id: int, order: dict, **kw) -> list[int]:
    """Rasm/videolar albom bo'lib, birinchisining tagida bezatilgan matn. Media bo'lmasa — oddiy matn.
    kw — business lichka uchun business_connection_id."""
    items = [media_item(x) for x in order["photos"][:10]]
    if not items:
        caption = build_caption(order["data"], footer(), limit=TEXT_LIMIT)
        msg = await bot.send_message(chat_id, caption, disable_web_page_preview=True, **kw)
        return [msg.message_id]

    caption = build_caption(order["data"], footer()) or None
    if len(items) == 1:
        kind, fid = items[0]
        if kind == "video":
            msg = await bot.send_video(chat_id, fid, caption=caption, **kw)
        else:
            msg = await bot.send_photo(chat_id, fid, caption=caption, **kw)
        return [msg.message_id]

    media = []
    for i, (kind, fid) in enumerate(items):
        extra = {"caption": caption, "parse_mode": "HTML"} if i == 0 and caption else {}
        media.append(InputMediaVideo(media=fid, **extra) if kind == "video" else InputMediaPhoto(media=fid, **extra))
    msgs = await bot.send_media_group(chat_id, media, **kw)
    return [m.message_id for m in msgs]


def post_link(msg_id: int) -> str:
    if CHANNEL_USERNAME:
        return f"https://t.me/{CHANNEL_USERNAME}/{msg_id}"
    # yopiq kanal: -1001234567890 -> c/1234567890
    return f"https://t.me/c/{str(CHANNEL_ID).removeprefix('-100')}/{msg_id}"


def channel_link() -> str:
    return f"https://t.me/{CHANNEL_USERNAME}" if CHANNEL_USERNAME else ""


def norm_text(t: str) -> str:
    """Solishtirish uchun: teglarsiz, kichik harf, bo'shliqlar bitta, boshidagi 120 belgi."""
    t = unescape(re.sub(r"<[^>]+>", "", t or ""))
    return " ".join(t.lower().split())[:120]


def expected_text(order: dict) -> str:
    items = order["photos"][:10]
    caption = build_caption(order["data"], footer(), limit=TEXT_LIMIT if not items else 1024)
    return norm_text(caption)


async def publish(bot: Bot, order: dict) -> tuple[str, bool]:
    """Qaytaradi: (silka, pending). pending=True — Telegram postni navbatga qo'ydi (katta kanalga video),
    haqiqiy raqami hali yo'q (message_id=0). Unda vaqtincha kanal silkasi qaytadi."""
    ids = await send_ad(bot, CHANNEL_ID, order)
    await db.mark_published(order["id"], ids)
    if not ids or ids[0] == 0:
        return channel_link() or post_link(0), True
    return post_link(ids[0]), False


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
