# -*- coding: utf-8 -*-
"""Рубрики каналу за розкладом (content/channel_schedule.json), затвердженим Василем.

Запускає GitHub Actions (.github/workflows/channel-schedule.yml) щовечора. Публікує всі пункти,
час яких уже настав (за Києвом) і які ще не виходили; пропущене більше ніж на 12 годин не
публікує, щоб старий пост не вискочив несподівано. Опубліковане — у content/channel_schedule_done.json.

  python -X utf8 channel_schedule.py --dry     показати, що вийшло б зараз
  python -X utf8 channel_schedule.py --dry --at "2026-11-15 19:05"   те саме на інший момент
  python -X utf8 channel_schedule.py           опублікувати
"""
import html
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from channel_daily import CHANNEL, КИЇВ, UTM, читати_rss
from topics import bot_link

ТУТ = os.path.dirname(os.path.abspath(__file__))
РОЗКЛАД = os.path.join(ТУТ, "content", "channel_schedule.json")
ЗРОБЛЕНО = os.path.join(ТУТ, "content", "channel_schedule_done.json")
БЛОГ = "https://ai.semeystvo.com.ua/blog/"
ЗАПАС = timedelta(hours=12)


def посилання(ціль: str) -> str:
    if ціль.startswith("bot:"):
        return bot_link(ціль[4:])
    if ціль.startswith("blog:"):
        return f"{БЛОГ}{ціль[5:]}?{UTM}"
    return ціль


def кнопки(пункт: dict) -> dict | None:
    ряди = [[{"text": t, "url": посилання(u)}] for t, u in пункт.get("buttons", [])]
    return {"inline_keyboard": ряди} if ряди else None


def добірка(пункт: dict, зараз: datetime) -> str:
    тиждень = [с for с in читати_rss() if зараз - timedelta(days=7) <= с["date"].astimezone(КИЇВ) < зараз - timedelta(hours=10)]
    рядки = [f'• <a href="{html.escape(с["link"])}?{UTM}">{html.escape(с["title"])}</a>' for с in тиждень[-5:]]
    частини = [html.escape(пункт["intro"])]
    if рядки:
        частини.append("Статті тижня:\n" + "\n".join(рядки))
    частини.append(html.escape(пункт["outro"]))
    return "\n\n".join(частини)


def запит(пункт: dict, зараз: datetime) -> tuple[str, dict]:
    вид = пункт["kind"]
    if вид in ("quiz", "poll"):
        дані = {"chat_id": CHANNEL, "question": пункт["question"], "is_anonymous": True,
                "options": [{"text": o} for o in пункт["options"]]}
        if вид == "quiz":
            дані.update(type="quiz", correct_option_id=пункт["correct"], explanation=пункт["explanation"])
        метод = "sendPoll"
    elif вид == "text":
        дані = {"chat_id": CHANNEL, "text": пункт["text"], "link_preview_options": {"is_disabled": True}}
        метод = "sendMessage"
    elif вид == "digest":
        дані = {"chat_id": CHANNEL, "text": добірка(пункт, зараз), "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True}}
        метод = "sendMessage"
    else:
        raise SystemExit(f"Невідомий вид пункту: {вид}")
    if кнопки(пункт):
        дані["reply_markup"] = кнопки(пункт)
    return метод, дані


def надіслати(метод: str, дані: dict) -> None:
    токен = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    req = urllib.request.Request(f"https://api.telegram.org/bot{токен}/{метод}", data=json.dumps(дані).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        відповідь = json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Telegram відмовив: {e.code} {e.read().decode()[:200]}")
    if not відповідь.get("ok"):
        raise SystemExit(f"Telegram відмовив: {відповідь}")


def main() -> None:
    зараз = datetime.now(КИЇВ)
    if "--at" in sys.argv:
        зараз = datetime.strptime(sys.argv[sys.argv.index("--at") + 1], "%Y-%m-%d %H:%M").replace(tzinfo=КИЇВ)
    розклад = json.load(open(РОЗКЛАД, encoding="utf-8"))
    зроблено = set(json.load(open(ЗРОБЛЕНО, encoding="utf-8"))) if os.path.exists(ЗРОБЛЕНО) else set()
    черга = []
    for п in розклад:
        коли = datetime.strptime(п["at"], "%Y-%m-%d %H:%M").replace(tzinfo=КИЇВ)
        if п["id"] not in зроблено and коли <= зараз < коли + ЗАПАС:
            черга.append(п)
    if not черга:
        print("зараз нічого публікувати")
        return
    for п in черга:
        метод, дані = запит(п, зараз)
        if "--dry" in sys.argv:
            print(п["id"], метод, json.dumps(дані, ensure_ascii=False, indent=1))
            continue
        надіслати(метод, дані)
        зроблено.add(п["id"])
        json.dump(sorted(зроблено), open(ЗРОБЛЕНО, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
        print("опубліковано:", п["id"])


if __name__ == "__main__":
    main()
