"""
bot_core.py — ядро бота Сімейство AI.

Містить усі handlers, callback-и та ConversationHandler.
Експортує build_application() — використовується і polling (bot.py),
і webhook (api/telegram.py).
"""

import json
import logging
import os
import random
from pathlib import Path

from dotenv import load_dotenv
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from stats import track_start, increment

from personality import (
    WELCOME_TEXT,
    ABOUT_TEXT,
    REQUEST_TEXT,
    SUCCESS_REQUEST_TEXT,
    CONSULTATION_CONTACT_RECEIVED,
    BOOKS_TEXT,
    SERVICES_TEXT,
    BOOK_INTEREST_CONTACT_REQUEST,
    BOOK_INTEREST_CONTACT_RECEIVED,
    PHONE_TEXT,
    PHONE_CALL_TEXT,
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
ASSESS_TOPIC = 10
ASSESS_Q     = 11


# ─── Клавіатури ──────────────────────────────────────────────────────────────

def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏛 Послуги",              callback_data="services"),
            InlineKeyboardButton("📚 Книги",                callback_data="books"),
        ],
        [
            InlineKeyboardButton("📝 Консультація",         callback_data="request"),
            InlineKeyboardButton("🎯 Шанси на успіх",       callback_data="assess"),
        ],
        [
            InlineKeyboardButton("👨‍⚖️ Про адвоката",        callback_data="about"),
            InlineKeyboardButton("🧠 Порада дня",           callback_data="tips"),
        ],
        [
            InlineKeyboardButton("📚 Архів справ",           callback_data="archive"),
            InlineKeyboardButton("📞 Телефон",              callback_data="phone"),
        ],
    ])


def kb_services() -> InlineKeyboardMarkup:
    services = load_json("services.json")
    rows = [[InlineKeyboardButton("💰 Скільки це може коштувати?", callback_data="cost_info")]]
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


def kb_after_request() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Написати ще",  callback_data="request")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="back_main")],
    ])


def kb_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Статистика",            callback_data="admin_stats"),
            InlineKeyboardButton("📢 Опублікувати в канал",  callback_data="admin_publish"),
        ],
        [
            InlineKeyboardButton("👤 Переглянути як клієнт", callback_data="admin_view_client"),
            InlineKeyboardButton("🎯 Тест: Шанси на успіх",  callback_data="assess"),
        ],
        [
            InlineKeyboardButton("📚 Тест: Книги",           callback_data="books"),
            InlineKeyboardButton("📝 Тест: Консультація",    callback_data="request"),
        ],
    ])


ADMIN_PANEL_TEXT = (
    "👑 *Панель CooLaw*\n\n"
    "Ви в адмінському режимі.\n\n"
    "Тут можна перевірити статистику, опублікувати пост у канал або протестувати клієнтські сценарії.\n\n"
    "Оберіть дію:"
)


# ─── /start ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    if update.effective_user:
        track_start(update.effective_user.id)
        if update.effective_user.id == ADMIN_CHAT_ID:
            await update.message.reply_text(ADMIN_PANEL_TEXT, parse_mode="Markdown", reply_markup=kb_admin())
            return
    await update.message.reply_text(WELCOME_TEXT, reply_markup=kb_main())


# ─── Головне меню ────────────────────────────────────────────────────────────

async def cb_back_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data.pop("book_interest_pending",        None)
    context.user_data.pop("book_interest_title",          None)
    context.user_data.pop("book_interest_user",           None)
    context.user_data.pop("consultation_contact_pending", None)
    context.user_data.pop("consultation_original_text",   None)
    context.user_data.pop("consultation_user",            None)
    if query.message.photo:
        await query.message.delete()
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=WELCOME_TEXT,
            reply_markup=kb_main(),
        )
    else:
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
    context.user_data["selected_service"] = service["title"]
    text = (
        f"{service['emoji']} *{service['title']}*\n\n"
        f"{service['description']}\n\n"
        f"⏱ *Строки:* {service['typical_terms']}"
    )
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb_service_detail())


# ─── Вартість послуг ─────────────────────────────────────────────────────────

