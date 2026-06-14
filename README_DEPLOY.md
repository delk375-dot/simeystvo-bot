# Деплой Сімейство AI Bot на Vercel

## Структура проекту

```
simeystvo-bot/
├── api/
│   └── telegram.py      # Vercel serverless endpoint (webhook)
├── content/
│   ├── books.json
│   ├── courses.json
│   └── services.json
├── bot_core.py           # Вся логіка бота (handlers, меню, ConversationHandler)
├── bot.py                # Локальний запуск через polling (для тестів)
├── personality.py        # Тексти та голос бота
├── set_webhook.py        # Скрипт встановлення webhook
├── vercel.json           # Конфігурація Vercel
└── requirements.txt
```

---

## Крок 1 — Деплой на Vercel

### Через Vercel CLI

```bash
npm i -g vercel
vercel login
vercel --prod
```

### Через GitHub (рекомендовано)

1. Зайдіть на https://vercel.com
2. Натисніть **Add New → Project**
3. Виберіть репозиторій `simeystvo-bot`
4. Натисніть **Deploy**

Vercel автоматично знайде `api/telegram.py` і задеплоїть його як serverless function.

---

## Крок 2 — Environment Variables

У налаштуваннях проекту на Vercel: **Settings → Environment Variables**

Додайте дві змінні:

| Name | Value |
|------|-------|
| `TELEGRAM_BOT_TOKEN` | Токен вашого бота (від @BotFather) |
| `ADMIN_CHAT_ID` | Ваш Telegram ID (наприклад, `219205800`) |

> Свій Telegram ID можна дізнатись через [@userinfobot](https://t.me/userinfobot)

---

## Крок 3 — Встановлення webhook

Після деплою Vercel надасть URL вигляду:
```
https://simeystvo-bot.vercel.app
```

Встановіть webhook — один з двох способів:

### Варіант А: скрипт

Додайте `WEBHOOK_URL` у `.env`:
```
WEBHOOK_URL=https://simeystvo-bot.vercel.app/api/telegram
```

Запустіть:
```bash
python set_webhook.py
```

### Варіант Б: вручну через браузер

Відкрийте URL (підставте свій токен і домен):
```
https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://simeystvo-bot.vercel.app/api/telegram
```

### Перевірка webhook

```
https://api.telegram.org/bot<TOKEN>/getWebhookInfo
```

Поле `url` має містити ваш Vercel URL.

---

## Крок 4 — Перевірка

Відкрийте в браузері:
```
https://simeystvo-bot.vercel.app/api/telegram
```

Має повернути:
```
Simeystvo bot webhook is alive
```

Напишіть боту `/start` у Telegram — бот має відповісти.

---

## Локальне тестування (polling)

Для тестів без деплою — старий режим залишається:

```bash
python bot.py
```

> Увага: polling і webhook не можуть працювати одночасно.
> Якщо webhook встановлено, polling не працюватиме.
> Щоб повернутися до polling, видаліть webhook:
> `https://api.telegram.org/bot<TOKEN>/deleteWebhook`

---

## Важлива примітка про ConversationHandler

Стан розмови (ім'я, телефон, крок форми) зберігається в пам'яті
serverless-контейнера Vercel. Якщо контейнер перезапуститься між
повідомленнями користувача — незавершена форма скинеться.

Для низькотрафікового бота це несуттєво: контейнери залишаються
теплими кілька хвилин після останнього запиту.
