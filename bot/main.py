"""Шукає новинки парфумерії та публікує їх у Telegram-канал.

Запуск:
    python -m bot.main --dry-run     # лише показати пости, нічого не надсилати
    python -m bot.main               # опублікувати (потрібні TELEGRAM_BOT_TOKEN і TELEGRAM_CHANNEL)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import requests

from . import parfumo, telegram
from .post import build_caption
from .translate import Translator

STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "posted.json"


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text("utf-8"))
    return {"posted": []}


def save_state(state: dict) -> None:
    state["posted"] = state["posted"][-2000:]  # не роздуваємо файл
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", "utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="не надсилати в Telegram")
    ap.add_argument("--max-posts", type=int, default=int(os.environ.get("MAX_POSTS", 5)))
    ap.add_argument("--min-year", type=int, default=dt.date.today().year)
    args = ap.parse_args()

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    channel = os.environ.get("TELEGRAM_CHANNEL")
    if not args.dry_run and not (token and channel):
        # Не "валимо" запуск за розкладом, поки секрети ще не налаштовані.
        print("::warning::TELEGRAM_BOT_TOKEN або TELEGRAM_CHANNEL не задані, пропускаю публікацію.")
        return 0

    if channel:
        channel = telegram.normalize_channel(channel)

    state = load_state()
    posted = set(state["posted"])
    tr = Translator()
    session = requests.Session()
    sent = 0

    for p in parfumo.fetch_new(session, min_year=args.min_year, skip=posted):
        if not p.image:
            # Фото ще не завантажили: не позначаємо, спробуємо наступного разу.
            print(f"[skip] без фото поки що: {p.brand} — {p.name}")
            continue
        caption = build_caption(p, tr)
        if args.dry_run:
            print("=" * 60, f"\nФОТО: {p.image}\n{caption}\n")
        else:
            try:
                telegram.send_photo(token, channel, p.image, caption)
            except telegram.ConfigError as e:
                print(f"::error::{e}. Перевірте секрет TELEGRAM_CHANNEL і що бот є адміністратором каналу.")
                tr.save()
                return 1
            except Exception as e:  # одна невдача не зупиняє решту
                print(f"[error] {p.url}: {e}")
                continue
            state["posted"].append(p.url)
            posted.add(p.url)
            print(f"[ok] {p.brand} — {p.name}")
        sent += 1
        if sent >= args.max_posts:
            break

    tr.save()
    if not args.dry_run:
        save_state(state)
    print(f"Готово: {sent} пост(ів).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
