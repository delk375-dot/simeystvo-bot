"""
LexMind Telegram Bot
Публікує книги, фільми та інсайти для юристів у Telegram-супергрупу.
Сумісний з Python 3.14: запуск через asyncio.run(), без run_polling().
"""

import asyncio
import json
import logging
import os
import random
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import Update
from telegram.error import Forbidden, TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from personality import (
    BOOK_INTROS, FILM_INTROS, INSIGHT_INTROS,
    QUESTION_INTROS, MANIPULATION_INTROS, PHRASE_INTROS,
    VOICE_TEXT,
)
from radar import (
    LEAD_KEYWORDS, ADMIN_USER_ID as RADAR_ADMIN_ID,
    is_radar_enabled, set_radar_enabled,
    detect_lead, save_lead, already_saved,
    get_today_leads, build_admin_message,
)

# ─── Завантаження токена з .env ───────────────────────────────────────────────
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не знайдено у .env файлі")

# ─── Константи групи ──────────────────────────────────────────────────────────
GROUP_CHAT_ID = -1001282667395
FILMS_BOOKS_THREAD_ID = 23975  # тема "Фільми, книги"
KYIV_TZ = ZoneInfo("Europe/Kyiv")

# ─── Шляхи до файлів ─────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
CONTENT_DIR = BASE_DIR / "content"
STATE_FILE = BASE_DIR / "state.json"

# ─── Логування ───────────────────────────────────────────────────────────────
LOG_FILE = BASE_DIR / "logs" / "bot.log"
LOG_FILE.parent.mkdir(exist_ok=True)

_log_fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_log_fmt)

_file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
_file_handler.setFormatter(_log_fmt)

logging.basicConfig(level=logging.INFO, handlers=[_console_handler, _file_handler])
logger = logging.getLogger(__name__)


def log_command(update: Update, command: str) -> None:
    """Записує виклик команди з метаданими у лог."""
    msg = update.message
    thread_id = msg.message_thread_id if msg else None
    chat_id = msg.chat_id if msg else "?"
    user = msg.from_user.username or msg.from_user.full_name if msg and msg.from_user else "?"
    logger.info("CMD /%s | user=@%s | chat_id=%s | thread_id=%s", command, user, chat_id, thread_id)


# ─── Робота зі станом (який елемент вже публікувався) ────────────────────────

def load_state() -> dict:
    """Зчитує поточний стан індексів з файлу."""
    if STATE_FILE.exists():
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"book_index": 0, "film_index": 0, "insight_index": 0}


def save_state(state: dict) -> None:
    """Зберігає оновлений стан індексів у файл."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_content(filename: str) -> list:
    """Зчитує контент зі JSON-файлу."""
    path = CONTENT_DIR / filename
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_next_item(content_list: list, state: dict, key: str) -> tuple[dict, int]:
    """Повертає наступний елемент зі списку (циклічно)."""
    index = state.get(key, 0) % len(content_list)
    item = content_list[index]
    next_index = (index + 1) % len(content_list)
    return item, next_index


# ─── Форматування повідомлень ─────────────────────────────────────────────────

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


# ─── Відправка у групу ────────────────────────────────────────────────────────

async def send_to_group(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Надсилає повідомлення в тему 'Фільми, книги' супергрупи."""
    try:
        await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            message_thread_id=FILMS_BOOKS_THREAD_ID,
            text=text,
            parse_mode="Markdown",
        )
        logger.info("Повідомлення успішно надіслано в групу")
    except Forbidden:
        logger.error("Бот не має прав писати в цю групу. Додайте бота як адміністратора.")
        raise
    except TelegramError as e:
        logger.error(f"Помилка при надсиланні в групу: {e}")
        raise