COST_INFO_TEXT = (
    "💰 *Скільки це може коштувати?*\n\n"
    "Послухайте мене уважно.\n\n"
    "Розлучення, спадщина, ДТП чи кримінальна справа — це різний обсяг роботи.\n\n"
    "Тому я не люблю називати цифри навмання.\n\n"
    "Це було б схоже на те, як лікар називає вартість лікування ще до огляду пацієнта.\n\n"
    "Якщо хочете отримати орієнтир саме по своїй ситуації — просто опишіть проблему своїми словами.\n\n"
    "Я передам фабулу справи адвокату.\n\n"
    "Після ознайомлення із ситуацією Василь Васильович або хтось із команди повідомить:\n\n"
    "• можливі варіанти вирішення;\n\n"
    "• орієнтовну вартість допомоги;\n\n"
    "• що можна зробити вже зараз.\n\n"
    "🤖 Моє завдання — допомогти вам зорієнтуватися і доставити інформацію адвокату."
)


async def cb_cost_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        COST_INFO_TEXT,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Описати ситуацію", callback_data="request")],
            [InlineKeyboardButton("⚖️ Послуги",          callback_data="services")],
            [InlineKeyboardButton("🏠 Головне меню",     callback_data="back_main")],
        ]),
    )


# ─── Книги ───────────────────────────────────────────────────────────────────

async def cb_books(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    books = load_json("books.json")
    rows = [
        [InlineKeyboardButton(
            f"📘 {b.get('short_title', b['title'])}\n{'🎁' if b.get('url') else '💰'} {b['price']}",
            callback_data=f"book:{b['id']}",
        )]
        for b in books
    ]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_main")])
    markup = InlineKeyboardMarkup(rows)

    if query.message.photo:
        # Повертаємося з фото-повідомлення (обкладинка) — edit_message_text тут неприпустимий
        await query.message.delete()
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=BOOKS_TEXT,
            reply_markup=markup,
        )
    else:
        await query.edit_message_text(BOOKS_TEXT, reply_markup=markup)


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
    if book.get("url"):
        action_button = InlineKeyboardButton("📥 Завантажити PDF", url=book["url"])
    else:
        action_button = InlineKeyboardButton("✅ Цікавить книга", callback_data=f"book_interest:{book_id}")
    keyboard = InlineKeyboardMarkup([
        [action_button],
        [InlineKeyboardButton("⬅️ Назад до книг", callback_data="books")],
    ])

    cover_filename = book.get("cover", "")
    if cover_filename:
        cover_path = CONTENT_DIR / "book_covers" / cover_filename
        logger.info("Обкладинка книги %s: %s (exists=%s)", book_id, cover_path, cover_path.exists())
        if cover_path.exists():
            try:
                await query.message.delete()
                with open(cover_path, "rb") as photo:
                    await context.bot.send_photo(
                        chat_id=query.message.chat_id,
                        photo=photo,
                        caption=text,
                        parse_mode="Markdown",
                        reply_markup=keyboard,
                    )
                return
            except Exception as e:
                logger.error("Помилка відправки обкладинки книги %s: %s", book_id, e)

    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def cb_book_interest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    book_id = int(query.data.split(":", 1)[1])
    books = load_json("books.json")
    book = next((b for b in books if b["id"] == book_id), None)
    user = query.from_user
    username = f"@{user.username}" if user.username else "без username"
    book_title = book["title"] if book else str(book_id)

    admin_text = (
        f"📚 *Інтерес до книги*\n\n"
        f"Книга: *{book_title}*\n"
        f"Користувач: {user.full_name} ({username})\n"
        f"Telegram ID: `{user.id}`\n\n"
        f"Контакт: очікується окремим повідомленням"
    )
    try:
        await context.bot.send_message(ADMIN_CHAT_ID, admin_text, parse_mode="Markdown")
        logger.info("Книга [%s] — інтерес від user_id=%s", book_id, user.id)
    except Exception as e:
        logger.error("Помилка відправки адміну: %s", e)

    increment("book_interest")
    context.user_data["book_interest_pending"] = True
    context.user_data["book_interest_title"]   = book_title
    context.user_data["book_interest_user"]    = {
        "full_name": user.full_name,
        "username":  username,
        "id":        user.id,
    }

    if query.message.photo:
        await query.message.delete()
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=BOOK_INTEREST_CONTACT_REQUEST,
            reply_markup=kb_home(),
        )
    else:
        await query.edit_message_text(BOOK_INTEREST_CONTACT_REQUEST, reply_markup=kb_home())


