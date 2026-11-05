"""
bot_core.py — ядро бота Сімейство AI.

Містить усі handlers і callback-и. Стан між запитами в пам'яті не тримає.
Експортує build_application() — використовується і polling (bot.py),
і webhook (api/telegram.py).
"""

import asyncio
import hashlib
import json
import logging
import os
import random
import re
import time
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from stats import format_stats, increment, track_start, track_user
from topics import bot_link, topic_for

from personality import (
    WELCOME_TEXT,
    ABOUT_TEXT,
    REQUEST_TEXT,
    SUCCESS_REQUEST_TEXT,
    CONSULTATION_CONTACT_RECEIVED,
    BOOKS_TEXT,
    SERVICES_TEXT,
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

SITE_URL = "https://ai.semeystvo.com.ua"
UTM = "utm_source=telegram&utm_medium=coolaw"
SHOP_API = "https://practical-law.com/api/books"
BASE_DIR = Path(__file__).parent
CONTENT_DIR = BASE_DIR / "content"

logger = logging.getLogger(__name__)


def load_json(filename: str) -> list:
    with open(CONTENT_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


def site_url(path: str) -> str:
    """Посилання на сайт із міткою, щоб бачити в аналітиці заявки з Telegram."""
    if path.startswith("http"):
        return path
    return f"{SITE_URL}{path}?{UTM}"


# Ціни книг беремо з магазину, щоб не розходились із сайтом; у файлі лежить запасна.
_shop_cache = {"at": 0.0, "prices": {}}


def _shop_fetch() -> dict:
    req = urllib.request.Request(SHOP_API, headers={"User-Agent": "coolaw/1.0"})
    with urllib.request.urlopen(req, timeout=4) as r:
        data = json.load(r)
    items = data.get("books", data) if isinstance(data, dict) else data
    if isinstance(items, dict):
        items = list(items.values())
    return {x["id"]: x["price"] for x in items if x.get("id") and x.get("price")}


async def shop_prices() -> dict:
    if time.time() - _shop_cache["at"] > 3600:
        try:
            _shop_cache["prices"] = await asyncio.to_thread(_shop_fetch)
        except Exception as e:
            logger.warning("Магазин не відповів, беру ціни з файлу: %s", e)
        _shop_cache["at"] = time.time()
    return _shop_cache["prices"]


def book_price(book: dict, prices: dict) -> str:
    live = prices.get(book.get("shop_id"))
    return f"{live} грн" if live else book["price"]


def webhook_secret() -> str:
    """Секрет вебхука виводимо з токена: Telegram надсилає його в заголовку, чужі запити відсікаємо."""
    return hashlib.sha256(TOKEN.encode()).hexdigest()[:48]


# ─── Заявки адміну ───────────────────────────────────────────────────────────
# Бот працює на Vercel, де пам'ять процесу зникає між запитами. Тому заявка йде адміну
# одразу, стан тесту лежить у самій кнопці, а розмітку в цих повідомленнях не вмикаємо:
# «_» в імені чи тексті клієнта ламала Markdown, і заявка губилась.
TELEGRAM_LIMIT = 4000
POMAGAYLO_URL = os.getenv("POMAGAYLO_MCP_URL", "")
NOT_DELIVERED_TEXT = (
    "⚠️ Не вдалося передати повідомлення через технічний збій.\n\n"
    "Будь ласка, зателефонуйте: +380678390916\n\n"
    "🧑‍💼 Виручайло"
)
PHONE_RE = re.compile(r"(?:\+?\d[\s()\-]*){9,}")


def user_lines(user) -> str:
    username = f"@{user.username}" if user.username else "без username"
    return f"Клієнт: {user.full_name} ({username})\nTelegram ID: {user.id}"


def _pomagaylo_post(text: str) -> None:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": "notify_me", "arguments": {"text": text}}}).encode()
    req = urllib.request.Request(POMAGAYLO_URL, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "coolaw/1.0"})
    urllib.request.urlopen(req, timeout=15).read()


async def notify_admin(bot, text: str) -> bool:
    """True лише тоді, коли Telegram прийняв усі частини повідомлення."""
    parts = [text[i:i + TELEGRAM_LIMIT] for i in range(0, len(text), TELEGRAM_LIMIT)] or [""]
    delivered = True
    for part in parts:
        for attempt in range(2):
            try:
                await bot.send_message(ADMIN_CHAT_ID, part)
                break
            except Exception as e:
                logger.error("Заявка не дійшла адміну (спроба %s): %s", attempt + 1, e)
                if attempt == 0:
                    await asyncio.sleep(1)
        else:
            delivered = False
    if POMAGAYLO_URL:
        try:
            await asyncio.to_thread(_pomagaylo_post, f"📥 Виручайло\n\n{text[:3500]}")
        except Exception as e:
            logger.error("Копія в Помагайло не пішла: %s", e)
    return delivered


# ─── Клавіатури ──────────────────────────────────────────────────────────────

def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Описати ситуацію", callback_data="request")],
        [InlineKeyboardButton("🎯 Шанси на успіх", callback_data="assess")],
        [
            InlineKeyboardButton("🏛 Послуги", callback_data="services"),
            InlineKeyboardButton("📚 Книги",   callback_data="books"),
        ],
        [
            InlineKeyboardButton("💡 Корисне",        callback_data="useful"),
            InlineKeyboardButton("👨‍⚖️ Про адвоката", callback_data="about"),
        ],
        [InlineKeyboardButton("📞 Зв'язок", callback_data="phone")],
    ])


