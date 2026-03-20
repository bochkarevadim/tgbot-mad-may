from __future__ import annotations

import base64
import cgi
import html
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from bot import (
    ALLOWED_RECEIPT_EXTENSIONS,
    DEFAULT_FACTION_LIMITS,
    DEFAULT_TARIFF_MESSAGE,
    DEFAULT_TARIFFS,
    DriveStorage,
    PAYMENT_STATUS_PAID,
    PAYMENT_STATUS_PENDING,
    RegistrationSheet,
    build_player_snapshot,
    build_receipt_review_markup_dict,
    find_scenario_image_path,
    format_admin_receipt_notice,
    format_admin_registration_notice,
    load_text_content,
    make_qr_bytes,
    make_qr_from_text,
    normalize_callsign,
    normalize_full_name,
    normalize_phone,
    parse_admin_ids,
    parse_bool,
    parse_faction_chat_links,
    parse_faction_limits,
    parse_tariff_buttons,
    parse_tariffs,
    send_telegram_admin_notifications,
)


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("web_form")

BASE_DIR = Path(__file__).resolve().parent
MAX_RECEIPT_FILE_SIZE = 10 * 1024 * 1024


@dataclass
class WebConfig:
    telegram_token: str | None
    admin_ids: set[int]
    spreadsheet_name: str
    spreadsheet_id: str | None
    credentials_file: str
    credentials_json: str | None
    timezone_name: str
    faction_limits: dict[str, int]
    tariffs: list[str]
    tariff_message: str
    tariff_buttons: list[str]
    tariff_button_map: dict[str, str]
    payment_link: str
    faction_chat_links: dict[str, str]
    drive_receipts_folder_id: str | None
    receipt_public_links: bool


def load_web_config() -> WebConfig:
    load_dotenv()
    telegram_token = os.getenv("TOKEN", "").strip() or None
    admin_ids = parse_admin_ids(os.getenv("ADMIN_IDS"))
    spreadsheet_name = os.getenv("GOOGLE_SHEETS_SPREADSHEET", "MAD DAY REGISTRATION").strip()
    spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "").strip() or None
    credentials_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json").strip()
    credentials_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    timezone_name = os.getenv("REGISTRATION_TIMEZONE", "Europe/Moscow").strip()
    faction_limits = parse_faction_limits(os.getenv("FACTION_LIMITS")) or DEFAULT_FACTION_LIMITS.copy()
    tariffs = parse_tariffs(os.getenv("TARIFFS")) or DEFAULT_TARIFFS.copy()
    tariff_message = load_text_content("tariffs", DEFAULT_TARIFF_MESSAGE)
    tariff_buttons, tariff_button_map = parse_tariff_buttons(
        os.getenv("TARIFF_BUTTONS"),
        tariffs,
    )
    payment_link = os.getenv(
        "PAYMENT_LINK",
        "https://www.sberbank.com/sms/pbpn?requisiteNumber=79217300917",
    ).strip()
    faction_chat_links = parse_faction_chat_links(os.getenv("FACTION_CHAT_LINKS"))
    drive_receipts_folder_id = os.getenv("GOOGLE_DRIVE_RECEIPTS_FOLDER_ID", "").strip() or None
    receipt_public_links = parse_bool(os.getenv("RECEIPT_PUBLIC_LINKS"))

    if not spreadsheet_name and not spreadsheet_id:
        raise RuntimeError("Set GOOGLE_SHEETS_SPREADSHEET or GOOGLE_SHEETS_SPREADSHEET_ID.")
    if not credentials_json and not os.path.exists(credentials_file):
        raise RuntimeError(
            "Google credentials not found. Set GOOGLE_CREDENTIALS_JSON or place credentials.json near web_form.py."
        )

    return WebConfig(
        telegram_token=telegram_token,
        admin_ids=admin_ids,
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
        payment_link=payment_link,
        faction_chat_links=faction_chat_links,
        drive_receipts_folder_id=drive_receipts_folder_id,
        receipt_public_links=receipt_public_links,
    )


