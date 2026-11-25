"""Публікація в Telegram-канал через Bot API."""
from __future__ import annotations

import requests

API = "https://api.telegram.org/bot{token}/{method}"


class ConfigError(RuntimeError):
    """Помилка налаштувань (неправильний канал чи токен): далі пробувати марно."""


def normalize_channel(value: str) -> str:
    """Приймає @name, name, https://t.me/name або числовий id (-100...)."""
    v = value.strip()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if v.startswith(prefix):
            v = v[len(prefix):]
    v = v.strip("/")
    if v.lstrip("-").isdigit() or v.startswith("@"):
        return v
    return "@" + v


def send_photo(token: str, chat_id: str, photo_url: str, caption: str) -> None:
    resp = requests.post(
        API.format(token=token, method="sendPhoto"),
        data={"chat_id": chat_id, "photo": photo_url, "caption": caption, "parse_mode": "HTML"},
        timeout=60,
    )
    data = resp.json()
    if not data.get("ok"):
        if resp.status_code in (400, 401, 403) and any(
            m in data.get("description", "") for m in ("chat not found", "Unauthorized", "not enough rights", "bot is not a member")
        ):
            raise ConfigError(f"Telegram: {data.get('description')}")
        raise RuntimeError(f"Telegram: {data.get('description', resp.text)}")


def diagnose(token: str, chat_id: str) -> None:
    """Пише в лог, до якого бота й каналу насправді йдуть запити."""
    me = requests.get(API.format(token=token, method="getMe"), timeout=30).json()
    print("Бот:", me.get("result", {}).get("username") if me.get("ok") else me.get("description"))
    chat = requests.get(API.format(token=token, method="getChat"), params={"chat_id": chat_id}, timeout=30).json()
    if chat.get("ok"):
        c = chat["result"]
        print(f"Канал: назва «{c.get('title')}», тип {c.get('type')}, публічний: {'так' if c.get('username') else 'ні'}")
    else:
        print("Канал:", chat.get("description"))
