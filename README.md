# MAD DAY registration bot

Telegram-бот для регистрации игроков MAD DAY с автоматической записью в Google Sheets.

Бот собирает:
- позывной
- фамилию и имя
- телефон
- фракцию
- тариф
- внутренний ID игрока
- Telegram ID для уведомлений
- дату регистрации

После регистрации бот отправляет игроку QR-код с его ID.

## Что лежит в проекте

- `bot.py` — основной код бота
- `requirements.txt` — Python-зависимости
- `.env.example` — пример переменных окружения
- `credentials.json` — ключ сервисного аккаунта Google (не коммитить)
- `content/map.txt` — подпись/текст для команды `/map`
- `content/lore.txt` — история мира
- `content/schedule.txt` — расписание игры
- `content/info.txt` — информация об игре и оплата
- `content/tariffs.txt` — описание тарифов при регистрации
- `content/radio.txt` — набор радиоперехватов
- `content/scenario1.txt` — текст сценария 1
- `content/scenario2.txt` — текст сценария 2
- `content/scenario3.txt` — текст сценария 3
- `content/briefing_steel.txt` — брифинг Корпуса Стали
- `content/briefing_state.txt` — брифинг Нового Штата
- `map.jpg` — карта полигона, если хочешь отправлять её изображением

## 1. Создай Telegram-бота

1. Открой `@BotFather`.
2. Выполни `/newbot`.
3. Получи токен и сохрани его.

## 2. Создай Google Sheet

1. Создай таблицу с именем `MAD DAY REGISTRATION` или укажи своё имя в `GOOGLE_SHEETS_SPREADSHEET`.
2. Бот сам создаст заголовки:
   `ID | Позывной | Фамилия Имя | Телефон | Фракция | Тариф | Telegram ID | Дата | Оплата | Дата оплаты`
3. Если не хочешь включать Google Drive API, можно взять ID таблицы из URL и записать его в `GOOGLE_SHEETS_SPREADSHEET_ID`.

## 3. Подключи Google API

1. Открой Google Cloud Console.
2. Создай проект, например `MAD DAY BOT`.
3. Включи:
   - Google Sheets API
   - Google Drive API
4. Создай `Service Account`.
5. Скачай JSON-ключ и сохрани его как `credentials.json` рядом с `bot.py`.
6. Открой Google Таблицу и выдай доступ email сервисного аккаунта с ролью `Editor`.

## 4. Установи зависимости

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 5. Заполни настройки

1. Скопируй `.env.example` в `.env`.
2. Заполни `TOKEN`.
3. При необходимости измени:
   - `GOOGLE_SHEETS_SPREADSHEET`
   - `GOOGLE_SHEETS_SPREADSHEET_ID`
   - `REGISTRATION_TIMEZONE`
   - `FACTION_LIMITS`
   - `TARIFFS`
   - `TARIFF_BUTTONS`
   - `MAP_IMAGE_PATH`
   - `GAME_START_AT`
   - `GAME_REMINDER_HOURS_BEFORE`
   - `GAME_REMINDER_TEXT`
   - `ADMIN_IDS`
   - `FACTION_CHAT_LINKS`
   - `PAYMENT_LINK`

Пример:

```env
TOKEN=123456:ABCDEF
GOOGLE_SHEETS_SPREADSHEET=MAD DAY REGISTRATION
GOOGLE_SHEETS_SPREADSHEET_ID=
GOOGLE_CREDENTIALS_FILE=credentials.json
REGISTRATION_TIMEZONE=Europe/Moscow
FACTION_LIMITS=🔵 Корпус Стали=60,🔴 Новый Штат=60
TARIFFS=Рейдер,Нефтешлам,Мародер,Бензиновый барон
TARIFF_BUTTONS=🏜️ РЕЙДЕР — 1000₽=Рейдер,🛢️ НЕФТЕШЛАМ — 2200₽=Нефтешлам,💀 МАРОДЕР — 2500₽=Мародер,👑 БЕНЗИНОВЫЙ БАРОН — 3000₽=Бензиновый барон
MAP_IMAGE_PATH=map.jpg
GAME_START_AT=2026-07-12 10:00
GAME_REMINDER_HOURS_BEFORE=24
GAME_REMINDER_TEXT=До начала MAD DAY осталось 24 часа.
ADMIN_IDS=123456789
FACTION_CHAT_LINKS=🔵 Корпус Стали=https://t.me/steel_chat,🔴 Новый Штат=https://t.me/state_chat
PAYMENT_LINK=https://www.sberbank.com/sms/pbpn?requisiteNumber=79217300917
```

Если запускаешь на Render и не хочешь хранить `credentials.json` файлом, используй `GOOGLE_CREDENTIALS_JSON` и вставь туда содержимое JSON-ключа.

