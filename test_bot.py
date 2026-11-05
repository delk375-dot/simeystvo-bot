# -*- coding: utf-8 -*-
"""Сценарії бота без мережі: python -X utf8 test_bot.py"""
import asyncio
import datetime as dt
import os

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456:TEST")
os.environ["ADMIN_CHAT_ID"] = "1000"
os.environ.pop("POMAGAYLO_MCP_URL", None)

from telegram import Update, User  # noqa: E402
from telegram.ext import ExtBot  # noqa: E402

import bot_core  # noqa: E402

ADMIN, CLIENT = 1000, 2000
надіслано, відредаговано, підказки, пересилання = [], [], [], []
збій = {"адміну": False}


async def fake_send(self, chat_id, text=None, **kw):
    if збій["адміну"] and chat_id == ADMIN:
        raise RuntimeError("Telegram недоступний")
    if kw.get("parse_mode") is None and chat_id == ADMIN and text is None:
        raise AssertionError("порожнє повідомлення")
    надіслано.append((chat_id, text, kw))
    return None


async def fake_edit(self, text=None, **kw):
    відредаговано.append((text, kw))
    return None


async def fake_answer(self, *a, **kw):
    підказки.append((a, kw))
    return True


async def fake_forward(self, chat_id, from_chat_id, message_id, **kw):
    пересилання.append((chat_id, from_chat_id, message_id))
    return None


async def fake_init(self):
    self._bot_user = User(1, "CooLaw", True, username="CooLaw007_bot")
    self._initialized = True


ExtBot.send_message = fake_send
ExtBot.edit_message_text = fake_edit
ExtBot.answer_callback_query = fake_answer
ExtBot.forward_message = fake_forward
ExtBot.initialize = fake_init
кнопки_постів = []


async def fake_markup(self, chat_id=None, message_id=None, reply_markup=None, **kw):
    кнопки_постів.append(reply_markup.inline_keyboard[0][0].url)
    return None


ExtBot.edit_message_reply_markup = fake_markup
bot_core.increment = lambda *a, **k: None
bot_core.track_start = lambda *a, **k: None
_sleep = asyncio.sleep
bot_core.asyncio.sleep = lambda *_a, **_k: _sleep(0)

лічильник = {"n": 0}
ок = 0


def перевір(умова, назва):
    global ок
    assert умова, назва
    ок += 1
    print("✓", назва)


def юзер(uid, username="ivan_petrenko"):
    return {"id": uid, "is_bot": False, "first_name": "Іван_*Тест", "username": username}


def текст_апдейт(app, uid, text=None, **extra):
    лічильник["n"] += 1
    msg = {"message_id": лічильник["n"], "date": int(dt.datetime.now().timestamp()),
           "chat": {"id": uid, "type": "private"}, "from": юзер(uid), **extra}
    if text is not None:
        msg["text"] = text
        if text.startswith("/"):
            msg["entities"] = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
    return Update.de_json({"update_id": лічильник["n"], "message": msg}, app.bot)


def кнопка_апдейт(app, uid, data):
    лічильник["n"] += 1
    return Update.de_json({"update_id": лічильник["n"], "callback_query": {
        "id": str(лічильник["n"]), "from": юзер(uid), "chat_instance": "x", "data": data,
        "message": {"message_id": 1, "date": 1, "chat": {"id": uid, "type": "private"}, "text": "старе"},
    }}, app.bot)


def адміну():
    return [t for c, t, _ in надіслано if c == ADMIN]


def клієнту():
    return [t for c, t, _ in надіслано if c == CLIENT]


def кнопки(kw):
    return [b.callback_data for ряд in kw["reply_markup"].inline_keyboard for b in ряд]


async def новий():
    """Новий застосунок щоразу: так виглядає перезапуск сервера, пам'ять порожня."""
    app = bot_core.build_application()
    await app.initialize()
    return app


