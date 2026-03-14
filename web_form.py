from __future__ import annotations

import base64
import html
import logging
import os
from pathlib import Path
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from bot import (
    Config,
    DEFAULT_TARIFF_MESSAGE,
    RegistrationSheet,
    load_text_content,
    make_qr_bytes,
    make_qr_from_text,
    normalize_callsign,
    normalize_full_name,
    normalize_phone,
    parse_admin_ids,
    parse_faction_chat_links,
    parse_faction_limits,
    parse_tariff_buttons,
    parse_tariffs,
)


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("web_form")

BASE_DIR = Path(__file__).resolve().parent
COMMAND_CONTACT_LINK = "https://t.me/bochkarrrev"

MODAL_CSS = """
          {MODAL_CSS}
</style>
      </head>
      <body>
        <div class="container">
          <h1>Регистрация без Telegram</h1>
          <p>Заполни форму — данные сразу попадут в общую таблицу регистрации.</p>
          {error_block}
          <form method="post" action="/register">
            <label for="callsign">Позывной</label>
            <input id="callsign" name="callsign" placeholder="Например: Стелс" value="{_escape(values.get("callsign", ""))}" required>

            <label for="full_name">Фамилия и имя</label>
            <input id="full_name" name="full_name" placeholder="Иванов Иван" value="{_escape(values.get("full_name", ""))}" required>

            <label for="phone">Телефон</label>
            <input id="phone" name="phone" placeholder="+7 999 123-45-67" value="{_escape(values.get("phone", ""))}" required>

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
          <div class="tariffs">{tariff_message}</div>
          <div class="note">Если фракция заполнена, она будет недоступна для выбора.</div>
        </div>
      </body>
    </html>
    """


def _format_block_text(text: str) -> str:
    return _escape(text).replace("\n", "<br>")

def _image_data_uri_from_path(path: Path) -> str | None:
    if not path.exists():
        return None
    ext = path.suffix.lower().lstrip(".")
    if ext in ("jpg", "jpeg"):
        mime = "image/jpeg"
    elif ext == "png":
        mime = "image/png"
    elif ext == "gif":
        mime = "image/gif"
    else:
        mime = "application/octet-stream"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def _first_existing_image(paths: list[Path]) -> str | None:
    for path in paths:
        data = _image_data_uri_from_path(path)
        if data:
            return data
    return None


def _collect_map_images() -> list[tuple[str, str]]:
    images: list[tuple[str, str]] = []
    base_candidates = [
        BASE_DIR / "map.jpg",
        BASE_DIR / "map.jpeg",
        BASE_DIR / "map.png",
    ]
    base_map = _first_existing_image(base_candidates)
    if base_map:
        images.append(("Карта полигона", base_map))

    scenario_candidates = [
        ("Эпизод 1", [
            BASE_DIR / "content" / "scenario1.jpg",
            BASE_DIR / "content" / "scenario1.jpeg",
            BASE_DIR / "content" / "scenario1.png",
        ]),
        ("Эпизод 2", [
            BASE_DIR / "content" / "scenario2.jpg",
            BASE_DIR / "content" / "scenario2.jpeg",
            BASE_DIR / "content" / "scenario2.png",
        ]),
        ("Эпизод 3", [
            BASE_DIR / "content" / "scenario3.jpg",
            BASE_DIR / "content" / "scenario3.jpeg",
            BASE_DIR / "content" / "scenario3.png",
        ]),
    ]
    for title, candidates in scenario_candidates:
        data = _first_existing_image(candidates)
        if data:
            images.append((f"Карта — {title}", data))
    return images


