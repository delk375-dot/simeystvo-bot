"""
set_webhook.py — встановлює webhook для бота на Telegram.

Використання:
    WEBHOOK_URL=https://<your-domain>/api/telegram python set_webhook.py

Або додайте WEBHOOK_URL у .env і запустіть просто:
    python set_webhook.py
"""

import os
import sys
import urllib.request
import urllib.parse
import json

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL") or (sys.argv[1] if len(sys.argv) > 1 else None)

if not TOKEN:
    print("❌ TELEGRAM_BOT_TOKEN не знайдено. Додайте у .env або встановіть змінну середовища.")
    sys.exit(1)

if not WEBHOOK_URL:
    print("❌ WEBHOOK_URL не вказано.")
    print("   Використання: WEBHOOK_URL=https://<domain>/api/telegram python set_webhook.py")
    print("   Або додайте WEBHOOK_URL у .env")
    sys.exit(1)

url = f"https://api.telegram.org/bot{TOKEN}/setWebhook"
data = json.dumps({"url": WEBHOOK_URL}).encode("utf-8")

req = urllib.request.Request(
    url,
    data=data,
    headers={"Content-Type": "application/json"},
    method="POST",
)

try:
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
except urllib.error.HTTPError as e:
    result = json.loads(e.read())

if result.get("ok"):
    print(f"✅ Webhook встановлено: {WEBHOOK_URL}")
else:
    print(f"❌ Помилка: {result}")
    sys.exit(1)
