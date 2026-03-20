from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict
from zoneinfo import ZoneInfo

import gspread
import qrcode
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


BASE_DIR = Path(__file__).resolve().parent
INTRO, CALLSIGN, PHONE, FACTION, FULL_NAME, TARIFF = range(6)
START_REGISTRATION_BUTTON = "⚔ Начать регистрацию"
MENU_PROFILE = "📄 Мой профиль"
MENU_REGISTER = "⚔ Регистрация"
MENU_MAP = "🗺 Карта полигона"
MENU_SCHEDULE = "📋 Расписание"
MENU_RADIO = "📻 Радио Пустоши"
MENU_LORE = "🌍 История мира MAD DAY"
MENU_INFO = "ℹ Информация об игре"
MENU_BRIEFING = "📘 Брифинг фракции"
MENU_FACTION_CHAT = "💬 Чат фракции"
MENU_STATS = "📊 Баланс фракций"
PAYMENT_CONFIRMED_CALLBACK = "payment_confirmed"
FACTION_CALLBACK_PREFIX = "faction:"
FACTION_BUTTONS = {
    "🔵 Вступить в Корпус Стали": "🔵 Корпус Стали",
    "🔴 Вступить в Новый Штат": "🔴 Новый Штат",
}
SHEET_HEADERS = [
    "ID",
    "Позывной",
    "Фамилия Имя",
    "Телефон",
    "Фракция",
    "Тариф",
    "Telegram ID",
    "Дата",
    "Оплата",
    "Дата оплаты",
]
DEFAULT_FACTION_LIMITS = {
    "🔵 Корпус Стали": 60,
    "🔴 Новый Штат": 60,
}
DEFAULT_FACTION_CHAT_LINKS = {
    "🔵 Корпус Стали": "https://t.me/+2zXarUbPumE5NGI6",
    "🔴 Новый Штат": "https://t.me/+FfPwewaFvcQ4NGMy",
}
DEFAULT_TARIFFS = [
    "Рейдер",
    "Нефтешлам",
    "Мародер",
    "Бензиновый барон",
]
DEFAULT_TARIFF_LABELS = {
    "Рейдер": "🏜️ РЕЙДЕР — 1000₽",
    "Нефтешлам": "🛢️ НЕФТЕШЛАМ — 2200₽",
    "Мародер": "💀 МАРОДЕР — 2500₽",
    "Бензиновый барон": "👑 БЕНЗИНОВЫЙ БАРОН — 3000₽",
}
DEFAULT_TARIFF_MESSAGE = (
    "🏜️ РЕЙДЕР - 1000₽\n"
    "Свое снаряжение: Твоё верное железо, проверенное песками.\n"
    "• В комплекте: Входной билет, заправка воздухом, доступ к инфраструктуре Хольмгарда.\n"
    "• Статус: Опасный одиночка. Пришел из пустоши, чтобы забрать своё.\n\n"
    "🛢️ НЕФТЕШЛАМ - 2200₽\n"
    "• Снаряжение: Базовый комплект выживания (маркер, маска, форма).\n"
    "• Боезапас: 500 шаров — залей их краской!\n"
    "• Статус: Рекрут. Твоя задача — бежать вперед и надеяться, что в баке хватит давления.\n\n"
    "💀 МАРОДЕР - 2500₽\n"
    "• Снаряжение: Улучшенная экипировка (термальная маска с двойным стеклом — не потеет даже в аду).\n"
    "• Боезапас: 500 шаров.\n"
    "• Статус: Опытный боец. Ты знаешь цену хорошему обзору и не любишь лишних движений.\n\n"
    "👑 БЕНЗИНОВЫЙ БАРОН - 3000₽\n"
    "• Снаряжение: Топовая экипировка + полная бронезащита.\n"
    "• Боезапас: 1000 шаров — бесконечный поток ярости.\n"
    "• Статус: Хозяин вышки. Пока у остальных кончается краска, ты продолжаешь вершить историю."
)
CONTENT_FILES = {
    "map": BASE_DIR / "content" / "map.txt",
    "lore": BASE_DIR / "content" / "lore.txt",
    "schedule": BASE_DIR / "content" / "schedule.txt",
    "info": BASE_DIR / "content" / "info.txt",
    "tariffs": BASE_DIR / "content" / "tariffs.txt",
    "payment": BASE_DIR / "content" / "payment.txt",
    "radio": BASE_DIR / "content" / "radio.txt",
    "scenario1": BASE_DIR / "content" / "scenario1.txt",
    "scenario2": BASE_DIR / "content" / "scenario2.txt",
    "scenario3": BASE_DIR / "content" / "scenario3.txt",
    "briefing_steel": BASE_DIR / "content" / "briefing_steel.txt",
    "briefing_state": BASE_DIR / "content" / "briefing_state.txt",
}
SCENARIO_IMAGE_CANDIDATES = {
    "scenario1": [
        BASE_DIR / "content" / "scenario1.jpg",
        BASE_DIR / "content" / "scenario1.jpeg",
        BASE_DIR / "content" / "scenario1.png",
    ],
    "scenario2": [
        BASE_DIR / "content" / "scenario2.jpg",
        BASE_DIR / "content" / "scenario2.jpeg",
        BASE_DIR / "content" / "scenario2.png",
    ],
    "scenario3": [
        BASE_DIR / "content" / "scenario3.jpg",
        BASE_DIR / "content" / "scenario3.jpeg",
        BASE_DIR / "content" / "scenario3.png",
    ],
}
GAME_REMINDER_PLAN = [
    (timedelta(days=5), "5 дней"),
    (timedelta(days=2), "2 дня"),
    (timedelta(hours=24), "24 часа"),
    (timedelta(hours=12), "12 часов"),
]


@dataclass
class Config:
    token: str
    spreadsheet_name: str
    spreadsheet_id: str | None
    credentials_file: str
    credentials_json: str | None
    timezone_name: str
    faction_limits: Dict[str, int]
    tariffs: list[str]
    tariff_message: str
    tariff_buttons: list[str]
    tariff_button_map: Dict[str, str]
    map_image_path: str | None
    game_start_at: str | None
    admin_ids: set[int]
    faction_chat_links: Dict[str, str]
    payment_link: str


