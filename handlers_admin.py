"""Admin buyruqlari (shaxsiy chatda ham, to'lov guruhida ham ishlaydi) va chekni tasdiqlash tugmalari."""
import time
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

import db
from config import ADMIN_IDS
from formatting import fmt_sum
from services import confirm_and_publish, notify_user, republish

router = Router()
is_admin = F.from_user.id.in_(ADMIN_IDS)


@router.message(Command("id"))
async def cmd_id(m: Message):
    """Sozlash uchun: guruh/kanal/foydalanuvchi ID sini ko'rsatadi."""
    text = f"Chat ID: <code>{m.chat.id}</code>\nSizning ID: <code>{m.from_user.id}</code>"
    if m.reply_to_message and m.reply_to_message.from_user:
        u = m.reply_to_message.from_user
        text += f"\nJavob berilgan xabar egasi: <code>{u.id}</code> ({'bot' if u.is_bot else 'odam'})"
    for src in (m, m.reply_to_message):
        origin = getattr(src, "forward_origin", None) if src else None
        if origin and getattr(origin, "chat", None):
            text += f"\nForward qilingan kanal: <code>{origin.chat.id}</code> ({escape(origin.chat.title or '')})"
            break
    await m.answer(text)


@router.message(Command("tasdiq"), is_admin)
async def cmd_confirm(m: Message, command: CommandObject, bot: Bot):
    if not command.args or not command.args.strip().lstrip("#").isdigit():
        await m.answer("Ishlatish: /tasdiq 123")
        return
    oid = int(command.args.strip().lstrip("#"))
    res = await confirm_and_publish(bot, oid, f"admin:{m.from_user.id}", manual=True)
    await m.answer(res)


@router.message(Command("joyla"), is_admin)
async def cmd_republish(m: Message, command: CommandObject, bot: Bot):
    if not command.args or not command.args.strip().isdigit():
        await m.answer("Ishlatish: /joyla 123")
        return
    try:
        await m.answer(await republish(bot, int(command.args.strip())))
    except Exception as e:
        await m.answer(f"Xato: {escape(str(e))}")


@router.message(Command("bekor"), is_admin)
async def cmd_cancel(m: Message, command: CommandObject):
    if not command.args or not command.args.strip().isdigit():
        await m.answer("Ishlatish: /bekor 123")
        return
    oid = int(command.args.strip())
    o = await db.get_order(oid)
    if not o or o["status"] not in ("draft", "awaiting_payment", "expired"):
        await m.answer("Bu buyurtmani bekor qilib bo'lmaydi.")
        return
    await db.set_status(oid, "cancelled")
    await m.answer(f"#{oid} bekor qilindi.")


@router.message(Command("ai"), is_admin)
async def cmd_resume_ai(m: Message, command: CommandObject):
    """Siz lichkada mijozga o'zingiz yozgach bot o'sha chatda jim turadi. /ai USER_ID — qayta yoqadi."""
    if not command.args or not command.args.strip().isdigit():
        await m.answer("Ishlatish: /ai USER_ID  (mijoz ID si «to'lov kutilmoqda» xabaridagi ismga bosib ko'rinadi)\n"
                       "Yoki mijoz chatining o'zida /ai deb yozing.")
        return
    await db.set_pause(int(command.args.strip()), 0)
    await m.answer("✅ Bot shu mijoz bilan yana javob beradi.")


@router.message(Command("kutilmoqda"), is_admin)
async def cmd_awaiting(m: Message):
    orders = await db.awaiting_orders()
    if not orders:
        await m.answer("To'lov kutayotgan e'lon yo'q.")
        return
    lines = [f"#{o['id']} — {fmt_sum(o['amount'])} so'm — {escape(o['data'].get('title', '?'))}" for o in orders]
    await m.answer("⏳ To'lov kutilmoqda:\n" + "\n".join(lines))


@router.message(Command("stat"), is_admin)
async def cmd_stat(m: Message):
    lt = time.localtime()
    today = int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)))
    d = await db.stats(today)
    month = await db.stats(int(time.mktime((lt.tm_year, lt.tm_mon, 1, 0, 0, 0, 0, 0, -1))))
    await m.answer(
        f"📊 <b>Statistika</b>\n\n"
        f"Bugun: {d['published']} ta e'lon — {fmt_sum(d['sum'])} so'm\n"
        f"Shu oy: {month['published']} ta e'lon — {fmt_sum(month['sum'])} so'm\n"
        f"To'lov kutmoqda: {d['awaiting']} ta\n"
        f"Foydalanuvchilar: {d['users']}"
    )


# ---- chek tugmalari (to'lov guruhida) ----
@router.callback_query(F.data.startswith("adm_ok:"))
async def cb_adm_ok(cb: CallbackQuery, bot: Bot):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("Faqat admin tasdiqlay oladi", show_alert=True)
        return
    oid = int(cb.data.split(":")[1])
    await cb.answer("Tekshirilmoqda…")
    res = await confirm_and_publish(bot, oid, f"admin:{cb.from_user.id}", manual=True)
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.reply(res + f"\n👤 {escape(cb.from_user.full_name)}")


@router.callback_query(F.data.startswith("adm_no:"))
async def cb_adm_no(cb: CallbackQuery, bot: Bot):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer("Faqat admin rad eta oladi", show_alert=True)
        return
    oid = int(cb.data.split(":")[1])
    o = await db.get_order(oid)
    await cb.answer("Rad etildi")
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.reply(f"❌ #{oid} cheki rad etildi — {escape(cb.from_user.full_name)}")
    if o and o["status"] == "awaiting_payment":
        await notify_user(bot, o["user_id"], "rejected", amount=fmt_sum(o["amount"]))
