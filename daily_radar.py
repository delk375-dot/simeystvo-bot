"""
daily_radar.py — LexMind Daily Radar через GitHub Actions.

Підключається до Telegram як user-акаунт (Telethon StringSession),
читає повідомлення групи за останні 24 години, знаходить потенційні
робочі заявки і надсилає адміну один дайджест через Bot API.

Запуск:
    python daily_radar.py

Потрібні env-змінні:
    TELEGRAM_API_ID           — з my.telegram.org
    TELEGRAM_API_HASH         — з my.telegram.org
    TELEGRAM_SESSION_STRING   — StringSession (генерується один раз)
    TELEGRAM_BOT_TOKEN        — токен бота для відправки дайджесту
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession
from telegram import Bot
from telegram.error import TelegramError

from radar import detect_lead

# ─── Константи ───────────────────────────────────────────────────────────────

GROUP_CHAT_ID = -1001282667395
ADMIN_USER_ID = 219205800
LOOKBACK_HOURS = 24

# ─── Логування ───────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Формування дайджесту ─────────────────────────────────────────────────────

def _message_link(chat_id: int, message_id: int) -> str:
    """Посилання на повідомлення в супергрупі."""
    internal_id = str(chat_id)[4:]  # -100XXXXXXXXXX → XXXXXXXXXX
    return f"https://t.me/c/{internal_id}/{message_id}"


def build_digest(leads: list[dict]) -> str:
    if not leads:
        return (
            "🔕 LexMind Daily Radar\n\n"
            "За останні 24 години я не знайшов робочих сигналів.\n\n"
            "Або юристи мовчали.\n"
            "Або просили допомогу так завуальовано, що навіть я зробив вигляд, що не почув."
        )

    lines = [
        "🔔 LexMind Daily Radar\n",
        f"Я переглянув чат за останні {LOOKBACK_HOURS} години.\n",
        f"Знайдено потенційних заявок: {len(leads)}\n",
    ]

    for i, lead in enumerate(leads, 1):
        confidence_label = "висока" if lead["confidence"] == "high" else "середня"
        keywords_str = ", ".join(lead["matched_keywords"])
        author = lead["author"]
        date_str = lead["date"].strftime("%d.%m.%Y %H:%M")
        text = lead["text"]
        link = _message_link(GROUP_CHAT_ID, lead["message_id"])

        lines.append(
            f"{i}. Ймовірність: {confidence_label}\n"
            f"Збіги: {keywords_str}\n"
            f"Автор: {author}\n"
            f"Дата: {date_str}\n"
            f"Текст:\n{text}\n\n"
            f"Посилання:\n{link}\n\n"
            f"— — —\n"
        )

    return "\n".join(lines)


# ─── Основна логіка ───────────────────────────────────────────────────────────

async def run() -> None:
    load_dotenv()

    api_id_raw = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    session_string = os.getenv("TELEGRAM_SESSION_STRING")
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")

    missing = [name for name, val in [
        ("TELEGRAM_API_ID", api_id_raw),
        ("TELEGRAM_API_HASH", api_hash),
        ("TELEGRAM_SESSION_STRING", session_string),
        ("TELEGRAM_BOT_TOKEN", bot_token),
    ] if not val]

    if missing:
        logger.error("Відсутні env-змінні: %s", ", ".join(missing))
        sys.exit(1)

    api_id = int(api_id_raw)
    cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

    logger.info("Підключення до Telegram (Telethon)...")
    async with TelegramClient(StringSession(session_string), api_id, api_hash) as client:
        logger.info("З'єднано. Читаю повідомлення з групи за останні %s год...", LOOKBACK_HOURS)

        leads: list[dict] = []
        seen_ids: set[int] = set()

        async for message in client.iter_messages(GROUP_CHAT_ID, offset_date=None, reverse=False):
            # iter_messages повертає від нових до старих; зупиняємось коли виходимо за вікно
            if message.date < cutoff:
                break
            if not message.text:
                continue
            if message.id in seen_ids:
                continue

            result = detect_lead(message.text)
            if not result:
                continue

            seen_ids.add(message.id)
            sender = await message.get_sender()
            if sender:
                name = getattr(sender, "first_name", "") or ""
                last = getattr(sender, "last_name", "") or ""
                username = getattr(sender, "username", None)
                author = f"{name} {last}".strip()
                if username:
                    author += f" @{username}"
            else:
                author = "Невідомо"

            leads.append({
                "message_id": message.id,
                "date": message.date,
                "author": author,
                "text": message.text[:300],  # обрізаємо дуже довгі тексти
                "matched_keywords": result["matched_keywords"],
                "confidence": result["confidence"],
            })

        logger.info("Знайдено заявок: %d", len(leads))

    # Сортуємо від старших до новіших для зручного читання
    leads.sort(key=lambda x: x["date"])

    digest = build_digest(leads)

    logger.info("Надсилаю дайджест адміну (user_id=%s)...", ADMIN_USER_ID)
    async with Bot(token=bot_token) as bot:
        try:
            # Telegram обмежує повідомлення до 4096 символів
            if len(digest) <= 4096:
                await bot.send_message(chat_id=ADMIN_USER_ID, text=digest)
            else:
                # Розбиваємо по роздільнику "— — —"
                chunks = digest.split("— — —\n")
                header = chunks[0]
                current = header
                for chunk in chunks[1:]:
                    block = chunk + "— — —\n"
                    if len(current) + len(block) > 4096:
                        await bot.send_message(chat_id=ADMIN_USER_ID, text=current.strip())
                        current = block
                    else:
                        current += block
                if current.strip():
                    await bot.send_message(chat_id=ADMIN_USER_ID, text=current.strip())

            logger.info("Дайджест надіслано успішно")
        except TelegramError as e:
            logger.error("Помилка при надсиланні дайджесту: %s", e)
            sys.exit(1)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