def load_config() -> Config:
    load_dotenv()
    token = os.getenv("TOKEN", "").strip()
    spreadsheet_name = os.getenv("GOOGLE_SHEETS_SPREADSHEET", "MAD DAY REGISTRATION").strip()
    spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "").strip() or None
    credentials_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json").strip()
    credentials_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    timezone_name = os.getenv("REGISTRATION_TIMEZONE", "Europe/Moscow").strip()
    faction_limits = parse_faction_limits(os.getenv("FACTION_LIMITS"))
    tariffs = parse_tariffs(os.getenv("TARIFFS"))
    tariff_message = load_text_content("tariffs", DEFAULT_TARIFF_MESSAGE)
    tariff_buttons, tariff_button_map = parse_tariff_buttons(
        os.getenv("TARIFF_BUTTONS"),
        tariffs,
    )
    map_image_path = os.getenv("MAP_IMAGE_PATH", "map.jpg").strip() or None
    game_start_at = os.getenv("GAME_START_AT", "").strip() or None
    admin_ids = parse_admin_ids(os.getenv("ADMIN_IDS"))
    faction_chat_links = parse_faction_chat_links(os.getenv("FACTION_CHAT_LINKS"))
    payment_link = os.getenv(
        "PAYMENT_LINK",
        "https://www.sberbank.com/sms/pbpn?requisiteNumber=79217300917",
    ).strip()

    if not token:
        raise RuntimeError("Environment variable TOKEN is required.")
    if not spreadsheet_name and not spreadsheet_id:
        raise RuntimeError(
            "Set GOOGLE_SHEETS_SPREADSHEET or GOOGLE_SHEETS_SPREADSHEET_ID."
        )
    if not credentials_json and not os.path.exists(credentials_file):
        raise RuntimeError(
            "Google credentials not found. Set GOOGLE_CREDENTIALS_JSON or place credentials.json near bot.py."
        )

    return Config(
        token=token,
        spreadsheet_name=spreadsheet_name,
        spreadsheet_id=spreadsheet_id,
        credentials_file=credentials_file,
        credentials_json=credentials_json,
        timezone_name=timezone_name,
        faction_limits=faction_limits,
        tariffs=tariffs,
        tariff_message=tariff_message,
        tariff_buttons=tariff_buttons,
        tariff_button_map=tariff_button_map,
        map_image_path=map_image_path,
        game_start_at=game_start_at,
        admin_ids=admin_ids,
        faction_chat_links=faction_chat_links,
        payment_link=payment_link,
    )


def parse_faction_limits(raw_value: str | None) -> Dict[str, int]:
    if not raw_value:
        return DEFAULT_FACTION_LIMITS.copy()
    return {name: int(value) for name, value in parse_key_value_pairs(raw_value).items()}


def parse_tariffs(raw_value: str | None) -> list[str]:
    if not raw_value:
        return DEFAULT_TARIFFS.copy()
    values = [value.strip() for value in raw_value.split(",") if value.strip()]
    if not values:
        raise RuntimeError("TARIFFS is empty after parsing.")
    return values


def parse_tariff_buttons(
    raw_value: str | None,
    tariffs: list[str],
) -> tuple[list[str], Dict[str, str]]:
    if raw_value:
        mapping = parse_key_value_pairs(raw_value)
        unknown = [value for value in mapping.values() if value not in tariffs]
        if unknown:
            raise RuntimeError(
                "TARIFF_BUTTONS содержит тарифы, которых нет в TARIFFS: "
                + ", ".join(sorted(set(unknown)))
            )
        return list(mapping.keys()), mapping

    buttons: list[str] = []
    mapping: Dict[str, str] = {}
    for tariff in tariffs:
        label = DEFAULT_TARIFF_LABELS.get(tariff, tariff)
        buttons.append(label)
        mapping[label] = tariff
    return buttons, mapping


def parse_faction_chat_links(raw_value: str | None) -> Dict[str, str]:
    if not raw_value:
        return DEFAULT_FACTION_CHAT_LINKS.copy()
    return parse_key_value_pairs(raw_value)


def parse_admin_ids(raw_value: str | None) -> set[int]:
    if not raw_value:
        return set()
    values = set()
    for chunk in raw_value.split(","):
        chunk = chunk.strip()
        if chunk:
            values.add(int(chunk))
    return values


def parse_key_value_pairs(raw_value: str | None) -> Dict[str, str]:
    if not raw_value:
        return {}

    parsed: Dict[str, str] = {}
    for item in raw_value.split(","):
        chunk = item.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise RuntimeError(f"Invalid key-value item: {chunk}")
        key, value = chunk.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def parse_game_start(raw_value: str | None, timezone_name: str) -> datetime | None:
    if not raw_value:
        return None

    timezone = ZoneInfo(timezone_name)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(raw_value, fmt).replace(tzinfo=timezone)
        except ValueError:
            continue

    raise RuntimeError(
        "GAME_START_AT must look like '2026-07-12 10:00' or '12.07.2026 10:00'."
    )


