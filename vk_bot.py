from __future__ import annotations

import io
import logging
import os
import random
import tempfile
from dataclasses import dataclass
from datetime import datetime
from typing import Dict
from zoneinfo import ZoneInfo

import vk_api
from dotenv import load_dotenv
from vk_api.bot_longpoll import VkBotEventType, VkBotLongPoll
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.upload import VkUpload

from bot import (
    DEFAULT_FACTION_LIMITS,
    DEFAULT_TARIFF_MESSAGE,
    DEFAULT_TARIFFS,
    RegistrationSheet,
    find_scenario_image_path,
    format_countdown,
    format_passport,
    format_registration_result,
    format_start_message,
    load_text_content,
    make_qr_bytes,
    make_qr_from_text,
    normalize_callsign,
    normalize_full_name,
    normalize_phone,
    parse_faction_chat_links,
    parse_faction_limits,
    parse_game_start,
    parse_tariff_buttons,
    parse_tariffs,
    progress_bar,
)


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("vk_bot")


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
START_REGISTRATION_BUTTON = "⚔ Начать регистрацию"
PAYMENT_BUTTON = "✅ Оплатил"
CANCEL_BUTTON = "Отмена"
INTRO_ALIASES = {
    "/start",
    "start",
    "старт",
    "начать",
    "начать регистрацию",
    MENU_REGISTER.lower(),
}
REGISTRATION_TRIGGER_ALIASES = {
    START_REGISTRATION_BUTTON.lower(),
}

SESSION_CALLSIGN = "callsign"
SESSION_PHONE = "phone"
SESSION_FACTION = "faction"
SESSION_FULL_NAME = "full_name"
SESSION_TARIFF = "tariff"


@dataclass
class VkConfig:
    vk_token: str
    vk_group_id: int
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
    game_start_at: str | None
    faction_chat_links: Dict[str, str]
    payment_link: str


def load_vk_config() -> VkConfig:
    load_dotenv()
    vk_token = os.getenv("VK_TOKEN", "").strip()
    vk_group_id_raw = os.getenv("VK_GROUP_ID", "").strip()
    if not vk_token:
        raise RuntimeError("Environment variable VK_TOKEN is required.")
    if not vk_group_id_raw.isdigit():
        raise RuntimeError("VK_GROUP_ID must be numeric.")

    spreadsheet_name = os.getenv("GOOGLE_SHEETS_SPREADSHEET", "MAD DAY REGISTRATION").strip()
    spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "").strip() or None
    credentials_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json").strip()
    credentials_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    timezone_name = os.getenv("REGISTRATION_TIMEZONE", "Europe/Moscow").strip()
    faction_limits = parse_faction_limits(os.getenv("FACTION_LIMITS"))
    tariffs = parse_tariffs(os.getenv("TARIFFS")) or DEFAULT_TARIFFS.copy()
    tariff_message = load_text_content("tariffs", DEFAULT_TARIFF_MESSAGE)
    tariff_buttons, tariff_button_map = parse_tariff_buttons(
        os.getenv("TARIFF_BUTTONS"),
        tariffs,
    )
    game_start_at = os.getenv("GAME_START_AT", "").strip() or None
    faction_chat_links = parse_faction_chat_links(os.getenv("FACTION_CHAT_LINKS"))
    payment_link = os.getenv(
        "PAYMENT_LINK",
        "https://www.sberbank.com/sms/pbpn?requisiteNumber=79217300917",
    ).strip()

    if not spreadsheet_name and not spreadsheet_id:
        raise RuntimeError(
            "Set GOOGLE_SHEETS_SPREADSHEET or GOOGLE_SHEETS_SPREADSHEET_ID."
        )
    if not credentials_json and not os.path.exists(credentials_file):
        raise RuntimeError(
            "Google credentials not found. Set GOOGLE_CREDENTIALS_JSON or place credentials.json near bot.py."
        )

    return VkConfig(
        vk_token=vk_token,
        vk_group_id=int(vk_group_id_raw),
        spreadsheet_name=spreadsheet_name,
        spreadsheet_id=spreadsheet_id,
        credentials_file=credentials_file,
        credentials_json=credentials_json,
        timezone_name=timezone_name,
        faction_limits=faction_limits or DEFAULT_FACTION_LIMITS.copy(),
        tariffs=tariffs,
        tariff_message=tariff_message,
        tariff_buttons=tariff_buttons,
        tariff_button_map=tariff_button_map,
        game_start_at=game_start_at,
        faction_chat_links=faction_chat_links,
        payment_link=payment_link,
    )


