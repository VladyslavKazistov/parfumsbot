"""Публікація в Telegram-канал через Bot API."""
from __future__ import annotations

import time

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
    for _ in range(3):
        resp = requests.post(
            API.format(token=token, method="sendPhoto"),
            data={"chat_id": chat_id, "photo": photo_url, "caption": caption, "parse_mode": "HTML"},
            timeout=60,
        )
        data = resp.json()
        if resp.status_code != 429:
            break
        time.sleep(data.get("parameters", {}).get("retry_after", 30) + 1)
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


def _call(token: str, method: str, payload: dict) -> dict:
    for _ in range(3):
        resp = requests.post(API.format(token=token, method=method), json=payload, timeout=60)
        data = resp.json()
        if resp.status_code != 429:
            break
        time.sleep(data.get("parameters", {}).get("retry_after", 30) + 1)
    if not data.get("ok"):
        desc = data.get("description", resp.text)
        if any(m in desc for m in ("chat not found", "Unauthorized", "not enough rights", "bot is not a member")):
            raise ConfigError(f"Telegram: {desc}")
        raise RuntimeError(f"Telegram {method}: {desc}")
    return data


def send_message(token: str, chat_id, text: str, preview: bool = False) -> None:
    _call(token, "sendMessage", {
        "chat_id": chat_id, "text": text, "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": not preview},
    })


def send_album(token: str, chat_id, photos: list[str], caption: str = "") -> None:
    """Альбом до 10 фото; підпис під першим."""
    media = [{"type": "photo", "media": u} for u in photos[:10]]
    if media and caption:
        media[0].update({"caption": caption, "parse_mode": "HTML"})
    if len(media) == 1:
        send_photo(token, chat_id, media[0]["media"], caption)
    elif media:
        _call(token, "sendMediaGroup", {"chat_id": chat_id, "media": media})


def get_updates(token: str, offset: int) -> list[dict]:
    return _call(token, "getUpdates", {"offset": offset, "timeout": 0,
                                       "allowed_updates": ["message"]})["result"]
