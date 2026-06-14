"""
bot.py — локальний запуск через polling.
Використовується для тестування: python bot.py
Логіка бота — в bot_core.py
"""

import asyncio
import logging
from pathlib import Path

from telegram import BotCommand, Update

from bot_core import build_application

# ─── Логування ───────────────────────────────────────────────────────────────
LOG_FILE = Path(__file__).parent / "logs" / "bot.log"
LOG_FILE.parent.mkdir(exist_ok=True)
_fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
_ch = logging.StreamHandler()
_ch.setFormatter(_fmt)
_fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
_fh.setFormatter(_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_ch, _fh])
logger = logging.getLogger(__name__)


async def main_async() -> None:
    logger.info("Запуск Сімейство AI Bot (polling)...")

    app = build_application()
    await app.initialize()

    await app.bot.set_my_commands([
        BotCommand("start",  "🏠 Головне меню"),
        BotCommand("cancel", "❌ Скасувати поточну дію"),
    ])
    logger.info("Команди синхронізовано з BotFather")

    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("Бот запущений у polling-режимі. Зупинити: Ctrl+C")

    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        logger.info("Зупинка бота...")
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        logger.info("Бот зупинений.")


if __name__ == "__main__":
    asyncio.run(main_async())