def _render_info_sections(player: dict) -> str:
    map_text = _format_block_text(
        load_text_content("map", "Карта полигона пока не добавлена.")
    )
    schedule_text = _format_block_text(
        load_text_content(
            "schedule",
            "MAD DAY\n\n10:00 — регистрация\n11:00 — сценарий 1\n13:00 — сценарий 2\n15:00 — финальная битва",
        )
    )
    lore_text = _format_block_text(
        load_text_content(
            "lore",
            "После энергетического коллапса нефть стала единственной валютой.",
        )
    )
    info_text = _format_block_text(
        load_text_content(
            "info",
            "Информация об игре пока не заполнена.",
        )
    )
    briefing_steel = _format_block_text(
        load_text_content("briefing_steel", "Брифинг Корпуса Стали пока не заполнен.")
    )
    briefing_state = _format_block_text(
        load_text_content("briefing_state", "Брифинг Нового Штата пока не заполнен.")
    )

    images = _collect_map_images()
    if images:
        image_cards = "".join(
            f"""<figure><img class="zoomable" src="{src}" alt="{_escape(title)}"><figcaption>{_escape(title)}</figcaption></figure>"""
            for title, src in images
        )
        map_images_html = f'<div class="image-grid">{image_cards}</div>'
    else:
        map_images_html = ""

    chat_link = CONFIG.faction_chat_links.get(player.get("faction") or player.get("Фракция", ""))
    if chat_link:
        chat_block = f'<a class="action-btn" href="{_escape(chat_link)}">ЧАТ ФРАКЦИИ</a>'
    else:
        chat_block = '<div class="section-text">Ссылка на чат для этой фракции пока не задана.</div>'

    counts = SHEET.faction_counts()
    balance_rows = "".join(
        f"""<div class="balance-row"><span>{_escape(faction)}</span><span>{counts.get(faction, 0)}/{limit}</span></div>"""
        for faction, limit in CONFIG.faction_limits.items()
    )

    return f"""
    <div class="info-nav">
      <a class="pill" href="#section-map">Карта полигона</a>
      <a class="pill" href="#section-schedule">Расписание</a>
      <a class="pill" href="#section-lore">История мира</a>
      <a class="pill" href="#section-info">Информация</a>
      <a class="pill" href="#section-briefing">Брифинг</a>
      <a class="pill" href="#section-chat">Чат фракции</a>
      <a class="pill" href="#section-command">Связь</a>
      <a class="pill" href="#section-balance">Баланс</a>
    </div>

    <section id="section-map" class="section">
      <h2>Карта полигона</h2>
      <div class="section-text">{map_text}</div>
      {map_images_html}
    </section>

    <section id="section-schedule" class="section">
      <h2>Расписание</h2>
      <div class="section-text">{schedule_text}</div>
    </section>

    <section id="section-lore" class="section">
      <h2>История мира MAD DAY</h2>
      <div class="section-text">{lore_text}</div>
    </section>

    <section id="section-info" class="section">
      <h2>Информация об игре</h2>
      <div class="section-text">{info_text}</div>
    </section>

    <section id="section-briefing" class="section">
      <h2>Брифинг фракций</h2>
      <div class="briefing-grid">
        <div class="briefing-card">
          <h3>🔵 Корпус Стали</h3>
          <div class="section-text">{briefing_steel}</div>
        </div>
        <div class="briefing-card">
          <h3>🔴 Новый Штат</h3>
          <div class="section-text">{briefing_state}</div>
        </div>
      </div>
    </section>

    <section id="section-chat" class="section">
      <h2>Чат фракции</h2>
      {chat_block}
    </section>

    <section id="section-command" class="section">
      <h2>Связь с командованием</h2>
      <a class="action-btn" href="{COMMAND_CONTACT_LINK}">Связь с командованием</a>
    </section>

    <section id="section-balance" class="section">
      <h2>Баланс фракций</h2>
      <div class="balance-grid">{balance_rows}</div>
    </section>
    """