def resolve_local_path(raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def load_text_content(name: str, fallback: str) -> str:
    path = CONTENT_FILES[name]
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return fallback


def find_scenario_image_path(scenario_key: str) -> Path | None:
    for path in SCENARIO_IMAGE_CANDIDATES.get(scenario_key, []):
        if path.exists():
            return path
    return None


class RegistrationSheet:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.worksheet = self._open_worksheet()
        self.ensure_headers()

    def _open_worksheet(self):
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]

        if self.config.credentials_json:
            credentials_info = json.loads(self.config.credentials_json)
            credentials = Credentials.from_service_account_info(credentials_info, scopes=scopes)
        else:
            credentials = Credentials.from_service_account_file(
                self.config.credentials_file,
                scopes=scopes,
            )

        client = gspread.authorize(credentials)
        if self.config.spreadsheet_id:
            return client.open_by_key(self.config.spreadsheet_id).sheet1
        return client.open(self.config.spreadsheet_name).sheet1

    def ensure_headers(self) -> None:
        first_row = self.worksheet.row_values(1)
        if first_row[: len(SHEET_HEADERS)] != SHEET_HEADERS:
            self.worksheet.update(range_name="A1:J1", values=[SHEET_HEADERS])

    def all_records(self) -> list[dict]:
        return self.worksheet.get_all_records(expected_headers=SHEET_HEADERS)

    def next_player_id(self) -> str:
        values = self.worksheet.col_values(1)[1:]
        numeric_ids = [int(value) for value in values if value.isdigit()]
        next_value = (max(numeric_ids) + 1) if numeric_ids else 1
        return f"{next_value:03d}"

    def faction_counts(self) -> Dict[str, int]:
        counts = {faction: 0 for faction in self.config.faction_limits}
        for record in self.all_records():
            faction = str(record.get("Фракция", "")).strip()
            if faction in counts:
                counts[faction] += 1
        return counts

    def registered_chat_ids(self) -> list[int]:
        chat_ids = {
            int(str(record.get("Telegram ID", "")).strip())
            for record in self.all_records()
            if str(record.get("Telegram ID", "")).strip().isdigit()
        }
        return sorted(chat_ids)

    def append_player(self, player: Dict[str, str]) -> None:
        self.worksheet.append_row(
            [
                player["id"],
                player["name"],
                player["full_name"],
                player["phone"],
                player["faction"],
                player["tariff"],
                player["chat_id"],
                player["date"],
                player["payment_status"],
                player["payment_date"],
            ],
            value_input_option="USER_ENTERED",
        )

    def mark_paid(self, chat_id: int, paid_at: str) -> bool:
        chat_id_str = str(chat_id)
        rows = self.worksheet.get_all_values()
        for row_index in range(len(rows), 1, -1):
            row = rows[row_index - 1]
            if len(row) >= 7 and row[6].strip() == chat_id_str:
                self.worksheet.update(
                    range_name=f"I{row_index}:J{row_index}",
                    values=[["оплачено", paid_at]],
                )
                return True
        return False

    def player_by_chat_id(self, chat_id: int) -> dict | None:
        chat_id_str = str(chat_id)
        for record in reversed(self.all_records()):
            if str(record.get("Telegram ID", "")).strip() == chat_id_str:
                return record
        return None

    def latest_players(self, limit: int = 30) -> list[dict]:
        records = self.all_records()
        return records[-limit:]


def normalize_callsign(raw_value: str) -> str | None:
    value = raw_value.strip()
    if 2 <= len(value) <= 32:
        return value
    return None


def normalize_phone(raw_value: str) -> str | None:
    value = raw_value.strip()
    digits_only = re.sub(r"\D", "", value)
    if len(digits_only) < 7:
        return None
    return f"+{digits_only}" if value.startswith("+") else digits_only


def normalize_full_name(raw_value: str) -> str | None:
    value = re.sub(r"\s+", " ", raw_value).strip()
    if len(value.split()) < 2:
        return None
    if 4 <= len(value) <= 80:
        return value
    return None


def make_qr_bytes(player_id: str) -> io.BytesIO:
    image = qrcode.make(player_id)
    buffer = io.BytesIO()
    buffer.name = f"mad-day-{player_id}.png"
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def make_qr_from_text(value: str, filename: str) -> io.BytesIO:
    image = qrcode.make(value)
    buffer = io.BytesIO()
    buffer.name = filename
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def load_photo_buffer(path: Path) -> io.BytesIO:
    data = path.read_bytes()
    buffer = io.BytesIO(data)
    buffer.name = path.name
    buffer.seek(0)
    return buffer


def build_keyboard(items: list[str], row_size: int = 1) -> ReplyKeyboardMarkup:
    rows = [items[index : index + row_size] for index in range(0, len(items), row_size)]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


def progress_bar(current: int, limit: int, width: int = 10) -> str:
    if limit <= 0:
        return "░" * width
    filled = min(width, round((current / limit) * width))
    return ("█" * filled) + ("░" * (width - filled))


def format_passport(player: dict) -> str:
    payment_status_raw = str(player.get("payment_status", "")).strip().lower()
    payment_status = "оплачено" if payment_status_raw == "оплачено" else "не оплачено"
    return "\n".join(
        [
            "☢ ПАСПОРТ БОЙЦА",
            "",
            f"ID: {player['id']}",
            f"Позывной: {player['name']}",
            f"Фамилия имя: {player['full_name']}",
            f"Фракция: {player['faction']}",
            f"Тариф: {player['tariff']}",
            f"Статус оплаты: {payment_status}",
            "",
            "Статус: зарегистрирован",
        ]
    )