CONFIG = load_web_config()
SHEET = RegistrationSheet(CONFIG)
STORAGE = DriveStorage(CONFIG)
TIMEZONE = ZoneInfo(CONFIG.timezone_name)


def _escape(value: str) -> str:
    return html.escape(str(value), quote=True)


def _format_block_text(text: str) -> str:
    return _escape(text).replace("\n", "<br>")


def _as_data_uri(buffer) -> str:
    payload = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{payload}"


def _image_data_uri_from_path(path: Path) -> str | None:
    if not path.exists():
        return None
    ext = path.suffix.lower().lstrip(".")
    mime = "image/jpeg" if ext in {"jpg", "jpeg"} else "image/png"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def _collect_map_images() -> list[tuple[str, str]]:
    images: list[tuple[str, str]] = []
    for title, path in [
        ("Эпизод 1", find_scenario_image_path("scenario1")),
        ("Эпизод 2", find_scenario_image_path("scenario2")),
        ("Эпизод 3", find_scenario_image_path("scenario3")),
    ]:
        if not path:
            continue
        data = _image_data_uri_from_path(path)
        if data:
            images.append((title, data))
    return images


def _render_layout(title: str, body: str) -> str:
    return f"""
    <!doctype html>
    <html lang="ru">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{_escape(title)}</title>
        <style>
          body {{
            margin: 0;
            padding: 32px 16px;
            font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
            background: radial-gradient(circle at top, #242424, #090909);
            color: #f5f5f5;
          }}
          .container {{
            max-width: 980px;
            margin: 0 auto;
            background: rgba(16, 16, 16, 0.94);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 18px;
            padding: 28px;
            box-shadow: 0 20px 48px rgba(0, 0, 0, 0.45);
          }}
          h1, h2, h3 {{
            margin-top: 0;
          }}
          .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 18px;
          }}
          .card {{
            padding: 18px;
            border-radius: 14px;
            background: rgba(255, 255, 255, 0.05);
          }}
          label {{
            display: block;
            margin: 14px 0 6px;
            font-weight: 700;
          }}
          input, select, button {{
            width: 100%;
            box-sizing: border-box;
            border-radius: 10px;
            border: 1px solid rgba(255, 255, 255, 0.12);
            padding: 12px 14px;
            font-size: 15px;
          }}
          input, select {{
            background: rgba(255, 255, 255, 0.08);
            color: #fff;
          }}
          option {{
            color: #111;
          }}
          button {{
            margin-top: 16px;
            background: linear-gradient(135deg, #f39c12, #e67e22);
            color: #141414;
            font-weight: 800;
            cursor: pointer;
            border: none;
          }}
          .muted {{
            color: #cfcfcf;
            line-height: 1.6;
          }}
          .errors {{
            margin: 0 0 18px;
            padding: 14px 16px;
            border-radius: 12px;
            background: rgba(192, 57, 43, 0.18);
            border: 1px solid rgba(231, 76, 60, 0.35);
          }}
          .success {{
            margin: 0 0 18px;
            padding: 14px 16px;
            border-radius: 12px;
            background: rgba(39, 174, 96, 0.16);
            border: 1px solid rgba(46, 204, 113, 0.35);
          }}
          .section {{
            margin-top: 22px;
            padding: 18px;
            border-radius: 14px;
            background: rgba(255, 255, 255, 0.04);
          }}
          .chips {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-top: 14px;
          }}
          .chip {{
            background: rgba(243, 156, 18, 0.15);
            color: #ffcf7e;
            padding: 8px 12px;
            border-radius: 999px;
            font-size: 13px;
            font-weight: 700;
          }}
          .image-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 16px;
            margin-top: 16px;
          }}
          .image-grid img, .qr img {{
            max-width: 100%;
            height: auto;
            border-radius: 12px;
            background: #fff;
            padding: 8px;
          }}
          .qr {{
            margin-top: 18px;
          }}
          a {{
            color: #ffcf7e;
          }}
          .small {{
            font-size: 13px;
            color: #bdbdbd;
          }}
        </style>
      </head>
      <body>
        <div class="container">
          {body}
        </div>
      </body>
    </html>
    """