def kb_services() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"{g['emoji']} {g['title']}", callback_data=f"sg:{g['id']}")]
        for g in load_json("services.json")
    ]
    rows.append([InlineKeyboardButton("📝 Не знайшли своє? Опишіть ситуацію", callback_data="request")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)


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
            InlineKeyboardButton("🎯 Тест: Шанси на успіх", callback_data="assess"),
        ],
        [
            InlineKeyboardButton("📚 Тест: Книги",           callback_data="books"),
            InlineKeyboardButton("📝 Тест: Описати ситуацію", callback_data="request"),
        ],
    ])


ADMIN_PANEL_TEXT = (
    "👑 *Панель Виручайла*\n\n"
    "Ви в адмінському режимі.\n\n"
    "Тут можна перевірити статистику, опублікувати пост у канал або протестувати клієнтські сценарії.\n\n"
    "Оберіть дію:"
)


# ─── /start ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    if update.effective_user:
        # Перехід із посту каналу: /start s_<послуга> одразу показує потрібну послугу.
        arg = context.args[0] if context.args else ""
        track_start(update.effective_user.id, arg[2:] if arg.startswith("s_") else "")
        view = service_view(arg[2:]) if arg.startswith("s_") else None
        if view:
            context.user_data["selected_service"] = view[2]
            await update.message.reply_text(view[0], reply_markup=view[1])
            return
        if update.effective_user.id == ADMIN_CHAT_ID:
            await update.message.reply_text(ADMIN_PANEL_TEXT, parse_mode="Markdown", reply_markup=kb_admin())
            return
    await update.message.reply_text(WELCOME_TEXT, reply_markup=kb_main())


# ─── Головне меню ────────────────────────────────────────────────────────────

async def cb_back_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
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


async def cb_service_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    group_id = query.data.split(":", 1)[1]
    group = next((g for g in load_json("services.json") if g["id"] == group_id), None)
    if not group:
        await cb_stale(update, context)
        return
    await query.answer()
    rows = [[InlineKeyboardButton(i["title"], callback_data=f"service:{i['id']}")] for i in group["items"]]
    rows.append([InlineKeyboardButton("⬅️ До послуг", callback_data="services")])
    await query.edit_message_text(f"{group['emoji']} {group['title']}\n\nОберіть, що сталося:", reply_markup=InlineKeyboardMarkup(rows))


def service_view(service_id: str):
    """(текст, кнопки, напрям) або None, якщо такої послуги немає."""
    found = next(((g, i) for g in load_json("services.json") for i in g["items"] if i["id"] == service_id), None)
    if not found:
        return None
    group, item = found
    text = f"{group['emoji']} {item['title']}\n\n{item['text']}"
    if item.get("price"):
        text += f"\n\n💰 {item['price'][0].upper()}{item['price'][1:]}"
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Описати ситуацію", callback_data="request")],
        [InlineKeyboardButton("🌐 Детальніше на сайті", url=site_url(item["url"]))],
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"sg:{group['id']}")],
    ])
    return text, markup, f"Напрям: {item['title']}"


async def cb_service_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    view = service_view(query.data.split(":", 1)[1])
    if not view:
        await cb_stale(update, context)
        return
    await query.answer()
    context.user_data["selected_service"] = view[2]
    await query.edit_message_text(view[0], reply_markup=view[1])


# ─── Книги ───────────────────────────────────────────────────────────────────

