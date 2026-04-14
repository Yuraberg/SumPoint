"""
Генерация StringSession для Telethon.

Запусти этот скрипт ОДИН РАЗ на локальной машине:
    pip install telethon
    python generate_session.py

Скрипт запросит:
  1. API ID (число с my.telegram.org)
  2. API Hash (строка с my.telegram.org)
  3. Номер телефона
  4. Код подтверждения из Telegram

На выходе — строка сессии, которую нужно вставить
в переменную TELEGRAM_SESSION_STRING в Coolify.
"""

from telethon.sync import TelegramClient
from telethon.sessions import StringSession

API_ID = int(input("Введи API_ID: "))
API_HASH = input("Введи API_HASH: ")

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    session_string = client.session.save()
    print("\n" + "=" * 60)
    print("ТВОЯ СТРОКА СЕССИИ (скопируй целиком):")
    print("=" * 60)
    print(session_string)
    print("=" * 60)
    print("\nВставь эту строку в Coolify как переменную")
    print("TELEGRAM_SESSION_STRING")