## 6. Запуск локально

`.env` подхватится автоматически, поэтому достаточно выполнить:

```bash
python bot.py
```


## Веб-форма для регистрации без Telegram

Если нужно регистрировать игроков без Telegram, запусти веб-форму.

1. Установи зависимости (см. выше).
2. Запусти:

```bash
python web_form.py
```

По умолчанию форма стартует на порту `8080`. Можно задать `PORT` или `WEB_PORT`.

Форма использует те же переменные окружения Google Sheets. В колонку `Telegram ID`
записывается `WEB`, чтобы было видно, что регистрация прошла через сайт.

## Команды бота

- `/start` — начать регистрацию
- `/me` — показать паспорт бойца
- `/stats` — посмотреть заполнение фракций
- `/lore` — показать историю мира
- `/map` — отправить карту полигона
- `/schedule` — расписание игры
- `/radio` — случайный радиоперехват
- `/info` — информация об игре и QR оплаты
- `/briefing` — брифинг твоей фракции
- `/scenario1` — сценарий 1
- `/scenario2` — сценарий 2
- `/scenario3` — сценарий 3
- `/countdown` — таймер до начала игры
- `/cancel` — отменить текущую регистрацию
- `/help` — справка

Команды организатора:

- `/players` — последние зарегистрированные игроки
- `/broadcast текст` — рассылка по всем зарегистрированным
- `/close_registration` — закрыть регистрацию
- `/open_registration` — открыть регистрацию

## Автонапоминание перед игрой

Бот может сам написать всем зарегистрированным игрокам за 24 часа до старта.

Для этого задай:

- `GAME_START_AT=2026-07-12 10:00`
- `GAME_REMINDER_HOURS_BEFORE=24`
- `GAME_REMINDER_TEXT=До начала MAD DAY осталось 24 часа.`

Напоминание уходит всем, у кого уже есть запись в таблице и сохранён `Telegram ID`.

## Карта и сценарии

- Положи карту в `map.jpg` рядом с ботом или измени `MAP_IMAGE_PATH`.
- История мира редактируется в `content/lore.txt`.
- Расписание игры редактируется в `content/schedule.txt`.
- Информация об игре и текст оплаты редактируются в `content/info.txt`.
- Тексты тарифов редактируются в `content/tariffs.txt`.
- Радиоперехваты редактируются в `content/radio.txt`.
- После регистрации бот автоматически отправляет блок оплаты и кнопку `✅ Оплатил`.
- При нажатии на кнопку в Google Таблице обновляются колонки `Оплата` и `Дата оплаты`.
- Брифинги фракций редактируются в `content/briefing_steel.txt` и `content/briefing_state.txt`.
- Редактируй тексты сценариев прямо в файлах:
  - `content/scenario1.txt`
  - `content/scenario2.txt`
  - `content/scenario3.txt`
- Если хочешь, чтобы сценарий отправлялся с картинкой, положи рядом:
  - `content/scenario1.jpg` или `content/scenario1.png`
  - `content/scenario2.jpg` или `content/scenario2.png`
  - `content/scenario3.jpg` или `content/scenario3.png`
- Текст подписи для `/map` хранится в `content/map.txt`

## Админ-панель и чаты фракций

- Укажи Telegram ID организаторов в `ADMIN_IDS`, например `123456789,987654321`.
- Укажи ссылки на закрытые чаты в `FACTION_CHAT_LINKS`.
- Кнопка `ЧАТ ФРАКЦИИ` появится в `/briefing`, если ссылка задана именно для фракции игрока.

## Деплой на Render

Подойдёт обычный Background Worker или Web Service.

Настройки:

- Build Command: `pip install -r requirements.txt`
- Start Command: `python bot.py`

Environment Variables:

- `TOKEN`
- `GOOGLE_SHEETS_SPREADSHEET`
- `GOOGLE_SHEETS_SPREADSHEET_ID`
- `GOOGLE_CREDENTIALS_JSON` или `GOOGLE_CREDENTIALS_FILE`
- `REGISTRATION_TIMEZONE`
- `FACTION_LIMITS`
- `TARIFFS`
- `MAP_IMAGE_PATH`
- `GAME_START_AT`
- `GAME_REMINDER_HOURS_BEFORE`
- `GAME_REMINDER_TEXT`
- `ADMIN_IDS`
- `FACTION_CHAT_LINKS`
- `PAYMENT_LINK`

## Важные замечания

- Лимиты фракций проверяются по данным из Google Sheets.
- Если таблицу очищать вручную, нумерация ID начнётся заново от максимального найденного значения.
- Автонапоминание сработает только пока бот запущен.
- Админ-команды работают только для пользователей из `ADMIN_IDS`.
- Для продакшена лучше не хранить токен и Google credentials внутри репозитория.