def build_keyboard(rows: list[list[str]], one_time: bool = False) -> VkKeyboard:
    keyboard = VkKeyboard(one_time=one_time, inline=False)
    for row_index, row in enumerate(rows):
        for label in row:
            keyboard.add_button(label, color=VkKeyboardColor.PRIMARY)
        if row_index != len(rows) - 1:
            keyboard.add_line()
    return keyboard


def build_main_menu(is_registered: bool, payment_pending: bool = False) -> VkKeyboard:
    rows = [
        [MENU_PROFILE],
        [MENU_MAP, MENU_SCHEDULE],
        [MENU_RADIO, MENU_LORE],
        [MENU_INFO, MENU_BRIEFING],
        [MENU_STATS],
    ]
    if is_registered:
        rows.insert(4, [MENU_FACTION_CHAT])
        if payment_pending:
            rows.append([PAYMENT_BUTTON])
    if not is_registered:
        rows.insert(0, [MENU_REGISTER])
    return build_keyboard(rows, one_time=False)


def build_user_menu(sheet: RegistrationSheet, vk_user_id: int) -> VkKeyboard:
    player = sheet.player_by_vk_id(vk_user_id)
    if not player:
        return build_main_menu(False)
    payment_pending = str(player.get("Оплата", "")).strip().lower() != "оплачено"
    return build_main_menu(True, payment_pending=payment_pending)


def build_faction_keyboard() -> VkKeyboard:
    return build_keyboard(
        [["🔵 Корпус Стали"], ["🔴 Новый Штат"], [CANCEL_BUTTON]],
        one_time=True,
    )


def build_tariff_keyboard(buttons: list[str]) -> VkKeyboard:
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([CANCEL_BUTTON])
    return build_keyboard(rows, one_time=True)


def build_open_link_keyboard(label: str, link: str) -> VkKeyboard:
    keyboard = VkKeyboard(one_time=False, inline=False)
    keyboard.add_openlink_button(label=label, link=link)
    return keyboard


def send_message(vk, peer_id: int, text: str, keyboard: VkKeyboard | None = None, attachment: str | None = None) -> None:
    params = {
        "peer_id": peer_id,
        "message": text,
        "random_id": random.randint(1, 2_000_000_000),
    }
    if keyboard:
        params["keyboard"] = keyboard.get_keyboard()
    if attachment:
        params["attachment"] = attachment
    logger.info(
        "Sending VK message: peer_id=%s text=%r attachment=%s keyboard=%s",
        peer_id,
        text[:120],
        bool(attachment),
        bool(keyboard),
    )
    response = vk.messages.send(**params)
    logger.info("VK message sent successfully: peer_id=%s response=%s", peer_id, response)


def upload_photo(vk, path: str) -> str:
    upload = VkUpload(vk)
    photo = upload.photo_messages(path)[0]
    return f"photo{photo['owner_id']}_{photo['id']}"


def upload_photo_from_bytes(vk, buffer: io.BytesIO, suffix: str = ".png") -> str:
    with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
        tmp.write(buffer.getvalue())
        tmp.flush()
        return upload_photo(vk, tmp.name)


def is_registered(sheet: RegistrationSheet, vk_user_id: int) -> bool:
    return sheet.player_by_vk_id(vk_user_id) is not None


def send_main_menu(vk, sheet: RegistrationSheet, peer_id: int, vk_user_id: int) -> None:
    keyboard = build_user_menu(sheet, vk_user_id)
    send_message(
        vk,
        peer_id,
        "☢ ТЕРМИНАЛ ПУСТОШИ\n\nТы подключён к системе операции MAD DAY.\n\nДоступные функции терминала:",
        keyboard=keyboard,
    )


