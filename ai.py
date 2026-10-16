"""Claude agent: mijoz bilan suhbat, e'lon ma'lumotlarini yig'ish, to'lov xabarini o'qish."""
import json
import logging
import re
from typing import Awaitable, Callable

from anthropic import AsyncAnthropic

from config import (AD_PRICE, ANTHROPIC_API_KEY, CHANNEL_TITLE, CLAUDE_FAST_MODEL,
                    CLAUDE_MODEL, MAX_PHOTOS)
from formatting import CATEGORY_STYLE, fmt_sum

log = logging.getLogger(__name__)
client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY, max_retries=3, timeout=60)

SYSTEM_PROMPT = f"""Sen "{CHANNEL_TITLE}" Telegram kanalining e'lon qabul qiluvchi yordamchisisan. 24/7 ishlaysan.
Vazifang: mijozdan sotiladigan buyum haqida ma'lumot yig'ish, chiroyli e'lon tayyorlash va to'lovga yo'naltirish.

QOIDALAR:
- Kanal FAQAT sotiladigan buyumlar e'lonlarini qabul qiladi: uy-joy (kvartira, hovli, yer, tijorat bino), avtomobil va moto,
  ehtiyot qismlar, maishiy texnika, telefon/kompyuter, mebel, qurilish mollari, kiyim, bolalar buyumlari, chorva, uskunalar va boshqa buyumlar.
- QABUL QILINMAYDI (muloyim rad et va nima qabul qilinishini ayt): Telegram kanal/guruh/bot reklamasi, yangilik kanallari,
  boshqa e'lon kanallari, onlayn kurs/xizmat reklamasi, ish e'lonlari, kredit/qarz, kazino/bukmeker/stavka, kripto "daromad",
  qurol, dori-darmon, giyohvand, tamaki/alkogol, 18+, hujjat sotish, aldov ehtimoli bor narsalar.
- E'lon narxi: {fmt_sum(AD_PRICE)} so'm. 1 ta e'lon kanalga 1 marta joylanadi. To'lov faqat Payme orqali.
  To'lov silkasini SEN bermaysan — mijoz oldindan ko'rishni tasdiqlagach bot o'zi yuboradi. O'zingdan karta raqami yoki silka o'ylab topma.
- Mijoz qaysi tilda yozsa (o'zbek lotin/kirill, rus) — o'sha tilda javob ber. Qisqa, samimiy yoz, bir xabarda ko'pi bilan 2 ta savol ber.
- Hech qachon faktlarni o'ylab topma. Mijoz aytmagan narx, yil, probeg, maydon va h.k. yozma.

E'LON UCHUN KERAK:
1) category (kategoriya), 2) title — qisqa sarlavha (masalan "Chevrolet Cobalt 2021", "3 xonali kvartira, Yangi Namangan"),
3) price — narx valyutasi bilan ("12 500 $", "450 mln so'm", "Kelishiladi"), 4) location — manzil (tuman/mahalla),
5) phone — telefon raqam, 6) kamida 1 ta rasm (3-4 ta tavsiya qilinadi, ko'pi bilan {MAX_PHOTOS} ta).
Qo'shimcha (ixtiyoriy): condition (holati), details — muhim xususiyatlar ro'yxati
(avto: yili, probeg, rangi, yoqilg'i, karobka; uy: xonalar, qavat, maydon, remont; texnika: modeli, xotira, garantiya),
description — 1-3 gaplik jozibali tavsif (mijoz aytganlari asosida, savodli qilib).

ISH TARTIBI:
- Mijoz ma'lumot bergan zahoti update_ad bilan saqla (bir nechta maydonni birga saqlasa bo'ladi).
- Yetishmayotganini so'ra. Rasm bo'lmasa, 3-4 ta sifatli rasm yuborishni so'ra (rasmlarni bot o'zi qabul qiladi,
  senga "[Tizim: ...]" ko'rinishida xabar keladi).
- Hammasi to'liq bo'lgach show_preview chaqir — bot mijozga tayyor e'lonni ko'rsatadi va tasdiqlash tugmalarini beradi.
- Mijoz boshidan boshlamoqchi bo'lsa reset_ad chaqir.
- "[Tizim: ...]" xabarlari mijozdan emas, botdan keladi — ularga mos javob ber.
"""

