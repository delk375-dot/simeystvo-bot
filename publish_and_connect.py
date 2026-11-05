# -*- coding: utf-8 -*-
"""Кнопка «Запустити бота CooLaw»: публікує на Vercel, перевіряє, підключає до Telegram.

Вебхук ставимо лише після перевірки нової версії: клієнти не потраплять на стару.
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
TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
БАЗА = "https://simeystvo-bot-ebon.vercel.app"
СЕКРЕТ = hashlib.sha256(TOKEN.encode()).hexdigest()[:48]


def стоп(текст):
    print("\n❌ " + текст)
    print("Сфотографуйте або скопіюйте цей текст і надішліть у діалог.")
    sys.exit(1)


def запит(адреса, дані=None, заголовки=None):
    тіло = json.dumps(дані).encode() if дані is not None else None
    r = urllib.request.Request(адреса, data=тіло, method="POST" if дані is not None else "GET",
                               headers={"Content-Type": "application/json", "User-Agent": "coolaw-deploy/1.0", **(заголовки or {})})
    try:
        with urllib.request.urlopen(r, timeout=60) as x:
            return x.status, x.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def main():
    if not TOKEN:
        стоп("У файлі .env немає токена бота.")

    # Vercel CLI може бути видно не з кожного вікна Windows, тоді беремо його через npx.
    cli = "vercel" if subprocess.run("where vercel", shell=True, capture_output=True).returncode == 0 else "npx --yes vercel"
    if cli != "vercel" and subprocess.run("where npx", shell=True, capture_output=True).returncode != 0:
        стоп("На цьому комп'ютері не видно ні Vercel, ні Node.js.")
    if subprocess.run(f"{cli} whoami", shell=True, capture_output=True).returncode != 0:
        print("Vercel просить увійти: підтвердьте вхід у браузері, який зараз відкриється.\n")
        if subprocess.run(f"{cli} login", shell=True).returncode != 0:
            стоп("Вхід у Vercel не вдався.")

    print("1/4 Публікую бота на Vercel, це 1–2 хвилини…\n")
    if subprocess.run(f"{cli} deploy --prod --yes", shell=True).returncode != 0:
        стоп("Vercel не опублікував бота.")

    print("\n2/4 Перевіряю нову версію…")
    for _ in range(12):
        ping, _т = запит(f"{БАЗА}/api/ping")
        чужий, _т = запит(f"{БАЗА}/api/telegram", {"update_id": 1})
        if ping == 200 and чужий == 403:
            break
        time.sleep(10)
    else:
        стоп(f"Нова версія не відповідає як слід: ping {ping}, чужий запит {чужий}. Telegram не підключав.")
    print("   ✓ Нова версія працює, чужі запити відхиляються.")

    print("3/4 Надсилаю вам тестову заявку…")
    тест = {"update_id": int(time.time()), "message": {
        "message_id": 1, "date": int(time.time()), "text": "Технічна перевірка бота: це не клієнт.",
        "chat": {"id": 999999, "type": "private"},
        "from": {"id": 999999, "is_bot": False, "first_name": "Перевірка_CooLaw"},
    }}
    код, _т = запит(f"{БАЗА}/api/telegram", тест, {"X-Telegram-Bot-Api-Secret-Token": СЕКРЕТ})
    if код != 200:
        стоп(f"Сервер не прийняв перевірку (код {код}): токен на Vercel, мабуть, відрізняється від .env. Telegram не підключав.")
    print("   ✓ Сервер прийняв. У Telegram має прийти «Технічна перевірка бота».")

    print("4/4 Підключаю бота до Telegram…")
    код, т = запит(f"https://api.telegram.org/bot{TOKEN}/setWebhook",
                   {"url": f"{БАЗА}/api/telegram", "secret_token": СЕКРЕТ, "allowed_updates": ["message", "callback_query", "channel_post"]})
    if код != 200 or not json.loads(т).get("ok"):
        стоп(f"Telegram не прийняв підключення (код {код}).")
    код, т = запит(f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo")
    інфо = json.loads(т).get("result", {})
    if інфо.get("url") != f"{БАЗА}/api/telegram":
        стоп("Telegram показує іншу адресу бота.")
    print("   ✓ Підключено.")
    print("\n✅ Готово. Напишіть /start у @CooLaw007_bot і повідомте в діалог, що все пройшло.")


if __name__ == "__main__":
    main()
