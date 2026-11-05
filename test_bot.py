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

    # Книга.
    надіслано.clear()
    відредаговано.clear()
    await app.process_update(кнопка_апдейт(app, CLIENT, "book_interest:2"))
    перевір(any("Інтерес до книги" in t for t in адміну()), "інтерес до книги дійшов адміну")
    print(f"\n✅ {ок} перевірок пройдено")


asyncio.run(main())
