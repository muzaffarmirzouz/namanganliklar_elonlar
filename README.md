# Namanganliklar E'lonlari — AI agent bot

Mijoz bilan Claude AI gaplashadi → e'lon ma'lumotlari va 3-4 ta rasmni yig'adi → oldindan ko'rsatadi →
Payme silkasini beradi → to'lov guruhiga Payme bot xabari tushganda summani o'qib tasdiqlaydi →
e'lonni albom + bezatilgan matn bilan kanalga joylaydi. 24/7.

## Qanday ishlaydi

```
Mijoz: "Cobalt 2021 sotaman"
  └─ AI: narxi? manzil? probeg? telefon? rasmlar?
Mijoz: 4 ta rasm (albom)
  └─ Bot: tayyor e'lonni ko'rsatadi  [✅ To'lovga o'tish] [✏️ O'zgartirish]
Mijoz: ✅
  └─ Bot: "50 037 so'm to'lang"  [💳 Payme orqali to'lash]   ← Payme silka faqat shu yerda beriladi
Payme bot → to'lov guruhiga: "Поступление 50 037,00 UZS"
  └─ Bot: AI xabarni o'qiydi → 50 037 = #37 buyurtma → kanalga joylaydi → mijozga post silkasi
```

**Noyob summa** (`UNIQUE_AMOUNT=1`): har bir buyurtmaga 50 001 – 50 999 oralig'ida alohida summa beriladi.
Shu tufayli bir vaqtda 10 kishi to'lasa ham bot kim to'laganini adashmasdan topadi.
Agar aniq 50 000 bo'lishini xohlasangiz `UNIQUE_AMOUNT=0` qiling — unda bir vaqtda bir nechta
to'lov kutilsa, bot guruhda "qaysi biri?" deb so'raydi va admin `/tasdiq ID` qiladi.

**Zaxira yo'l:** to'lov avtomatik topilmasa, mijoz chek skrinshotini botga yuboradi →
guruhga [✅ Tasdiqlash] [❌ Rad etish] tugmalari bilan keladi.

**AI nimani rad etadi:** Telegram kanal/guruh/bot reklamasi, yangilik kanallari, boshqa e'lon kanallari,
kurs/xizmat reklamasi, ish e'lonlari, kredit, stavka, 18+, taqiqlangan narsalar. Rad etish **to'lovdan oldin** bo'ladi.
Ro'yxatni o'zgartirish: `ai.py` → `SYSTEM_PROMPT`.

## Telegram Business — lichka orqali ishlash

Mijozlar botga emas, **sizning shaxsiy akkauntingizga** yozadi, bot esa siz nomingizdan javob beradi.
Lichkada tugmalar bo'lmaydi: mijoz e'lonni "ha" deb tasdiqlaydi, Payme silkasi matnda boradi.
Botning o'z chati (/start, tugmalar) ham ishlab turaveradi.

**Ulash:** Telegram → Sozlamalar → **Telegram Business** → **Chatbots** (Чат-боты) →
`@namelon_ai_bot` ni yozing → **javob berish (Reply to messages)** huquqini yoqing.
Telegram Premium kerak.

**Qaysi chatlarda ishlaydi:** shu sahifada "Chats" bo'limida **"Exclude contacts"** (Kontaktlardan tashqari)
ni tanlang — shunda oila va do'stlaringizga bot javob bermaydi, faqat notanish mijozlarga.
Kerakli odamlarni ro'yxatdan qo'lda chiqarib ham qo'yish mumkin.

**Siz o'zingiz yozsangiz:** mijoz chatiga o'zingiz biror narsa yozishingiz bilan bot o'sha chatda
`BUSINESS_PAUSE_HOURS` (12) soat jim turadi — suhbatni siz davom ettirasiz.
Botni qayta yoqish: o'sha chatda `/ai` deb yozing yoki guruhda `/ai USER_ID`.

Ulanish va uzilish haqida to'lov guruhiga xabar keladi.

## Sozlash (1 marta)

### 1. BotFather
1. Yangi bot yarating → token `BOT_TOKEN` ga.
2. `/mybots` → bot → **Bot Settings → Group Privacy → Turn off**.
3. `/mybots` → bot → **Bot Settings → Bot-to-Bot Communication → Enable**.
   ⚠️ Bu majburiy! Telegram botlari odatda boshqa botning xabarini ko'rmaydi. Shu rejim yoqilib,
   bot guruhda **admin** bo'lsagina Payme bot xabarlarini o'qiy oladi.

