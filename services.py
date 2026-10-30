"""To'lov tasdiqlangach: kanalga joylash va hammaga xabar berish."""
import asyncio
import datetime
import logging
import random
import time
from html import escape

from aiogram import Bot

import db
import publisher
from config import PAYMENT_GROUP_ID, POST_SLOTS, TARIFFS
from formatting import fmt_sum, is_job, is_nonsale
from texts import t

log = logging.getLogger(__name__)


_publish_locks: dict[int, asyncio.Lock] = {}


async def confirm_and_publish(bot: Bot, order_id: int, paid_by: str, manual: bool = False) -> str:
    """To'lov tasdiqlanganda chaqiriladi. Qaytaradi: guruhga yoziladigan qisqa natija matni.
    E'lon tayyor va mijoz tasdiqlagan bo'lsa — darhol joylanadi. Aks holda (avval to'lov, keyin e'lon) —
    bot mijoz bilan e'lonni tayyorlaydi, mijoz tasdiqlagach o'zi joylaydi."""
    from order_rules import missing_fields, ready_to_publish
    if not await db.mark_paid(order_id, paid_by, allow_expired=manual):
        o = await db.get_order(order_id)
        st = o["status"] if o else "yo'q"
        return f"⚠️ #{order_id} buyurtma tasdiqlanmadi (holati: {st})."

    order = await db.get_order(order_id)
    uid = order["user_id"]
    if ready_to_publish(order):
        await notify_user(bot, uid, "paid")
        return await publish_order(bot, order_id)

    # Avval to'lov, keyin e'lon: endi mijoz bilan e'lonni tayyorlaymiz
    await notify_user(bot, uid, "paid_collect")
    miss = missing_fields(order)
    note = (f"[Tizim: #{order_id} uchun to'lov TUSHDI ({fmt_sum(order['amount'])} so'm). Endi e'lonni tayyorlash kerak. "
            + ("Yetishmayapti: " + ", ".join(miss) + ". Mijozdan shularni so'ra (bir-ikki savol bilan)."
               if miss else "Hamma ma'lumot bor — show_preview chaqirib, mijozga tayyor e'lonni ko'rsat.")
            + " Mijoz tayyor e'lonni tasdiqlasa — publish_now.]")
    asyncio.create_task(_ai_followup(bot, uid, note))
    return (f"💰 #{order_id} — {fmt_sum(order['amount'])} so'm to'landi. E'lon hali tayyor emas"
            + (f" (yetishmayapti: {', '.join(miss)})" if miss else " (mijoz tasdiqlashi kerak)")
            + " — bot mijoz bilan tayyorlab, tasdiqlagach o'zi joylaydi.")


async def _ai_followup(bot: Bot, uid: int, note: str) -> None:
    from handlers_client import run_ai  # aylanma importdan qochish uchun shu yerda
    try:
        await asyncio.sleep(2)
        await run_ai(bot, uid, note)
    except Exception:
        log.exception("to'lovdan keyingi AI javobi ishlamadi")


async def publish_order(bot: Bot, order_id: int) -> str:
    """To'langan buyurtmani kanalga joylaydi, mijozga xabar beradi, tarif bo'lsa kampaniyani boshlaydi.
    Ikki marta joylanmasligi uchun buyurtma bo'yicha qulf ishlatiladi."""
    lock = _publish_locks.setdefault(order_id, asyncio.Lock())
    async with lock:
        order = await db.get_order(order_id)
        if not order or order["status"] != "paid":
            return f"#{order_id} joylanmadi: holati {order['status'] if order else 'yo‘q'} (faqat to'langan e'lon joylanadi)."
        try:
            link, pending = await publisher.publish(bot, order)
        except Exception as e:
            log.exception("publish failed")
            await notify_user(bot, order["user_id"], "publish_delay")
            return (f"❗️ #{order_id} to'langan, lekin kanalga joylanmadi: {escape(str(e))}\n"
                    f"Qayta urinish: /joyla {order_id}")

        kind = "published_job" if is_job(order["data"]) else "published_service" if is_nonsale(order["data"]) else "published"
        await notify_user(bot, order["user_id"], kind, link=link)
        if pending:
            asyncio.create_task(resolve_post_link(bot, order_id))
        days = int(order["data"].get("_days") or 1)
        if days > 1 and days in TARIFFS:
            await start_campaign(order_id, days)
            await notify_user(bot, order["user_id"], "campaign_started", days=days)
        # Suhbatni tozalamaymiz — AI e'lon joylanganini bilsin ("rahmat"ga to'g'ri javob bersin)
        await db.add_history_note(order["user_id"],
                                  f"[Tizim: #{order_id} e'lon to'langan va kanalga joylandi: {link}. Mijozga xabar berildi.]")
        return (f"✅ #{order_id} — {fmt_sum(order['amount'])} so'm, kanalga joylandi: {link}"
                + ("\n⏳ Telegram postni navbatga qo'ydi (video), aniq silka chiqqach mijozga yuboriladi" if pending else ""))


