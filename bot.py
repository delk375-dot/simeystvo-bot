"""
Сімейство AI — Telegram-бот для генерації лідів та продажу юридичних послуг.
АО Сімейство | Василь Васильович Масюк | Адвокат | к.ю.н. | магістр психології
"""

import asyncio
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from personality import (
    WELCOME_TEXT,
    ABOUT_TEXT,
    CONSULTATION_TEXT,
    CONSULT_NAME_TEXT,
    CONSULT_PHONE_TEXT,
    SUCCESS_CONSULTATION_TEXT,
    REQUEST_TEXT,
    REQUEST_NAME_TEXT,
    REQUEST_PHONE_TEXT,
    REQUEST_DESC_TEXT,
    SUCCESS_REQUEST_TEXT,
    BOOKS_TEXT,
    COURSES_TEXT,
    SERVICES_TEXT,
    BOOK_INTEREST_TEXT,
    COURSE_INTEREST_TEXT,
)

# ─── Конфігурація ─────────────────────────────────────────────────────────────
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "219205800"))

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не знайдено у .env файлі")

BASE_DIR = Path(__file__).parent
CONTENT_DIR = BASE_DIR / "content"

# ─── Логування ───────────────────────────────────────────────────────────────
LOG_FILE = BASE_DIR / "logs" / "bot.log"
LOG_FILE.parent.mkdir(exist_ok=True)
_fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
_ch = logging.StreamHandler()
_ch.setFormatter(_fmt)
_fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
_fh.setFormatter(_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_ch, _fh])
logger = logging.getLogger(__name__)


def load_json(filename: str) -> list:
    with open(CONTENT_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


# ─── Стани розмови ───────────────────────────────────────────────────────────
(
    CONSULT_TYPE,
    CONSULT_NAME,
    CONSULT_PHONE,
    REQUEST_NAME,
    REQUEST_PHONE,
    REQUEST_DESC,
) = range(6)


# ─── Клавіатури ──────────────────────────────────────────────────────────────

def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏛 Юридичні послуги", callback_data="services")],
        [InlineKeyboardButton("📚 Книги",             callback_data="books")],
        [InlineKeyboardButton("🎓 Відеокурси",        callback_data="courses")],
        [InlineKeyboardButton("📞 Консультація",      callback_data="consultation")],
        [InlineKeyboardButton("📝 Залишити заявку",   callback_data="request")],
        [InlineKeyboardButton("ℹ️ Про нас",           callback_data="about")],
    ])


def kb_services() -> InlineKeyboardMarkup:
    services = load_json("services.json")
    rows = [
        [InlineKeyboardButton(f"{s['emoji']} {s['title']}", callback_data=f"service:{s['id']}")]
        for s in services
    ]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)


def kb_service_detail() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📞 Замовити консультацію", callback_data="consultation")],
        [InlineKeyboardButton("⬅️ Назад до послуг",      callback_data="services")],
    ])


def kb_consultation() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💻 Онлайн консультація", callback_data="consult:online")],
        [InlineKeyboardButton("🤝 Особиста зустріч",    callback_data="consult:meeting")],
        [InlineKeyboardButton("⚡ Термінове питання",   callback_data="consult:urgent")],
        [InlineKeyboardButton("⬅️ Назад",               callback_data="back_main")],
    ])


def kb_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Головне меню", callback_data="back_main")],
    ])


# ─── /start ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await update.message.reply_text(WELCOME_TEXT, reply_markup=kb_main())


# ─── Головне меню (callback) ─────────────────────────────────────────────────

async def cb_back_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(WELCOME_TEXT, reply_markup=kb_main())


# ─── Юридичні послуги ────────────────────────────────────────────────────────

async def cb_services(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(SERVICES_TEXT, reply_markup=kb_services())


async def cb_service_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    service_id = query.data.split(":", 1)[1]
    services = load_json("services.json")
    service = next((s for s in services if s["id"] == service_id), None)
    if not service:
        await query.answer("Послугу не знайдено", show_alert=True)
        return
    text = (
        f"{service['emoji']} *{service['title']}*\n\n"
        f"{service['description']}\n\n"
        f"⏱ *Строки:* {service['typical_terms']}"
    )
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb_service_detail())


# ─── Книги ───────────────────────────────────────────────────────────────────

async def cb_books(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    books = load_json("books.json")
    rows = [
        [InlineKeyboardButton(f"📖 {b['title']} — {b['price']}", callback_data=f"book:{b['id']}")]
        for b in books
    ]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_main")])
    await query.edit_message_text(BOOKS_TEXT, reply_markup=InlineKeyboardMarkup(rows))


async def cb_book_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    book_id = int(query.data.split(":", 1)[1])
    books = load_json("books.json")
    book = next((b for b in books if b["id"] == book_id), None)
    if not book:
        await query.answer("Книгу не знайдено", show_alert=True)
        return
    text = (
        f"📖 *{book['title']}*\n\n"
        f"{book['description']}\n\n"
        f"💰 *Ціна:* {book['price']}"
    )
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Цікавить книга",    callback_data=f"book_interest:{book_id}")],
            [InlineKeyboardButton("⬅️ Назад до книг",    callback_data="books")],
        ]),
    )