# ─── Порада дня ──────────────────────────────────────────────────────────────

def _kb_tips() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Ще одна порада", callback_data="tips")],
        [InlineKeyboardButton("📝 Консультація",   callback_data="request")],
        [InlineKeyboardButton("🏠 Головне меню",   callback_data="back_main")],
    ])


async def cb_tips(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    try:
        tips = load_json("tips.json")
        if not tips:
            raise ValueError("порожньо")
        tip = random.choice(tips)
        text = (
            f"🧠 *Порада від CooLaw*\n\n"
            f"{tip['text']}\n\n"
            f"🤖 Якщо ваша ситуація складніша за одну пораду — натисніть «Консультація»."
        )
        try:
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=_kb_tips())
        except BadRequest as e:
            if "not modified" in str(e).lower():
                pass  # та сама порада обрана двічі підряд — повідомлення вже актуальне
            else:
                raise
    except Exception as e:
        logger.error("Помилка завантаження порад: %s", e)
        await query.edit_message_text(
            "🧠 Поради тимчасово недоступні.\n\nСпробуйте пізніше або зверніться через «📝 Консультація».",
            reply_markup=kb_home(),
        )


# ─── Архів справ ─────────────────────────────────────────────────────────────

def _kb_archive() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Ще одна історія", callback_data="archive")],
        [InlineKeyboardButton("🏠 Головне меню",    callback_data="back_main")],
    ])


async def cb_archive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    try:
        stories = load_json("archive.json")
        if not stories:
            raise ValueError("порожньо")
        story = random.choice(stories)
        try:
            await query.edit_message_text(story["text"], parse_mode="Markdown", reply_markup=_kb_archive())
        except BadRequest as e:
            if "not modified" in str(e).lower():
                pass  # та сама історія обрана двічі підряд — повідомлення вже актуальне
            else:
                raise
    except Exception as e:
        logger.error("Помилка завантаження архіву: %s", e)
        await query.edit_message_text(
            "📚 Архів справ тимчасово недоступний.\n\nСпробуйте пізніше.",
            reply_markup=kb_home(),
        )


# ─── Оцінка ситуації (ConversationHandler) ───────────────────────────────────