def format_countdown(target: datetime, timezone_name: str) -> str:
    now = datetime.now(ZoneInfo(timezone_name))
    delta = target - now
    if delta.total_seconds() <= 0:
        return "MAD DAY уже начался."

    total_hours = int(delta.total_seconds() // 3600)
    days = total_hours // 24
    hours = total_hours % 24

    return "\n".join(
        [
            "До начала MAD DAY осталось",
            "",
            f"{days} дн.",
            f"{hours} ч.",
        ]
    )


def format_start_message() -> str:
    return (
        "☢ СЕТЬ ПУСТОШИ АКТИВНА\n\n"
        "Ты подключился к вербовочному терминалу\n"
        "операции MAD DAY.\n\n"
        "После энергетического коллапса мир изменился.\n"
        "Топливо стало новой валютой,\n"
        "а работающий двигатель — символом власти.\n\n"
        "Две силы борются за контроль\n"
        "над последними нефтяными ресурсами:\n\n"
        "🔵 КОРПУС СТАЛИ\n"
        "Видят в Пустоши территорию хаоса, которую нужно взять под жесткий военный контроль. "
        "Нефть для них — топливо для бронетехники и залог доминирования.\n\n"
        "🔴 НОВЫЙ ШТАТ\n"
        "Верят в правила, бюрократию и прогресс. "
        "Нефть для них — фундамент для восстановления городов.\n\n"
        "Через этот терминал ты можешь:\n\n"
        "⚔ зарегистрироваться на игру\n"
        "🗺 получить карту полигона\n"
        "📋 узнать расписание операций\n"
        "📻 слушать Радио Пустоши\n\n"
        "Готов присоединиться к войне?\n\n"
        "Нажми кнопку ниже, чтобы начать регистрацию."
    )


def format_faction_message() -> str:
    return (
        "☢ ВЕРБОВОЧНЫЙ ТЕРМИНАЛ\n\n"
        "Перед выходом в Пустошь\n"
        "ты должен выбрать сторону конфликта.\n\n"
        "⚠ Решение определит твоих союзников\n"
        "и врагов на поле боя.\n\n"
        "Доступные фракции:\n\n"
        "🔵 КОРПУС СТАЛИ\n\n"
        "Последняя дисциплинированная армия Пустоши.\n\n"
        "Они сохраняют остатки технологий\n"
        "и верят, что порядок можно восстановить.\n\n"
        "Их техника работает.\n"
        "Их строй железный.\n\n"
        "🔴 НОВЫЙ ШТАТ\n\n"
        "Коалиция рейдерских кланов,\n"
        "захватившая нефтяные дороги.\n\n"
        "Их правило простое:\n\n"
        "Кто контролирует топливо —\n"
        "контролирует будущее."
    )


def build_main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [MENU_PROFILE],
            [MENU_MAP, MENU_SCHEDULE],
            [MENU_RADIO, MENU_LORE],
            [MENU_INFO, MENU_BRIEFING],
            [MENU_FACTION_CHAT, MENU_STATS],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выбери действие терминала",
    )


def build_faction_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔵 Вступить в Корпус Стали",
                    callback_data=f"{FACTION_CALLBACK_PREFIX}steel",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔴 Вступить в Новый Штат",
                    callback_data=f"{FACTION_CALLBACK_PREFIX}state",
                )
            ],
        ]
    )


async def send_main_menu(message_target) -> None:
    await message_target.reply_text(
        "☢ ТЕРМИНАЛ ПУСТОШИ\n\n"
        "Ты подключён к системе операции MAD DAY.\n\n"
        "Доступные функции терминала:",
        reply_markup=build_main_menu(),
    )


async def send_payment_info(message_target, config: Config) -> None:
    text = load_text_content(
        "payment",
        "ℹ ОПЛАТА УЧАСТИЯ\n\n"
        "Перевод участия:\n"
        "https://www.sberbank.com/sms/pbpn?requisiteNumber=79217300917\n\n"
        "Если оплатил, нажми кнопку ✅ Оплатил.",
    )
    qr_image = await asyncio.to_thread(
        make_qr_from_text,
        config.payment_link,
        "mad-day-payment.png",
    )
    await message_target.reply_text(text)
    await message_target.reply_photo(
        photo=qr_image,
        caption=f"Ссылка для перевода:\n{config.payment_link}",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("✅ Оплатил", callback_data=PAYMENT_CONFIRMED_CALLBACK)]]
        ),
    )


def format_registration_result(player: dict) -> str:
    return "\n".join(
        [
            "☢ БОЕЦ ЗАРЕГИСТРИРОВАН",
            "",
            f"Фамилия имя: {player['full_name']}",
            f"Позывной: {player['name']}",
            f"Фракция: {player['faction']}",
            "",
            "Твой профиль внесён",
            "в реестр бойцов операции MAD DAY.",
            "",
            "Тебе присвоен идентификационный номер:",
            "",
            f"ID: {player['id']}",
            "",
            "Этот ID будет использоваться",
            "для регистрации на полигоне.",
        ]
    )


def format_admin_registration_notice(player: dict, source: str) -> str:
    source_label = "Telegram-бот" if source == "telegram" else "Веб-форма"
    return "\n".join(
        [
            "🆕 Новая регистрация",
            "",
            f"Источник: {source_label}",
            f"ID: {player['id']}",
            f"Позывной: {player['name']}",
            f"Имя: {player['full_name']}",
            f"Телефон: {player['phone']}",
            f"Фракция: {player['faction']}",
            f"Тариф: {player['tariff']}",
        ]
    )


def format_admin_payment_notice(player: dict, source: str, paid_at: str) -> str:
    source_label = "Telegram-бот" if source == "telegram" else "Веб-форма"
    return "\n".join(
        [
            "💸 Оплата отмечена",
            "",
            f"Источник: {source_label}",
            f"ID: {player['id']}",
            f"Позывной: {player['name']}",
            f"Имя: {player['full_name']}",
            f"Фракция: {player['faction']}",
            f"Тариф: {player['tariff']}",
            f"Время оплаты: {paid_at}",
        ]
    )


