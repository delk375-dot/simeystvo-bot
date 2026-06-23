"""
stats.py — проста in-file статистика бота.

На Vercel serverless файл може скидатись при деплої,
тому запис у файл — best-effort: не ламає бота при помилці.
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# На Vercel файлова система read-only, крім /tmp
_DEFAULT_STATS = Path(__file__).parent / "content" / "stats.json"
STATS_FILE = Path("/tmp/stats.json") if os.getenv("VERCEL") else _DEFAULT_STATS

_DEFAULTS: dict = {
    "total_start_count": 0,
    "unique_users": [],
    "consultation_requests": 0,
    "assessment_completed": 0,
    "assessment_sent_to_admin": 0,
    "book_interest": 0,
}


def load_stats() -> dict:
    # Спочатку намагаємось прочитати робочий файл (STATS_FILE)
    for path in [STATS_FILE, _DEFAULT_STATS]:
        try:
            if path.exists():
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                for k, v in _DEFAULTS.items():
                    data.setdefault(k, v)
                return data
        except Exception as e:
            logger.error("Не вдалося завантажити %s: %s", path, e)
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