async def cb_assess_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    for key in ("assessment_topic", "assessment_title", "assessment_score",
                "assessment_level", "assessment_factors", "assessment_flags",
                "assessment_answers", "assessment_sent", "assessment_followup",
                "assessment_q_idx"):
        context.user_data.pop(key, None)

    assessments = load_json("assessments.json")
    rows = [
        [InlineKeyboardButton(data["title"], callback_data=f"assess_topic:{key}")]
        for key, data in assessments.items()
    ]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_main")])
    await query.edit_message_text(
        "🎯 *Шанси на успіх*\n\n"
        "Так, я знаю, звучить сміливо.\n\n"
        "Василь Васильович, можливо, сказав би: «Мій електронний друже, не роздавай людям прогнози без аналізу документів».\n\n"
        "І був би правий.\n\n"
        "Тому домовимось так: я не прогнозую рішення суду і не даю юридичний висновок.\n\n"
        "Я просто ставлю кілька питань і показую, наскільки ситуація виглядає підготовленою.\n\n"
        "Якщо коротко — це моя попередня навігація.\n\n"
        "Оберіть напрям, з якого почнемо:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return ASSESS_TOPIC


async def cb_assess_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    topic_key = query.data.split(":", 1)[1]
    assessments = load_json("assessments.json")
    topic = assessments.get(topic_key)
    if not topic:
        await query.answer("Напрям не знайдено", show_alert=True)
        return ASSESS_TOPIC

    context.user_data["assessment_topic"]   = topic_key
    context.user_data["assessment_title"]   = topic["title"]
    context.user_data["assessment_score"]   = 50
    context.user_data["assessment_factors"] = []
    context.user_data["assessment_answers"] = []
    context.user_data["assessment_q_idx"]   = 0

    await _show_assess_question(query, context, topic)
    return ASSESS_Q


async def _show_assess_question(query, context, topic: dict) -> None:
    q_idx    = context.user_data["assessment_q_idx"]
    question = topic["questions"][q_idx]
    total    = len(topic["questions"])
    text = (
        f"🎯 *{topic['title']}*\n\n"
        f"Питання {q_idx + 1} з {total}\n\n"
        f"{question['text']}"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(question["answers"]["yes"]["label"],     callback_data="assess_ans:yes"),
        InlineKeyboardButton(question["answers"]["no"]["label"],      callback_data="assess_ans:no"),
        InlineKeyboardButton(question["answers"]["unknown"]["label"], callback_data="assess_ans:unknown"),
    ]])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def cb_assess_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query      = update.callback_query
    await query.answer()
    answer_key = query.data.split(":", 1)[1]

    assessments = load_json("assessments.json")
    topic_key   = context.user_data["assessment_topic"]
    topic       = assessments[topic_key]
    q_idx       = context.user_data["assessment_q_idx"]
    question    = topic["questions"][q_idx]
    answer      = question["answers"][answer_key]

    context.user_data["assessment_score"] += answer["score"]
    if "factor" in answer and len(context.user_data["assessment_factors"]) < 3:
        context.user_data["assessment_factors"].append(answer["factor"])
    context.user_data["assessment_answers"].append({
        "question": question["text"],
        "answer_label": answer["label"],
    })
    if "flag" in answer:
        flags = context.user_data.setdefault("assessment_flags", [])
        if answer["flag"] not in flags:
            flags.append(answer["flag"])

    q_idx += 1
    context.user_data["assessment_q_idx"] = q_idx

    if q_idx < len(topic["questions"]):
        await _show_assess_question(query, context, topic)
        return ASSESS_Q

    await _show_assess_result(query, context, topic)
    return ConversationHandler.END


def _build_accident_legal_blocks(context) -> str:
    flags = context.user_data.get("assessment_flags", [])
    blocks = []

    if "injuries_serious" in flags:
        blocks.append(
            "\n\n⚠️ *На що звернув увагу CooLaw*\n\n"
            "Тут ситуація може виходити за межі адміністративного провадження.\n\n"
            "Якщо тілесні ушкодження будуть підтверджені відповідною експертизою, "
            "можливе застосування ст. 286 КК України.\n\n"
            "У подібних ситуаціях уже може йтися не лише про штраф чи водійське посвідчення. "
            "Залежно від обставин законом передбачені, зокрема, обмеження волі на строк до 3 років та інші наслідки.\n\n"
            "Не драматизую, але тут я б не відкладав консультацію."
        )
    elif "injuries_no" in flags:
        blocks.append(
            "\n\n⚠️ *На що звернув увагу CooLaw*\n\n"
            "Схоже, ситуація більше нагадує адміністративне ДТП.\n\n"
            "У таких випадках часто застосовується ст. 124 КУпАП.\n\n"
            "Можливі наслідки:\n"
            "• штраф 850 грн;\n\n"
            "або\n\n"
            "• позбавлення права керування транспортними засобами на строк від 6 місяців до 1 року.\n\n"
            "Звичайно, остаточне рішення залежить від конкретних обставин справи."
        )

    if "left_scene" in flags:
        blocks.append(
            "\n\n⚠️ *На що звернув увагу CooLaw*\n\n"
            "Тут є ще один момент.\n\n"
            "Залишення місця ДТП може утворювати окреме адміністративне правопорушення за ст. 122-4 КУпАП.\n\n"
            "Можливі наслідки:\n"
            "• штраф;\n\n"
            "або\n\n"
            "• громадські роботи від 30 до 40 годин;\n\n"
            "або\n\n"
            "• адміністративний арешт від 10 до 15 діб.\n\n"
            "Послухайте мене уважно: цей фактор я б точно не ігнорував."
        )
        blocks.append(
            "\n\n⚠️ *Ще один момент, на який звернув увагу CooLaw*\n\n"
            "Якщо після ДТП є потерпілі або людина перебувала у небезпечному для життя чи здоров'я стані, "
            "залишення місця пригоди може створювати не лише адміністративні, а й кримінально-правові ризики.\n\n"
            "У подібних ситуаціях може ставитися питання про застосування ст. 135 КК України (залишення в небезпеці).\n\n"
            "За певних обставин законом передбачені, зокрема:\n"
            "• обмеження волі від 2 до 3 років;\n\n"
            "або\n\n"
            "• позбавлення волі на той самий строк.\n\n"
            "Якщо залишення в небезпеці спричинило смерть людини або інші тяжкі наслідки, "
            "може ставитися питання про позбавлення волі від 3 до 8 років.\n\n"
            "Моя задача — підсвітити ризики, а не налякати. Але я б тут не геройствував."
        )

    return "".join(blocks)