async def cb_book_interest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    book_id = int(query.data.split(":", 1)[1])
    books = load_json("books.json")
    book = next((b for b in books if b["id"] == book_id), None)
    user = query.from_user
    username = f"@{user.username}" if user.username else "без username"

    admin_text = (
        f"📚 *Інтерес до книги*\n\n"
        f"Книга: *{book['title'] if book else book_id}*\n"
        f"Користувач: {user.full_name} ({username})\n"
        f"Telegram ID: `{user.id}`"
    )
    try:
        await context.bot.send_message(ADMIN_CHAT_ID, admin_text, parse_mode="Markdown")
        logger.info("Книга [%s] — інтерес від user_id=%s", book_id, user.id)
    except Exception as e:
        logger.error("Помилка відправки адміну: %s", e)

    await query.edit_message_text(BOOK_INTEREST_TEXT, reply_markup=kb_home())


# ─── Відеокурси ──────────────────────────────────────────────────────────────

async def cb_courses(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    courses = load_json("courses.json")
    rows = [
        [InlineKeyboardButton(f"🎓 {c['title']} — {c['price']}", callback_data=f"course:{c['id']}")]
        for c in courses
    ]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_main")])
    await query.edit_message_text(COURSES_TEXT, reply_markup=InlineKeyboardMarkup(rows))


async def cb_course_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    course_id = int(query.data.split(":", 1)[1])
    courses = load_json("courses.json")
    course = next((c for c in courses if c["id"] == course_id), None)
    if not course:
        await query.answer("Курс не знайдено", show_alert=True)
        return
    text = (
        f"🎓 *{course['title']}*\n\n"
        f"{course['description']}\n\n"
        f"💰 *Ціна:* {course['price']}"
    )
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Хочу отримати",      callback_data=f"course_interest:{course_id}")],
            [InlineKeyboardButton("⬅️ Назад до курсів",   callback_data="courses")],
        ]),
    )


async def cb_course_interest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    course_id = int(query.data.split(":", 1)[1])
    courses = load_json("courses.json")
    course = next((c for c in courses if c["id"] == course_id), None)
    user = query.from_user
    username = f"@{user.username}" if user.username else "без username"

    admin_text = (
        f"🎓 *Інтерес до курсу*\n\n"
        f"Курс: *{course['title'] if course else course_id}*\n"
        f"Користувач: {user.full_name} ({username})\n"
        f"Telegram ID: `{user.id}`"
    )
    try:
        await context.bot.send_message(ADMIN_CHAT_ID, admin_text, parse_mode="Markdown")
        logger.info("Курс [%s] — інтерес від user_id=%s", course_id, user.id)
    except Exception as e:
        logger.error("Помилка відправки адміну: %s", e)

    await query.edit_message_text(COURSE_INTEREST_TEXT, reply_markup=kb_home())


# ─── Про нас ─────────────────────────────────────────────────────────────────

async def cb_about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(ABOUT_TEXT, reply_markup=kb_home())


# ─── Консультація (ConversationHandler) ──────────────────────────────────────

async def cb_consultation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(CONSULTATION_TEXT, reply_markup=kb_consultation())
    return CONSULT_TYPE


async def cb_consult_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    type_key = query.data.split(":", 1)[1]
    labels = {
        "online":  "💻 Онлайн консультація",
        "meeting": "🤝 Особиста зустріч",
        "urgent":  "⚡ Термінове питання",
    }
    context.user_data["consult_type"] = labels.get(type_key, type_key)
    await query.edit_message_text(
        f"Ви обрали: *{context.user_data['consult_type']}*\n\n{CONSULT_NAME_TEXT}",
        parse_mode="Markdown",
    )
    return CONSULT_NAME


async def consult_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["consult_name"] = update.message.text.strip()
    await update.message.reply_text(
        f"Дякую, *{context.user_data['consult_name']}*.\n\n{CONSULT_PHONE_TEXT}",
        parse_mode="Markdown",
    )
    return CONSULT_PHONE


async def consult_get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone = update.message.text.strip()
    user = update.message.from_user
    username = f"@{user.username}" if user.username else "без username"
    name = context.user_data.get("consult_name", "—")
    consult_type = context.user_data.get("consult_type", "—")

    admin_text = (
        f"📞 *Нова заявка на консультацію*\n\n"
        f"Тип: *{consult_type}*\n"
        f"Ім'я: *{name}*\n"
        f"Телефон: `{phone}`\n"
        f"Telegram: {user.full_name} ({username})\n"
        f"ID: `{user.id}`"
    )
    try:
        await context.bot.send_message(ADMIN_CHAT_ID, admin_text, parse_mode="Markdown")
        logger.info("Консультація — заявка від user_id=%s (%s)", user.id, consult_type)
    except Exception as e:
        logger.error("Помилка відправки адміну: %s", e)

    await update.message.reply_text(SUCCESS_CONSULTATION_TEXT, reply_markup=kb_home())
    context.user_data.clear()
    return ConversationHandler.END


