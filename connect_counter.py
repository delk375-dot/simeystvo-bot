# -*- coding: utf-8 -*-
"""Кнопка «Підключити лічильник бота»: дає боту доступ до сховища Upstash сайту й публікує бота.

Копіює з проєкту сайту (semeystvo-system) у проєкт бота (simeystvo-bot) дві змінні Upstash,
публікує бота й перевіряє, що лічильник пише в сховище. Ключі не виводяться на екран.
"""
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from dotenv import load_dotenv

ТУТ = os.path.dirname(os.path.abspath(__file__))
os.chdir(ТУТ)
load_dotenv(os.path.join(ТУТ, ".env"))
ЗМІННІ = ["UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"]
БАЗА = "https://simeystvo-bot-ebon.vercel.app"


def стоп(текст):
    print("\n❌ " + текст + "\nСфотографуйте або скопіюйте цей текст і надішліть у діалог.")
    sys.exit(1)


def токен_vercel() -> str:
    for шлях in (os.path.join(os.environ.get("APPDATA", ""), "xdg.data", "com.vercel.cli", "auth.json"),
                 os.path.join(os.environ.get("APPDATA", ""), "com.vercel.cli", "Data", "auth.json")):
        if os.path.exists(шлях):
            t = json.load(open(шлях, encoding="utf-8")).get("token")
            if t:
                return t
    стоп("Не знайшов входу у Vercel. Спершу натисніть кнопку «Запустити бота CooLaw», вона попросить увійти.")


def vercel(шлях, токен, дані=None, метод=None):
    req = urllib.request.Request("https://api.vercel.com" + шлях, data=json.dumps(дані).encode() if дані is not None else None,
                                 method=метод or ("POST" if дані is not None else "GET"),
                                 headers={"Authorization": f"Bearer {токен}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        стоп(f"Vercel відповів помилкою {e.code}: {e.read().decode()[:200]}")


def main():
    токен = токен_vercel()
    print("1/4 Беру доступ до сховища з проєкту сайту…")
    сайт = vercel("/v9/projects/semeystvo-system/env?decrypt=true", токен)["envs"]
    значення = {}
    for e in сайт:
        if e["key"] in ЗМІННІ and "production" in e.get("target", []):
            повна = vercel(f"/v1/projects/semeystvo-system/env/{e['id']}", токен)
            значення[e["key"]] = повна.get("value") or e.get("value")
    if set(значення) != set(ЗМІННІ) or not all(значення.values()):
        стоп("У проєкті сайту не знайшов змінних Upstash.")
    print("   ✓ Знайшов.")

    print("2/4 Додаю їх у проєкт бота…")
    бот = vercel("/v9/projects/simeystvo-bot/env", токен)["envs"]
    for ключ, v in значення.items():
        for старий in [e for e in бот if e["key"] == ключ]:
            vercel(f"/v9/projects/simeystvo-bot/env/{старий['id']}", токен, метод="DELETE")
        vercel("/v10/projects/simeystvo-bot/env", токен,
               {"key": ключ, "value": v, "type": "encrypted", "target": ["production", "preview"]})
    print("   ✓ Додав.")

    print("3/4 Публікую бота, щоб він побачив сховище (1–2 хвилини)…\n")
    cli = "vercel" if subprocess.run("where vercel", shell=True, capture_output=True).returncode == 0 else "npx --yes vercel"
    if subprocess.run(f"{cli} deploy --prod --yes", shell=True).returncode != 0:
        стоп("Vercel не опублікував бота.")

    print("\n4/4 Перевіряю, що лічильник пише…")
    tg = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    секрет = hashlib.sha256(tg.encode()).hexdigest()[:48]
    оновлення = {"update_id": int(time.time()), "message": {
        "message_id": 1, "date": int(time.time()), "text": "/start", "entities": [{"type": "bot_command", "offset": 0, "length": 6}],
        "chat": {"id": 999999, "type": "private"}, "from": {"id": 999999, "is_bot": False, "first_name": "Перевірка"}}}
    time.sleep(5)
    req = urllib.request.Request(f"{БАЗА}/api/telegram", data=json.dumps(оновлення).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Telegram-Bot-Api-Secret-Token": секрет})
    urllib.request.urlopen(req, timeout=60).read()
    url, t = значення["UPSTASH_REDIS_REST_URL"].rstrip("/"), значення["UPSTASH_REDIS_REST_TOKEN"]
    req = urllib.request.Request(f"{url}/sismember/coolaw:users/999999", headers={"Authorization": f"Bearer {t}"})
    if json.load(urllib.request.urlopen(req, timeout=30)).get("result") != 1:
        стоп("Бот опубліковано, але запису в сховищі не бачу.")
    from stats import _today
    for шлях in ("srem/coolaw:users/999999", f"srem/coolaw:day:{_today()}/999999", "decr/coolaw:c:starts"):
        req = urllib.request.Request(f"{url}/{шлях}", headers={"Authorization": f"Bearer {t}"})
        urllib.request.urlopen(req, timeout=30).read()  # пробного користувача прибираємо з цифр
    print("   ✓ Лічильник працює.")
    print("\n✅ Готово. У боті: /start → «📊 Статистика».")


if __name__ == "__main__":
    main()
