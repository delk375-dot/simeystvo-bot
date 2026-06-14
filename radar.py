"""
LexMind Radar 0.3 — тихий радар робочих можливостей.
Моніторить повідомлення в групі і шле адміну приватні сповіщення.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# ─── Налаштування ─────────────────────────────────────────────────────────────

ADMIN_USER_ID = 219205800
RADAR_ENABLED_DEFAULT = True
KYIV_TZ = ZoneInfo("Europe/Kyiv")

DATA_DIR = Path(__file__).parent / "data"
LEADS_FILE = DATA_DIR / "leads.json"
RADAR_STATE_FILE = DATA_DIR / "radar_state.json"

# ─── Ключові слова ────────────────────────────────────────────────────────────

LEAD_KEYWORDS = [
    "хто може",
    "хто візьме",
    "хто готовий",
    "потрібен адвокат",
    "потрібна адвокат",
    "потрібен юрист",
    "потрібна юристка",
    "потрібен представник",
    "потрібна представниця",
    "може хтось",
    "піти в суд",
    "сходити в суд",
    "замінити в суді",
    "підстрахувати",
    "представити інтереси",
    "є справа",
    "є клієнт",
    "клієнт шукає",
    "шукаю адвоката",
    "шукаю юриста",
    "шукаю колегу",
    "шукаємо колегу",
    "по справі",
    "судове засідання",
    "засідання завтра",
    "терміново треба",
    "терміново потрібен",
    "може хто",
    "хто займається",
    "порадьте адвоката",
    "порадьте юриста",
]

# ─── Стан радара ─────────────────────────────────────────────────────────────

def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def is_radar_enabled() -> bool:
    _ensure_data_dir()
    if not RADAR_STATE_FILE.exists():
        return RADAR_ENABLED_DEFAULT
    try:
        with open(RADAR_STATE_FILE, encoding="utf-8") as f:
            return json.load(f).get("enabled", RADAR_ENABLED_DEFAULT)
    except Exception:
        return RADAR_ENABLED_DEFAULT


def set_radar_enabled(value: bool) -> None:
    _ensure_data_dir()
    with open(RADAR_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"enabled": value}, f, ensure_ascii=False)
    logger.info("Radar %s", "увімкнено" if value else "вимкнено")


# ─── Детектор заявок ─────────────────────────────────────────────────────────

def detect_lead(text: str) -> dict | None:
    """
    Шукає ключові слова в тексті (без регістру).
    Повертає dict з результатом або None.
    """
    lower = text.lower()
    matched = [kw for kw in LEAD_KEYWORDS if kw in lower]
    if not matched:
        return None
    return {
        "matched_keywords": matched,
        "confidence": "high" if len(matched) >= 2 else "medium",
        "lead_type": "delegation_or_referral",
    }


# ─── Збереження і завантаження leads ─────────────────────────────────────────

def load_leads() -> list:
    _ensure_data_dir()
    if not LEADS_FILE.exists():
        return []
    try:
        with open(LEADS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _write_leads(leads: list) -> None:
    _ensure_data_dir()
    with open(LEADS_FILE, "w", encoding="utf-8") as f:
        json.dump(leads, f, ensure_ascii=False, indent=2)


def already_saved(chat_id: int, message_id: int) -> bool:
    return any(
        lead.get("chat_id") == chat_id and lead.get("message_id") == message_id
        for lead in load_leads()
    )


def save_lead(lead: dict) -> None:
    leads = load_leads()
    leads.append(lead)
    _write_leads(leads)
    logger.info("Lead збережено: chat_id=%s message_id=%s", lead.get("chat_id"), lead.get("message_id"))


def get_today_leads() -> list:
    today = datetime.now(tz=KYIV_TZ).date()
    result = []
    for lead in load_leads():
        try:
            created = datetime.fromisoformat(lead["created_at"]).astimezone(KYIV_TZ).date()
            if created == today:
                result.append(lead)
        except Exception:
            pass
    return result


# ─── Формування повідомлення адміну ──────────────────────────────────────────

def build_admin_message(lead: dict) -> str:
    confidence_label = "🔴 висока" if lead["confidence"] == "high" else "🟡 середня"
    keywords_str = ", ".join(lead["matched_keywords"])
    username = lead.get("from_username")
    author = lead["from_name"]
    if username:
        author += f" @{username}"

    # Посилання для supergroup: chat_id вигляду -100XXXXXXXXXX → internal = chat_id + 100_000_000_000
    link_line = ""
    chat_id = lead.get("chat_id", 0)
    msg_id = lead.get("message_id", 0)
    thread_id = lead.get("message_thread_id")
    if str(chat_id).startswith("-100"):
        internal_id = str(chat_id)[4:]  # прибираємо -100
        base = f"https://t.me/c/{internal_id}/{msg_id}"
        link_line = f"\nПосилання: {base}"

    thread_display = str(thread_id) if thread_id else "—"

    return (
        f"🔔 LexMind Radar\n\n"
        f"Я знайшов можливу робочу заявку.\n\n"
        f"Тип: делегування / пошук колеги\n"
        f"Ймовірність: {confidence_label}\n"
        f"Збіги: {keywords_str}\n\n"
        f"Автор: {author}\n"
        f"Група: {lead.get('chat_title', '—')}\n"
        f"Тема ID: {thread_display}\n"
        f"Message ID: {msg_id}"
        f"{link_line}\n\n"
        f"Текст:\n{lead['text']}\n\n"
        f"Що можна зробити:\n"
        f"— швидко відповісти в чаті;\n"
        f"— забрати в роботу;\n"
        f"— передати колезі з мережі."
    )
