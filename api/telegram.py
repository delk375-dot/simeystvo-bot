"""
api/telegram.py — Vercel serverless webhook endpoint (Flask / WSGI).

Vercel виявляє змінну `app` (Flask WSGI callable) як entrypoint.
Стара форма `class handler(BaseHTTPRequestHandler)` більше не підтримується
новим Vercel Python Runtime — тому замінено на Flask.

POST /api/telegram  — приймає Update від Telegram, передає боту.
GET  /api/telegram  — health-check.

Стан ConversationHandler зберігається в пам'яті процесу на час
життя теплого контейнера Vercel. При холодному рестарті незавершені
розмови скидаються — це нормальна поведінка serverless.
"""

import asyncio
import logging
import os
import sys

# api/ треба прибрати з sys.path ДО будь-яких імпортів:
# файл api/telegram.py має те саме ім'я, що й пакет python-telegram-bot,
# тому Python знаходить наш файл замість пакету → circular import.
_api_dir = os.path.dirname(os.path.abspath(__file__))
_root_dir = os.path.dirname(_api_dir)
if _api_dir in sys.path:
    sys.path.remove(_api_dir)
if _root_dir not in sys.path:
    sys.path.insert(0, _root_dir)

from flask import Flask, request
from telegram import Update
from bot_core import build_application

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Flask WSGI app (Vercel entrypoint) ──────────────────────────────────────
app = Flask(__name__)

# ─── Singleton: один Application на весь час життя контейнера ────────────────
_tg_app = None
_loop = None


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop, _tg_app
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        _tg_app = None  # loop змінився — Application треба перестворити
    return _loop


def _get_tg_app():
    global _tg_app
    loop = _get_loop()
    if _tg_app is None:
        logger.info("Cold start: ініціалізація Application")
        _tg_app = build_application()
        loop.run_until_complete(_tg_app.initialize())
    return _tg_app


# ─── Routes ───────────────────────────────────────────────────────────────────
# Vercel може передавати шлях і як /api/telegram, і як /

@app.route("/api/telegram", methods=["GET"])
@app.route("/api/ping", methods=["GET"])
@app.route("/", methods=["GET"])
def health():
    # /api/ping використовується Vercel cron для warm-up контейнера
    try:
        _get_tg_app()  # ініціалізуємо Application під час ping, щоб cold start не вдарив по webhook
    except Exception:
        pass
    return "Simeystvo bot webhook is alive", 200


@app.route("/api/telegram", methods=["POST"])
@app.route("/", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return "Bad Request: empty body", 400

        tg_app = _get_tg_app()
        loop = _get_loop()
        update = Update.de_json(data, tg_app.bot)
        loop.run_until_complete(tg_app.process_update(update))
        return "OK", 200
    except Exception as e:
        logger.error("Помилка обробки update: %s", e)
        return "Internal Server Error", 500
