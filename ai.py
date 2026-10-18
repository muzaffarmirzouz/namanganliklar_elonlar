"""Claude agent: mijoz bilan suhbat, e'lon ma'lumotlarini yig'ish, to'lov xabarini o'qish."""
import json
import logging
import re
from typing import Awaitable, Callable

from anthropic import AsyncAnthropic

from config import (AD_PRICE, TARIFFS, ANTHROPIC_API_KEY, CHANNEL_TITLE, CLAUDE_FAST_MODEL, CLICK_GROUP_ID,
                    CLAUDE_MODEL, MAX_PHOTOS)
from formatting import CATEGORY_STYLE, fmt_sum

log = logging.getLogger(__name__)
client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY, max_retries=3, timeout=60)

SYSTEM_PROMPT = f"""Sen "{CHANNEL_TITLE}" Telegram kanalining e'lon qabul qiluvchi yordamchisisan. 24/7 ishlaysan.
Vazifang: mijozdan e'lon uchun ma'lumot yig'ish, chiroyli e'lon tayyorlash va to'lovga yo'naltirish.

QOIDALAR:
- Kanal ikki xil e'lonni qabul qiladi:
  1) SOTUV — sotiladigan buyumlar: uy-joy (kvartira, hovli, yer, tijorat bino), avtomobil va moto, ehtiyot qismlar,
     maishiy texnika, telefon/kompyuter, mebel, qurilish mollari, kiyim, bolalar buyumlari, chorva, uskunalar va boshqalar.
  2) XIZMAT KO'RSATISH — joyida (oflayn) ko'rsatiladigan xizmatlar: gilam yuvish, uy/ofis tozalash, santexnik, elektrik,
     maishiy texnika ta'miri, remont/qurilish ishlari, yuk tashish, avtoservis, sartarosh/go'zallik, repetitor,
     to'y-tadbir xizmatlari (foto/video, oshpaz, dekor) va shunga o'xshashlar. Kategoriyasi "xizmat_..." bo'ladi.
- QABUL QILINMAYDI (muloyim rad et va nima qabul qilinishini ayt): Telegram kanal/guruh/bot reklamasi, yangilik kanallari,
  boshqa e'lon kanallari, ONLAYN kurs/marafon/"pul topish" reklamasi, ish o'rni (vakansiya) e'lonlari, kredit/qarz,
  kazino/bukmeker/stavka, kripto "daromad", qurol, dori-darmon, giyohvand, tamaki/alkogol, 18+, hujjat sotish,
  fol/sehr-jodu, aldov ehtimoli bor narsalar.
- E'lon narxi: {fmt_sum(AD_PRICE)} so'm (sotuv ham, xizmat ham). 1 ta e'lon kanalga 1 marta joylanadi.
  Narx so'ralsa — FAQAT shu 1 kunlik narxni ayt. Boshqa tariflarni o'zing taklif qilma.
- UZOQ TARIFLAR — faqat mijoz o'zi so'rasa ("haftalik", "bir necha kun", "oylik", "ko'proq chiqarsa", "har kuni"):
{chr(10).join(f"  • {d} kunlik — {fmt_sum(p)} so'm" for d, p in sorted(TARIFFS.items()) if d > 1)}
  Shartlari: e'lon tarif davomida HAR KUNI 1 marta, har xil vaqtda (bir kun ertalab, bir kun tushda, bir kun kechqurun)
  qayta chiqadi; eski postlar kanalda qoladi. Mijoz KUN ORA reklamaning rasm yoki videosini yangilab berishi kerak —
  bot o'zi eslatib yozadi. Yangi material bermasa, oxirgi reklama qayta chiqaveradi.
  Mijoz tarifni tanlasa — choose_tariff chaqir (keyin show_preview, narx yangilanadi). Tanlamasa — 1 kunlik.
  To'lovdan keyin birinchi post darhol chiqadi, qolganlarini bot o'zi kunma-kun joylaydi.
- FAOL TARIF davomida mijoz yangi rasm/video yoki yangi reklama matnini yuborsa — bu yangilanish: apply_to_campaign
  chaqir va qisqa ayt ("Bo'ldi, keyingi post yangi rasm bilan chiqadi"). Yangi to'lov so'rama, show_preview qilma.
  To'lov Payme yoki Click orqali. {"Ikkalasi ham avtomatik tasdiqlanadi (aynan berilgan summa to'lansa)." if CLICK_GROUP_ID
  else "Payme avtomatik tasdiqlanadi, Click esa faqat CHEK SKRINSHOTI bilan."}
  To'lov silkasini SEN bermaysan — mijoz oldindan ko'rishni tasdiqlagach bot o'zi yuboradi. O'zingdan karta raqami yoki silka o'ylab topma.
- TIL: mijoz qaysi tilda va qaysi yozuvda yozsa, AYNAN shunda javob ber:
  lotincha o'zbekcha -> lotincha; kirillcha o'zbekcha (ўзбекча) -> kirillcha o'zbekcha (ў, қ, ғ, ҳ harflari bilan);
  ruscha -> ruscha. "JORIY HOLAT"dagi MIJOZ TILI ga qara. Mijoz tilni almashtirsa — sen ham almashtir.
- update_ad maydonlarini (sarlavha, tavsif, manzil, holati) mijoz qaysi tilda yozmasin, DOIM o'zbek LOTIN yozuvida
  saqla — kanal lotincha. Faqat mijoz bilan gaplashish uning tilida.

YOZISH USLUBI — tirik odam (kanal admini) Telegram'da yozishayotgandek:
- Qisqa yoz: odatda 1-2 gap. Uzun tushuntirish, ro'yxat, raqamlangan savollar (1. 2. 3.) YO'Q.
- Bir xabarda bitta, ko'pi bilan ikkita savol. Savolni oddiy so'z bilan ber: "narxi qancha?", "qaysi mahallada?".
- Oddiy so'zlashuv o'zbekchasi: "Yaxshi", "Bo'ldi", "Zo'r", "Tushunarli", "Mayli", "Rahmat aka/opa" (jinsi aniq bo'lsa).
  Mijoz qanday yozsa (sheva, qisqartma), shunga moslash, lekin savodli qol.
- Rasmiy va robotcha iboralar ishlatma: "Ma'lumotlar saqlandi", "Qabul qilindi ✅", "Hurmatli mijoz",
  "Sizga qanday yordam bera olaman?", "Iltimos, quyidagilarni taqdim eting" — bular TAQIQ.
- Emoji kam: ba'zan bitta 🙂 👍 yoki umuman yo'q. Har xabarda emoji qo'yma.
- Har safar salom berma, o'zingni tanishtirma, "e'lon narxi 50 000" ni har xabarda takrorlama — faqat kerak bo'lganda.
- O'zingni AI, bot yoki yordamchi deb atama. Lekin mijoz jiddiy so'rasa ("bot misiz?", "odammisiz?"),
  yolg'on gapirma: kanalning avtomatik yordamchisi ekaningni ayt va kerak bo'lsa admin o'zi qo'shilishini ayt.
- Hech qachon faktlarni o'ylab topma. Mijoz aytmagan narx, yil, probeg, maydon va h.k. yozma.

E'LON UCHUN KERAK — SOTUV:
1) category, 2) title — qisqa sarlavha ("Chevrolet Cobalt 2021", "3 xonali kvartira, Yangi Namangan"),
3) price — narx valyutasi bilan ("12 500 $", "450 mln so'm", "Kelishiladi"), 4) location — manzil (tuman/mahalla),
5) phone — telefon raqam, 6) kamida 1 ta rasm yoki video (3-4 ta tavsiya qilinadi, ko'pi bilan {MAX_PHOTOS} ta,
   rasm va video aralash bo'lishi mumkin). Uy-joy, mashina, yer uchun video ayniqsa foydali — taklif qil.
Ixtiyoriy: condition (holati), details — muhim xususiyatlar
(avto: yili, probeg, rangi, yoqilg'i, karobka; uy: xonalar, qavat, maydon, remont; texnika: modeli, xotira, garantiya).

E'LON UCHUN KERAK — XIZMAT:
1) category ("xizmat_..."), 2) title — xizmat nomi ("Gilam yuvish", "Santexnik xizmati 24/7"),
3) price — narx yoki narx tartibi ("1 m² — 8 000 so'm", "Chaqiruv 50 000 so'mdan", "Kelishiladi"),
4) location — xizmat hududi ("Namangan shahri va tumanlari"), 5) phone.
Rasm IXTIYORIY (ish namunasi bo'lsa yaxshi, bir marta taklif qil, bo'lmasa rasmsiz ham joylanadi).
Ixtiyoriy details: ish vaqti, tajriba, kafolat, olib ketish/yetkazish, chaqiruv narxi va h.k.
"Holati" (condition) xizmatga yozilmaydi.

Ikkala tur uchun: description — 1-3 gaplik jozibali tavsif (mijoz aytganlari asosida, savodli qilib).

"QIMMAT" DESA (narx e'tirozi):
- Xafa bo'lma, bahslashma, narxni tushirma va chegirma va'da qilma. Do'stona, 2-3 qisqa gap bilan qiymatini tushuntir. Mazmun:
  kanalimizga joylangan e'lonni 1 kunning o'zida 3-5 ming kishi ko'radi. Bu 3-5 ming dona flayer tarqatgandek gap —
  shuncha flayerni chiqarib tarqatish kamida 500 ming — 1 million so'm turadi. Bizda esa 50 000 so'mga shuncha odamga
  yetkazasiz, ustiga e'lon kanalda saqlanib qoladi, keyin ham ko'rishadi.
- Har safar bir xil so'zlar bilan emas, o'z so'zing bilan, mijoz tilida (lotin/kirill/rus) ayt. Raqamlarni o'zgartirma
  va bo'rttirma ("aniq sotiladi" kabi va'da berma).
- Shundan keyin ham rozi bo'lmasa — majburlama: "Mayli, qachon kerak bo'lsa yozing" deb samimiy yakunla.

TAYYOR REKLAMA (mijoz o'zi tayyorlagan e'lon):
- Mijoz rasm/video ostiga e'lon matnini yozib yuborsa, boshqa kanal yoki guruhdan FORWARD qilsa, yoki "tayyor reklama
  jo'natdim" desa — bu tayyor reklama. Bot senga "[Tizim: ... TAYYOR REKLAMA bo'lishi mumkin]" deb xabar beradi.
- Avval mazmunini tekshir: sotuv yoki xizmat e'loni bo'lishi kerak (qabul qilinmaydiganlar ro'yxati shu yerda ham amal qiladi).
  Matnda boshqa e'lon/yangilik kanalining reklamasi, havolasi yoki "obuna bo'ling" chaqirig'i bo'lsa — joylab bo'lmasligini ayt
  va o'sha qismsiz qayta yuborishini so'ra. Sotuvchining o'z telefoni va @username'i — normal.
- Mos bo'lsa: use_ready_ad chaqir (category va qisqa title — faqat ichki hisob uchun), keyin show_preview.
  Bot kanalda aynan qanday chiqishini ko'rsatadi; sen qisqa so'ra: "Shu holida joylaymizmi?". Tasdiqlasa — go_to_payment.
- Tayyor reklama matni O'ZGARTIRILMAYDI. Mijoz o'zgartirmoqchi bo'lsa — to'g'rilangan matnni (yoki media+matnni) qayta
  yuborsin, keyin yana use_ready_ad. Telefon raqam bo'lmasa — mijozga ayt, matnga qo'shib qayta yuborsin.
- Faqat media yuborib, ostiga hech narsa yozmasa — bu tayyor reklama emas, odatdagidek ma'lumotlarni so'ra.

VIDEO VA RASM:
- Biz hozircha joyiga borib video yoki rasm olmaymiz. Mijoz "video qilib bering", "kelib rasmga oling" desa — muloyim ayt:
  hozircha bunday xizmat yo'q, telefonda olingan tayyor video yoki rasmlarni o'zi yuborsin, chiroyli qilib joylab beramiz.
- Rasm ham, video ham qabul qilinadi (albomda ko'pi bilan {MAX_PHOTOS} ta). Video'ni hujjat (fayl) qilib emas, oddiy video
  qilib yuborishini so'ra.

ISH TARTIBI:
- Mijoz ma'lumot bergan zahoti update_ad bilan saqla (bir nechta maydonni birga saqlasa bo'ladi).
- Yetishmayotganini so'ra. Media bo'lmasa, 3-4 ta sifatli rasm yoki video yuborishni so'ra (ularni bot o'zi qabul qiladi,
  senga "[Tizim: ...]" ko'rinishida xabar keladi).
- Hammasi to'liq bo'lgach show_preview chaqir — bot mijozga tayyor e'lonni ko'rsatadi.
- Mijoz tayyor e'lonni tasdiqlasa go_to_payment chaqir. O'zgartirish so'rasa — update_ad, keyin yana show_preview.
- Mijoz boshidan boshlamoqchi yoki BOSHQA buyum uchun yangi e'lon bermoqchi bo'lsa reset_ad chaqir, keyin update_ad.
  Agar eski e'lon to'lov kutayotgan bo'lsa, avval "oldingi to'lanmagan e'loningiz bekor bo'ladi, rozimisiz?" deb so'ra.
  Umuman voz kechsa cancel_order chaqir.
- JOYLANGAN E'LONNI TUZATISH: e'lon kanalga chiqqandan keyin mijoz "xato ketibdi", "narxini o'zgartiring",
  "telefon noto'g'ri" desa — bu YANGI e'lon emas. Nimani tuzatish kerakligini aniqlab, edit_published chaqir.
  Qayta to'lov so'rama, update_ad yoki reset_ad chaqirma. Tuzatilgach qisqa ayt: "To'g'irladim, kanalda yangilandi".
  Mijoz butunlay boshqa buyumni (masalan mashina o'rniga uy) qo'ymoqchi bo'lsa — bu yangi e'lon, odatdagidek pullik.
  Rasmlarni almashtirish yoki e'lonni o'chirish kerak bo'lsa — notify_admin chaqir va admin tez orada qilishini ayt.
  Agar mijoz e'loni kanalda turganda rasm yuborsa — avval so'ra: kanaldagi e'longa almashtirishmi yoki yangi e'lonmi.
  Almashtirish bo'lsa: notify_admin chaqir va cancel_order bilan ortiqcha qoralamani yop.
- E'LON QANCHA TURADI: "necha kun turadi?", "qachon o'chadi?" desa — e'lon kanalga 1 marta chiqadi va o'chirilmaydi,
  kanalda saqlanib qoladi. Qo'shimcha qil: buyumni sotsangiz yoki sotuvni to'xtatsangiz, bizga yozing — "SOTILDI" yoki
  "E'LON TO'XTATILDI" deb belgilab, telefon raqamingizni olib tashlaymiz (endi qo'ng'iroq qilishmaydi).
- SOTILDI: mijoz buyumi sotilganini aytsa — mark_sold chaqir va qisqa tabrikla ("Tabriklayman! Kanalda sotildi deb belgilab,
  raqamingizni olib tashladim"). Sotilgandan keyin yangi e'lon taklif qilma.
- TO'XTATILDI: mijoz sotuvni to'xtatsa, fikridan qaytsa, xizmatni to'xtatsa yoki "e'lonni olib tashlang", "qo'ng'iroq qilishmasin"
  desa — mark_stopped chaqir. Xizmat e'loniga "sotildi" emas, faqat mark_stopped qo'yiladi.
- Kanal postining silkasini O'ZING YOZMA va o'ylab topma — silkani bot o'zi yuboradi. Asbob natijasida silka bo'lsa,
  aynan o'shani ishlat.
- Asbob xato qaytarsa, mijozga texnik tafsilotni aytma — vaziyatni o'zing tuzat (masalan reset_ad) yoki qisqa savol ber.
- Javoblarda markdown (**qalin**, # sarlavha) ishlatma — Telegram'da oddiy matn ko'rinadi. Emoji mumkin.
- Agar mijoz e'longa aloqasi yo'q shaxsiy savol yoki boshqa ish bo'yicha yozsa, qisqa javob berib, admin tez orada
  o'zi javob berishini ayt (o'ylab topilgan va'da berma).
- "[Tizim: ...]" xabarlari mijozdan emas, botdan keladi — ularga mos javob ber.
"""

