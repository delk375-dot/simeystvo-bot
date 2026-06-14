"""
bot_core.py — ядро бота Сімейство AI.

Містить усі handlers, callback-и та ConversationHandler.
Експортує build_application() — використовується і polling (bot.py),
і webhook (api/telegram.py).
"""

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
    REQUEST_TEXT,
    SUCCESS_REQUEST_TEXT,
    BOOKS_TEXT,
    SERVICES_TEXT,
    BOOK_INTEREST_TEXT,
)

# ─── Конфігурація ─────────────────────────────────────────────────────────────
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "219205800"))
CHANNEL_ID = os.getenv("CHANNEL_ID")

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN не знайдено у .env файлі")

BASE_DIR = Path(__file__).parent
CONTENT_DIR = BASE_DIR / "content"

logger = logging.getLogger(__name__)


def load_json(filename: str) -> list:
    with open(CONTENT_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


# ─── Стани розмови ───────────────────────────────────────────────────────────
REQUEST_DESC = 0


# ─── Клавіатури ──────────────────────────────────────────────────────────────

def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📞 Телефон",  callback_data="phone"),
            InlineKeyboardButton("📱 Viber",   url="https://invite.viber.com/?number=380678390916"),
        ],
        [
            InlineKeyboardButton("🏛 Послуги",       callback_data="services"),
            InlineKeyboardButton("📚 Мої книги",     callback_data="books"),
        ],
        [
            InlineKeyboardButton("📝 Консультація",  callback_data="request"),
            InlineKeyboardButton("👨‍⚖️ Про адвоката", callback_data="about"),
        ],
    ])


def kb_services() -> InlineKeyboardMarkup:
    services = load_json("services.json")
    # Кнопки по 2 в ряд
    rows = []
    for i in range(0, len(services), 2):
        pair = services[i:i + 2]
        rows.append([
            InlineKeyboardButton(
                f"{s['emoji']} {s.get('button_title', s['title'])}",
                callback_data=f"service:{s['id']}",
            )
            for s in pair
        ])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)


def kb_service_detail() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Консультація",  callback_data="request")],
        [InlineKeyboardButton("⬅️ Назад до послуг", callback_data="services")],
    ])


def kb_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Головне меню", callback_data="back_main")],
    ])


# ─── /start ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await update.message.reply_text(WELCOME_TEXT, reply_markup=kb_main())


# ─── Головне меню ────────────────────────────────────────────────────────────

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
        await query.answer("Не можу знайти цю послугу — спробуйте ще раз", show_alert=True)
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
        await query.answer("Не можу знайти цю книгу — спробуйте ще раз", show_alert=True)
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
            [InlineKeyboardButton("✅ Цікавить книга", callback_data=f"book_interest:{book_id}")],
            [InlineKeyboardButton("⬅️ Назад до книг", callback_data="books")],
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


# ─── Контакти ────────────────────────────────────────────────────────────────

async def cb_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    text = (
        "📞 Телефон адвоката:\n"
        "+380678390916\n\n"
        "Якщо питання термінове — краще одразу телефонуйте.\n"
        "Якщо може почекати — опишіть ситуацію в розділі «📝 Консультація»."
    )
    await query.edit_message_text(text, reply_markup=kb_home())


# ─── Про адвоката ─────────────────────────────────────────────────────────────

async def cb_about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(ABOUT_TEXT, reply_markup=kb_home())


# ─── Консультація (ConversationHandler) ──────────────────────────────────────

async def cb_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(REQUEST_TEXT)
    return REQUEST_DESC


async def req_get_desc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    desc = update.message.text.strip()
    user = update.message.from_user
    username = f"@{user.username}" if user.username else "без username"

    admin_text = (
        f"📝 *Нова заявка на консультацію*\n\n"
        f"Ситуація: {desc}\n\n"
        f"Telegram name: {user.full_name}\n"
        f"Username: {username}\n"
        f"Telegram ID: `{user.id}`"
    )
    try:
        await context.bot.send_message(ADMIN_CHAT_ID, admin_text, parse_mode="Markdown")
        logger.info("Заявка на консультацію — від user_id=%s", user.id)
    except Exception as e:
        logger.error("Помилка відправки адміну: %s", e)

    await update.message.reply_text(SUCCESS_REQUEST_TEXT, reply_markup=kb_home())
    return ConversationHandler.END


# ─── Публікація в канал ──────────────────────────────────────────────────────

async def publish_to_channel(bot, text: str) -> None:
    if not CHANNEL_ID:
        raise ValueError("CHANNEL_ID не задано")
    await bot.send_message(chat_id=CHANNEL_ID, text=text)


async def cmd_publish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("Ця команда доступна тільки адміністратору.")
        return

    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("Використання: /publish текст повідомлення")
        return

    if not CHANNEL_ID:
        await update.message.reply_text("❌ CHANNEL_ID не задано в Environment Variables.")
        return

    try:
        await publish_to_channel(context.bot, text)
        await update.message.reply_text("✅ Опубліковано в канал.")
        logger.info("Публікація в канал від admin: %s...", text[:50])
    except Exception as e:
        logger.error("Помилка публікації в канал: %s", e)
        await update.message.reply_text(f"❌ Помилка: {e}")


# ─── Скасування розмови ──────────────────────────────────────────────────────

async def conv_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(WELCOME_TEXT, reply_markup=kb_main())
    elif update.message:
        await update.message.reply_text(
            "Добре, зупиняємось. Повертаю до головного меню — якщо що, я тут. 🤖",
            reply_markup=kb_home(),
        )
    return ConversationHandler.END


# ─── Збірка Application ──────────────────────────────────────────────────────

def build_application() -> Application:
    """
    Створює Application і реєструє всі handlers.
    Не викликає initialize() / start() — це робить виклик ззовні.
    """
    app = Application.builder().token(TOKEN).build()

    request_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_request, pattern="^request$")],
        states={
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

    app.add_handler(request_conv)
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("publish", cmd_publish))
    app.add_handler(CallbackQueryHandler(cb_back_main,      pattern="^back_main$"))
    app.add_handler(CallbackQueryHandler(cb_services,       pattern="^services$"))
    app.add_handler(CallbackQueryHandler(cb_service_detail, pattern="^service:"))
    app.add_handler(CallbackQueryHandler(cb_books,          pattern="^books$"))
    app.add_handler(CallbackQueryHandler(cb_book_detail,    pattern="^book:\\d+$"))
    app.add_handler(CallbackQueryHandler(cb_book_interest,  pattern="^book_interest:\\d+$"))
    app.add_handler(CallbackQueryHandler(cb_phone,          pattern="^phone$"))
    app.add_handler(CallbackQueryHandler(cb_about,          pattern="^about$"))

    return app
