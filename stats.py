"""
stats.py — проста in-file статистика бота.

На Vercel serverless файл може скидатись при деплої,
тому запис у файл — best-effort: не ламає бота при помилці.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

STATS_FILE = Path(__file__).parent / "content" / "stats.json"

_DEFAULTS: dict = {
    "total_start_count": 0,
    "unique_users": [],
    "consultation_requests": 0,
    "assessment_completed": 0,
    "assessment_sent_to_admin": 0,
    "book_interest": 0,
}


def load_stats() -> dict:
    try:
        if STATS_FILE.exists():
            with open(STATS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            # Merge with defaults so missing keys always exist
            for k, v in _DEFAULTS.items():
                data.setdefault(k, v)
            return data
    except Exception as e:
        logger.error("Не вдалося завантажити stats.json: %s", e)
    return dict(_DEFAULTS)


def save_stats(data: dict) -> None:
    try:
        STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("Не вдалося зберегти stats.json: %s", e)


def track_start(user_id: int) -> None:
    data = load_stats()
    data["total_start_count"] += 1
    if user_id not in data["unique_users"]:
        data["unique_users"].append(user_id)
    save_stats(data)


def increment(key: str) -> None:
    data = load_stats()
    if key in data and isinstance(data[key], int):
        data[key] += 1
        save_stats(data)
    else:
        logger.warning("stats.increment: невідомий ключ '%s'", key)