async def _show_assess_result(query, context, topic: dict) -> None:
    raw_score = context.user_data["assessment_score"]
    score     = max(0, min(100, raw_score))
    level     = "high" if score >= 70 else ("medium" if score >= 35 else "low")

    context.user_data["assessment_score"] = score
    context.user_data["assessment_level"] = level

    factors     = context.user_data.get("assessment_factors", [])
    if factors:
        factors_block = "*Ключові фактори:*\n" + "\n".join(f"• {f}" for f in factors)
    else:
        factors_block = "*Ключові фактори:*\nЯвних ризиків не зафіксовано."

    legal_blocks = _build_accident_legal_blocks(context) if topic.get("title") == "ДТП" else ""

    text = (
        f"🎯 *Попередня навігація CooLaw*\n\n"
        f"Напрям: {topic['title']}\n"
        f"Орієнтовна готовність: *{score}%*\n\n"
        f"Я подивився на ваші відповіді і бачу таку картину:\n\n"
        f"{factors_block}\n\n"
        f"*Мій висновок:*\n{topic['results'][level]}"
        f"{legal_blocks}\n\n"
        f"_Послухайте мене уважно: це не юридичний висновок і не прогноз суду. "
        f"Це лише моя попередня навігація, щоб ви не йшли навмання._\n\n"
        f"🤖 CooLaw"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Передати адвокату та отримати консультацію", callback_data="assess_transfer")],
        [InlineKeyboardButton("🔄 Пройти ще раз",    callback_data="assess")],
        [InlineKeyboardButton("🏠 Головне меню",      callback_data="back_main")],
    ])
    increment("assessment_completed")
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def cb_assess_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query

    if context.user_data.get("assessment_sent"):
        await query.answer("Я вже передав цю оцінку адвокату.", show_alert=True)
        return

    await query.answer()

    user        = query.from_user
    username    = f"@{user.username}" if user.username else "без username"
    topic_title = context.user_data.get("assessment_title", "не вказано")
    score       = context.user_data.get("assessment_score", "—")
    level       = context.user_data.get("assessment_level", "—")
    factors     = context.user_data.get("assessment_factors", [])
    answers     = context.user_data.get("assessment_answers", [])

    level_ua     = {"high": "висока", "medium": "середня", "low": "низька"}.get(level, level)
    answers_text = "\n\n".join(
        f"{i + 1}. {a['question']}\n   Відповідь: {a['answer_label']}"
        for i, a in enumerate(answers)
    )
    factors_str = "\n".join(f"• {f}" for f in factors) if factors else "не визначено"

    admin_text = (
        f"🎯 *Нова заявка після оцінки CooLaw*\n\n"
        f"Напрям: {topic_title}\n"
        f"Орієнтовна оцінка: {score}%\n"
        f"Рівень: {level_ua}\n\n"
        f"*Відповіді користувача:*\n\n"
        f"{answers_text}\n\n"
        f"*Ключові фактори:*\n{factors_str}\n\n"
        f"Telegram name: {user.full_name}\n"
        f"Username: {username}\n"
        f"Telegram ID: `{user.id}`"
    )
    try:
        await context.bot.send_message(ADMIN_CHAT_ID, admin_text, parse_mode="Markdown")
        logger.info("Оцінка передана адміну — user_id=%s", user.id)
        increment("assessment_sent_to_admin")
    except Exception as e:
        logger.error("Помилка відправки адміну: %s", e)

    context.user_data["assessment_sent"]     = True
    context.user_data["assessment_followup"] = True

    await query.edit_message_text(
        "✅ Передав вашу оцінку адвокату.\n\n"
        "Василь Васильович або хтось із команди ознайомиться з відповідями та зв'яжеться з вами для консультації.\n\n"
        "Базову картину ситуації я вже передав, тому вам не доведеться пояснювати все з нуля.\n\n"
        "🤖 CooLaw",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Додати деталі",  callback_data="request")],
            [InlineKeyboardButton("🔄 Пройти ще раз",  callback_data="assess")],
            [InlineKeyboardButton("🏠 Головне меню",   callback_data="back_main")],
        ]),
    )