def format_help_message() -> str:
    return (
        "Команды:\n"
        "/start - начать регистрацию\n"
        "/menu - открыть терминал\n"
        "/me - мой паспорт бойца\n"
        "/ping - проверка бота\n"
        "/myid - показать VK ID\n"
        "/stats - баланс фракций\n"
        "/lore - лор мира\n"
        "/map - карта полигона\n"
        "/schedule - расписание игры\n"
        "/radio - радио пустоши\n"
        "/info - информация об игре\n"
        "/briefing - брифинг фракции\n"
        "/faction_chat - чат фракции\n"
        "/scenario1 - сценарий 1\n"
        "/scenario2 - сценарий 2\n"
        "/scenario3 - сценарий 3\n"
        "/countdown - таймер до игры"
    )


def handle_menu_command(
    vk,
    sheet: RegistrationSheet,
    config: VkConfig,
    peer_id: int,
    vk_user_id: int,
    text: str,
) -> None:
    text_lower = text.lower().strip()
    normalized_text = text_lower.rstrip(".!? ")

    if normalized_text in INTRO_ALIASES:
        keyboard = build_keyboard([[START_REGISTRATION_BUTTON]], one_time=True)
        send_message(vk, peer_id, format_start_message(), keyboard=keyboard)
        return

    if normalized_text in {"/menu", "меню"}:
        send_main_menu(vk, sheet, peer_id, vk_user_id)
        return

    if normalized_text == "/help":
        send_message(
            vk,
            peer_id,
            format_help_message(),
            keyboard=build_user_menu(sheet, vk_user_id),
        )
        return

    if normalized_text == "/ping":
        send_message(vk, peer_id, "OK", keyboard=build_user_menu(sheet, vk_user_id))
        return

    if normalized_text == "/myid":
        send_message(vk, peer_id, f"Твой VK ID: {vk_user_id}", keyboard=build_user_menu(sheet, vk_user_id))
        return

    if normalized_text in {"/me", MENU_PROFILE.lower()}:
        player = sheet.player_by_vk_id(vk_user_id)
        if not player:
            send_message(vk, peer_id, "Ты ещё не зарегистрирован. Напиши /start.", keyboard=build_main_menu(False))
            return
        normalized = {
            "id": str(player.get("ID", "")).strip(),
            "name": str(player.get("Позывной", "")).strip(),
            "full_name": str(player.get("Фамилия Имя", "")).strip(),
            "faction": str(player.get("Фракция", "")).strip(),
            "tariff": str(player.get("Тариф", "")).strip(),
            "payment_status": str(player.get("Оплата", "")).strip(),
        }
        send_message(vk, peer_id, format_passport(normalized), keyboard=build_user_menu(sheet, vk_user_id))
        qr_image = make_qr_bytes(normalized["id"])
        attachment = upload_photo_from_bytes(vk, qr_image)
        send_message(vk, peer_id, f"QR-код бойца {normalized['id']}", attachment=attachment)
        return

    if normalized_text in {"/stats", MENU_STATS.lower()}:
        counts = sheet.faction_counts()
        lines = ["⚔ Баланс сил", ""]
        for faction, limit in config.faction_limits.items():
            current = counts.get(faction, 0)
            lines.append(faction)
            lines.append(f"{progress_bar(current, limit)} {current}/{limit}")
            lines.append("")
        send_message(vk, peer_id, "\n".join(lines).strip(), keyboard=build_user_menu(sheet, vk_user_id))
        return

    if normalized_text in {"/lore", MENU_LORE.lower()}:
        text = load_text_content("lore", "После энергетического коллапса нефть стала единственной валютой.")
        send_message(vk, peer_id, text, keyboard=build_user_menu(sheet, vk_user_id))
        return

    if normalized_text in {"/schedule", MENU_SCHEDULE.lower()}:
        text = load_text_content(
            "schedule",
            "MAD DAY\n\n10:00 — регистрация\n11:00 — сценарий 1\n13:00 — сценарий 2\n15:00 — финальная битва",
        )
        send_message(vk, peer_id, text, keyboard=build_user_menu(sheet, vk_user_id))
        return

    if normalized_text in {"/info", MENU_INFO.lower()}:
        text = load_text_content("info", "ℹ ИНФОРМАЦИЯ ОБ ИГРЕ\n\nMAD DAY 5.0")
        send_message(vk, peer_id, text, keyboard=build_user_menu(sheet, vk_user_id))
        return

    if normalized_text in {"/briefing", MENU_BRIEFING.lower()}:
        player = sheet.player_by_vk_id(vk_user_id)
        if not player:
            send_message(vk, peer_id, "Сначала зарегистрируйся через /start, чтобы получить брифинг.", keyboard=build_main_menu(False))
            return
        faction = str(player.get("Фракция", "")).strip()
        briefing_key = "briefing_steel" if "Корпус" in faction else "briefing_state"
        briefing_text = load_text_content(briefing_key, "Брифинг пока не заполнен.")
        send_message(vk, peer_id, briefing_text, keyboard=build_user_menu(sheet, vk_user_id))
        return

    if normalized_text in {MENU_FACTION_CHAT.lower(), "/faction_chat"}:
        player = sheet.player_by_vk_id(vk_user_id)
        if not player:
            send_message(
                vk,
                peer_id,
                "Сначала зарегистрируйся через /start, чтобы получить доступ к чату фракции.",
                keyboard=build_main_menu(False),
            )
            return
        faction = str(player.get("Фракция", "")).strip()
        chat_link = config.faction_chat_links.get(faction)
        if not chat_link:
            send_message(vk, peer_id, "Чат этой фракции ещё не настроен.", keyboard=build_user_menu(sheet, vk_user_id))
            return
        send_message(
            vk,
            peer_id,
            "Вот чат твоей фракции:",
            keyboard=build_open_link_keyboard("ЧАТ ФРАКЦИИ", chat_link),
        )
        send_main_menu(vk, sheet, peer_id, vk_user_id)
        return

    if normalized_text in {"/radio", MENU_RADIO.lower()}:
        raw = load_text_content(
            "radio",
            "Радиоперехват...\n\nКомандование вызывает тебя.\nПроверь снаряжение перед выходом.",
        )
        messages = [part.strip() for part in raw.split("\n\n---\n\n") if part.strip()] or [raw]
        send_message(vk, peer_id, random.choice(messages), keyboard=build_user_menu(sheet, vk_user_id))
        return

    if normalized_text == "/countdown":
        game_start = parse_game_start(config.game_start_at, config.timezone_name)
        if not game_start:
            send_message(vk, peer_id, "Дата старта игры ещё не настроена.", keyboard=build_user_menu(sheet, vk_user_id))
            return
        send_message(vk, peer_id, format_countdown(game_start, config.timezone_name), keyboard=build_user_menu(sheet, vk_user_id))
        return

    if normalized_text in {"/map", MENU_MAP.lower()}:
        send_message(vk, peer_id, "🗺 Карты полигона по миссиям:", keyboard=build_user_menu(sheet, vk_user_id))
        for key, title in [("scenario1", "🗺 Эпизод 1"), ("scenario2", "🗺 Эпизод 2"), ("scenario3", "🗺 Эпизод 3")]:
            image_path = find_scenario_image_path(key)
            scenario_text = load_text_content(key, "Описание сценария пока не заполнено.")
            caption = f"{title}\n{scenario_text.splitlines()[0].strip()}" if scenario_text else title
            if image_path:
                attachment = upload_photo(vk, str(image_path))
                send_message(vk, peer_id, caption, attachment=attachment)
            else:
                send_message(vk, peer_id, caption)
        return

    if normalized_text in {"/scenario1", "/scenario2", "/scenario3"}:
        scenario_key = normalized_text.lstrip("/")
        scenario_text = load_text_content(scenario_key, "Сценарий пока не заполнен.")
        image_path = find_scenario_image_path(scenario_key)
        if image_path:
            attachment = upload_photo(vk, str(image_path))
            send_message(vk, peer_id, scenario_text, attachment=attachment, keyboard=build_user_menu(sheet, vk_user_id))
        else:
            send_message(vk, peer_id, scenario_text, keyboard=build_user_menu(sheet, vk_user_id))
        return

    if normalized_text == PAYMENT_BUTTON.lower():
        player = sheet.player_by_vk_id(vk_user_id)
        if not player:
            send_message(vk, peer_id, "Сначала зарегистрируйся через /start, затем подтверди оплату.", keyboard=build_main_menu(False))
            return
        if str(player.get("Оплата", "")).strip().lower() == "оплачено":
            send_message(vk, peer_id, "Оплата уже отмечена. Увидимся на полигоне.", keyboard=build_user_menu(sheet, vk_user_id))
            return
        paid_at = datetime.now(ZoneInfo(config.timezone_name)).strftime("%d.%m.%Y %H:%M")
        if sheet.mark_paid("vk", vk_user_id, paid_at):
            send_message(vk, peer_id, "✅ Оплата отмечена.\n\nСтатус бойца обновлён в реестре MAD DAY.", keyboard=build_user_menu(sheet, vk_user_id))
        else:
            send_message(vk, peer_id, "Не удалось обновить оплату. Попробуй ещё раз позже.", keyboard=build_user_menu(sheet, vk_user_id))
        return

    send_main_menu(vk, sheet, peer_id, vk_user_id)