async def republish(bot: Bot, order_id: int) -> str:
    """Admin /joyla: to'langan, lekin joylanmagan e'lonni (tayyorlanayotgan bo'lsa ham) joylaydi."""
    return await publish_order(bot, order_id)


async def remind_unpublished(bot: Bot) -> None:
    """To'langan-u, kanalga chiqmagan e'lonlar: tayyor bo'lsa joylaydi; tayyor bo'lmasa 3 soatdan keyin mijozga
    1 marta eslatma, 24 soatdan keyin guruhga 1 marta ogohlantirish."""
    from order_rules import ready_to_publish
    now = time.time()
    for o in await db.paid_unpublished():
        age = now - (o.get("paid_at") or now)
        d = o["data"]
        if ready_to_publish(o):
            # Tayyor va tasdiqlangan, lekin joylanmay qolgan (masalan to'lov va "ha" bir vaqtda kelgan) — 1 marta urinamiz
            if age > 120 and not d.get("_auto_pub"):
                await db.update_data(o["id"], {"_auto_pub": int(now)})
                await to_group(bot, await publish_order(bot, o["id"]))
            continue
        if age > 3 * 3600 and not d.get("_rem_client"):
            await db.update_data(o["id"], {"_rem_client": int(now)})
            await notify_user(bot, o["user_id"], "paid_collect_reminder")
        if age > 24 * 3600 and not d.get("_rem_admin"):
            await db.update_data(o["id"], {"_rem_admin": int(now)})
            await to_group(bot, f"⏰ #{o['id']} «{escape(d.get('title', ''))}» — to'langaniga 1 kundan oshdi, e'lon hali "
                                f"tayyor emas. Mijoz: <a href=\"tg://user?id={o['user_id']}\">{o['user_id']}</a>. "
                                f"O'zingiz yozib qo'ying yoki bor ma'lumot bilan joylash: /joyla {o['id']}")


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


# ================= Uzoq tariflar: har kuni 1 marta, har xil vaqtda =================
def _slot_index(hour: int) -> int:
    for i, (lo, hi) in enumerate(POST_SLOTS):
        if lo <= hour < hi:
            return i
    return 0 if hour < POST_SLOTS[0][0] else len(POST_SLOTS) - 1