async def cb_books(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    books = load_json("books.json")
    prices = await shop_prices()
    rows = [
        [InlineKeyboardButton(f"📘 {b['short_title']} · {book_price(b, prices)}", callback_data=f"book:{b['id']}")]
        for b in books
    ]
    rows.append([
        InlineKeyboardButton("📄 Гайди · 99 грн", url=site_url("/gaydy")),
        InlineKeyboardButton("📄 Методички · 199 грн", url=site_url("/metodychky")),
    ])
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
        f"💰 *Ціна:* {book_price(book, await shop_prices())}"
    )
    action_button = InlineKeyboardButton(
        "📥 Отримати безкоштовно" if book.get("free") else "🛒 Купити", url=site_url(book["url"]))
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


# ─── Корисне ─────────────────────────────────────────────────────────────────

async def cb_useful(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("💡 Корисне\n\nКороткі поради й історії зі справ.", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🧠 Порада дня",  callback_data="tips")],
        [InlineKeyboardButton("📚 Архів справ", callback_data="archive")],
        [InlineKeyboardButton("⬅️ Назад",       callback_data="back_main")],
    ]))


# ─── Порада дня ──────────────────────────────────────────────────────────────

def _kb_tips() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Ще одна порада", callback_data="tips")],
        [InlineKeyboardButton("📝 Описати ситуацію", callback_data="request")],
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
            f"🧠 *Порада від Виручайла*\n\n"
            f"{tip['text']}\n\n"
            f"🧑‍💼 Якщо ваша ситуація складніша за одну пораду — натисніть «Описати ситуацію»."
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
            "🧠 Поради тимчасово недоступні.\n\nСпробуйте пізніше або натисніть «📝 Описати ситуацію».",
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


# ─── Оцінка ситуації ─────────────────────────────────────────────────────────
# Відповіді лежать у кнопці: at:<напрям>, an:<напрям>:<ynu…>, atr:<напрям>:<ynu…>.
ANSWER_KEYS = {"y": "yes", "n": "no", "u": "unknown"}


def _assess_parse(data: str):
    """(ключ напряму, напрям, відповіді) або None для застарілої чи чужої кнопки."""
    parts = data.split(":")
    key = parts[1] if len(parts) > 1 else ""
    answers = parts[2] if len(parts) > 2 else ""
    topic = load_json("assessments.json").get(key)
    if not topic or not re.fullmatch(r"[ynu]*", answers) or len(answers) > len(topic["questions"]):
        return None
    return key, topic, answers


def _assess_calc(topic: dict, answers: str) -> dict:
    score, factors, flags, items = 50, [], [], []
    for question, code in zip(topic["questions"], answers):
        answer = question["answers"][ANSWER_KEYS[code]]
        score += answer["score"]
        if "factor" in answer and len(factors) < 3:
            factors.append(answer["factor"])
        if "flag" in answer and answer["flag"] not in flags:
            flags.append(answer["flag"])
        items.append((question["text"], answer["label"]))
    score = max(0, min(100, score))
    level = "high" if score >= 70 else ("medium" if score >= 35 else "low")
    return {"score": score, "level": level, "factors": factors, "flags": flags, "items": items}


async def _assess_stale(query) -> None:
    await query.answer("Цей тест застарів. Почнімо спочатку.", show_alert=True)
    await query.edit_message_text(WELCOME_TEXT, reply_markup=kb_main())