# ─── Команди бота ─────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — відповідь у приваті."""
    log_command(update, "start")
    intro = random.choice(BOOK_INTROS[:5])  # перші 5 — найбільш "вступні"
    text = (
        f"{intro}\n\n"
        f"Пиши /voice, щоб дізнатись більше про мене.\n"
        f"Пиши /help, щоб побачити, що я вмію."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/help — список команд."""
    log_command(update, "help")
    text = (
        "Що я вмію:\n\n"
        "📚 /book — книжкова провокація → в групу\n"
        "🎬 /film — кінопровокація → в групу\n"
        "💡 /insight — думка тижня → в групу\n"
        "❓ /question — незручне питання → в групу\n"
        "🧩 /manipulation — маніпуляція тижня → в групу\n"
        "🗣 /phrase — фраза для переговорів → в групу\n\n"
        "👁 *Перегляд \\(без публікації\\):*\n"
        "/previewbook · /previewfilm\n"
        "/previewquestion · /previewmanipulation · /previewphrase\n\n"
        "🗣 /voice — хто такий LexMind\n\n"
        "⏰ *Автопублікації \\(Europe/Kyiv\\):*\n"
        "Пн 10:00 — книга\n"
        "Вт 10:00 — питання\n"
        "Ср 10:00 — маніпуляція\n"
        "Чт 10:00 — фільм\n"
        "Пт 10:00 — думка  |  Пт 15:00 — фраза\n\n"
        "⚙️ *Адміністративні:*\n"
        "/health · /topicinfo · /testtopic · /listtopics · /resetcontent"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_book(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/book — публікує наступну книгу в тему групи."""
    log_command(update, "book")
    state = load_state()
    books = load_content("books.json")
    book, next_index = get_next_item(books, state, "book_index")

    text = format_book(book)
    await send_to_group(context, text)

    state["book_index"] = next_index
    save_state(state)

    await update.message.reply_text("✅ Книгу тижня опубліковано в групу!")


async def cmd_film(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/film — публікує наступний фільм у тему групи."""
    log_command(update, "film")
    state = load_state()
    films = load_content("films.json")
    film, next_index = get_next_item(films, state, "film_index")

    text = format_film(film)
    await send_to_group(context, text)

    state["film_index"] = next_index
    save_state(state)

    await update.message.reply_text("✅ Фільм тижня опубліковано в групу!")


async def cmd_insight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/insight — публікує наступний інсайт у тему групи."""
    log_command(update, "insight")
    state = load_state()
    insights = load_content("insights.json")
    insight, next_index = get_next_item(insights, state, "insight_index")

    text = format_insight(insight)
    await send_to_group(context, text)

    state["insight_index"] = next_index
    save_state(state)

    await update.message.reply_text("✅ Інсайт тижня опубліковано в групу!")


async def cmd_testpost(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/testpost — надсилає тестове повідомлення в тему групи."""
    log_command(update, "testpost")
    text = (
        "🔧 *Тестове повідомлення від LexMind Bot*\n\n"
        "Якщо ви бачите це — бот успішно підключений до теми «Фільми, книги» ✅"
    )
    try:
        await send_to_group(context, text)
        await update.message.reply_text("✅ Тестове повідомлення надіслано в групу!")
    except Forbidden:
        await update.message.reply_text(
            "❌ Бот не має прав писати в групу.\n"
            "Додайте бота як адміністратора у групу «Зум посиденьки юристів»."
        )
    except TelegramError as e:
        await update.message.reply_text(f"❌ Помилка: {e}")


# ─── Нові рубрики: question / manipulation / phrase ──────────────────────────

async def cmd_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/question — публікує незручне питання тижня в групу."""
    log_command(update, "question")
    state = load_state()
    items = load_content("questions.json")
    item, next_index = get_next_item(items, state, "question_index")
    await send_to_group(context, format_question(item))
    state["question_index"] = next_index
    save_state(state)
    await update.message.reply_text("✅ Незручне питання тижня опубліковано!")


async def cmd_manipulation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/manipulation — публікує маніпуляцію тижня в групу."""
    log_command(update, "manipulation")
    state = load_state()
    items = load_content("manipulations.json")
    item, next_index = get_next_item(items, state, "manipulation_index")
    await send_to_group(context, format_manipulation(item))
    state["manipulation_index"] = next_index
    save_state(state)
    await update.message.reply_text("✅ Маніпуляцію тижня опубліковано!")


async def cmd_phrase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/phrase — публікує фразу для переговорів у групу."""
    log_command(update, "phrase")
    state = load_state()
    items = load_content("phrases.json")
    item, next_index = get_next_item(items, state, "phrase_index")
    await send_to_group(context, format_phrase(item))
    state["phrase_index"] = next_index
    save_state(state)
    await update.message.reply_text("✅ Фразу для переговорів опубліковано!")


async def cmd_previewquestion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/previewquestion — показує наступне питання у приваті."""
    log_command(update, "previewquestion")
    state = load_state()
    items = load_content("questions.json")
    item, _ = get_next_item(items, state, "question_index")
    total = len(items)
    current = state.get("question_index", 0) % total
    header = f"👁 *Попередній перегляд питання* ({current + 1}/{total}):\n\n"
    await update.message.reply_text(header + format_question(item), parse_mode="Markdown")


async def cmd_previewmanipulation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/previewmanipulation — показує наступну маніпуляцію у приваті."""
    log_command(update, "previewmanipulation")
    state = load_state()
    items = load_content("manipulations.json")
    item, _ = get_next_item(items, state, "manipulation_index")
    total = len(items)
    current = state.get("manipulation_index", 0) % total
    header = f"👁 *Попередній перегляд маніпуляції* ({current + 1}/{total}):\n\n"
    await update.message.reply_text(header + format_manipulation(item), parse_mode="Markdown")


async def cmd_previewphrase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/previewphrase — показує наступну фразу у приваті."""
    log_command(update, "previewphrase")
    state = load_state()
    items = load_content("phrases.json")
    item, _ = get_next_item(items, state, "phrase_index")
    total = len(items)
    current = state.get("phrase_index", 0) % total
    header = f"👁 *Попередній перегляд фрази* ({current + 1}/{total}):\n\n"
    await update.message.reply_text(header + format_phrase(item), parse_mode="Markdown")


# ─── /voice — представлення персонажа ───────────────────────────────────────

async def cmd_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/voice — хто такий LexMind."""
    log_command(update, "voice")
    await update.message.reply_text(VOICE_TEXT, parse_mode="Markdown")


# ─── LexMind Radar — команди і обробник повідомлень ─────────────────────────

def _radar_admin_only(update: Update) -> bool:
    """Повертає True якщо user є адміном радара."""
    return update.effective_user and update.effective_user.id == RADAR_ADMIN_ID


async def cmd_leadson(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/leadson — увімкнути радар (тільки адмін)."""
    log_command(update, "leadson")
    if not _radar_admin_only(update):
        await update.message.reply_text("⛔ Ця команда доступна тільки адміністратору.")
        return
    set_radar_enabled(True)
    await update.message.reply_text(
        "✅ LexMind Radar увімкнено\\.\n"
        "Я тихо слухаю потік і ловлю робочі можливості\\.",
        parse_mode="MarkdownV2",
    )


async def cmd_leadsoff(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/leadsoff — вимкнути радар (тільки адмін)."""
    log_command(update, "leadsoff")
    if not _radar_admin_only(update):
        await update.message.reply_text("⛔ Ця команда доступна тільки адміністратору.")
        return
    set_radar_enabled(False)
    await update.message.reply_text(
        "⏸ LexMind Radar вимкнено\\.\nЯ поки не ловлю заявки\\.",
        parse_mode="MarkdownV2",
    )


async def cmd_radar_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/radar_test — перевірка стану радара (тільки адмін)."""
    log_command(update, "radar_test")
    if not _radar_admin_only(update):
        await update.message.reply_text("⛔ Ця команда доступна тільки адміністратору.")
        return
    from radar import LEADS_FILE, RADAR_STATE_FILE
    enabled = is_radar_enabled()
    leads_count = len(get_today_leads())
    status = "увімкнено ✅" if enabled else "вимкнено ⏸"
    text = (
        f"✅ *Radar працює*\n\n"
        f"Статус: {status}\n"
        f"Файл leads: `{LEADS_FILE}`\n"
        f"Файл стану: `{RADAR_STATE_FILE}`\n"
        f"Ключових фраз: {len(LEAD_KEYWORDS)}\n"
        f"Leads сьогодні: {leads_count}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_lead_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/lead_keywords — показує список ключових фраз (тільки адмін)."""
    log_command(update, "lead_keywords")
    if not _radar_admin_only(update):
        await update.message.reply_text("⛔ Ця команда доступна тільки адміністратору.")
        return
    lines = [f"🔍 *Ключові фрази радара* ({len(LEAD_KEYWORDS)}):\n"]
    lines += [f"• {kw}" for kw in LEAD_KEYWORDS]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_leads_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/leads_today — leads за сьогодні (тільки адмін)."""
    log_command(update, "leads_today")
    if not _radar_admin_only(update):
        await update.message.reply_text("⛔ Ця команда доступна тільки адміністратору.")
        return
    leads = get_today_leads()
    if not leads:
        await update.message.reply_text(
            "Сьогодні я ще не бачив робочих сигналів.\n"
            "Або юристи нарешті перестали просити когось сходити в суд. Що малоймовірно."
        )
        return
    lines = [f"📌 *Leads today: {len(leads)}*\n"]
    for i, lead in enumerate(leads, 1):
        conf = lead.get("confidence", "?")
        kws = ", ".join(lead.get("matched_keywords", []))
        author = lead.get("from_name", "?")
        username = lead.get("from_username")
        if username:
            author += f" @{username}"
        text_preview = lead.get("text", "")[:80].replace("\n", " ")
        if len(lead.get("text", "")) > 80:
            text_preview += "…"
        lines.append(f"{i}. [{conf}] {kws}\nАвтор: {author}\nТекст: {text_preview}\n")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def handle_radar_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """MessageHandler — тихо аналізує кожне текстове повідомлення в групах."""
    msg = update.message
    # Debug: підтверджуємо що handler викликано
    _text_repr = repr(msg.text) if msg else "None"
    print(
        f"\n[RADAR] handle_radar_message called\n"
        f"  chat_id   = {msg.chat_id if msg else 'None'}\n"
        f"  chat_type = {msg.chat.type if msg else 'None'}\n"
        f"  thread_id = {msg.message_thread_id if msg else 'None'}\n"
        f"  text      = {_text_repr}",
        flush=True,
    )

    if not msg or not msg.text:
        return
    # Ігноруємо ботів
    if msg.from_user and msg.from_user.is_bot:
        return
    # Тільки групи / супергрупи
    if msg.chat.type not in ("group", "supergroup"):
        return
    # Радар вимкнений
    if not is_radar_enabled():
        return

    result = detect_lead(msg.text)
    if not result:
        return

    matched_keywords = result["matched_keywords"]
    logger.info("RADAR MATCH: %s", matched_keywords)

    # Захист від дублювання
    if already_saved(msg.chat_id, msg.message_id):
        return

    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _ZI
    now_iso = _dt.now(tz=_ZI("Europe/Kyiv")).isoformat()

    lead = {
        "created_at": now_iso,
        "chat_id": msg.chat_id,
        "chat_title": msg.chat.title or "",
        "message_thread_id": msg.message_thread_id,
        "message_id": msg.message_id,
        "from_user_id": msg.from_user.id if msg.from_user else None,
        "from_username": msg.from_user.username if msg.from_user else None,
        "from_name": msg.from_user.full_name if msg.from_user else "Невідомо",
        "text": msg.text,
        "matched_keywords": matched_keywords,
        "confidence": result["confidence"],
        "lead_type": result["lead_type"],
    }
    save_lead(lead)

    admin_text = build_admin_message(lead)
    try:
        await context.bot.send_message(
            chat_id=RADAR_ADMIN_ID,
            text=admin_text,
        )
        logger.info("RADAR ALERT SENT to admin")
        logger.info("Radar: сповіщення надіслано адміну, msg_id=%s", msg.message_id)
    except Exception as e:
        logger.error("Radar: не вдалось надіслати адміну: %s", e)


# ─── Адміністративні команди ─────────────────────────────────────────────────

async def cmd_topicinfo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/topicinfo — показує інфо про поточну тему форуму."""
    log_command(update, "topicinfo")
    msg = update.message
    thread_id = msg.message_thread_id

    if thread_id is None:
        await msg.reply_text(
            "ℹ️ Ця команда викликана поза темою форуму.\n"
            "Напишіть її всередині будь-якої теми групи."
        )
        return

    chat = msg.chat
    text = (
        f"📌 *Інфо про тему*\n\n"
        f"Тема: `{chat.title or '—'}`\n"
        f"chat\\_id: `{chat.id}`\n"
        f"message\\_thread\\_id: `{thread_id}`\n"
        f"Група: *{chat.title or '—'}*"
    )
    await msg.reply_text(text, parse_mode="Markdown")


async def cmd_testtopic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/testtopic — підтверджує, що бот бачить поточну тему."""
    log_command(update, "testtopic")
    msg = update.message
    thread_id = msg.message_thread_id

    if thread_id is None:
        await msg.reply_text(
            "⚠️ Ця команда викликана поза темою форуму.\n"
            "Напишіть її всередині теми, яку хочете перевірити."
        )
        return

    # Отримуємо назву теми через ForumTopic якщо є, або через reply_to_message
    topic_name = "—"
    if msg.reply_to_message and msg.reply_to_message.forum_topic_created:
        topic_name = msg.reply_to_message.forum_topic_created.name

    text = (
        f"✅ *LexMind бачить цю тему*\n\n"
        f"Тема: {topic_name}\n"
        f"message\\_thread\\_id: `{thread_id}`\n"
        f"chat\\_id: `{msg.chat_id}`"
    )
    await msg.reply_text(text, parse_mode="Markdown")


async def cmd_listtopics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/listtopics — виводить відомі боту теми групи."""
    log_command(update, "listtopics")

    # Статичний список відомих тем — додавайте нові після /topicinfo
    known_topics = [
        {"name": "Фільми, книги", "thread_id": 23975},
    ]

    lines = [f"📋 *Відомі теми групи* (chat\\_id: `{GROUP_CHAT_ID}`):\n"]
    for t in known_topics:
        lines.append(f"• *{t['name']}* — thread\\_id: `{t['thread_id']}`")
    lines.append(
        "\n💡 Щоб дізнатись thread\\_id нової теми — напишіть `/topicinfo` всередині неї."
    )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/health — звіт про стан бота."""
    log_command(update, "health")
    from datetime import datetime

    now = datetime.now(tz=KYIV_TZ)

    # Перевіряємо доступність Telegram API
    try:
        await context.bot.get_me()
        api_status = "✅ Telegram API доступний"
    except TelegramError:
        api_status = "❌ Telegram API недоступний"

    # Перевіряємо JobQueue — детально
    jq = context.application.job_queue
    jobs = jq.jobs() if jq else []
    if jobs:
        jq_active = f"✅ JobQueue активний — {len(jobs)} jobs"
        job_lines = []
        for j in jobs:
            next_run = ""
            if hasattr(j, "next_t") and j.next_t:
                try:
                    from datetime import timezone
                    nt = j.next_t.astimezone(KYIV_TZ)
                    next_run = f" → {nt.strftime('%a %H:%M')}"
                except Exception:
                    pass
            job_lines.append(f"  • {j.name}{next_run}")
        jq_detail = "\n".join(job_lines)
    else:
        jq_active = "⚠️ JobQueue: задачі не зареєстровані"
        jq_detail = ""

    # Рахуємо контент
    content_counts = {}
    content_ok = True
    for fname, label in [
        ("books.json", "📚 Books"),
        ("films.json", "🎬 Films"),
        ("insights.json", "⚖️ Insights"),
        ("questions.json", "❓ Questions"),
        ("manipulations.json", "🧩 Manipulations"),
        ("phrases.json", "🗣 Phrases"),
    ]:
        try:
            content_counts[label] = len(load_content(fname))
        except Exception:
            content_counts[label] = "❌"
            content_ok = False

    content_lines = "\n".join(f"{k}: {v}" for k, v in content_counts.items())
    jq_block = f"\n{jq_detail}" if jq_detail else ""

    text = (
        f"🩺 *LexMind Health Report*\n\n"
        f"Статус: {'OK ✅' if content_ok else 'ERROR ❌'}\n"
        f"Час: `{now.strftime('%Y\\-%m\\-%d %H:%M')}`\n"
        f"Timezone: `Europe/Kyiv`\n\n"
        f"✅ Бот працює\n"
        f"{api_status}\n"
        f"{jq_active}{jq_block}\n\n"
        f"{content_lines}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ─── Команди попереднього перегляду і адмін-скидання ────────────────────────

ADMIN_USER_ID = 219205800


async def cmd_previewbook(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/previewbook — показує наступну книгу у приваті, не публікуючи в групу."""
    log_command(update, "previewbook")
    state = load_state()
    books = load_content("books.json")
    book, _ = get_next_item(books, state, "book_index")
    total = len(books)
    current = state.get("book_index", 0) % total

    header = f"👁 *Попередній перегляд книги* ({current + 1}/{total}):\n\n"
    await update.message.reply_text(header + format_book(book), parse_mode="Markdown")


async def cmd_previewfilm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/previewfilm — показує наступний фільм у приваті, не публікуючи в групу."""
    log_command(update, "previewfilm")
    state = load_state()
    films = load_content("films.json")
    film, _ = get_next_item(films, state, "film_index")
    total = len(films)
    current = state.get("film_index", 0) % total

    header = f"👁 *Попередній перегляд фільму* ({current + 1}/{total}):\n\n"
    await update.message.reply_text(header + format_film(film), parse_mode="Markdown")


async def cmd_resetcontent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/resetcontent — скидає індекси state.json (тільки для адміна)."""
    log_command(update, "resetcontent")
    user_id = update.effective_user.id

    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("⛔ Ця команда доступна тільки адміністратору.")
        return

    save_state({
        "book_index": 0, "film_index": 0, "insight_index": 0,
        "question_index": 0, "manipulation_index": 0, "phrase_index": 0,
    })
    logger.info("Індекси контенту скинуто адміном (user_id=%s)", user_id)
    await update.message.reply_text("✅ Індекси контенту скинуто.")


# ─── Функції автопублікацій (JobQueue callbacks) ──────────────────────────────
# JobQueue передає context: CallbackContext, де context.bot — це бот

async def auto_book(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Щопонеділка о 10:00 — автоматична публікація книги тижня."""
    logger.info("Автопублікація: книга тижня")
    state = load_state()
    books = load_content("books.json")
    book, next_index = get_next_item(books, state, "book_index")

    await context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        message_thread_id=FILMS_BOOKS_THREAD_ID,
        text=format_book(book),
        parse_mode="Markdown",
    )

    state["book_index"] = next_index
    save_state(state)
    logger.info(f"Книга опублікована: {book['title']}")


async def auto_film(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Щочетверга о 10:00 — автоматична публікація фільму тижня."""
    logger.info("Автопублікація: фільм тижня")
    state = load_state()
    films = load_content("films.json")
    film, next_index = get_next_item(films, state, "film_index")

    await context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        message_thread_id=FILMS_BOOKS_THREAD_ID,
        text=format_film(film),
        parse_mode="Markdown",
    )

    state["film_index"] = next_index
    save_state(state)
    logger.info(f"Фільм опублікований: {film['title']}")


async def auto_insight(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Щоп'ятниці о 10:00 — автоматична публікація інсайту тижня."""
    logger.info("Автопублікація: інсайт тижня")
    state = load_state()
    insights = load_content("insights.json")
    insight, next_index = get_next_item(insights, state, "insight_index")

    await context.bot.send_message(
        chat_id=GROUP_CHAT_ID,
        message_thread_id=FILMS_BOOKS_THREAD_ID,
        text=format_insight(insight),
        parse_mode="Markdown",
    )

    state["insight_index"] = next_index
    save_state(state)
    logger.info(f"Інсайт опублікований: {insight['title']}")


async def auto_question(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Щовівторка о 10:00 — незручне питання тижня."""
    logger.info("Автопублікація: питання тижня")
    state = load_state()
    items = load_content("questions.json")
    item, next_index = get_next_item(items, state, "question_index")
    await context.bot.send_message(
        chat_id=GROUP_CHAT_ID, message_thread_id=FILMS_BOOKS_THREAD_ID,
        text=format_question(item), parse_mode="Markdown",
    )
    state["question_index"] = next_index
    save_state(state)
    logger.info("Питання опубліковано: %s", item["title"])


async def auto_manipulation(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Щосереди о 10:00 — маніпуляція тижня."""
    logger.info("Автопублікація: маніпуляція тижня")
    state = load_state()
    items = load_content("manipulations.json")
    item, next_index = get_next_item(items, state, "manipulation_index")
    await context.bot.send_message(
        chat_id=GROUP_CHAT_ID, message_thread_id=FILMS_BOOKS_THREAD_ID,
        text=format_manipulation(item), parse_mode="Markdown",
    )
    state["manipulation_index"] = next_index
    save_state(state)
    logger.info("Маніпуляція опублікована: %s", item["title"])


async def auto_phrase(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Щоп'ятниці о 15:00 — фраза для переговорів."""
    logger.info("Автопублікація: фраза для переговорів")
    state = load_state()
    items = load_content("phrases.json")
    item, next_index = get_next_item(items, state, "phrase_index")
    await context.bot.send_message(
        chat_id=GROUP_CHAT_ID, message_thread_id=FILMS_BOOKS_THREAD_ID,
        text=format_phrase(item), parse_mode="Markdown",
    )
    state["phrase_index"] = next_index
    save_state(state)
    logger.info("Фраза опублікована: %s", item["title"])


# ─── Реєстрація JobQueue задач ───────────────────────────────────────────────

def register_jobs(app: Application) -> None:
    """Реєструє заплановані публікації у вбудованому JobQueue PTB."""
    jq = app.job_queue

    # Пн 10:00 — книга тижня
    jq.run_daily(auto_book,        time=time(10, 0, tzinfo=KYIV_TZ), days=(0,), name="weekly_book")
    # Вт 10:00 — незручне питання
    jq.run_daily(auto_question,    time=time(10, 0, tzinfo=KYIV_TZ), days=(1,), name="weekly_question")
    # Ср 10:00 — маніпуляція
    jq.run_daily(auto_manipulation,time=time(10, 0, tzinfo=KYIV_TZ), days=(2,), name="weekly_manipulation")
    # Чт 10:00 — фільм тижня
    jq.run_daily(auto_film,        time=time(10, 0, tzinfo=KYIV_TZ), days=(3,), name="weekly_film")
    # Пт 10:00 — інсайт
    jq.run_daily(auto_insight,     time=time(10, 0, tzinfo=KYIV_TZ), days=(4,), name="weekly_insight")
    # Пт 15:00 — фраза для переговорів
    jq.run_daily(auto_phrase,      time=time(15, 0, tzinfo=KYIV_TZ), days=(4,), name="weekly_phrase")

    logger.info("JobQueue: заплановано Пн/Вт/Ср/Чт/Пт — 6 автопублікацій")


# ─── Повністю ручний async lifecycle (сумісний з Python 3.14) ────────────────

async def main_async() -> None:
    """
    Запускає бота без run_polling().
    asyncio.run() створює свіжий event loop — жодних викликів get_event_loop().
    """
    logger.info("Запуск LexMind Bot...")

    # Будуємо застосунок (без .post_init — задачі реєструємо вручну нижче)
    app = Application.builder().token(TOKEN).build()

    # Реєструємо команди — публічні
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("voice", cmd_voice))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("book", cmd_book))
    app.add_handler(CommandHandler("film", cmd_film))
    app.add_handler(CommandHandler("insight", cmd_insight))
    app.add_handler(CommandHandler("previewbook", cmd_previewbook))
    app.add_handler(CommandHandler("previewfilm", cmd_previewfilm))
    # Адміністративні
    app.add_handler(CommandHandler("question",           cmd_question))
    app.add_handler(CommandHandler("manipulation",       cmd_manipulation))
    app.add_handler(CommandHandler("phrase",             cmd_phrase))
    app.add_handler(CommandHandler("previewquestion",    cmd_previewquestion))
    app.add_handler(CommandHandler("previewmanipulation",cmd_previewmanipulation))
    app.add_handler(CommandHandler("previewphrase",      cmd_previewphrase))
    # Адміністративні
    app.add_handler(CommandHandler("health",             cmd_health))
    app.add_handler(CommandHandler("topicinfo",          cmd_topicinfo))
    app.add_handler(CommandHandler("testtopic",          cmd_testtopic))
    app.add_handler(CommandHandler("listtopics",         cmd_listtopics))
    app.add_handler(CommandHandler("resetcontent",       cmd_resetcontent))
    # Radar команди
    app.add_handler(CommandHandler("leadson",            cmd_leadson))
    app.add_handler(CommandHandler("leadsoff",           cmd_leadsoff))
    app.add_handler(CommandHandler("radar_test",         cmd_radar_test))
    app.add_handler(CommandHandler("lead_keywords",      cmd_lead_keywords))
    app.add_handler(CommandHandler("leads_today",        cmd_leads_today))
    # Radar MessageHandler — аналізує групові повідомлення
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_radar_message))

    # Ініціалізація (підключення до Telegram API, підготовка JobQueue)
    await app.initialize()

    # Синхронізуємо список команд з BotFather (відображається у меню /)
    from telegram import BotCommand
    await app.bot.set_my_commands([
        BotCommand("start",               "Вступ від LexMind"),
        BotCommand("voice",               "Хто такий LexMind"),
        BotCommand("help",                "Список команд"),
        BotCommand("book",                "📚 Книжкова провокація тижня → в групу"),
        BotCommand("film",                "🎬 Кінопровокація тижня → в групу"),
        BotCommand("insight",             "💡 Думка тижня → в групу"),
        BotCommand("question",            "❓ Незручне питання тижня → в групу"),
        BotCommand("manipulation",        "🧩 Маніпуляція тижня → в групу"),
        BotCommand("phrase",              "🗣 Фраза для переговорів → в групу"),
        BotCommand("previewbook",         "👁 Наступна книга (без публікації)"),
        BotCommand("previewfilm",         "👁 Наступний фільм (без публікації)"),
        BotCommand("previewquestion",     "👁 Наступне питання (без публікації)"),
        BotCommand("previewmanipulation", "👁 Наступна маніпуляція (без публікації)"),
        BotCommand("previewphrase",       "👁 Наступна фраза (без публікації)"),
        BotCommand("health",              "⚙️ Стан бота і JobQueue"),
        BotCommand("topicinfo",           "ℹ️ Інфо про тему форуму"),
        BotCommand("testtopic",           "✅ Перевірити видимість теми"),
        BotCommand("listtopics",          "📋 Список відомих тем"),
        BotCommand("resetcontent",        "🔄 Скинути індекси (тільки адмін)"),
        BotCommand("leadson",             "📡 Увімкнути Radar (адмін)"),
        BotCommand("leadsoff",            "📡 Вимкнути Radar (адмін)"),
        BotCommand("radar_test",          "🔍 Статус Radar (адмін)"),
        BotCommand("lead_keywords",       "🔍 Ключові фрази Radar (адмін)"),
        BotCommand("leads_today",         "📌 Leads за сьогодні (адмін)"),
    ])
    logger.info("Команди синхронізовано з BotFather")

    # Реєструємо JobQueue задачі після initialize(), але до start()
    register_jobs(app)

    # Запускаємо dispatcher і JobQueue
    await app.start()

    # Починаємо отримувати оновлення через long polling
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("Бот запущений і чекає на команди. Зупинити: Ctrl+C")

    # Тримаємо процес живим до Ctrl+C
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