def _render_errors(errors: list[str]) -> str:
    if not errors:
        return ""
    items = "".join(f"<li>{_escape(error)}</li>" for error in errors)
    return f'<div class="errors"><strong>Нужно поправить:</strong><ul>{items}</ul></div>'


def _render_info_sections() -> str:
    images_html = ""
    images = _collect_map_images()
    if images:
        images_html = '<div class="image-grid">' + "".join(
            f'<figure><img src="{src}" alt="{_escape(title)}"><figcaption>{_escape(title)}</figcaption></figure>'
            for title, src in images
        ) + "</div>"

    return f"""
    <div class="section">
      <h2>Карта и сценарии</h2>
      <div class="muted">{_format_block_text(load_text_content("map", "Карта полигона пока не добавлена."))}</div>
      {images_html}
    </div>
    <div class="section">
      <h2>Расписание</h2>
      <div class="muted">{_format_block_text(load_text_content("schedule", "Расписание пока не заполнено."))}</div>
    </div>
    <div class="section">
      <h2>Лор мира MAD DAY</h2>
      <div class="muted">{_format_block_text(load_text_content("lore", "Лор мира пока не заполнен."))}</div>
    </div>
    <div class="section">
      <h2>Информация об игре</h2>
      <div class="muted">{_format_block_text(load_text_content("info", "Информация об игре пока не заполнена."))}</div>
    </div>
    """


def _render_register_page(
    values: dict[str, str] | None = None,
    errors: list[str] | None = None,
    receipt_values: dict[str, str] | None = None,
    receipt_errors: list[str] | None = None,
    notice: str = "",
) -> str:
    values = values or {}
    receipt_values = receipt_values or {}
    errors = errors or []
    receipt_errors = receipt_errors or []

    faction_options = []
    counts = SHEET.faction_counts()
    for faction, limit in CONFIG.faction_limits.items():
        current = counts.get(faction, 0)
        disabled = "disabled" if current >= limit else ""
        selected = "selected" if values.get("faction") == faction else ""
        faction_options.append(
            f'<option value="{_escape(faction)}" {selected} {disabled}>{_escape(faction)} ({current}/{limit})</option>'
        )

    tariff_options = []
    for tariff in CONFIG.tariffs:
        selected = "selected" if values.get("tariff") == tariff else ""
        tariff_options.append(f'<option value="{_escape(tariff)}" {selected}>{_escape(tariff)}</option>')

    notice_block = f'<div class="success">{_escape(notice)}</div>' if notice else ""
    return _render_layout(
        "MAD DAY — регистрация и чек",
        f"""
        <h1>MAD DAY 5.0</h1>
        <p class="muted">Регистрация игрока и загрузка чека оплаты в одном терминале.</p>
        {notice_block}
        <div class="grid">
          <div class="card">
            <h2>Новая регистрация</h2>
            {_render_errors(errors)}
            <form method="post" action="/register">
              <label for="callsign">Позывной</label>
              <input id="callsign" name="callsign" value="{_escape(values.get('callsign', ''))}" required>

              <label for="full_name">Фамилия и имя</label>
              <input id="full_name" name="full_name" value="{_escape(values.get('full_name', ''))}" required>

              <label for="phone">Телефон</label>
              <input id="phone" name="phone" value="{_escape(values.get('phone', ''))}" required>

              <label for="faction">Фракция</label>
              <select id="faction" name="faction" required>
                <option value="">Выбери фракцию</option>
                {''.join(faction_options)}
              </select>

              <label for="tariff">Тариф</label>
              <select id="tariff" name="tariff" required>
                <option value="">Выбери тариф</option>
                {''.join(tariff_options)}
              </select>

              <button type="submit">Зарегистрироваться</button>
            </form>
            <div class="section">
              <h3>Тарифы</h3>
              <div class="muted">{_format_block_text(CONFIG.tariff_message)}</div>
            </div>
          </div>

          <div class="card">
            <h2>Загрузить чек оплаты</h2>
            <p class="muted">Если ты уже зарегистрирован, введи ID бойца и телефон, затем прикрепи PDF, JPG или PNG.</p>
            {_render_errors(receipt_errors)}
            <form method="post" action="/upload-receipt" enctype="multipart/form-data">
              <label for="player_id">ID бойца</label>
              <input id="player_id" name="player_id" value="{_escape(receipt_values.get('player_id', ''))}" required>

              <label for="receipt_phone">Телефон</label>
              <input id="receipt_phone" name="phone" value="{_escape(receipt_values.get('phone', ''))}" required>

              <label for="receipt_file">Файл чека</label>
              <input id="receipt_file" name="receipt_file" type="file" accept=".pdf,.jpg,.jpeg,.png,image/*,application/pdf" required>

              <button type="submit">Отправить чек</button>
            </form>
            <div class="chips">
              <div class="chip">PDF</div>
              <div class="chip">JPG</div>
              <div class="chip">PNG</div>
              <div class="chip">До 10 МБ</div>
            </div>
          </div>
        </div>
        {_render_info_sections()}
        """,
    )