async def cb_assess_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    assessments = load_json("assessments.json")
    rows = [
        [InlineKeyboardButton(data["title"], callback_data=f"at:{key}")]
        for key, data in assessments.items()
    ]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_main")])
    await query.edit_message_text(
        "🎯 *Шанси на успіх*\n\n"
        "Так, я знаю, звучить сміливо. Тому домовимось одразу: я не прогнозую рішення суду і не даю юридичний висновок.\n\n"
        "Я ставлю кілька питань і показую, наскільки ситуація підготовлена і на що звернути увагу.\n\n"
        "Оберіть напрям, з якого почнемо:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def _show_assess_question(query, key: str, topic: dict, answers: str) -> None:
    q_idx    = len(answers)
    question = topic["questions"][q_idx]
    total    = len(topic["questions"])
    text = (
        f"🎯 *{topic['title']}*\n\n"
        f"Питання {q_idx + 1} з {total}\n\n"
        f"{question['text']}"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(question["answers"][full]["label"], callback_data=f"an:{key}:{answers}{code}")
        for code, full in ANSWER_KEYS.items()
    ]])
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def cb_assess_step(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Вибір напряму або відповідь на питання: усе потрібне приходить у самій кнопці."""
    query = update.callback_query
    parsed = _assess_parse(query.data)
    if not parsed:
        await _assess_stale(query)
        return
    key, topic, answers = parsed
    await query.answer()
    if len(answers) < len(topic["questions"]):
        await _show_assess_question(query, key, topic, answers)
    else:
        await _show_assess_result(query, key, topic, answers)


def _build_accident_legal_blocks(flags: list) -> str:
    blocks = []

    if "injuries_serious" in flags:
        blocks.append(
            "\n\n⚠️ *На що звернув увагу Виручайло*\n\n"
            "Тут ситуація може виходити за межі адміністративного провадження.\n\n"
            "Якщо тілесні ушкодження будуть підтверджені відповідною експертизою, "
            "можливе застосування ст. 286 КК України.\n\n"
            "У подібних ситуаціях уже може йтися не лише про штраф чи водійське посвідчення. "
            "За середньої тяжкості ушкоджень закон передбачає, зокрема, обмеження волі до 3 років, а за тяжких ушкоджень чи смерті потерпілого позбавлення волі від 3 до 8 років.\n\n"
            "Не драматизую, але тут я б не відкладав консультацію."
        )
    elif "injuries_no" in flags:
        blocks.append(
            "\n\n⚠️ *На що звернув увагу Виручайло*\n\n"
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
            "\n\n⚠️ *На що звернув увагу Виручайло*\n\n"
            "Тут є ще один момент.\n\n"
            "Залишення місця ДТП може утворювати окреме адміністративне правопорушення за ст. 122-4 КУпАП.\n\n"
            "Можливі наслідки:\n"
            "• штраф 3 400 грн;\n\n"
            "або\n\n"
            "• позбавлення права керування на строк від 1 до 2 років;\n\n"
            "або\n\n"
            "• адміністративний арешт від 10 до 15 діб.\n\n"
            "Послухайте мене уважно: цей фактор я б точно не ігнорував."
        )
        blocks.append(
            "\n\n⚠️ *Ще один момент, на який звернув увагу Виручайло*\n\n"
            "Якщо після ДТП є потерпілі або людина перебувала у небезпечному для життя чи здоров'я стані, "
            "залишення місця пригоди може створювати не лише адміністративні, а й кримінально-правові ризики.\n\n"
            "У подібних ситуаціях може ставитися питання про застосування ст. 135 КК України (залишення в небезпеці).\n\n"
            "За певних обставин законом передбачені, зокрема:\n"
            "• обмеження волі до 2 років;\n\n"
            "або\n\n"
            "• позбавлення волі на той самий строк.\n\n"
            "Якщо залишення в небезпеці спричинило смерть людини або інші тяжкі наслідки, "
            "може ставитися питання про позбавлення волі від 3 до 8 років.\n\n"
            "Моя задача — підсвітити ризики, а не налякати. Але я б тут не геройствував."
        )

    return "".join(blocks)


async def _show_assess_result(query, key: str, topic: dict, answers: str) -> None:
    calc = _assess_calc(topic, answers)
    if calc["factors"]:
        factors_block = "*Ключові фактори:*\n" + "\n".join(f"• {f}" for f in calc["factors"])
    else:
        factors_block = "*Ключові фактори:*\nЯвних ризиків не зафіксовано."

    legal_blocks = _build_accident_legal_blocks(calc["flags"]) if topic.get("title") == "ДТП" else ""

    text = (
        f"🎯 *Попередня навігація Виручайла*\n\n"
        f"Напрям: {topic['title']}\n"
        f"Наскільки ситуація підготовлена: *{calc['score']}%*\n\n"
        f"Я подивився на ваші відповіді і бачу таку картину:\n\n"
        f"{factors_block}\n\n"
        f"*Мій висновок:*\n{topic['results'][calc['level']]}"
        f"{legal_blocks}\n\n"
        f"_Послухайте мене уважно: це не юридичний висновок і не прогноз суду. "
        f"Це лише моя попередня навігація, щоб ви не йшли навмання._\n\n"
        f"🧑‍💼 Виручайло"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Передати адвокату та отримати консультацію", callback_data=f"atr:{key}:{answers}")],
        [InlineKeyboardButton("🔄 Пройти ще раз",    callback_data="assess")],
        [InlineKeyboardButton("🏠 Головне меню",      callback_data="back_main")],
    ])
    increment("assessment_completed")
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def cb_assess_transfer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    parsed = _assess_parse(query.data)
    if not parsed or len(parsed[2]) != len(parsed[1]["questions"]):
        await _assess_stale(query)
        return
    key, topic, answers = parsed
    await query.answer()
    calc = _assess_calc(topic, answers)
    level_ua = {"high": "висока", "medium": "середня", "low": "низька"}[calc["level"]]
    answers_text = "\n\n".join(
        f"{i + 1}. {question}\n   Відповідь: {label}" for i, (question, label) in enumerate(calc["items"])
    )
    factors_str = "\n".join(f"• {f}" for f in calc["factors"]) if calc["factors"] else "не визначено"
    delivered = await notify_admin(context.bot, (
        f"🎯 Нова заявка після оцінки Виручайла\n\n"
        f"Напрям: {topic['title']}\n"
        f"Орієнтовна оцінка: {calc['score']}%\n"
        f"Рівень: {level_ua}\n\n"
        f"Відповіді:\n\n{answers_text}\n\n"
        f"Ключові фактори:\n{factors_str}\n\n"
        f"{user_lines(query.from_user)}"
    ))
    if not delivered:
        await query.edit_message_text(NOT_DELIVERED_TEXT, reply_markup=kb_home())
        return
    increment("assessment_sent_to_admin")
    context.user_data["selected_service"] = f"Напрям: {topic['title']}"
    await query.edit_message_text(
        "✅ Передав вашу оцінку адвокату.\n\n"
        "Василь Васильович або хтось із команди ознайомиться з відповідями та зв'яжеться з вами.\n\n"
        "Якщо хочете, щоб зв'язались швидше — напишіть одним повідомленням номер телефону або інший контакт.\n\n"
        "🧑‍💼 Виручайло",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Додати деталі",  callback_data="request")],
            [InlineKeyboardButton("🔄 Пройти ще раз",  callback_data="assess")],
            [InlineKeyboardButton("🏠 Головне меню",   callback_data="back_main")],
        ]),
    )


# ─── Контакти ────────────────────────────────────────────────────────────────

async def cb_phone_call(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer(PHONE_CALL_TEXT, show_alert=True)


async def cb_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Описати ситуацію", callback_data="request")],
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


# ─── Консультація ────────────────────────────────────────────────────────────

async def cb_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if query.message.photo:
        await query.message.delete()
        await context.bot.send_message(query.message.chat_id, REQUEST_TEXT, reply_markup=kb_home())
    else:
        await query.edit_message_text(REQUEST_TEXT, reply_markup=kb_home())


async def msg_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Будь-який текст клієнта і є зверненням: опис ситуації, телефон чи уточнення."""
    message = update.message
    user = message.from_user
    if user.id == ADMIN_CHAT_ID:
        await message.reply_text(ADMIN_PANEL_TEXT, parse_mode="Markdown", reply_markup=kb_admin())
        return
    track_user(user.id)
    text = message.text.strip()
    has_phone = bool(PHONE_RE.search(text))
    topic = context.user_data.pop("selected_service", None)
    header = "☎️ Контакт клієнта" if has_phone and len(text) < 60 else "📝 Звернення клієнта"
    delivered = await notify_admin(context.bot, "\n\n".join(filter(None, [
        header, topic, text, user_lines(user),
    ])))
    if not delivered:
        await message.reply_text(NOT_DELIVERED_TEXT, reply_markup=kb_home())
        return
    increment("consultation_requests")
    if has_phone:
        await message.reply_text(CONSULTATION_CONTACT_RECEIVED, reply_markup=kb_main())
    elif context.user_data.get("contact_asked"):
        await message.reply_text("✅ Передав адвокату.\n\n🧑‍💼 Виручайло", reply_markup=kb_home())
    else:
        context.user_data["contact_asked"] = True
        await message.reply_text(SUCCESS_REQUEST_TEXT, reply_markup=kb_home())


async def msg_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Голосові, фото, документи й контакт: пересилаємо адміну як є."""
    message = update.message
    user = message.from_user
    if user.id == ADMIN_CHAT_ID:
        return
    delivered = await notify_admin(context.bot, f"📎 Файл або голосове від клієнта\n\n{user_lines(user)}")
    if delivered:
        try:
            await message.forward(ADMIN_CHAT_ID)
        except Exception as e:
            logger.error("Не вдалося переслати файл адміну: %s", e)
            delivered = False
    if not delivered:
        await message.reply_text(NOT_DELIVERED_TEXT, reply_markup=kb_home())
        return
    increment("consultation_requests")
    await message.reply_text(
        "✅ Передав адвокату.\n\nЯкщо ще не залишали контакт, напишіть, будь ласка, номер телефону.\n\n🧑‍💼 Виручайло",
        reply_markup=kb_home(),
    )


CHANNEL_USERNAME = "aadvokatt"


async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Під кожен новий пост каналу додаємо кнопку до бота, зокрема під пости, написані вручну."""
    post = update.channel_post
    if not post or (post.chat.username or "").lower() != CHANNEL_USERNAME or post.reply_markup:
        return
    text = post.text or post.caption or ""
    if not text:
        return  # фото без підпису, опитування й службові повідомлення не чіпаємо
    try:
        await post.edit_reply_markup(reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Написати адвокату", url=bot_link(topic_for(text)))],
        ]))
    except Exception as e:
        logger.error("Не вдалося додати кнопку під пост %s: %s", post.message_id, e)