async def conv_assess_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    for key in ("assessment_topic", "assessment_title", "assessment_score",
                "assessment_level", "assessment_factors", "assessment_flags",
                "assessment_answers", "assessment_sent", "assessment_followup", "assessment_q_idx"):
        context.user_data.pop(key, None)
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(WELCOME_TEXT, reply_markup=kb_main())
    elif update.message:
        await update.message.reply_text(
            "Зрозумів. Повертаємось на початок.\n\n🤖 CooLaw",
            reply_markup=kb_home(),
        )
    return ConversationHandler.END


# ─── Контакти ────────────────────────────────────────────────────────────────

async def cb_phone_call(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer(PHONE_CALL_TEXT, show_alert=True)


async def cb_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Безкоштовна експрес-оцінка", callback_data="request")],
        [InlineKeyboardButton("🏠 Головне меню", callback_data="back_main")],
    ])

    contact_photo = CONTENT_DIR / "contact" / "vasyl_masiuk_contact.jpg"
    if contact_photo.exists():
        try:
            await query.message.delete()
            with open(contact_photo, "rb") as photo:
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=photo,
                    caption=PHONE_TEXT,
                    reply_markup=keyboard,
                )
            return
        except Exception as e:
            logger.error("Помилка відправки контактного фото: %s", e)

    if query.message.photo:
        await query.message.delete()
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=PHONE_TEXT,
            reply_markup=keyboard,
        )
    else:
        await query.edit_message_text(PHONE_TEXT, reply_markup=keyboard)


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
    service_name = context.user_data.pop("selected_service", None)
    napryam = f"Напрям: {service_name}" if service_name else "Напрям: не вказано"

    followup       = context.user_data.pop("assessment_followup", False)
    assess_title   = context.user_data.pop("assessment_title",    None)
    context.user_data.pop("assessment_topic",   None)
    context.user_data.pop("assessment_score",   None)
    context.user_data.pop("assessment_level",   None)
    context.user_data.pop("assessment_factors", None)
    context.user_data.pop("assessment_answers", None)
    context.user_data.pop("assessment_flags",   None)
    context.user_data.pop("assessment_sent",    None)
    context.user_data.pop("assessment_q_idx",   None)

    if followup:
        header  = f"📝 *Уточнення після оцінки CooLaw*"
        napryam = f"Напрям: {assess_title or 'не вказано'}"
    else:
        header  = f"📝 *Нова заявка на консультацію*"

    admin_text = (
        f"{header}\n\n"
        f"{napryam}\n\n"
        f"Ситуація: {desc}\n\n"
        f"Telegram name: {user.full_name}\n"
        f"Username: {username}\n"
        f"Telegram ID: `{user.id}`\n\n"
        f"Контакт: очікується окремим повідомленням"
    )
    try:
        await context.bot.send_message(ADMIN_CHAT_ID, admin_text, parse_mode="Markdown")
        logger.info("Заявка на консультацію — від user_id=%s", user.id)
    except Exception as e:
        logger.error("Помилка відправки адміну: %s", e)

    increment("consultation_requests")
    context.user_data["consultation_contact_pending"] = True
    context.user_data["consultation_original_text"]   = desc
    context.user_data["consultation_user"]            = {
        "full_name": user.full_name,
        "username":  username,
        "id":        user.id,
    }

    await update.message.reply_text(SUCCESS_REQUEST_TEXT, reply_markup=kb_home())
    return ConversationHandler.END