def _render_upload_form(player_id: str, phone: str) -> str:
    return f"""
    <div class="section">
      <h2>Отправить чек оплаты</h2>
      <p class="muted">После перевода прикрепи PDF, JPG или PNG. Чек уйдёт организатору на ручную проверку.</p>
      <form method="post" action="/upload-receipt" enctype="multipart/form-data">
        <input type="hidden" name="player_id" value="{_escape(player_id)}">
        <input type="hidden" name="phone" value="{_escape(phone)}">
        <label for="receipt_file">Файл чека</label>
        <input id="receipt_file" name="receipt_file" type="file" accept=".pdf,.jpg,.jpeg,.png,image/*,application/pdf" required>
        <button type="submit">Загрузить чек</button>
      </form>
      <p class="small">Если вернёшься позже, используй этот ID и свой телефон на главной странице.</p>
    </div>
    """


def _render_success(player: dict, qr_data: str, payment_qr: str | None) -> str:
    payment_block = ""
    if payment_qr:
        payment_block = f"""
        <div class="section">
          <h2>Оплата участия</h2>
          <div class="muted">{_format_block_text(load_text_content("payment", "Оплата участия пока не заполнена."))}</div>
          <div class="qr"><img src="{payment_qr}" alt="QR оплаты"></div>
          <p><a href="{_escape(CONFIG.payment_link)}">{_escape(CONFIG.payment_link)}</a></p>
        </div>
        """

    return _render_layout(
        "MAD DAY — регистрация завершена",
        f"""
        <h1>Боец зарегистрирован</h1>
        <div class="success">Регистрация сохранена. После оплаты загрузи чек ниже.</div>
        <div class="card">
          <p><strong>ID:</strong> {_escape(player['id'])}</p>
          <p><strong>Позывной:</strong> {_escape(player['name'])}</p>
          <p><strong>Фамилия и имя:</strong> {_escape(player['full_name'])}</p>
          <p><strong>Фракция:</strong> {_escape(player['faction'])}</p>
          <p><strong>Тариф:</strong> {_escape(player['tariff'])}</p>
          <p><strong>Статус оплаты:</strong> {_escape(player['payment_status'])}</p>
        </div>
        <div class="qr">
          <p>Сохрани QR-код бойца для чек-ина на полигоне.</p>
          <img src="{qr_data}" alt="QR бойца">
        </div>
        {payment_block}
        {_render_upload_form(player['id'], player['phone'])}
        {_render_info_sections()}
        """,
    )


