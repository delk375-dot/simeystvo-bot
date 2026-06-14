"""
publish_once.py — одноразовий публікатор для GitHub Actions.

Запуск:
    python publish_once.py            # авто-визначення рубрики за днем/часом
    python publish_once.py book       # примусово публікує книгу
    python publish_once.py auto       # те саме, що без аргументу

Не запускає polling, не підключає Radar, просто надсилає одне повідомлення.
"""

import asyncio
import json
import logging
import os
import random
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import Bot
from telegram.error import TelegramError

from personality import (
    BOOK_INTROS, FILM_INTROS, INSIGHT_INTROS,
    QUESTION_INTROS, MANIPULATION_INTROS, PHRASE_INTROS,
)

# ─── Константи ───────────────────────────────────────────────────────────────

GROUP_CHAT_ID = -1001282667395
FILMS_BOOKS_THREAD_ID = 23975
KYIV_TZ = ZoneInfo("Europe/Kyiv")

BASE_DIR = Path(__file__).parent
CONTENT_DIR = BASE_DIR / "content"
STATE_FILE = BASE_DIR / "state.json"

VALID_KINDS = ("book", "question", "manipulation", "film", "insight", "phrase")

# ─── Логування ───────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Стан ────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {
        "book_index": 0, "film_index": 0, "insight_index": 0,
        "question_index": 0, "manipulation_index": 0, "phrase_index": 0,
    }


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_content(filename: str) -> list:
    with open(CONTENT_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


def get_next_item(content_list: list, state: dict, key: str) -> tuple[dict, int]:
    index = state.get(key, 0) % len(content_list)
    item = content_list[index]
    next_index = (index + 1) % len(content_list)
    return item, next_index

# ─── Форматування ─────────────────────────────────────────────────────────────

def format_book(book: dict) -> str:
    ideas = "\n".join(f"{i+1}. {idea}" for i, idea in enumerate(book["key_ideas"]))
    intro = random.choice(BOOK_INTROS)
    hook = book.get("hook", "")
    hook_block = f"\n{hook}\n" if hook else ""
    return (
        f"{intro}\n\n"
        f"— — —\n"
        f"📚 *Моя книжкова провокація тижня*\n"
        f"— — —\n"
        f"{hook_block}\n"
        f"«{book['title']}» — {book['author']}\n\n"
        f"*Навіщо це юристу:*\n{book['why_for_lawyers']}\n\n"
        f"*3 практичні ідеї:*\n{ideas}\n\n"
        f"*Питання до спільноти:*\n_{book['discussion_question']}_"
    )


def format_film(film: dict) -> str:
    lens = "\n".join(f"{i+1}. {point}" for i, point in enumerate(film["legal_lens"]))
    intro = random.choice(FILM_INTROS)
    hook = film.get("hook", "")
    hook_block = f"\n{hook}\n" if hook else ""
    return (
        f"{intro}\n\n"
        f"— — —\n"
        f"🎬 *Моя кінопровокація тижня*\n"
        f"— — —\n"
        f"{hook_block}\n"
        f"«{film['title']}» ({film['year']})\n\n"
        f"*Навіщо це юристу:*\n{film['why_for_lawyers']}\n\n"
        f"*3 спостереження:*\n{lens}\n\n"
        f"*Питання до спільноти:*\n_{film['discussion_question']}_"
    )


def format_insight(insight: dict) -> str:
    intro = random.choice(INSIGHT_INTROS)
    return (
        f"{intro}\n\n"
        f"— — —\n"
        f"💡 *Думка, яку я сьогодні приніс у чат*\n"
        f"— — —\n\n"
        f"*{insight['title']}*\n\n"
        f"{insight['body']}\n\n"
        f"*Питання до спільноти:*\n_{insight['question']}_"
    )


def format_question(item: dict) -> str:
    intro = random.choice(QUESTION_INTROS)
    hook = item.get("hook", "")
    hook_block = f"\n{hook}\n" if hook else ""
    return (
        f"{intro}\n\n"
        f"— — —\n"
        f"❓ *Моє незручне питання тижня*\n"
        f"— — —\n"
        f"{hook_block}\n"
        f"*{item['title']}*\n\n"
        f"{item['body']}\n\n"
        f"*Питання до спільноти:*\n_{item['discussion_question']}_"
    )


def format_manipulation(item: dict) -> str:
    intro = random.choice(MANIPULATION_INTROS)
    return (
        f"{intro}\n\n"
        f"— — —\n"
        f"🧩 *Маніпуляція тижня*\n"
        f"— — —\n\n"
        f"*{item['title']}*\n\n"
        f"Фраза:\n_«{item['phrase']}»_\n\n"
        f"*Що тут відбувається:*\n{item['what_is_happening']}\n\n"
        f"*Як може відповісти юрист:*\n{item['lawyer_response']}\n\n"
        f"*Питання до спільноти:*\n_{item['discussion_question']}_"
    )


def format_phrase(item: dict) -> str:
    intro = random.choice(PHRASE_INTROS)
    return (
        f"{intro}\n\n"
        f"— — —\n"
        f"🗣 *Фраза для переговорів*\n"
        f"— — —\n\n"
        f"*{item['title']}*\n\n"
        f"Замість:\n_«{item['bad_phrase']}»_\n\n"
        f"Спробуйте:\n_«{item['better_phrase']}»_\n\n"
        f"*Чому це працює:*\n{item['why_it_works']}\n\n"
        f"*Питання до спільноти:*\n_{item['discussion_question']}_"
    )

# ─── Визначення рубрики за днем/часом ────────────────────────────────────────

def resolve_kind(arg: str) -> str:
    """Повертає назву рубрики: з аргументу або за поточним днем/часом Kyiv."""
    if arg and arg != "auto":
        if arg not in VALID_KINDS:
            logger.error("Невідома рубрика: %r. Допустимі: %s", arg, ", ".join(VALID_KINDS))
            sys.exit(1)
        return arg

    now = datetime.now(tz=KYIV_TZ)
    weekday = now.weekday()  # 0=Mon … 6=Sun
    hour = now.hour

    schedule = {
        0: "book",
        1: "question",
        2: "manipulation",
        3: "film",
    }
    if weekday in schedule:
        return schedule[weekday]
    if weekday == 4:  # Friday
        return "insight" if hour < 12 else "phrase"

    logger.error(
        "Сьогодні %s — публікацій не заплановано. "
        "Передайте аргумент явно: python publish_once.py book",
        now.strftime("%A"),
    )
    sys.exit(1)

# ─── Збірка повідомлення ─────────────────────────────────────────────────────

CONTENT_MAP = {
    "book":         ("books.json",         "book_index",         format_book),
    "film":         ("films.json",          "film_index",         format_film),
    "insight":      ("insights.json",       "insight_index",      format_insight),
    "question":     ("questions.json",      "question_index",     format_question),
    "manipulation": ("manipulations.json",  "manipulation_index", format_manipulation),
    "phrase":       ("phrases.json",        "phrase_index",       format_phrase),
}


def build_message(kind: str) -> tuple[str, dict, str]:
    """Повертає (текст, оновлений_state, state_key)."""
    filename, state_key, formatter = CONTENT_MAP[kind]
    content = load_content(filename)
    state = load_state()
    item, next_index = get_next_item(content, state, state_key)
    text = formatter(item)
    state[state_key] = next_index
    return text, state, state_key

# ─── Основна логіка ───────────────────────────────────────────────────────────

async def publish(kind: str) -> None:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN не знайдено в оточенні")
        sys.exit(1)

    text, new_state, state_key = build_message(kind)

    logger.info("Публікую рубрику: %s (індекс %s → %s)",
                kind, new_state[state_key] - 1, new_state[state_key])

    async with Bot(token=token) as bot:
        try:
            await bot.send_message(
                chat_id=GROUP_CHAT_ID,
                message_thread_id=FILMS_BOOKS_THREAD_ID,
                text=text,
                parse_mode="Markdown",
            )
            logger.info("Опубліковано успішно")
        except TelegramError as e:
            logger.error("Помилка Telegram: %s", e)
            sys.exit(1)

    save_state(new_state)
    logger.info("state.json оновлено: %s = %s", state_key, new_state[state_key])


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else "auto"
    kind = resolve_kind(arg)
    asyncio.run(publish(kind))


if __name__ == "__main__":
    main()