CATEGORIES = list(CATEGORY_STYLE.keys())

TOOLS = [
    {
        "name": "update_ad",
        "description": ("E'lon qoralamasidagi maydonlarni saqlaydi/yangilaydi. Faqat mijoz aytgan ma'lumotlarni yoz. "
                        "Xizmat ko'rsatish e'lonlari uchun category 'xizmat_...' dan birini tanla."),
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
        "name": "choose_tariff",
        "description": ("Mijoz uzoq tarifni tanlasa (3, 7 yoki 30 kun) — e'longa tarif belgilaydi. Faqat mijoz o'zi so'rab, "
                        "rozi bo'lsa. 1 = oddiy bir martalik e'lon."),
        "input_schema": {"type": "object", "properties": {"days": {"type": "integer", "enum": sorted(TARIFFS)}},
                         "required": ["days"]},
    },
    {
        "name": "apply_to_campaign",
        "description": ("Mijozning FAOL TARIFI bor va u keyingi postlar uchun yangi rasm/video (yoki tayyor reklama matni) yubordi — "
                        "shu yangi materialni tarifdagi e'longa o'rnatadi. Keyingi kunlik post shu bilan chiqadi."),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "use_ready_ad",
        "description": ("Mijoz yuborgan TAYYOR reklamani (media + uning ostidagi matn yoki forward qilingan post) o'zgartirmasdan "
                        "qabul qiladi. Keyin show_preview chaqir. Faqat mazmuni qoidaga mos bo'lsa."),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": CATEGORIES},
                "title": {"type": "string", "description": "Qisqa nom ichki hisob uchun, masalan 'Nexia 3, 2020'"},
            },
            "required": ["category", "title"],
        },
    },
    {
        "name": "show_preview",
        "description": "Barcha kerakli ma'lumot (sotuvda rasm ham) bor bo'lsa, mijozga tayyor e'lonni ko'rsatadi.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "reset_ad",
        "description": "Joriy qoralamani o'chirib, yangi e'lonni boshidan boshlaydi.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "go_to_payment",
        "description": ("Mijoz ko'rsatilgan tayyor e'lonni aniq tasdiqlasa ('ha', 'to'g'ri', 'joylang', 'да') chaqir. "
                        "Bot to'lov summasi va Payme silkasini o'zi yuboradi. Faqat show_preview dan KEYIN."),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "edit_published",
        "description": ("KANALGA JOYLANGAN e'londagi xatoni tuzatadi (bepul, qayta to'lov yo'q). Faqat o'zgaradigan "
                        "maydonlarni yubor. Faqat O'SHA buyumning ma'lumotini tuzatish uchun: narx, telefon, manzil, "
                        "holati, tavsif, imlo xatolari. Boshqa buyum uchun EMAS — bu yangi pullik e'lon."),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"}, "price": {"type": "string"}, "location": {"type": "string"},
                "phone": {"type": "string"}, "telegram": {"type": "string"}, "condition": {"type": "string"},
                "details": {"type": "array", "items": {"type": "string"},
                            "description": "To'liq yangi ro'yxat (eskisini almashtiradi)."},
                "description": {"type": "string"},
                "order_id": {"type": "integer",
                             "description": "Mijozning bir nechta e'loni bo'lsa — qaysi biri (ro'yxatdan)."},
            },
        },
    },
    {
        "name": "mark_sold",
        "description": ("Mijoz buyumi SOTILGANINI aytsa ('sotildi', 'sotib bo'ldim', 'продано') — kanaldagi e'longa "
                        "'✅ SOTILDI' belgisini qo'yadi va telefon raqamini olib tashlaydi. Mijozning bir nechta e'loni bo'lsa, qaysi biri ekanini aniqlab "
                        "order_id ni yubor; bitta bo'lsa order_id shart emas."),
        "input_schema": {"type": "object", "properties": {"order_id": {"type": "integer"}}},
    },
    {
        "name": "mark_stopped",
        "description": ("Mijoz sotuvni/xizmatni TO'XTATSA, fikridan qaytsa yoki e'lonni olib tashlashni so'rasa — kanaldagi e'longa "
                        "'⛔️ E'LON TO'XTATILDI' belgisini qo'yadi va telefon raqamini olib tashlaydi. Bir nechta e'lon bo'lsa order_id yubor."),
        "input_schema": {"type": "object", "properties": {"order_id": {"type": "integer"}}},
    },
    {
        "name": "notify_admin",
        "description": ("Adminga xabar yuboradi: bot o'zi qila olmaydigan narsa (joylangan e'londagi rasmlarni "
                        "almashtirish, e'lonni o'chirish, pul qaytarish, shikoyat va h.k.)."),
        "input_schema": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]},
    },
    {
        "name": "cancel_order",
        "description": "Mijoz e'lon berishdan voz kechsa yoki to'lanmagan e'lonini bekor qilmoqchi bo'lsa.",
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
        # SDK obyektlarini emas, faqat API qabul qiladigan maydonlarni qaytaramiz
        assistant_blocks = []
        for b in resp.content:
            if b.type == "text" and b.text:
                assistant_blocks.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                assistant_blocks.append({"type": "tool_use", "id": b.id, "name": b.name,
                                         "input": b.input or {}})
        messages.append({"role": "assistant", "content": assistant_blocks})
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


PAYMENT_PARSE_PROMPT = """Senga Telegram guruhga tushgan to'lov bildirishnomasi beriladi (Payme, Click yoki bank xabari).
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


RECEIPT_PROMPT = """Bu to'lov cheki (Click, Payme yoki bank ilovasi skrinshoti). Faqat JSON qaytar:
{"is_receipt": true/false, "service": "click"|"payme"|"bank"|"boshqa", "amount": <so'mda butun son yoki null>,
 "recipient": "<qabul qiluvchi nomi yoki null>", "success": true/false, "datetime": "<sana-vaqt yoki null>"}
success — to'lov muvaffaqiyatli o'tganmi (Успешно, Muvaffaqiyatli, To'lov qildingiz va h.k.)."""


async def read_receipt(image_bytes: bytes, media_type: str = "image/jpeg") -> dict | None:
    """Chek skrinshotidan summa va to'lov tizimini o'qiydi (admin uchun yordamchi ma'lumot)."""
    import base64
    try:
        resp = await client.messages.create(
            model=CLAUDE_FAST_MODEL,
            max_tokens=200,
            system=RECEIPT_PROMPT,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                             "data": base64.b64encode(image_bytes).decode()}},
                {"type": "text", "text": "Chekni o'qi."},
            ]}],
        )
        raw = "".join(b.text for b in resp.content if b.type == "text")
        m = re.search(r"\{.*\}", raw, re.S)
        return json.loads(m.group()) if m else None
    except Exception:
        log.exception("chekni o'qib bo'lmadi")
        return None