def _render_upload_success(player: dict, receipt_link: str) -> str:
    return _render_layout(
        "MAD DAY — чек загружен",
        f"""
        <h1>Чек загружен</h1>
        <div class="success">Организатор получил чек и проверит оплату вручную.</div>
        <div class="card">
          <p><strong>ID:</strong> {_escape(player['ID'])}</p>
          <p><strong>Позывной:</strong> {_escape(player['Позывной'])}</p>
          <p><strong>Статус оплаты:</strong> {_escape(str(player.get('Оплата', '')) or PAYMENT_STATUS_PENDING)}</p>
          <p><strong>Ссылка на чек:</strong> <a href="{_escape(receipt_link)}">{_escape(receipt_link)}</a></p>
        </div>
        <p><a href="/">Вернуться на главную</a></p>
        """,
    )


def _parse_urlencoded(data: bytes) -> dict[str, str]:
    parsed = parse_qs(data.decode("utf-8"), keep_blank_values=True)
    return {key: values[0] if values else "" for key, values in parsed.items()}


def _parse_multipart(handler: BaseHTTPRequestHandler) -> tuple[dict[str, str], bytes | None, str, str]:
    form = cgi.FieldStorage(
        fp=handler.rfile,
        headers=handler.headers,
        environ={
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": handler.headers.get("Content-Type", ""),
        },
    )
    values: dict[str, str] = {}
    for key in ("player_id", "phone"):
        values[key] = form.getfirst(key, "")

    file_item = form["receipt_file"] if "receipt_file" in form else None
    if file_item is None or not getattr(file_item, "file", None) or not getattr(file_item, "filename", ""):
        return values, None, "", ""

    content = file_item.file.read()
    filename = file_item.filename or "receipt"
    mime_type = file_item.type or "application/octet-stream"
    return values, content, filename, mime_type


class WebFormHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        self._send_html(_render_register_page())

    def do_POST(self) -> None:
        if self.path == "/register":
            self._handle_register()
            return
        if self.path == "/upload-receipt":
            self._handle_receipt_upload()
            return
        self.send_error(404)

    def _handle_register(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        data = _parse_urlencoded(self.rfile.read(length))

        callsign = normalize_callsign(data.get("callsign", ""))
        full_name = normalize_full_name(data.get("full_name", ""))
        phone = normalize_phone(data.get("phone", ""))
        faction = data.get("faction", "").strip()
        tariff = data.get("tariff", "").strip()

        errors: list[str] = []
        if not callsign:
            errors.append("Позывной должен быть длиной от 2 до 32 символов.")
        if not full_name:
            errors.append("Нужно указать фамилию и имя через пробел.")
        if not phone:
            errors.append("Не удалось распознать телефон.")
        if faction not in CONFIG.faction_limits:
            errors.append("Выбери фракцию из списка.")
        if tariff not in CONFIG.tariffs:
            errors.append("Выбери тариф из списка.")

        counts = SHEET.faction_counts()
        if faction in CONFIG.faction_limits and counts.get(faction, 0) >= CONFIG.faction_limits[faction]:
            errors.append(f"Фракция {faction} уже заполнена.")

        if errors:
            self._send_html(_render_register_page(values=data, errors=errors), status=400)
            return

        player_id = SHEET.next_player_id()
        player = {
            "id": player_id,
            "name": callsign,
            "full_name": full_name,
            "phone": phone,
            "faction": faction,
            "tariff": tariff,
            "telegram_id": "",
            "vk_id": "",
            "date": datetime.now(TIMEZONE).strftime("%d.%m.%Y %H:%M"),
            "payment_status": PAYMENT_STATUS_PENDING,
            "payment_date": "",
            "receipt_link": "",
            "receipt_uploaded_at": "",
            "payment_reviewer": "",
            "payment_comment": "",
        }

        try:
            SHEET.append_player(player)
            send_telegram_admin_notifications(
                telegram_token=CONFIG.telegram_token,
                admin_ids=CONFIG.admin_ids,
                text=format_admin_registration_notice(player, "web"),
            )
            qr_data = _as_data_uri(make_qr_bytes(player_id))
            payment_qr = _as_data_uri(make_qr_from_text(CONFIG.payment_link, "mad-day-payment.png")) if CONFIG.payment_link else None
            self._send_html(_render_success(player, qr_data, payment_qr))
        except Exception:
            logger.exception("Failed to register web player")
            self._send_html(
                _render_register_page(errors=["Не удалось сохранить регистрацию. Попробуй позже."]),
                status=500,
            )

    def _handle_receipt_upload(self) -> None:
        values, content, filename, mime_type = _parse_multipart(self)
        errors: list[str] = []
        player_id = values.get("player_id", "").strip()
        phone = normalize_phone(values.get("phone", ""))

        if not player_id:
            errors.append("Укажи ID бойца.")
        if not phone:
            errors.append("Укажи телефон так же, как при регистрации.")
        if not content or not filename:
            errors.append("Прикрепи PDF, JPG или PNG файл.")
        elif len(content) > MAX_RECEIPT_FILE_SIZE:
            errors.append("Файл слишком большой. Максимум 10 МБ.")
        elif Path(filename).suffix.lower() not in ALLOWED_RECEIPT_EXTENSIONS:
            errors.append("Поддерживаются только PDF, JPG и PNG.")

        player = SHEET.player_by_id(player_id) if player_id else None
        if not player:
            errors.append("Игрок с таким ID не найден.")
        elif normalize_phone(str(player.get("Телефон", ""))) != phone:
            errors.append("Телефон не совпадает с записью в реестре.")
        elif str(player.get("Оплата", "")).strip().lower() == PAYMENT_STATUS_PAID:
            errors.append("Оплата уже подтверждена, загружать новый чек не нужно.")

        if errors:
            self._send_html(
                _render_register_page(
                    receipt_values={"player_id": player_id, "phone": values.get("phone", "")},
                    receipt_errors=errors,
                ),
                status=400,
            )
            return

        uploaded_at = datetime.now(TIMEZONE).strftime("%d.%m.%Y %H:%M")
        try:
            upload_result = STORAGE.upload_receipt(
                player_id,
                "web",
                filename,
                content or b"",
                mime_type or "application/octet-stream",
            )
            SHEET.record_receipt_upload(player_id, upload_result["link"], uploaded_at)
            refreshed_player = SHEET.player_by_id(player_id) or player
            send_telegram_admin_notifications(
                telegram_token=CONFIG.telegram_token,
                admin_ids=CONFIG.admin_ids,
                text=format_admin_receipt_notice(
                    build_player_snapshot(refreshed_player),
                    "web",
                    uploaded_at,
                    upload_result["link"],
                ),
                reply_markup=build_receipt_review_markup_dict(player_id),
            )
            self._send_html(_render_upload_success(refreshed_player, upload_result["link"]))
        except Exception:
            logger.exception("Failed to upload web receipt")
            self._send_html(
                _render_register_page(
                    receipt_values={"player_id": player_id, "phone": values.get("phone", "")},
                    receipt_errors=["Не удалось загрузить чек. Попробуй позже."],
                ),
                status=500,
            )

    def _send_html(self, body: str, status: int = 200) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main() -> None:
    port = int(os.getenv("PORT") or os.getenv("WEB_PORT") or "8080")
    server = HTTPServer(("0.0.0.0", port), WebFormHandler)
    logger.info("Web registration form started on port %s", port)
    server.serve_forever()


if __name__ == "__main__":
    main()
