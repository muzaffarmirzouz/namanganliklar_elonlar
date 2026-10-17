"""Barcha sozlamalar .env (yoki Railway Variables) dan o'qiladi."""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _ids(value: str) -> set[int]:
    return {int(x) for x in value.replace(" ", "").split(",") if x}


# --- Telegram ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))            # -100... e'lonlar kanali
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "").lstrip("@")  # post silkasi va footer uchun
CHANNEL_TITLE = os.getenv("CHANNEL_TITLE", "Namanganliklar E'lonlari")
PAYMENT_GROUP_ID = int(os.getenv("PAYMENT_GROUP_ID", "0"))  # Payme xabarlari tushadigan guruh
ADMIN_IDS = _ids(os.getenv("ADMIN_IDS", ""))
# Guruhda kimning xabari "to'lov xabari" deb qabul qilinadi (Payme bot ID si va h.k.).
# Bo'sh bo'lsa — guruhdagi har qanday xabar tekshiriladi (guruh yopiq bo'lishi shart!)
PAYMENT_SOURCE_IDS = _ids(os.getenv("PAYMENT_SOURCE_IDS", ""))
ADMIN_CONTACT = os.getenv("ADMIN_CONTACT", "")  # masalan @namanganliklar_admin

# --- Claude ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")      # mijoz bilan suhbat
CLAUDE_FAST_MODEL = os.getenv("CLAUDE_FAST_MODEL", "claude-haiku-5-5")  # to'lov xabarini o'qish

# --- Narx va to'lov ---
AD_PRICE = int(os.getenv("AD_PRICE", "50000"))
# 1 = har bir buyurtmaga noyob summa (50 001 ... 50 999) — to'lovni aniq topish uchun
UNIQUE_AMOUNT = os.getenv("UNIQUE_AMOUNT", "1") == "1"
UNIQUE_MAX_OFFSET = int(os.getenv("UNIQUE_MAX_OFFSET", "999"))
# Payme silkasi. Ichida {amount} bo'lsa, summa bilan almashtiriladi.
PAYME_LINK = os.getenv("PAYME_LINK", "")
# Payme Business kassa ID si bo'lsa — summa avtomatik qo'yilgan checkout silka yasaladi
PAYME_MERCHANT_ID = os.getenv("PAYME_MERCHANT_ID", "")
PAYME_ACCOUNT_KEY = os.getenv("PAYME_ACCOUNT_KEY", "order_id")
# Silka ochilmasa, Payme ilovasida shu nom bilan qidiriladi
PAYME_SEARCH_NAME = os.getenv("PAYME_SEARCH_NAME", "Namanganliklar")
# Click: alohida guruh yo'q — mijoz chek skrinshotini yuboradi, admin tasdiqlaydi
CLICK_ENABLED = os.getenv("CLICK_ENABLED", "1") == "1"
CLICK_SEARCH_NAME = os.getenv("CLICK_SEARCH_NAME", "Namanganliklar group")
# Click bildirishnomalari tushadigan guruh. Bot u yerda JIM kuzatadi: hech narsa yozmaydi, buyruqlarga javob bermaydi.
# Berilsa — Click to'lovi ham Payme kabi avtomatik tasdiqlanadi (chek faqat zaxira yo'l)
CLICK_GROUP_ID = int(os.getenv("CLICK_GROUP_ID", "0") or 0)
# Click guruhida kimning xabari to'lov deb hisoblanadi (Click bildirishnoma botining ID si). Bo'sh — hammasi
CLICK_SOURCE_IDS = _ids(os.getenv("CLICK_SOURCE_IDS", ""))
PAYMENT_TTL_HOURS = int(os.getenv("PAYMENT_TTL_HOURS", "24"))

# --- E'lon ---
MAX_PHOTOS = int(os.getenv("MAX_PHOTOS", "10"))
# 0 = o'chirilmaydi. 24 = e'lon 1 kundan keyin kanaldan o'chiriladi (Telegram 48 soatgacha ruxsat beradi)
AUTO_DELETE_HOURS = int(os.getenv("AUTO_DELETE_HOURS", "0"))

# Joylangan e'lonni tuzatish: necha kun ichida va necha marta bepul
EDIT_WINDOW_DAYS = int(os.getenv("EDIT_WINDOW_DAYS", "7"))
MAX_EDITS = int(os.getenv("MAX_EDITS", "3"))
# "Sotildi" belgisini necha kun ichida qo'yish mumkin
SOLD_WINDOW_DAYS = int(os.getenv("SOLD_WINDOW_DAYS", "60"))

# --- Telegram Business (lichka) ---
# Siz mijoz chatiga o'zingiz yozsangiz, bot shu chatda necha soat jim turadi
BUSINESS_PAUSE_HOURS = int(os.getenv("BUSINESS_PAUSE_HOURS", "12"))

# --- Userbot (Payme guruhini sizning akkauntingiz orqali o'qish) ---
TG_API_ID = int(os.getenv("TG_API_ID", "0") or 0)
TG_API_HASH = os.getenv("TG_API_HASH", "")
TG_SESSION = os.getenv("TG_SESSION", "")

# --- Saqlash ---
DB_PATH = os.getenv("DB_PATH") or ("/data/elon.db" if os.path.isdir("/data") else "elon.db")
