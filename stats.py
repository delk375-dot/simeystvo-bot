"""
stats.py — лічильник користувачів і заявок бота.

Головне сховище — Upstash Redis (підключене у Vercel як Storage). Ключі мають префікс
coolaw:, щоб не змішуватись із даними сайту в тому самому сховищі. Без Redis лічильник
пише у файл, але на Vercel цей файл обнуляється, тому такі цифри лише орієнтовні.
"""

import datetime as dt
import json
import logging
import os
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

P = "coolaw:"
DAY_TTL = 400 * 24 * 3600
_DEFAULT_STATS = Path(__file__).parent / "content" / "stats.json"
STATS_FILE = Path("/tmp/stats.json") if os.getenv("VERCEL") else _DEFAULT_STATS
_DEFAULTS: dict = {
    "total_start_count": 0,
    "unique_users": [],
    "consultation_requests": 0,
    "assessment_completed": 0,
    "assessment_sent_to_admin": 0,
}
COUNTERS = ["consultation_requests", "assessment_completed", "assessment_sent_to_admin"]


def _creds():
    """Назви змінних залежать від префікса, обраного при підключенні сховища у Vercel."""
    for url_key, token_key in (
        ("UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"),
        ("KV_REST_API_URL", "KV_REST_API_TOKEN"),
        ("UPSTASH_REDIS_KV_REST_API_URL", "UPSTASH_REDIS_KV_REST_API_TOKEN"),
        ("STORAGE_KV_REST_API_URL", "STORAGE_KV_REST_API_TOKEN"),
    ):
        if os.getenv(url_key) and os.getenv(token_key):
            return os.getenv(url_key).rstrip("/"), os.getenv(token_key)
    return None


def _redis(commands: list) -> list | None:
    creds = _creds()
    if not creds:
        return None
    url, token = creds
    try:
        req = urllib.request.Request(f"{url}/pipeline", data=json.dumps(commands).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as r:
            return [x.get("result") for x in json.load(r)]
    except Exception as e:
        logger.error("Redis недоступний: %s", e)
        return None


def _today() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=2))).date().isoformat()


def track_user(user_id: int, start: bool = False, source: str = "") -> None:
    """Людина, яка відкрила бота або написала йому."""
    day = f"{P}day:{_today()}"
    cmds = [["SADD", f"{P}users", str(user_id)], ["SADD", day, str(user_id)], ["EXPIRE", day, str(DAY_TTL)]]
    if start:
        cmds.append(["INCR", f"{P}c:starts"])
    if source:
        cmds.append(["HINCRBY", f"{P}sources", source, "1"])
    if _redis(cmds) is not None:
        return
    data = load_stats()
    data["total_start_count"] += 1 if start else 0
    if user_id not in data["unique_users"]:
        data["unique_users"].append(user_id)
    save_stats(data)


def track_start(user_id: int, source: str = "") -> None:
    track_user(user_id, start=True, source=source)


def increment(key: str) -> None:
    if _redis([["INCR", f"{P}c:{key}"]]) is not None:
        return
    data = load_stats()
    if isinstance(data.get(key), int):
        data[key] += 1
        save_stats(data)


def load_stats() -> dict:
    for path in [STATS_FILE, _DEFAULT_STATS]:
        try:
            if path.exists():
                data = json.load(open(path, encoding="utf-8"))
                for k, v in _DEFAULTS.items():
                    data.setdefault(k, v)
                return data
        except Exception as e:
            logger.error("Не вдалося завантажити %s: %s", path, e)
    return dict(_DEFAULTS)


def save_stats(data: dict) -> None:
    try:
        STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        json.dump(data, open(STATS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("Не вдалося зберегти stats.json: %s", e)


def format_stats() -> str:
    """Текст для адміна. Без розмітки: цифри й назви тем не ламають повідомлення."""
    today = dt.date.fromisoformat(_today())
    days7 = [f"{P}day:{(today - dt.timedelta(days=i)).isoformat()}" for i in range(7)]
    days30 = [f"{P}day:{(today - dt.timedelta(days=i)).isoformat()}" for i in range(30)]
    res = _redis([["SCARD", f"{P}users"], ["SCARD", days7[0]], ["SUNION", *days7], ["SUNION", *days30],
                  ["GET", f"{P}c:starts"], *[["GET", f"{P}c:{k}"] for k in COUNTERS], ["HGETALL", f"{P}sources"]])
    if res is None:
        d = load_stats()
        return ("📊 Статистика Виручайла (тимчасова: сховище не підключене, цифри обнуляються)\n\n"
                f"Користувачів: {len(d['unique_users'])}\nЗаявок: {d['consultation_requests']}\n"
                f"Оцінок передано адвокату: {d['assessment_sent_to_admin']}")
    total, today_n, w7, w30, starts, req, done, sent, src = res
    num = lambda x: int(x or 0)
    sources = dict(zip(src[0::2], src[1::2])) if src else {}
    lines = [
        "📊 Статистика Виручайла",
        "",
        f"Людей усього: {num(total)}",
        f"Сьогодні: {num(today_n)}",
        f"За 7 днів: {len(w7 or [])}",
        f"За 30 днів: {len(w30 or [])}",
        "",
        f"Відкривали бота (/start): {num(starts)}",
        f"Заявок і повідомлень адвокату: {num(req)}",
        f"Тестів «Шанси на успіх» пройдено: {num(done)}, передано адвокату: {num(sent)}",
    ]
    if sources:
        lines += ["", "Прийшли з постів каналу за темою:"]
        lines += [f"• {k}: {v}" for k, v in sorted(sources.items(), key=lambda kv: -int(kv[1]))]
    lines += ["", "Лічильник веде облік від дня підключення сховища."]
    return "\n".join(lines)