# ─── Fallback: довільний текст поза сценарієм ────────────────────────────────

async def msg_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get("book_interest_pending"):
        contact_text = update.message.text.strip()
        book_title   = context.user_data.get("book_interest_title", "невідомо")
        saved_user   = context.user_data.get("book_interest_user", {})
        full_name    = saved_user.get("full_name", update.message.from_user.full_name)
        username     = saved_user.get("username", "без username")
        user_id      = saved_user.get("id", update.message.from_user.id)

        admin_text = (
            f"📚 *Контакт по книзі*\n\n"
            f"Книга: *{book_title}*\n"
            f"Контакт користувача:\n{contact_text}\n\n"
            f"Користувач: {full_name} ({username})\n"
            f"Telegram ID: `{user_id}`"
        )
        try:
            await context.bot.send_message(ADMIN_CHAT_ID, admin_text, parse_mode="Markdown")
            logger.info("Контакт по книзі [%s] — від user_id=%s", book_title, user_id)
        except Exception as e:
            logger.error("Помилка відправки контакту адміну: %s", e)

        context.user_data.pop("book_interest_pending", None)
        context.user_data.pop("book_interest_title",   None)
        context.user_data.pop("book_interest_user",    None)

        await update.message.reply_text(BOOK_INTEREST_CONTACT_RECEIVED, reply_markup=kb_main())
        return

    if context.user_data.get("consultation_contact_pending"):
        contact_text  = update.message.text.strip()
        original_desc = context.user_data.get("consultation_original_text", "—")
        saved_user    = context.user_data.get("consultation_user", {})
        full_name     = saved_user.get("full_name", update.message.from_user.full_name)
        username      = saved_user.get("username", "без username")
        user_id       = saved_user.get("id", update.message.from_user.id)

        admin_text = (
            f"☎️ *Контакт до експрес-оцінки*\n\n"
            f"Контакт користувача:\n{contact_text}\n\n"
            f"Попередній опис:\n{original_desc}\n\n"
            f"Користувач: {full_name} ({username})\n"
            f"Telegram ID: `{user_id}`"
        )
        try:
            await context.bot.send_message(ADMIN_CHAT_ID, admin_text, parse_mode="Markdown")
            logger.info("Контакт по консультації — від user_id=%s", user_id)
        except Exception as e:
            logger.error("Помилка відправки контакту адміну: %s", e)

        context.user_data.pop("consultation_contact_pending", None)
        context.user_data.pop("consultation_original_text",   None)
        context.user_data.pop("consultation_user",            None)

        await update.message.reply_text(CONSULTATION_CONTACT_RECEIVED, reply_markup=kb_main())
        return

    text = (
        "Зрозумів.\n\n"
        "Якщо хочете передати ситуацію адвокату — натисніть «📝 Консультація» "
        "і коротко опишіть, що сталося.\n\n"
        "Я занотую і передам Василю Васильовичу.\n\n"
        "🤖 CooLaw"
    )
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Консультація", callback_data="request")],
            [InlineKeyboardButton("🏠 Головне меню", callback_data="back_main")],
        ]),
    )


# ─── Статистика ──────────────────────────────────────────────────────────────

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("Ця команда доступна тільки адміну.")
        return

    from stats import load_stats
    data = load_stats()
    text = (
        f"📊 *Статистика CooLaw*\n\n"
        f"Стартів /start: {data['total_start_count']}\n"
        f"Унікальних користувачів: {len(data['unique_users'])}\n\n"
        f"Заявок на консультацію: {data['consultation_requests']}\n"
        f"Оцінок завершено: {data['assessment_completed']}\n"
        f"Оцінок передано адвокату: {data['assessment_sent_to_admin']}\n"
        f"Інтересів до книг: {data['book_interest']}\n\n"
        f"🤖 CooLaw"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ─── Адмін-панель callbacks ──────────────────────────────────────────────────

def _kb_back_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ До панелі", callback_data="back_admin")],
    ])