def _render_success(player: dict, qr_data: str, payment_qr: str | None) -> str:
    payment_text = _format_block_text(
        load_text_content(
            "payment",
            "ℹ ОПЛАТА УЧАСТИЯ\n\nПеревод участия:\nhttps://www.sberbank.com/sms/pbpn?requisiteNumber=79217300917",
        )
    )
    payment_block = ""
    if payment_qr:
        payment_block = f"""
        <div class="payment">
          <h2>Оплата участия</h2>
          <div class="payment-text">{payment_text}</div>
          <img src="{payment_qr}" alt="QR оплаты">
        </div>
        """

    info_sections = _render_info_sections(player)

    return f"""
    <!doctype html>
    <html lang="ru">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>MAD DAY — регистрация завершена</title>
        <style>
          body {{
            margin: 0;
            padding: 32px 16px;
            font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
            background: radial-gradient(circle at top, #1f1f1f, #0b0b0b);
            color: #f5f5f5;
          }}
          .container {{
            max-width: 920px;
            margin: 0 auto;
            background: rgba(18, 18, 18, 0.95);
            padding: 28px;
            border-radius: 16px;
            border: 1px solid rgba(255, 255, 255, 0.08);
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.45);
          }}
          h1 {{
            margin-top: 0;
          }}
          .card {{
            margin-top: 18px;
            padding: 16px;
            border-radius: 12px;
            background: rgba(255, 255, 255, 0.05);
          }}
          .qr {{
            margin-top: 16px;
            text-align: center;
          }}
          img {{
            max-width: 240px;
            border-radius: 12px;
            background: #fff;
            padding: 8px;
          }}
          a {{
            color: #f39c12;
          }}
          .payment {{
            margin-top: 24px;
            padding: 16px;
            border-radius: 12px;
            background: rgba(255, 255, 255, 0.04);
          }}
          .payment-text {{
            font-size: 14px;
            line-height: 1.5;
            color: #e4e4e4;
          }}
          .info-nav {{
            margin-top: 28px;
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
          }}
          .pill {{
            text-decoration: none;
            color: #1a1a1a;
            background: linear-gradient(135deg, #f39c12, #e67e22);
            padding: 8px 12px;
            border-radius: 999px;
            font-weight: 700;
            font-size: 12px;
            letter-spacing: 0.04em;
          }}
          .section {{
            margin-top: 24px;
            padding: 16px;
            border-radius: 12px;
            background: rgba(255, 255, 255, 0.04);
          }}
          .section h2 {{
            margin-top: 0;
          }}
          .section-text {{
            font-size: 14px;
            line-height: 1.6;
            color: #e4e4e4;
          }}
          .image-grid {{
            margin-top: 16px;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 16px;
          }}
          .image-grid figure {{
            margin: 0;
            text-align: center;
          }}
          .image-grid img {{
            max-width: 100%;
            height: auto;
            padding: 0;
            background: #000;
          }}
          .image-grid figcaption {{
            margin-top: 8px;
            font-size: 13px;
            color: #cfcfcf;
          }}
          .action-btn {{
            display: inline-block;
            margin-top: 12px;
            padding: 10px 14px;
            background: #f39c12;
            color: #1a1a1a;
            border-radius: 10px;
            text-decoration: none;
            font-weight: 700;
          }}
          .briefing-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 16px;
            margin-top: 12px;
          }}
          .briefing-card {{
            padding: 12px;
            border-radius: 10px;
            background: rgba(255, 255, 255, 0.05);
          }}
          .briefing-card h3 {{
            margin-top: 0;
            font-size: 15px;
          }}
          .balance-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 10px;
            margin-top: 12px;
          }}
          .balance-row {{
            display: flex;
            justify-content: space-between;
            padding: 10px 12px;
            border-radius: 10px;
            background: rgba(255, 255, 255, 0.06);
            font-size: 14px;
          }}
        
          .zoomable {
            cursor: zoom-in;
            transition: transform 0.2s ease;
          }
          .zoomable:hover {
            transform: scale(1.02);
          }
          .modal {
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.75);
            display: none;
            align-items: center;
            justify-content: center;
            padding: 24px;
            z-index: 9999;
          }
          .modal.open {
            display: flex;
          }
          .modal-content {
            max-width: min(92vw, 1100px);
            width: 100%;
            background: #111;
            border-radius: 14px;
            padding: 16px;
            position: relative;
            box-shadow: 0 24px 60px rgba(0, 0, 0, 0.5);
          }
          .modal-content img {
            max-width: 100%;
            height: auto;
            display: block;
            margin: 0 auto;
            background: #000;
            padding: 0;
          }
          .modal-caption {
            margin-top: 10px;
            font-size: 14px;
            color: #cfcfcf;
            text-align: center;
          }
          .modal-close {
            position: absolute;
            top: 10px;
            right: 12px;
            background: #f39c12;
            color: #1a1a1a;
            border: none;
            border-radius: 8px;
            padding: 6px 10px;
            font-weight: 700;
            cursor: pointer;
          }
</style>
      </head>
      <body>
        <div class="container">
          <h1>Боец зарегистрирован</h1>
          <div class="card">
            <p><strong>Фамилия имя:</strong> {_escape(player["full_name"])}</p>
            <p><strong>Позывной:</strong> {_escape(player["name"])}</p>
            <p><strong>Фракция:</strong> {_escape(player["faction"])}</p>
            <p><strong>Тариф:</strong> {_escape(player["tariff"])}</p>
            <p><strong>ID:</strong> {_escape(player["id"])}</p>
          </div>
          <div class="qr">
            <p>Сохрани этот QR‑код — он нужен для чек‑ина на полигоне.</p>
            <img src="{qr_data}" alt="QR бойца">
          </div>
          {payment_block}
          {info_sections}
        </div>
      
        {MODAL_HTML}
        {MODAL_SCRIPT}
</body>
    </html>
    """

class WebFormHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        html_body = _render_form()
        self._send_html(html_body)

    def do_POST(self) -> None:
        if self.path != "/register":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        data = _parse_form(body)

        callsign = normalize_callsign(data.get("callsign", ""))
        full_name = normalize_full_name(data.get("full_name", ""))
        phone = normalize_phone(data.get("phone", ""))
        faction = data.get("faction", "").strip()
        tariff = data.get("tariff", "").strip()

        errors = []
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
        if faction in CONFIG.faction_limits:
            if counts.get(faction, 0) >= CONFIG.faction_limits[faction]:
                errors.append(f"Фракция {faction} уже заполнена.")

        if errors:
            html_body = _render_form(data, errors)
            self._send_html(html_body, status=400)
            return

        player_id = SHEET.next_player_id()
        player = {
            "id": player_id,
            "name": callsign,
            "full_name": full_name,
            "phone": phone,
            "faction": faction,
            "tariff": tariff,
            "chat_id": "WEB",
            "date": datetime.now(TIMEZONE).strftime("%d.%m.%Y %H:%M"),
            "payment_status": "не оплачено",
            "payment_date": "",
        }

        try:
            SHEET.append_player(player)
            qr_buffer = make_qr_bytes(player_id)
            qr_data = _as_data_uri(qr_buffer)
            payment_qr = None
            if CONFIG.payment_link:
                payment_buffer = make_qr_from_text(CONFIG.payment_link, "mad-day-payment.png")
                payment_qr = _as_data_uri(payment_buffer)
            html_body = _render_success(player, qr_data, payment_qr)
            self._send_html(html_body)
        except Exception as exc:
            logger.exception("Failed to register player: %s", exc)
            self._send_html(
                "<h1>Ошибка регистрации</h1><p>Не удалось сохранить данные. Попробуй позже.</p>",
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