async def cb_stale(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Кнопки зі старих повідомлень, яких уже немає в боті."""
    query = update.callback_query
    await query.answer("Меню оновилось.")
    await query.edit_message_text(WELCOME_TEXT, reply_markup=kb_main())


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    await update.message.reply_text(WELCOME_TEXT, reply_markup=kb_main())


# ─── Статистика ──────────────────────────────────────────────────────────────

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("Ця команда доступна тільки адміну.")
        return

    text = await asyncio.to_thread(format_stats)
    await update.message.reply_text(text)


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
    text = await asyncio.to_thread(format_stats)
    await query.edit_message_text(text, reply_markup=_kb_back_admin())


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


# ─── Збірка Application ──────────────────────────────────────────────────────

def build_application() -> Application:
    """
    Створює Application і реєструє всі handlers.
    Не викликає initialize() / start() — це робить виклик ззовні.
    """
    app = Application.builder().token(TOKEN).build()

    private = filters.ChatType.PRIVATE & filters.UpdateType.MESSAGE
    app.add_handler(CommandHandler("cancel",  cmd_cancel))
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("stats",   cmd_stats))
    app.add_handler(CommandHandler("publish", cmd_publish))
    app.add_handler(CallbackQueryHandler(cb_back_admin,         pattern="^back_admin$"))
    app.add_handler(CallbackQueryHandler(cb_admin_stats,        pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(cb_admin_publish,      pattern="^admin_publish$"))
    app.add_handler(CallbackQueryHandler(cb_admin_view_client,  pattern="^admin_view_client$"))
    app.add_handler(CallbackQueryHandler(cb_back_main,          pattern="^back_main$"))
    app.add_handler(CallbackQueryHandler(cb_services,       pattern="^services$"))
    app.add_handler(CallbackQueryHandler(cb_service_group,  pattern="^sg:"))
    app.add_handler(CallbackQueryHandler(cb_service_detail, pattern="^service:"))
    app.add_handler(CallbackQueryHandler(cb_useful,         pattern="^useful$"))
    app.add_handler(CallbackQueryHandler(cb_books,          pattern="^books$"))
    app.add_handler(CallbackQueryHandler(cb_book_detail,    pattern="^book:\\d+$"))
    app.add_handler(CallbackQueryHandler(cb_request,         pattern="^request$"))
    app.add_handler(CallbackQueryHandler(cb_assess_start,    pattern="^assess$"))
    app.add_handler(CallbackQueryHandler(cb_assess_step,     pattern="^(at|an):"))
    app.add_handler(CallbackQueryHandler(cb_assess_transfer, pattern="^atr:"))
    app.add_handler(CallbackQueryHandler(cb_archive,         pattern="^archive$"))
    app.add_handler(CallbackQueryHandler(cb_tips,            pattern="^tips$"))
    app.add_handler(CallbackQueryHandler(cb_phone,          pattern="^phone$"))
    app.add_handler(CallbackQueryHandler(cb_phone_call,     pattern="^phone_call$"))
    app.add_handler(CallbackQueryHandler(cb_about,          pattern="^about$"))
    app.add_handler(CallbackQueryHandler(cb_stale))
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, on_channel_post))
    app.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, msg_text))
    app.add_handler(MessageHandler(
        private & (filters.VOICE | filters.AUDIO | filters.VIDEO | filters.VIDEO_NOTE | filters.PHOTO | filters.Document.ALL | filters.CONTACT),
        msg_media,
    ))

    return app