async def notify_admins(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    config = get_config(context)
    if not config.admin_ids:
        return

    for admin_id in sorted(config.admin_ids):
        try:
            await context.bot.send_message(chat_id=admin_id, text=text)
        except Exception as exc:
            logger.warning("Failed to send admin notification to %s: %s", admin_id, exc)


def parse_radio_messages() -> list[str]:
    raw = load_text_content(
        "radio",
        "Радиоперехват...\n\nКомандование вызывает тебя.\nПроверь снаряжение перед выходом.",
    )
    parts = [part.strip() for part in raw.split("\n\n---\n\n") if part.strip()]
    return parts or [raw]


def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    config = get_config(context)
    user = update.effective_user
    return bool(user and user.id in config.admin_ids)


async def require_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if is_admin(update, context):
        return True
    await update.message.reply_text("Эта команда доступна только организатору.")
    return False


def get_sheet(context: ContextTypes.DEFAULT_TYPE) -> RegistrationSheet:
    return context.application.bot_data["sheet"]


def get_config(context: ContextTypes.DEFAULT_TYPE) -> Config:
    return context.application.bot_data["config"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not context.application.bot_data.get("registration_open", True):
        await update.message.reply_text("Регистрация сейчас закрыта.")
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(
        format_start_message(),
        reply_markup=build_keyboard([START_REGISTRATION_BUTTON]),
    )
    return INTRO


async def begin_registration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message.text.strip() != START_REGISTRATION_BUTTON:
        await update.message.reply_text(
            "Нажми кнопку ниже, чтобы начать регистрацию.",
            reply_markup=build_keyboard([START_REGISTRATION_BUTTON]),
        )
        return INTRO

    await update.message.reply_text(
        "Введи позывной бойца:",
        reply_markup=ReplyKeyboardRemove(),
    )
    return CALLSIGN


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text(
        "Регистрация отменена. Если захочешь начать заново, напиши /start.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def get_callsign(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    callsign = normalize_callsign(update.message.text)
    if not callsign:
        await update.message.reply_text(
            "Позывной должен быть длиной от 2 до 32 символов. Попробуй ещё раз."
        )
        return CALLSIGN

    context.user_data["name"] = callsign
    phone_keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("Поделиться телефоном", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.message.reply_text(
        "Отправь телефон. Можно кнопкой ниже или обычным сообщением.",
        reply_markup=phone_keyboard,
    )
    return PHONE


async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw_phone = update.message.contact.phone_number if update.message.contact else update.message.text
    phone = normalize_phone(raw_phone)
    if not phone:
        await update.message.reply_text("Не удалось распознать телефон. Отправь номер ещё раз.")
        return PHONE

    context.user_data["phone"] = phone
    await update.message.reply_text(
        format_faction_message(),
        reply_markup=build_faction_inline_keyboard(),
    )
    return FACTION


async def continue_after_faction_choice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    faction: str,
) -> int:
    config = get_config(context)
    if faction not in config.faction_limits:
        await update.message.reply_text("Выбери фракцию кнопкой из списка.")
        return FACTION

    sheet = get_sheet(context)
    counts = await asyncio.to_thread(sheet.faction_counts)
    if counts.get(faction, 0) >= config.faction_limits[faction]:
        await update.message.reply_text(f"⚠ Фракция {faction} уже заполнена. Выбери другую.")
        return FACTION

    context.user_data["faction"] = faction
    target_message = update.callback_query.message if update.callback_query else update.message
    await target_message.reply_text(
        "Введи фамилию и имя бойца. Пример: Иванов Иван",
        reply_markup=ReplyKeyboardRemove(),
    )
    return FULL_NAME


async def get_faction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    faction_label = update.message.text.strip()
    normalized_map = {
        **FACTION_BUTTONS,
        "1": "🔵 Корпус Стали",
        "2": "🔴 Новый Штат",
        "корпус стали": "🔵 Корпус Стали",
        "новый штат": "🔴 Новый Штат",
        "🔵 корпус стали": "🔵 Корпус Стали",
        "🔴 новый штат": "🔴 Новый Штат",
    }
    faction = normalized_map.get(faction_label.lower(), FACTION_BUTTONS.get(faction_label, faction_label))
    return await continue_after_faction_choice(update, context, faction)


async def get_faction_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    callback_map = {
        f"{FACTION_CALLBACK_PREFIX}steel": "🔵 Корпус Стали",
        f"{FACTION_CALLBACK_PREFIX}state": "🔴 Новый Штат",
    }
    faction = callback_map.get(query.data)
    if not faction:
        await query.message.reply_text("Выбор фракции не распознан. Попробуй ещё раз.")
        return FACTION
    return await continue_after_faction_choice(update, context, faction)


async def get_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    full_name = normalize_full_name(update.message.text)
    if not full_name:
        await update.message.reply_text(
            "Нужно указать фамилию и имя через пробел. Пример: Иванов Иван"
        )
        return FULL_NAME

    context.user_data["full_name"] = full_name
    config = get_config(context)
    await update.message.reply_text(
        f"Выбери тариф:\n\n{config.tariff_message}",
        reply_markup=build_keyboard(config.tariff_buttons, row_size=1),
    )
    return TARIFF


async def get_tariff(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    tariff_choice = update.message.text.strip()
    config = get_config(context)
    tariff = config.tariff_button_map.get(tariff_choice, tariff_choice)
    if tariff not in config.tariffs:
        await update.message.reply_text("Выбери тариф кнопкой из списка.")
        return TARIFF

    sheet = get_sheet(context)
    timezone = ZoneInfo(config.timezone_name)
    player_id = await asyncio.to_thread(sheet.next_player_id)
    player = {
        "id": player_id,
        "name": context.user_data["name"],
        "full_name": context.user_data["full_name"],
        "phone": context.user_data["phone"],
        "faction": context.user_data["faction"],
        "tariff": tariff,
        "chat_id": str(update.effective_chat.id),
        "date": datetime.now(timezone).strftime("%d.%m.%Y %H:%M"),
        "payment_status": "не оплачено",
        "payment_date": "",
    }

    await asyncio.to_thread(sheet.append_player, player)
    await notify_admins(context, format_admin_registration_notice(player, "telegram"))
    qr_image = await asyncio.to_thread(make_qr_bytes, player_id)

    await update.message.reply_text(
        format_registration_result(player),
        reply_markup=ReplyKeyboardRemove(),
    )
    await update.message.reply_photo(photo=qr_image, caption="QR-код бойца")
    await update.message.reply_text(
        "⚠ Сохрани этот QR код.\n\n"
        "Он понадобится для быстрого чек-ина\n"
        "перед началом игры."
    )
    await send_payment_info(update.message, config)
    await send_main_menu(update.message)
    context.user_data.clear()
    return ConversationHandler.END


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sheet = get_sheet(context)
    config = get_config(context)
    counts = await asyncio.to_thread(sheet.faction_counts)

    lines = ["⚔ Баланс сил", ""]
    for faction, limit in config.faction_limits.items():
        current = counts.get(faction, 0)
        lines.append(f"{faction}")
        lines.append(f"{progress_bar(current, limit)} {current}/{limit}")
        lines.append("")
    await update.message.reply_text("\n".join(lines).strip(), reply_markup=build_main_menu())


async def lore(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = load_text_content(
        "lore",
        "После энергетического коллапса нефть стала единственной валютой.",
    )
    await update.message.reply_text(text, reply_markup=build_main_menu())


async def schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = load_text_content(
        "schedule",
        "MAD DAY\n\n10:00 — регистрация\n11:00 — сценарий 1\n13:00 — сценарий 2\n15:00 — финальная битва",
    )
    await update.message.reply_text(text, reply_markup=build_main_menu())


async def send_map(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scenario_maps = [
        ("scenario1", "🗺 Эпизод 1"),
        ("scenario2", "🗺 Эпизод 2"),
        ("scenario3", "🗺 Эпизод 3"),
    ]
    available_maps: list[tuple[str, str, Path]] = []
    for scenario_key, title in scenario_maps:
        image_path = find_scenario_image_path(scenario_key)
        if image_path:
            available_maps.append((scenario_key, title, image_path))

    if available_maps:
        await update.message.reply_text(
            "🗺 Карты полигона по миссиям:",
            reply_markup=build_main_menu(),
        )
        for scenario_key, title, image_path in available_maps:
            scenario_text = load_text_content(
                scenario_key,
                "Описание сценария пока не заполнено.",
            )
            scenario_title = scenario_text.splitlines()[0].strip() if scenario_text else title
            caption = f"{title}\n{scenario_title}"
            sent = False
            for _ in range(3):
                try:
                    photo_buffer = await asyncio.to_thread(load_photo_buffer, image_path)
                    await update.message.reply_photo(
                        photo=photo_buffer,
                        caption=caption,
                        reply_markup=build_main_menu(),
                    )
                    sent = True
                    break
                except (OSError, TimeoutError) as exc:
                    logger.warning("Failed to read/send map %s: %s", image_path, exc)
                    await asyncio.sleep(0.5)
            if not sent:
                await update.message.reply_text(
                    f"⚠ Не удалось отправить карту: {title}. Попробуй команду /map еще раз.",
                    reply_markup=build_main_menu(),
                )
            else:
                # Tiny pacing helps avoid network/API hiccups when sending 3 images in a row.
                await asyncio.sleep(0.25)
        return

    config = get_config(context)
    map_text = load_text_content(
        "map",
        "Карта полигона скоро появится здесь. Добавь изображения сценариев в content/scenario1.jpg, scenario2.jpg, scenario3.jpg.",
    )
    map_path = resolve_local_path(config.map_image_path)
    if map_path and map_path.exists():
        for _ in range(3):
            try:
                photo_buffer = await asyncio.to_thread(load_photo_buffer, map_path)
                await update.message.reply_photo(
                    photo=photo_buffer,
                    caption=map_text,
                    reply_markup=build_main_menu(),
                )
                return
            except (OSError, TimeoutError) as exc:
                logger.warning("Failed to read/send common map %s: %s", map_path, exc)
                await asyncio.sleep(0.5)

    await update.message.reply_text(map_text, reply_markup=build_main_menu())


async def send_scenario(update: Update, context: ContextTypes.DEFAULT_TYPE, scenario_key: str) -> None:
    text = load_text_content(
        scenario_key,
        "Сценарий пока не заполнен.\nОткрой файл в папке content и замени текст на боевую версию.",
    )
    image_path = find_scenario_image_path(scenario_key)
    if image_path:
        for _ in range(3):
            try:
                photo_buffer = await asyncio.to_thread(load_photo_buffer, image_path)
                await update.message.reply_photo(
                    photo=photo_buffer,
                    caption=text,
                    reply_markup=build_main_menu(),
                )
                return
            except (OSError, TimeoutError) as exc:
                logger.warning("Failed to read/send scenario image %s: %s", image_path, exc)
                await asyncio.sleep(0.5)
        await update.message.reply_text(
            "⚠ Картинку сценария не удалось отправить, показываю текст.",
            reply_markup=build_main_menu(),
        )

    await update.message.reply_text(text, reply_markup=build_main_menu())


async def scenario1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_scenario(update, context, "scenario1")


async def scenario2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_scenario(update, context, "scenario2")


async def scenario3(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_scenario(update, context, "scenario3")


async def briefing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sheet = get_sheet(context)
    config = get_config(context)
    player = await asyncio.to_thread(sheet.player_by_chat_id, update.effective_chat.id)

    if not player:
        await update.message.reply_text(
            "Сначала зарегистрируйся через /start, чтобы получить брифинг.",
            reply_markup=build_main_menu(),
        )
        return

    faction = str(player.get("Фракция", "")).strip()
    briefing_key = "briefing_steel" if "Корпус" in faction else "briefing_state"
    briefing_text = load_text_content(
        briefing_key,
        "Брифинг пока не заполнен.",
    )
    chat_link = config.faction_chat_links.get(faction)
    reply_markup = None
    if chat_link:
        reply_markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("ЧАТ ФРАКЦИИ", url=chat_link)]]
        )

    if reply_markup:
        await update.message.reply_text(briefing_text, reply_markup=reply_markup)
        await send_main_menu(update.message)
        return
    await update.message.reply_text(briefing_text, reply_markup=build_main_menu())


async def faction_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sheet = get_sheet(context)
    config = get_config(context)
    player = await asyncio.to_thread(sheet.player_by_chat_id, update.effective_chat.id)

    if not player:
        await update.message.reply_text(
            "Сначала зарегистрируйся через /start, чтобы получить доступ к чату фракции.",
            reply_markup=build_main_menu(),
        )
        return

    faction = str(player.get("Фракция", "")).strip()
    if not faction:
        await update.message.reply_text(
            "Не удалось определить фракцию. Обратись к организатору.",
            reply_markup=build_main_menu(),
        )
        return

    chat_link = config.faction_chat_links.get(faction)
    if not chat_link:
        await update.message.reply_text(
            "Чат этой фракции ещё не настроен.",
            reply_markup=build_main_menu(),
        )
        return

    reply_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("ЧАТ ФРАКЦИИ", url=chat_link)]]
    )
    await update.message.reply_text(
        "Вот чат твоей фракции:",
        reply_markup=reply_markup,
    )
    await send_main_menu(update.message)


async def countdown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = get_config(context)
    game_start = parse_game_start(config.game_start_at, config.timezone_name)
    if not game_start:
        await update.message.reply_text(
            "Дата старта игры ещё не настроена.",
            reply_markup=build_main_menu(),
        )
        return

    await update.message.reply_text(
        format_countdown(game_start, config.timezone_name),
        reply_markup=build_main_menu(),
    )


async def me(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sheet = get_sheet(context)
    player = await asyncio.to_thread(sheet.player_by_chat_id, update.effective_chat.id)

    if not player:
        await update.message.reply_text(
            "Ты ещё не зарегистрирован. Начни через /start.",
            reply_markup=build_main_menu(),
        )
        return

    normalized = {
        "id": str(player.get("ID", "")).strip(),
        "name": str(player.get("Позывной", "")).strip(),
        "full_name": str(player.get("Фамилия Имя", "")).strip(),
        "faction": str(player.get("Фракция", "")).strip(),
        "tariff": str(player.get("Тариф", "")).strip(),
        "payment_status": str(player.get("Оплата", "")).strip(),
    }
    await update.message.reply_text(format_passport(normalized), reply_markup=build_main_menu())
    qr_image = await asyncio.to_thread(make_qr_bytes, normalized["id"])
    await update.message.reply_photo(
        photo=qr_image,
        caption=f"QR-код бойца {normalized['id']}",
        reply_markup=build_main_menu(),
    )


async def radio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    messages = parse_radio_messages()
    await update.message.reply_text(random.choice(messages), reply_markup=build_main_menu())


async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = load_text_content(
        "info",
        "ℹ ИНФОРМАЦИЯ ОБ ИГРЕ\n\nMAD DAY 5.0",
    )
    await update.message.reply_text(text, reply_markup=build_main_menu())


async def payment_confirmed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    sheet = get_sheet(context)
    config = get_config(context)
    player = await asyncio.to_thread(sheet.player_by_chat_id, query.from_user.id)
    if not player:
        await query.message.reply_text(
            "Сначала зарегистрируйся через /start, затем подтверди оплату.",
            reply_markup=build_main_menu(),
        )
        return

    if str(player.get("Оплата", "")).strip().lower() == "оплачено":
        await query.message.reply_text(
            "Оплата уже отмечена. Увидимся на полигоне.",
            reply_markup=build_main_menu(),
        )
        return

    paid_at = datetime.now(ZoneInfo(config.timezone_name)).strftime("%d.%m.%Y %H:%M")
    updated = await asyncio.to_thread(sheet.mark_paid, query.from_user.id, paid_at)
    if not updated:
        await query.message.reply_text(
            "Не удалось обновить оплату в реестре. Попробуй ещё раз позже.",
            reply_markup=build_main_menu(),
        )
        return

    await query.message.reply_text(
        "✅ Оплата отмечена.\n\n"
        "Статус бойца обновлён в реестре MAD DAY.",
        reply_markup=build_main_menu(),
    )
    await notify_admins(
        context,
        format_admin_payment_notice(
            {
                "id": str(player.get("ID", "")).strip(),
                "name": str(player.get("Позывной", "")).strip(),
                "full_name": str(player.get("Фамилия Имя", "")).strip(),
                "phone": str(player.get("Телефон", "")).strip(),
                "faction": str(player.get("Фракция", "")).strip(),
                "tariff": str(player.get("Тариф", "")).strip(),
            },
            "telegram",
            paid_at,
        ),
    )


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_main_menu(update.message)


async def players(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_admin(update, context):
        return

    sheet = get_sheet(context)
    records = await asyncio.to_thread(sheet.latest_players, 30)
    if not records:
        await update.message.reply_text("Список игроков пока пуст.", reply_markup=build_main_menu())
        return

    lines = ["Игроки:"]
    for record in records:
        lines.append(
            f"{record.get('ID')} | {record.get('Позывной')} | {record.get('Фракция')} | {record.get('Тариф')}"
        )
    await update.message.reply_text("\n".join(lines), reply_markup=build_main_menu())


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_admin(update, context):
        return

    message = " ".join(context.args).strip()
    if not message:
        await update.message.reply_text(
            "Использование: /broadcast текст сообщения",
            reply_markup=build_main_menu(),
        )
        return

    sheet = get_sheet(context)
    chat_ids = await asyncio.to_thread(sheet.registered_chat_ids)
    success_count = 0

    for chat_id in chat_ids:
        try:
            await context.bot.send_message(chat_id=chat_id, text=message)
            success_count += 1
        except Exception as exc:
            logger.warning("Broadcast failed for chat_id=%s: %s", chat_id, exc)

    await update.message.reply_text(
        f"Рассылка завершена. Доставлено: {success_count}",
        reply_markup=build_main_menu(),
    )


def make_players_export_csv(records: list[dict]) -> io.BytesIO:
    text_buffer = io.StringIO()
    writer = csv.DictWriter(text_buffer, fieldnames=SHEET_HEADERS)
    writer.writeheader()
    for record in records:
        writer.writerow({header: str(record.get(header, "")).strip() for header in SHEET_HEADERS})

    bytes_buffer = io.BytesIO(text_buffer.getvalue().encode("utf-8-sig"))
    bytes_buffer.seek(0)
    return bytes_buffer


async def export_players(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_admin(update, context):
        return

    sheet = get_sheet(context)
    config = get_config(context)
    records = await asyncio.to_thread(sheet.all_records)
    export_file = await asyncio.to_thread(make_players_export_csv, records)
    export_file.name = (
        f"mad-day-players-{datetime.now(ZoneInfo(config.timezone_name)).strftime('%Y%m%d-%H%M')}.csv"
    )

    await update.message.reply_document(
        document=export_file,
        caption=f"Выгрузка реестра: {len(records)} игроков",
        reply_markup=build_main_menu(),
    )


async def close_registration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_admin(update, context):
        return
    context.application.bot_data["registration_open"] = False
    await update.message.reply_text("Регистрация закрыта.", reply_markup=build_main_menu())


async def open_registration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_admin(update, context):
        return
    context.application.bot_data["registration_open"] = True
    await update.message.reply_text("Регистрация снова открыта.", reply_markup=build_main_menu())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Команды:\n"
        "/start - начать регистрацию\n"
        "/menu - открыть терминал\n"
        "/me - мой паспорт бойца\n"
        "/stats - баланс фракций\n"
        "/lore - лор мира\n"
        "/map - карта полигона\n"
        "/schedule - расписание игры\n"
        "/radio - радио пустоши\n"
        "/info - информация об игре\n"
        "/briefing - брифинг фракции\n"
        "/scenario1 - сценарий 1\n"
        "/scenario2 - сценарий 2\n"
        "/scenario3 - сценарий 3\n"
        "/countdown - таймер до игры\n"
        "/cancel - отменить регистрацию\n"
        "\nОрганизатор:\n"
        "/players\n"
        "/broadcast текст\n"
        "/export\n"
        "/close_registration\n"
        "/open_registration",
        reply_markup=build_main_menu(),
    )


def format_game_reminder(reminder_label: str) -> str:
    return f"⚠ ВНИМАНИЕ\n\nДо MAD DAY осталось {reminder_label}"


async def run_game_reminder(
    application: Application,
    delay_seconds: float,
    reminder_label: str,
) -> None:
    await asyncio.sleep(delay_seconds)
    sheet: RegistrationSheet = application.bot_data["sheet"]
    chat_ids = await asyncio.to_thread(sheet.registered_chat_ids)

    if not chat_ids:
        logger.info("Reminder %s skipped: no registered chat IDs found.", reminder_label)
        return

    for chat_id in chat_ids:
        try:
            await application.bot.send_message(
                chat_id=chat_id,
                text=format_game_reminder(reminder_label),
            )
        except Exception as exc:
            logger.warning(
                "Failed to send reminder (%s) to chat_id=%s: %s",
                reminder_label,
                chat_id,
                exc,
            )

    logger.info("Game reminder (%s) sent to %s players", reminder_label, len(chat_ids))


async def post_init(application: Application) -> None:
    config: Config = application.bot_data["config"]
    game_start = parse_game_start(config.game_start_at, config.timezone_name)
    if not game_start:
        logger.info("GAME_START_AT is not set. Automatic reminder is disabled.")
        return

    now = datetime.now(ZoneInfo(config.timezone_name))
    reminder_tasks: list[asyncio.Task] = []

    for reminder_offset, reminder_label in GAME_REMINDER_PLAN:
        reminder_at = game_start - reminder_offset
        if reminder_at <= now:
            logger.info(
                "Reminder %s skipped: time %s already passed.",
                reminder_label,
                reminder_at.strftime("%d.%m.%Y %H:%M"),
            )
            continue

        delay_seconds = (reminder_at - now).total_seconds()
        reminder_task = asyncio.create_task(
            run_game_reminder(
                application=application,
                delay_seconds=delay_seconds,
                reminder_label=reminder_label,
            )
        )
        reminder_tasks.append(reminder_task)
        logger.info(
            "Game reminder (%s) scheduled for %s",
            reminder_label,
            reminder_at.strftime("%d.%m.%Y %H:%M"),
        )

    application.bot_data["reminder_tasks"] = reminder_tasks
    if not reminder_tasks:
        logger.info("All reminder times are already in the past. No reminder tasks were scheduled.")


async def post_shutdown(application: Application) -> None:
    reminder_tasks: list[asyncio.Task] = application.bot_data.get("reminder_tasks", [])
    for reminder_task in reminder_tasks:
        if reminder_task.done():
            continue
        reminder_task.cancel()
        try:
            await reminder_task
        except asyncio.CancelledError:
            logger.info("Reminder task cancelled.")


def build_application(config: Config) -> Application:
    sheet = RegistrationSheet(config)
    application = (
        Application.builder()
        .token(config.token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.bot_data["config"] = config
    application.bot_data["sheet"] = sheet
    application.bot_data["registration_open"] = True

    registration = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            INTRO: [MessageHandler(filters.TEXT & ~filters.COMMAND, begin_registration)],
            CALLSIGN: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_callsign)],
            PHONE: [MessageHandler((filters.CONTACT | filters.TEXT) & ~filters.COMMAND, get_phone)],
            FACTION: [
                CallbackQueryHandler(get_faction_callback, pattern=f"^{FACTION_CALLBACK_PREFIX}"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_faction),
            ],
            FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_full_name)],
            TARIFF: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_tariff)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    application.add_handler(registration)
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CommandHandler("me", me))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("lore", lore))
    application.add_handler(CommandHandler("map", send_map))
    application.add_handler(CommandHandler("schedule", schedule))
    application.add_handler(CommandHandler("radio", radio))
    application.add_handler(CommandHandler("info", info))
    application.add_handler(CallbackQueryHandler(payment_confirmed, pattern=f"^{PAYMENT_CONFIRMED_CALLBACK}$"))
    application.add_handler(CommandHandler("briefing", briefing))
    application.add_handler(CommandHandler("scenario1", scenario1))
    application.add_handler(CommandHandler("scenario2", scenario2))
    application.add_handler(CommandHandler("scenario3", scenario3))
    application.add_handler(CommandHandler("countdown", countdown))
    application.add_handler(CommandHandler("players", players))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("export", export_players))
    application.add_handler(CommandHandler("close_registration", close_registration))
    application.add_handler(CommandHandler("open_registration", open_registration))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_menu_buttons,
        )
    )
    return application


async def handle_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    if text == MENU_PROFILE:
        await me(update, context)
    elif text == MENU_REGISTER:
        await start(update, context)
    elif text == MENU_MAP:
        await send_map(update, context)
    elif text == MENU_SCHEDULE:
        await schedule(update, context)
    elif text == MENU_RADIO:
        await radio(update, context)
    elif text == MENU_LORE:
        await lore(update, context)
    elif text == MENU_INFO:
        await info(update, context)
    elif text == MENU_BRIEFING:
        await briefing(update, context)
    elif text == MENU_FACTION_CHAT:
        await faction_chat(update, context)
    elif text == MENU_STATS:
        await stats(update, context)


def main() -> None:
    config = load_config()
    application = build_application(config)
    logger.info("MAD DAY bot started")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