async def main():
    надіслано.clear()
    app = await новий()
    await app.process_update(текст_апдейт(app, CLIENT, "Розлучаюсь, є дитина_* і борг"))
    перевір(any("Розлучаюсь, є дитина_* і борг" in t and "@ivan_petrenko" in t for t in адміну()), "вільний текст одразу йде адміну, навіть із _ і * ")
    перевір(all(kw.get("parse_mode") is None for c, _, kw in надіслано if c == ADMIN), "заявки адміну без розмітки")
    перевір(any("Опис ситуації передав" in t for t in клієнту()), "клієнта просять залишити контакт")

    надіслано.clear()
    app = await новий()  # перезапуск сервера між двома повідомленнями
    await app.process_update(текст_апдейт(app, CLIENT, "+380 67 123 45 67"))
    перевір(any("Контакт клієнта" in t and "+380 67 123 45 67" in t for t in адміну()), "контакт дійшов і після перезапуску сервера")
    перевір(any("Передав контакт" in t for t in клієнту()), "клієнту підтверджено контакт")

    # Збій доставки: клієнту не брешемо.
    надіслано.clear()
    збій["адміну"] = True
    await app.process_update(текст_апдейт(app, CLIENT, "Важлива справа"))
    збій["адміну"] = False
    перевір(any("технічний збій" in t and "+380678390916" in t for t in клієнту()), "при збої клієнт бачить правду і телефон")
    перевір(not any("передав" in t.lower() for t in клієнту()), "при збої бот не каже «передав»")

    # Тест проходить між перезапусками: стан у кнопках.
    теми = bot_core.load_json("assessments.json")
    for ключ, тема in теми.items():
        дані = f"at:{ключ}"
        for _ in тема["questions"]:
            відредаговано.clear()
            app = await новий()
            await app.process_update(кнопка_апдейт(app, CLIENT, дані))
            кн = кнопки(відредаговано[-1][1])
            перевір(all(len(x.encode()) <= 64 for x in кн), f"{ключ}: кнопки в межах 64 байтів") if дані == f"at:{ключ}" else None
            дані = кн[1]
        відредаговано.clear()
        app = await новий()
        await app.process_update(кнопка_апдейт(app, CLIENT, дані))
        перевір("Орієнтовна готовність" in відредаговано[-1][0], f"{ключ}: тест дійшов до результату")
        передати = кнопки(відредаговано[-1][1])[0]
        надіслано.clear()
        app = await новий()
        await app.process_update(кнопка_апдейт(app, CLIENT, передати))
        перевір(any(f"Напрям: {тема['title']}" in t and "@ivan_petrenko" in t for t in адміну()), f"{ключ}: заявка з відповідями дійшла адміну")

    # Старі кнопки й адмін.
    відредаговано.clear()
    await app.process_update(кнопка_апдейт(app, CLIENT, "assess_transfer"))
    перевір(bot_core.WELCOME_TEXT == відредаговано[-1][0], "стара кнопка веде в меню, а не ламається")
    відредаговано.clear()
    await app.process_update(кнопка_апдейт(app, CLIENT, "an:nema:yy"))
    перевір(bot_core.WELCOME_TEXT == відредаговано[-1][0], "підроблена кнопка тесту не ламає бота")

    надіслано.clear()
    await app.process_update(текст_апдейт(app, ADMIN, "тест від адміна"))
    перевір(len(надіслано) == 1 and "Панель" in надіслано[0][1], "текст адміна не стає заявкою")

    # Файл і голосове.
    надіслано.clear()
    пересилання.clear()
    await app.process_update(текст_апдейт(app, CLIENT, voice={"file_id": "v", "file_unique_id": "u", "duration": 3}))
    перевір(пересилання and any("голосове" in t for t in адміну()), "голосове переслано адміну")

    # Канал: пост у каналі не обробляється як заявка.
    надіслано.clear()
    лічильник["n"] += 1
    пост = Update.de_json({"update_id": лічильник["n"], "channel_post": {"message_id": 5, "date": 1, "chat": {"id": -100, "type": "channel"}, "text": "пост"}}, app.bot)
    await app.process_update(пост)
    перевір(not надіслано, "пости каналу не стають заявками")

    # Меню, послуги, книги.
    bot_core._shop_fetch = lambda: {"police": 77}
    групи = bot_core.load_json("services.json")
    ідентифікатори = [i["id"] for g in групи for i in g["items"]]
    перевір(len(ідентифікатори) == len(set(ідентифікатори)), "ідентифікатори послуг не повторюються")
    відредаговано.clear()
    await app.process_update(кнопка_апдейт(app, CLIENT, "services"))
    перевір(len([b for b in кнопки(відредаговано[-1][1]) if b and b.startswith("sg:")]) == len(групи), "усі групи послуг у меню")
    for g in групи:
        відредаговано.clear()
        await app.process_update(кнопка_апдейт(app, CLIENT, f"sg:{g['id']}"))
        перевір(len(кнопки(відредаговано[-1][1])) == len(g["items"]) + 1, f"група {g['title']}")
        for i in g["items"]:
            відредаговано.clear()
            await app.process_update(кнопка_апдейт(app, CLIENT, f"service:{i['id']}"))
            текст, kw = відредаговано[-1]
            посилання = [b.url for ряд in kw["reply_markup"].inline_keyboard for b in ряд if b.url]
            assert i["text"] in текст and посилання and посилання[0].startswith("https://ai.semeystvo.com.ua") and "utm_source=telegram" in посилання[0], i["id"]
    перевір(True, f"усі {len(ідентифікатори)} послуг відкриваються з посиланням на сайт")
    # Напрям послуги доходить разом зі зверненням.
    надіслано.clear()
    await app.process_update(кнопка_апдейт(app, CLIENT, "service:s130"))
    await app.process_update(текст_апдейт(app, CLIENT, "Склали протокол"))
    перевір(any("Напрям: Ст. 130" in t for t in адміну()), "напрям послуги дійшов разом зі зверненням")
    відредаговано.clear()
    await app.process_update(кнопка_апдейт(app, CLIENT, "books"))
    перевір(any("Як розмовляти з поліцією · 77 грн" in b.text for ряд in відредаговано[-1][1]["reply_markup"].inline_keyboard for b in ряд), "ціну книги взято з магазину")
    bot_core._shop_cache["at"] = 0
    def збій_магазину():
        raise OSError("немає")
    bot_core._shop_fetch = збій_магазину
    bot_core._shop_cache["prices"] = {}
    відредаговано.clear()
    await app.process_update(кнопка_апдейт(app, CLIENT, "books"))
    перевір(any("Як розмовляти з поліцією · 99 грн" in b.text for ряд in відредаговано[-1][1]["reply_markup"].inline_keyboard for b in ряд), "без магазину ціна з файлу")
    відредаговано.clear()
    await app.process_update(кнопка_апдейт(app, CLIENT, "book:1"))
    перевір(any(b.url and "yak-rozmovlyaty-z-politsiyeyu" in b.url for ряд in відредаговано[-1][1]["reply_markup"].inline_keyboard for b in ряд), "кнопка купівлі веде на сайт")
    відредаговано.clear()
    await app.process_update(кнопка_апдейт(app, CLIENT, "book_interest:2"))
    перевір(bot_core.WELCOME_TEXT == відредаговано[-1][0], "стара кнопка книги веде в меню")
    # Перехід із каналу й кнопка під постом.
    надіслано.clear()
    await app.process_update(текст_апдейт(app, CLIENT, "/start s_s130"))
    перевір(any("Ст. 130" in t for t in клієнту()), "перехід із посту відкриває послугу")
    надіслано.clear()
    await app.process_update(текст_апдейт(app, CLIENT, "Склали протокол"))
    перевір(any("Напрям: Ст. 130" in t for t in адміну()), "тема з посту дійшла адміну")
    надіслано.clear()
    await app.process_update(текст_апдейт(app, CLIENT, "/start s_nema"))
    перевір(any(t == bot_core.WELCOME_TEXT for t in клієнту()), "невідома тема веде в меню")

    кнопки_постів.clear()
    def пост(ім_я, **extra):
        лічильник["n"] += 1
        return Update.de_json({"update_id": лічильник["n"], "channel_post": {"message_id": 7, "date": 1,
                               "chat": {"id": -100, "type": "channel", "username": ім_я}, **extra}}, app.bot)
    await app.process_update(пост("aadvokatt", text="Шахраї взяли кредит на вас"))
    перевір(кнопки_постів and кнопки_постів[-1].endswith("start=s_collectors"), "ручний пост отримав кнопку за темою")
    кнопки_постів.clear()
    await app.process_update(пост("inshyi", text="кредит"))
    перевір(not кнопки_постів, "чужий канал не чіпаємо")
    await app.process_update(пост("aadvokatt", photo=[{"file_id": "f", "file_unique_id": "u", "width": 1, "height": 1}]))
    перевір(not кнопки_постів, "фото без підпису не чіпаємо")
    await app.process_update(пост("aadvokatt", text="щось про кредит", reply_markup={"inline_keyboard": [[{"text": "x", "url": "https://t.me/x"}]]}))
    перевір(not кнопки_постів, "пост із власною кнопкою не чіпаємо")

    from topics import topic_for
    for t, очікую in [("Спадкоємець за законом", "inheritance"), ("Аліменти — це не все", "alimony"), ("О котрій годині п'яних? ст. 130", "s130"),
                      ("Якщо шахраї взяли кредит", "collectors"), ("Карас чи ґранфалун: що тримає ваш шлюб", "divorce"), ("Про погоду", "")]:
        assert topic_for(t) == очікую, t
    послуги = {i["id"] for g in групи for i in g["items"]}
    from topics import ПРАВИЛА
    перевір(all(п in послуги for _ш, п in ПРАВИЛА), "теми постів ведуть на наявні послуги")
    print(f"\n✅ {ок} перевірок пройдено")


asyncio.run(main())