def main() -> None:
    config = load_vk_config()
    sheet = RegistrationSheet(config)

    vk_session = vk_api.VkApi(token=config.vk_token)
    vk = vk_session.get_api()
    longpoll = VkBotLongPoll(vk_session, config.vk_group_id)
    sessions: dict[int, dict] = {}
    logger.info("MAD DAY VK bot started")

    for event in longpoll.listen():
        if event.type != VkBotEventType.MESSAGE_NEW:
            continue

        try:
            message = event.object.message
            vk_user_id = int(message["from_id"])
            peer_id = int(message["peer_id"])
            text = str(message.get("text", "")).strip()
            logger.info(
                "Incoming VK message: from_id=%s peer_id=%s text=%r",
                vk_user_id,
                peer_id,
                text,
            )
            if not text:
                continue

            if text == CANCEL_BUTTON:
                sessions.pop(vk_user_id, None)
                send_message(vk, peer_id, "Регистрация отменена. Если захочешь начать заново, напиши /start.")
                send_main_menu(vk, sheet, peer_id, vk_user_id)
                continue

            if vk_user_id in sessions:
                session = sessions[vk_user_id]
                state = session["state"]
                data = session["data"]

                if state == SESSION_CALLSIGN:
                    callsign = normalize_callsign(text)
                    if not callsign:
                        send_message(vk, peer_id, "Позывной должен быть длиной от 2 до 32 символов. Попробуй ещё раз.")
                        continue
                    data["name"] = callsign
                    session["state"] = SESSION_PHONE
                    send_message(vk, peer_id, "Отправь телефон.", keyboard=build_keyboard([[CANCEL_BUTTON]], one_time=True))
                    continue

                if state == SESSION_PHONE:
                    phone = normalize_phone(text)
                    if not phone:
                        send_message(vk, peer_id, "Не удалось распознать телефон. Отправь номер ещё раз.")
                        continue
                    data["phone"] = phone
                    session["state"] = SESSION_FACTION
                    send_message(vk, peer_id, "Выбери фракцию:", keyboard=build_faction_keyboard())
                    continue

                if state == SESSION_FACTION:
                    faction = text
                    if faction not in config.faction_limits:
                        send_message(vk, peer_id, "Выбери фракцию кнопкой из списка.")
                        continue
                    counts = sheet.faction_counts()
                    if counts.get(faction, 0) >= config.faction_limits[faction]:
                        send_message(vk, peer_id, f"⚠ Фракция {faction} уже заполнена. Выбери другую.")
                        continue
                    data["faction"] = faction
                    session["state"] = SESSION_FULL_NAME
                    send_message(vk, peer_id, "Введи фамилию и имя бойца. Пример: Иванов Иван", keyboard=build_keyboard([[CANCEL_BUTTON]], one_time=True))
                    continue

                if state == SESSION_FULL_NAME:
                    full_name = normalize_full_name(text)
                    if not full_name:
                        send_message(vk, peer_id, "Нужно указать фамилию и имя через пробел. Пример: Иванов Иван")
                        continue
                    data["full_name"] = full_name
                    session["state"] = SESSION_TARIFF
                    send_message(vk, peer_id, f"Выбери тариф:\n\n{config.tariff_message}", keyboard=build_tariff_keyboard(config.tariff_buttons))
                    continue

                if state == SESSION_TARIFF:
                    tariff_choice = text
                    tariff = config.tariff_button_map.get(tariff_choice, tariff_choice)
                    if tariff not in config.tariffs:
                        send_message(vk, peer_id, "Выбери тариф кнопкой из списка.")
                        continue

                    timezone = ZoneInfo(config.timezone_name)
                    player_id = sheet.next_player_id()
                    player = {
                        "id": player_id,
                        "name": data["name"],
                        "full_name": data["full_name"],
                        "phone": data["phone"],
                        "faction": data["faction"],
                        "tariff": tariff,
                        "telegram_id": "",
                        "vk_id": str(vk_user_id),
                        "date": datetime.now(timezone).strftime("%d.%m.%Y %H:%M"),
                        "payment_status": "не оплачено",
                        "payment_date": "",
                    }
                    logger.info("Appending VK player to sheet: vk_id=%s id=%s", vk_user_id, player_id)
                    sheet.append_player(player)
                    logger.info("VK player saved to sheet successfully: vk_id=%s id=%s", vk_user_id, player_id)

                    send_message(vk, peer_id, format_registration_result(player))
                    qr_image = make_qr_bytes(player_id)
                    attachment = upload_photo_from_bytes(vk, qr_image)
                    send_message(vk, peer_id, "QR-код бойца", attachment=attachment)
                    send_message(
                        vk,
                        peer_id,
                        "⚠ Сохрани этот QR код.\n\nОн понадобится для быстрого чек-ина перед началом игры.",
                    )
                    payment_text = load_text_content(
                        "payment",
                        "ℹ ОПЛАТА УЧАСТИЯ\n\nПеревод участия:\nhttps://www.sberbank.com/sms/pbpn?requisiteNumber=79217300917",
                    )
                    send_message(vk, peer_id, payment_text)
                    payment_qr = make_qr_from_text(config.payment_link, "mad-day-payment.png")
                    payment_attachment = upload_photo_from_bytes(vk, payment_qr)
                    send_message(
                        vk,
                        peer_id,
                        f"Ссылка для перевода:\n{config.payment_link}",
                        attachment=payment_attachment,
                        keyboard=build_keyboard([[PAYMENT_BUTTON]], one_time=True),
                    )
                    sessions.pop(vk_user_id, None)
                    send_main_menu(vk, sheet, peer_id, vk_user_id)
                    continue

            normalized_input = text.lower().strip().rstrip(".!? ")
            if normalized_input in REGISTRATION_TRIGGER_ALIASES:
                sessions[vk_user_id] = {"state": SESSION_CALLSIGN, "data": {}}
                send_message(vk, peer_id, "Введи позывной бойца:", keyboard=build_keyboard([[CANCEL_BUTTON]], one_time=True))
                continue

            handle_menu_command(vk, sheet, config, peer_id, vk_user_id, text)
        except Exception:
            logger.exception("VK message handling failed")
            if "peer_id" in locals():
                try:
                    send_message(
                        vk,
                        peer_id,
                        "⚠ Не удалось завершить действие. Попробуй ещё раз.",
                    )
                except Exception:
                    logger.exception("Failed to send VK error notification")


if __name__ == "__main__":
    main()
