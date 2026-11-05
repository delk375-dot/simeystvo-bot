"""
api/telegram.py — Vercel serverless webhook endpoint (Flask / WSGI).

Vercel виявляє змінну `app` (Flask WSGI callable) як entrypoint.
Стара форма `class handler(BaseHTTPRequestHandler)` більше не підтримується
новим Vercel Python Runtime — тому замінено на Flask.

POST /api/telegram  — приймає Update від Telegram, передає боту.
GET  /api/telegram  — health-check.

Бот не покладається на пам'ять контейнера: заявка йде адміну одразу,
а стан тесту лежить у кнопках. Запити без секрету Telegram відхиляються.
"""

import asyncio
import logging
import os
import sys
import threading

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
from bot_core import build_application, webhook_secret

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Flask WSGI app (Vercel entrypoint) ──────────────────────────────────────
app = Flask(__name__)

# ─── Singleton: один Application на весь час життя контейнера ────────────────
_tg_app = None
_loop = None
# Запити можуть іти паралельно, а цикл подій один. Без замка другий запит бачив
# ще не ініціалізований застосунок і назавжди отримував 500.
_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop, _tg_app
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
        _tg_app = None  # loop змінився — Application треба перестворити
    return _loop


def _get_tg_app():
    """Викликати лише під _lock. Глобальна змінна заповнюється після успішної ініціалізації."""
    global _tg_app
    loop = _get_loop()
    if _tg_app is None:
        logger.info("Cold start: ініціалізація Application")
        app_ = build_application()
        loop.run_until_complete(app_.initialize())
        _tg_app = app_
    return _tg_app


# ─── Routes ───────────────────────────────────────────────────────────────────
# Vercel може передавати шлях і як /api/telegram, і як /

@app.route("/api/telegram", methods=["GET"])
@app.route("/api/ping", methods=["GET"])
@app.route("/", methods=["GET"])
def health():
    # /api/ping використовується Vercel cron для warm-up контейнера
    try:
        with _lock:
            _get_tg_app()  # ініціалізуємо Application під час ping, щоб cold start не вдарив по webhook
    except Exception:
        logger.exception("Не вдалося ініціалізувати Application")
    return "Simeystvo bot webhook is alive", 200


@app.route("/api/telegram", methods=["POST"])
@app.route("/", methods=["POST"])
def webhook():
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != webhook_secret():
        return "Forbidden", 403
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return "Bad Request: empty body", 400

        with _lock:
            tg_app = _get_tg_app()
            update = Update.de_json(data, tg_app.bot)
            _get_loop().run_until_complete(tg_app.process_update(update))
        return "OK", 200
    except Exception:
        logger.exception("Помилка обробки update")
        return "Internal Server Error", 500