### 2. Kanal va guruh
1. Botni **e'lonlar kanaliga admin** qiling (xabar joylash + o'chirish huquqi).
2. Botni **to'lov guruhiga admin** qiling (Payme bot xabarlari tushadigan guruh).
3. Botni ishga tushirgach guruhda `/id` yozing → `PAYMENT_GROUP_ID`.
   Kanal ID si: kanal postini botga forward qilib `/id` ga javob qiling, yoki @username_to_id_bot.
4. Payme botining xabariga **reply** qilib `/id` yozing → uning ID sini `PAYMENT_SOURCE_IDS` ga qo'ying.
   (Shunda guruhdagi boshqa odam "50 037 tushdi" deb yozib, botni aldab qo'ya olmaydi.)

### 3. Claude API
console.anthropic.com → API Keys → `ANTHROPIC_API_KEY`. Hisobga balans qo'shing.
Taxminiy xarajat: 1 ta e'lon suhbati ~$0.02–0.05, to'lov xabarini o'qish ~$0.001.

### 4. Payme
- `PAYME_LINK` — sizning Payme to'lov silkangiz.
- Payme Business kassangiz bo'lsa `PAYME_MERCHANT_ID` ni qo'ying — bot summasi tayyor
  `checkout.paycom.uz` silkasini o'zi yasaydi (mijoz summani qo'lda yozmaydi).

### 5. Railway
1. GitHub'ga yangi repo (masalan `namelon_bot`) → shu fayllarni yuklang (`.env` ni YUKLAMANG).
2. Railway → New Project → Deploy from GitHub repo.
3. **Variables** → `.env.example` dagilarni to'ldiring. `TZ=Asia/Tashkent` ham qo'shing.
4. **Volume** qo'shing, mount path: `/data` — baza (`elon.db`) qayta deploy'da o'chib ketmasligi uchun.
5. Start command o'zi `Procfile` dan olinadi: `python main.py`.

## Admin buyruqlari (shaxsiy chatda yoki to'lov guruhida)

| Buyruq | Vazifasi |
|---|---|
| `/kutilmoqda` | To'lov kutayotgan e'lonlar va summalari |
| `/tasdiq 37` | #37 ni qo'lda tasdiqlab kanalga joylash (muddati o'tgan bo'lsa ham) |
| `/joyla 37` | To'langan, lekin xato sabab joylanmagan e'lonni qayta joylash |
| `/bekor 37` | Buyurtmani bekor qilish |
| `/stat` | Bugungi va oylik e'lonlar soni, tushum |
| `/ai 12345` | Lichkada jim turgan botni shu mijoz bilan qayta yoqish |
| `/id` | Chat / foydalanuvchi ID si |

## Fayllar

| Fayl | Vazifasi |
|---|---|
| `main.py` | Ishga tushirish, muddati o'tgan to'lovlarni yopish, avto-o'chirish |
| `ai.py` | Claude agent (suhbat + asboblar) va to'lov xabarini o'qish |
| `handlers_client.py` | Mijoz chati: AI, rasmlar albomi, oldindan ko'rish, to'lov, chek |
| `handlers_group.py` | To'lov guruhi: Payme xabarini buyurtmaga moslash |
| `handlers_admin.py` | Admin buyruqlari va chek tugmalari |
| `payments.py` | Noyob summa, Payme silka, summani matndan ajratish |
| `formatting.py` | Kanal posti bezagi (kategoriya ivonlari, 1024 belgi chegarasi) |
| `publisher.py` | Albom qilib yuborish, post silkasi |
| `db.py` | SQLite |

## Sinab ko'rish tartibi
1. Botga `/start` → "Telefon sotaman, iPhone 13" deb yozing, savollariga javob bering, 3 ta rasm yuboring.
2. Oldindan ko'rishda ✅ → bot summani aytadi (masalan 50 412).
3. Payme orqali **o'sha summani** to'lang → guruhga Payme xabari tushadi → 1-2 daqiqada post kanalda.
4. Sinov uchun to'lamasdan: guruhda `/tasdiq ID`.
