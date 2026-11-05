# -*- coding: utf-8 -*-
"""Раз на день публікує в канал найстарішу ще не опубліковану статтю блогу.

Запускає GitHub Actions (.github/workflows/channel-daily.yml). Опубліковане лежить
у content/channel_posted.json: workflow комітить цей файл, тому пост не задвоїться.

  python -X utf8 channel_daily.py --seed     запам'ятати всі нинішні статті, нічого не публікуючи
  python -X utf8 channel_daily.py --dry      показати наступний пост
  python -X utf8 channel_daily.py            опублікувати
"""
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

from topics import bot_link, topic_for

RSS = "https://ai.semeystvo.com.ua/rss.xml"
CHANNEL = "@aadvokatt"
UTM = "utm_source=telegram&utm_medium=channel"
КИЇВ = ZoneInfo("Europe/Kyiv")
СТАН = os.path.join(os.path.dirname(os.path.abspath(__file__)), "content", "channel_posted.json")


def читати_rss() -> list:
    req = urllib.request.Request(RSS, headers={"User-Agent": "Mozilla/5.0 coolaw"})
    xml = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    статті = []
    for item in re.findall(r"<item>(.*?)</item>", xml, re.S):
        def поле(t):
            m = re.search(rf"<{t}[^>]*>(.*?)</{t}>", item, re.S)
            return html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", m.group(1))).strip() if m else ""
        статті.append({"title": поле("title"), "link": поле("link"), "text": поле("description"),
                       "date": parsedate_to_datetime(поле("pubDate"))})
    return sorted(статті, key=lambda x: x["date"])


def скласти_пост(стаття: dict) -> dict:
    послуга = topic_for(f"{стаття['title']} {стаття['text']}")
    посилання = f"{стаття['link']}?{UTM}"
    return {
        "chat_id": CHANNEL,
        "text": f"{стаття['title']}\n\n{стаття['text']}",
        "link_preview_options": {"url": посилання, "prefer_large_media": True},
        "reply_markup": {"inline_keyboard": [
            [{"text": "📖 Читати статтю", "url": посилання}],
            [{"text": "📝 Написати адвокату", "url": bot_link(послуга)}],
        ]},
    }


def надіслати(пост: dict) -> None:
    токен = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    req = urllib.request.Request(f"https://api.telegram.org/bot{токен}/sendMessage", data=json.dumps(пост).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        відповідь = json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Telegram відмовив: {e.code} {e.read().decode()[:200]}")
    if not відповідь.get("ok"):
        raise SystemExit(f"Telegram відмовив: {відповідь}")


def main() -> None:
    статті = читати_rss()
    if "--seed" in sys.argv:
        json.dump(sorted(с["link"] for с in статті), open(СТАН, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
        print(f"запам'ятав {len(статті)} статей")
        return
    опубліковані = set(json.load(open(СТАН, encoding="utf-8")))
    # Навмисне запізнення на добу: у канал іде лише стаття, що вийшла на сайті до сьогоднішнього дня (за Києвом).
    сьогодні = datetime.now(КИЇВ).date()
    нові = [с for с in статті if с["link"] not in опубліковані and с["date"].astimezone(КИЇВ).date() < сьогодні]
    if not нові:
        print("нових статей немає")
        return
    стаття = нові[0]
    пост = скласти_пост(стаття)
    if "--dry" in sys.argv:
        print(json.dumps(пост, ensure_ascii=False, indent=1))
        print("у черзі нових:", len(нові))
        return
    надіслати(пост)
    опубліковані.add(стаття["link"])
    json.dump(sorted(опубліковані), open(СТАН, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print("опубліковано:", стаття["title"])


if __name__ == "__main__":
    main()
