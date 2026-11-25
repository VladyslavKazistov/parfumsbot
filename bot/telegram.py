"""Публікація в Telegram-канал через Bot API."""
from __future__ import annotations

import requests

API = "https://api.telegram.org/bot{token}/{method}"


def send_photo(token: str, chat_id: str, photo_url: str, caption: str) -> None:
    resp = requests.post(
        API.format(token=token, method="sendPhoto"),
        data={"chat_id": chat_id, "photo": photo_url, "caption": caption, "parse_mode": "HTML"},
        timeout=60,
    )
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram: {data.get('description', resp.text)}")
