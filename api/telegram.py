"""
api/telegram.py — Vercel serverless webhook endpoint.

POST /api/telegram  — приймає update від Telegram, передає боту.
GET  /api/telegram  — health-check: повертає текст "alive".

Стан Application (user_data, ConversationHandler) зберігається
в пам'яті процесу на весь час життя контейнера Vercel.
При рестарті холодного контейнера незавершені розмови скидаються —
це нормальна поведінка для serverless-режиму.
"""

import asyncio
import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler

# Додаємо корінь проекту до sys.path, щоб bot_core та personality знаходились
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram import Update
from bot_core import build_application

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Singleton: один Application на весь час життя контейнера ────────────────
# Зберігаємо стан ConversationHandler між запитами одного теплого контейнера.
_app = None
_loop = None


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop


def _get_app():
    global _app
    loop = _get_loop()
    if _app is None:
        logger.info("Ініціалізація Application (холодний старт)")
        _app = build_application()
        loop.run_until_complete(_app.initialize())
    return _app


# ─── Vercel handler ───────────────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            update_data = json.loads(body)

            app = _get_app()
            loop = _get_loop()
            update = Update.de_json(update_data, app.bot)
            loop.run_until_complete(app.process_update(update))

            self._respond(200, b"OK")
        except Exception as e:
            logger.error("Помилка обробки update: %s", e)
            self._respond(500, b"Internal Server Error")

    def do_GET(self):
        self._respond(200, b"Simeystvo bot webhook is alive")

    def _respond(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        logger.info(fmt, *args)
