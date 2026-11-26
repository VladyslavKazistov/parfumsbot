"""Пошук новинок в особистих повідомленнях бота.

Запускається GitHub Actions кожні 5 хвилин: забирає нові повідомлення через
getUpdates і відповідає списком знайдених ароматів з каталогу.
Тому відповідь приходить не миттєво, а протягом кількох хвилин.
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from html import escape
from pathlib import Path

from . import catalog, telegram
from .tiers import Tiers

STATE = Path(__file__).resolve().parent.parent / "data" / "dm_state.json"
LIMIT = 15

HELP = (
    "👋 Я шукаю новинки парфумерії, які вже були в каналі.\n\n"
    "Напишіть, що шукаєте:\n"
    "• бренд — <code>Dior</code>\n"
    "• ноту — <code>ваніль</code> або <code>vanilla</code>\n"
    "• парфумера — <code>Kurkdjian</code>\n"
    "• тир — <code>люкс</code>, <code>ніша</code>, <code>дизайнерський</code>\n\n"
    "Можна поєднувати: <code>ніша ваніль</code>.\n"
    "Відповідь приходить протягом кількох хвилин."
)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^\w]+", " ", s).strip()


def haystack(e: dict) -> str:
    parts = [e["brand"], e["name"], e.get("tier", ""), *e.get("notes", []),
             *e.get("notes_en", []), *e.get("perfumers", [])]
    return " " + norm(" ".join(parts)) + " "


def search(cat: dict[str, dict], query: str) -> list[tuple[str, dict]]:
    words = norm(query).split()
    if not words:
        return []
    found = []
    for url, e in cat.items():
        hay = haystack(e)
        if all(f" {w}" in hay for w in words):  # кожне слово — початок якогось слова
            found.append((url, e))
    found.sort(key=lambda x: (x[1].get("posted", ""), x[1].get("pid", 0)), reverse=True)
    return found


def answer(cat: dict[str, dict], tiers: Tiers, query: str) -> str:
    if query.strip().lower() in ("/start", "/help", "start", "help", "допомога"):
        return HELP
    res = search(cat, query)
    if not res:
        return f"Нічого не знайшов за запитом «{escape(query)}». Спробуйте інше слово або /help."
    lines = [f"🔎 «{escape(query)}»: знайдено {len(res)}" + (f", показую {LIMIT} найновіших" if len(res) > LIMIT else ""), ""]
    for url, e in res[:LIMIT]:
        emoji = tiers.of(e["brand"])["label"].split()[0]
        lines.append(f'{emoji} <a href="{escape(url)}">{escape(e["brand"])} — {escape(e["name"])}</a>')
    return "\n".join(lines)


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("::warning::TELEGRAM_BOT_TOKEN не заданий")
        return 0
    state = json.loads(STATE.read_text("utf-8")) if STATE.exists() else {"offset": 0}
    updates = telegram.get_updates(token, state["offset"])
    if not updates:
        print("Нових повідомлень немає")
        return 0
    cat, tiers = catalog.load(), Tiers()
    for u in updates:
        state["offset"] = u["update_id"] + 1
        msg = u.get("message") or {}
        chat = msg.get("chat", {})
        text = (msg.get("text") or "").strip()
        if chat.get("type") != "private" or not text:
            continue
        try:
            telegram.send_message(token, chat["id"], answer(cat, tiers, text))
            print(f"[dm] відповів на запит «{text[:40]}»")
        except Exception as e:  # одна невдача не зупиняє решту
            print(f"[dm] помилка: {e}")
    STATE.write_text(json.dumps(state) + "\n", "utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