CATEGORIES = list(CATEGORY_STYLE.keys())

TOOLS = [
    {
        "name": "update_ad",
        "description": "E'lon qoralamasidagi maydonlarni saqlaydi/yangilaydi. Faqat mijoz aytgan ma'lumotlarni yoz.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": CATEGORIES},
                "title": {"type": "string"},
                "price": {"type": "string"},
                "location": {"type": "string"},
                "phone": {"type": "string"},
                "telegram": {"type": "string", "description": "Mijoz Telegram username'ini ko'rsatishni xohlasa"},
                "condition": {"type": "string"},
                "details": {"type": "array", "items": {"type": "string"},
                            "description": "Masalan ['Yili: 2021', 'Probeg: 45 000 km']. To'liq ro'yxatni yubor (eskisini almashtiradi)."},
                "description": {"type": "string"},
            },
        },
    },
    {
        "name": "show_preview",
        "description": "Barcha kerakli ma'lumot va rasm(lar) bor bo'lsa, mijozga tayyor e'lonni ko'rsatadi.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "reset_ad",
        "description": "Joriy qoralamani o'chirib, yangi e'lonni boshidan boshlaydi.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

ToolHandler = Callable[[str, dict], Awaitable[str]]


async def agent_turn(history: list, user_text: str, state: Callable[[], Awaitable[str]],
                     on_tool: ToolHandler) -> str:
    """Bitta suhbat bosqichi: Claude kerak bo'lsa asboblarni chaqiradi, oxirida javob matni qaytadi.
    `history` faqat matnli user/assistant xabarlaridan iborat; qoralama holati system promptga qo'shiladi."""
    messages = list(history) + [{"role": "user", "content": user_text}]
    final_text = ""
    for _ in range(6):
        resp = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT + "\n\nJORIY HOLAT:\n" + await state(),
            tools=TOOLS,
            messages=messages,
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        if text:
            final_text = text
        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if not tool_uses:
            break
        messages.append({"role": "assistant",
                         "content": [b.model_dump(exclude_none=True) for b in resp.content]})
        results = []
        for tu in tool_uses:
            try:
                out = await on_tool(tu.name, tu.input or {})
            except Exception as e:  # asbob xatosi Claude'ga qaytariladi
                log.exception("tool %s failed", tu.name)
                out = f"Xato: {e}"
            results.append({"type": "tool_result", "tool_use_id": tu.id, "content": out})
        messages.append({"role": "user", "content": results})
    return final_text


PAYMENT_PARSE_PROMPT = """Senga Telegram guruhga tushgan to'lov bildirishnomasi beriladi (Payme yoki bank xabari).
Faqat JSON qaytar, boshqa hech narsa yozma:
{"is_payment": true/false, "incoming": true/false, "amount": <so'mda son yoki null>}
- is_payment: bu pul o'tkazmasi haqidagi xabarmi.
- incoming: pul KIRIM (tushdi, получено, поступление, пополнение, oplata prinyata) bo'lsa true; chiqim/yechildi bo'lsa false.
- amount: o'tkazma summasi (balans emas!), so'mda, tiyinsiz butun son. Masalan "50 037,00 UZS" -> 50037."""


async def parse_payment_text(text: str) -> dict | None:
    try:
        resp = await client.messages.create(
            model=CLAUDE_FAST_MODEL,
            max_tokens=150,
            system=PAYMENT_PARSE_PROMPT,
            messages=[{"role": "user", "content": text[:3000]}],
        )
        raw = "".join(b.text for b in resp.content if b.type == "text")
        m = re.search(r"\{.*\}", raw, re.S)
        return json.loads(m.group()) if m else None
    except Exception:
        log.exception("payment parse failed")
        return None
