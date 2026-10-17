"""TG_SESSION ni olish uchun — O'Z KOMPYUTERINGIZDA bir marta ishga tushiring.

    pip3 install telethon
    python3 gen_session.py

API ID va API HASH ni my.telegram.org -> API development tools dan oling.
Telefon raqamingiz va Telegram'ga kelgan kodni kiritasiz. Oxirida uzun satr chiqadi —
uni Railway Variables'ga TG_SESSION qilib qo'ying.

⚠️ Bu satr akkauntingizga to'liq kirish kaliti! Hech kimga bermang, GitHub'ga yuklamang.
"""
from telethon.sessions import StringSession
from telethon.sync import TelegramClient

api_id = int(input("API ID: ").strip())
api_hash = input("API HASH: ").strip()

with TelegramClient(StringSession(), api_id, api_hash) as client:
    print("\n✅ TG_SESSION (shuni Railway'ga qo'ying):\n")
    print(client.session.save())
    print()