def plan_post(start_date: datetime.date, day: int, start_slot: int) -> int:
    """day-kun (0 dan) uchun joylash vaqti: oraliqlar navbatma-navbat (ertalab → tush → kechqurun), tasodifiy daqiqa."""
    lo, hi = POST_SLOTS[(start_slot + day) % len(POST_SLOTS)]
    minute = random.randint(lo * 60, hi * 60 - 1)
    when = datetime.datetime.combine(start_date + datetime.timedelta(days=day),
                                     datetime.time(minute // 60, minute % 60))
    return int(when.timestamp())


def plan_reminder(posted_at: int) -> int:
    """Post chiqqandan ~2 soat keyin; tunda yozmaymiz (22:00 dan keyin bo'lsa — ertasi 08:00)."""
    t = datetime.datetime.fromtimestamp(posted_at + 2 * 3600)
    if t.hour >= 22 or t.hour < 8:
        day = t.date() + datetime.timedelta(days=1 if t.hour >= 22 else 0)
        t = datetime.datetime.combine(day, datetime.time(8, 0))
    return int(t.timestamp())


async def start_campaign(order_id: int, days: int) -> None:
    now = datetime.datetime.now()
    slot = _slot_index(now.hour)
    first = (await db.get_order(order_id))["channel_msgs"][:1]
    await db.update_data(order_id, {
        "_all_posts": [x for x in first if x],   # tarifdagi barcha postlar (sotildi/to'xtatildi hammasiga qo'yiladi)
        "_camp_active": True, "_camp_days": days, "_camp_posted": 1,
        "_camp_start": now.date().isoformat(), "_camp_slot": slot,
        "_camp_next": plan_post(now.date(), 1, slot),
        "_camp_remind": plan_reminder(int(now.timestamp())),   # 1-kundan keyin — yangilash eslatmasi
    })


async def run_campaigns(bot: Bot) -> None:
    """main.housekeeping har daqiqada chaqiradi: vaqti kelgan postlarni joylaydi va eslatmalarni yuboradi."""
    now = time.time()
    for o in await db.active_campaigns():
        d = o["data"]
        days, posted = int(d.get("_camp_days") or 1), int(d.get("_camp_posted") or 1)
        title = escape(d.get("title", ""))
        if d.get("_sold") or d.get("_stopped"):
            await db.update_data(o["id"], {"_camp_active": False})
            await to_group(bot, f"⏹ #{o['id']} «{title}» tarifi to'xtatildi (e'lon yopilgan), {posted}/{days} kun chiqdi")
            continue
        remind = int(d.get("_camp_remind") or 0)
        if remind and now >= remind and posted < days:
            await notify_user(bot, o["user_id"], "campaign_refresh")
            await db.add_history_note(o["user_id"], f"[Tizim: #{o['id']} tarifli e'lon uchun mijozdan ertangi postga "
                                                    "yangi rasm/video so'raldi. Kelsa — apply_to_campaign chaqir.]")
            await db.update_data(o["id"], {"_camp_remind": 0})
        if now < int(d.get("_camp_next") or 0):
            continue
        try:
            link, pending = await publisher.publish(bot, o)
        except Exception as e:
            log.exception("kampaniya postini joylab bo'lmadi")
            await to_group(bot, f"❗️ #{o['id']} tarif posti ({posted + 1}/{days}) joylanmadi: <code>{escape(str(e))[:300]}</code>\n"
                                "10 daqiqadan keyin qayta uriniladi")
            await db.update_data(o["id"], {"_camp_next": int(now) + 600})
            continue
        posted += 1
        upd = {"_camp_posted": posted}
        new_id = ((await db.get_order(o["id"]))["channel_msgs"] or [0])[0]
        if new_id:
            upd["_all_posts"] = list(d.get("_all_posts") or []) + [new_id]
        if pending:
            asyncio.create_task(resolve_post_link(bot, o["id"]))
        else:
            await notify_user(bot, o["user_id"], "campaign_posted", n=posted, days=days, link=link)
        await to_group(bot, f"📅 #{o['id']} «{title}» — {posted}/{days}-kun joylandi: {link}")
        if posted >= days:
            upd["_camp_active"] = False
            await notify_user(bot, o["user_id"], "campaign_done", days=days)
            await to_group(bot, f"🏁 #{o['id']} «{title}» — {days} kunlik tarif tugadi")
        else:
            start = datetime.date.fromisoformat(d.get("_camp_start"))
            upd["_camp_next"] = plan_post(start, posted, int(d.get("_camp_slot") or 0))
            if posted % 2 == 1:  # kun ora (1, 3, 5 ... -kunlardan keyin) yangilashni so'raymiz
                upd["_camp_remind"] = plan_reminder(int(now))
        await db.update_data(o["id"], upd)