async def cb_back_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(ADMIN_PANEL_TEXT, parse_mode="Markdown", reply_markup=kb_admin())


async def cb_admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    from stats import load_stats
    data = load_stats()
    text = (
        f"📊 *Статистика CooLaw*\n\n"
        f"Стартів /start: {data['total_start_count']}\n"
        f"Унікальних користувачів: {len(data['unique_users'])}\n\n"
        f"Заявок на консультацію: {data['consultation_requests']}\n"
        f"Оцінок завершено: {data['assessment_completed']}\n"
        f"Оцінок передано адвокату: {data['assessment_sent_to_admin']}\n"
        f"Інтересів до книг: {data['book_interest']}\n\n"
        f"🤖 CooLaw"
    )
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=_kb_back_admin())


async def cb_admin_publish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📢 *Публікація в канал*\n\n"
        "Щоб опублікувати пост у канал, надішліть команду:\n\n"
        "`/publish текст повідомлення`",
        parse_mode="Markdown",
        reply_markup=_kb_back_admin(),
    )


async def cb_admin_view_client(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(WELCOME_TEXT, reply_markup=kb_main())


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
            "Зрозумів. Повертаємось на початок.\n\n🤖 CooLaw",
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

    assess_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_assess_start, pattern="^assess$")],
        states={
            ASSESS_TOPIC: [
                CallbackQueryHandler(cb_assess_topic, pattern="^assess_topic:"),
            ],
            ASSESS_Q: [
                CallbackQueryHandler(cb_assess_answer, pattern="^assess_ans:"),
            ],
        },
        fallbacks=[
            CommandHandler("start",  conv_assess_cancel),
            CommandHandler("cancel", conv_assess_cancel),
            CallbackQueryHandler(conv_assess_cancel, pattern="^back_main$"),
        ],
        per_message=False,
        allow_reentry=True,
    )

    app.add_handler(request_conv)
    app.add_handler(assess_conv)
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("stats",   cmd_stats))
    app.add_handler(CommandHandler("publish", cmd_publish))
    app.add_handler(CallbackQueryHandler(cb_back_admin,         pattern="^back_admin$"))
    app.add_handler(CallbackQueryHandler(cb_admin_stats,        pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(cb_admin_publish,      pattern="^admin_publish$"))
    app.add_handler(CallbackQueryHandler(cb_admin_view_client,  pattern="^admin_view_client$"))
    app.add_handler(CallbackQueryHandler(cb_back_main,          pattern="^back_main$"))
    app.add_handler(CallbackQueryHandler(cb_services,       pattern="^services$"))
    app.add_handler(CallbackQueryHandler(cb_service_detail, pattern="^service:"))
    app.add_handler(CallbackQueryHandler(cb_cost_info,      pattern="^cost_info$"))
    app.add_handler(CallbackQueryHandler(cb_books,          pattern="^books$"))
    app.add_handler(CallbackQueryHandler(cb_book_detail,    pattern="^book:\\d+$"))
    app.add_handler(CallbackQueryHandler(cb_book_interest,  pattern="^book_interest:\\d+$"))
    app.add_handler(CallbackQueryHandler(cb_assess_transfer, pattern="^assess_transfer$"))
    app.add_handler(CallbackQueryHandler(cb_archive,         pattern="^archive$"))
    app.add_handler(CallbackQueryHandler(cb_tips,            pattern="^tips$"))
    app.add_handler(CallbackQueryHandler(cb_phone,          pattern="^phone$"))
    app.add_handler(CallbackQueryHandler(cb_phone_call,     pattern="^phone_call$"))
    app.add_handler(CallbackQueryHandler(cb_about,          pattern="^about$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_fallback))

    return app