# ─── Залишити заявку (ConversationHandler) ───────────────────────────────────

async def cb_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(REQUEST_TEXT)
    return REQUEST_NAME


async def req_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["req_name"] = update.message.text.strip()
    await update.message.reply_text(
        f"Дякую, *{context.user_data['req_name']}*.\n\n{REQUEST_PHONE_TEXT}",
        parse_mode="Markdown",
    )
    return REQUEST_PHONE


async def req_get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["req_phone"] = update.message.text.strip()
    await update.message.reply_text(REQUEST_DESC_TEXT, parse_mode="Markdown")
    return REQUEST_DESC


async def req_get_desc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    desc = update.message.text.strip()
    user = update.message.from_user
    username = f"@{user.username}" if user.username else "без username"
    name = context.user_data.get("req_name", "—")
    phone = context.user_data.get("req_phone", "—")

    admin_text = (
        f"📝 *Нова заявка*\n\n"
        f"Ім'я: *{name}*\n"
        f"Телефон: `{phone}`\n"
        f"Ситуація: {desc}\n\n"
        f"Telegram: {user.full_name} ({username})\n"
        f"ID: `{user.id}`"
    )
    try:
        await context.bot.send_message(ADMIN_CHAT_ID, admin_text, parse_mode="Markdown")
        logger.info("Заявка — від user_id=%s", user.id)
    except Exception as e:
        logger.error("Помилка відправки адміну: %s", e)

    await update.message.reply_text(SUCCESS_REQUEST_TEXT, reply_markup=kb_home())
    context.user_data.clear()
    return ConversationHandler.END


# ─── Скасування розмови ──────────────────────────────────────────────────────

async def conv_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(WELCOME_TEXT, reply_markup=kb_main())
    elif update.message:
        await update.message.reply_text(
            "Добре, зупиняємося. Повертаємося до головного меню.",
            reply_markup=kb_home(),
        )
    return ConversationHandler.END


# ─── Запуск бота ─────────────────────────────────────────────────────────────

async def main_async() -> None:
    logger.info("Запуск Сімейство AI Bot...")

    app = Application.builder().token(TOKEN).build()

    # ConversationHandler — консультація
    consult_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_consultation, pattern="^consultation$")],
        states={
            CONSULT_TYPE: [
                CallbackQueryHandler(cb_consult_type, pattern="^consult:"),
                CallbackQueryHandler(conv_cancel,     pattern="^back_main$"),
            ],
            CONSULT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, consult_get_name),
            ],
            CONSULT_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, consult_get_phone),
            ],
        },
        fallbacks=[
            CommandHandler("start",  conv_cancel),
            CommandHandler("cancel", conv_cancel),
            CallbackQueryHandler(conv_cancel, pattern="^back_main$"),
        ],
        per_message=False,
        allow_reentry=True,
    )

    # ConversationHandler — залишити заявку
    request_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_request, pattern="^request$")],
        states={
            REQUEST_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, req_get_name),
            ],
            REQUEST_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, req_get_phone),
            ],
            REQUEST_DESC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, req_get_desc),
            ],
        },
        fallbacks=[
            CommandHandler("start",  conv_cancel),
            CommandHandler("cancel", conv_cancel),
            CallbackQueryHandler(conv_cancel, pattern="^back_main$"),
        ],
        per_message=False,
        allow_reentry=True,
    )

    # ConversationHandlers першими
    app.add_handler(consult_conv)
    app.add_handler(request_conv)

    # Команди
    app.add_handler(CommandHandler("start", cmd_start))

    # Callback handlers
    app.add_handler(CallbackQueryHandler(cb_back_main,       pattern="^back_main$"))
    app.add_handler(CallbackQueryHandler(cb_services,        pattern="^services$"))
    app.add_handler(CallbackQueryHandler(cb_service_detail,  pattern="^service:"))
    app.add_handler(CallbackQueryHandler(cb_books,           pattern="^books$"))
    app.add_handler(CallbackQueryHandler(cb_book_detail,     pattern="^book:\\d+$"))
    app.add_handler(CallbackQueryHandler(cb_book_interest,   pattern="^book_interest:\\d+$"))
    app.add_handler(CallbackQueryHandler(cb_courses,         pattern="^courses$"))
    app.add_handler(CallbackQueryHandler(cb_course_detail,   pattern="^course:\\d+$"))
    app.add_handler(CallbackQueryHandler(cb_course_interest, pattern="^course_interest:\\d+$"))
    app.add_handler(CallbackQueryHandler(cb_about,           pattern="^about$"))

    await app.initialize()

    await app.bot.set_my_commands([
        BotCommand("start",  "🏠 Головне меню"),
        BotCommand("cancel", "❌ Скасувати поточну дію"),
    ])
    logger.info("Команди синхронізовано з BotFather")

    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("Сімейство AI Bot запущений. Зупинити: Ctrl+C")

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
