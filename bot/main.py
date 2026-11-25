"""Шукає новинки парфумерії та публікує їх у Telegram-канал.

Запуск:
    python -m bot.main --dry-run     # лише показати пости, нічого не надсилати
    python -m bot.main               # опублікувати все нове з минулого запуску
    python -m bot.main --since-days 3 # опублікувати все за останні 3 дні
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import requests

from . import parfumo, telegram
from .post import build_caption
from .translate import Translator

STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "posted.json"


def load_state() -> dict:
    state = {"posted": [], "last_pid": 0, "pending": {}}
    if STATE_PATH.exists():
        state.update(json.loads(STATE_PATH.read_text("utf-8")))
    return state


def save_state(state: dict) -> None:
    state["posted"] = state["posted"][-5000:]  # не роздуваємо файл
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", "utf-8")


def collect(session, state: dict, min_year: int, since_days: int | None):
    """Збирає нові аромати (від старших до новіших) і оновлює last_pid/pending."""
    today = dt.date.today()
    posted = set(state["posted"])
    last_pid = state.get("last_pid") or 0
    cutoff = today - dt.timedelta(days=since_days) if since_days else None
    if not cutoff and not last_pid:
        cutoff = today - dt.timedelta(days=1)  # перший запуск без історії
    found, max_pid, old_streak = [], last_pid, 0

    for url in parfumo.recent_urls(session):
        if url in posted:
            continue
        p = parfumo.fetch(session, url)
        if not p:
            continue
        if cutoff:
            # Точної дати додавання немає, орієнтуємося на дату оновлення картки.
            if p.updated and p.updated < cutoff:
                old_streak += 1
                if old_streak >= 20:
                    break
                continue
            old_streak = 0
        elif p.pid and p.pid <= last_pid:
            break  # дійшли до вже переглянутих
        max_pid = max(max_pid, p.pid)
        if (p.year or 0) < min_year:
            continue
        if not p.image:
            state["pending"].setdefault(url, today.isoformat())
            print(f"[wait] без фото поки що: {p.brand} — {p.name}")
            continue
        found.append(p)

    # Ті, що раніше були без фото: перевіряємо до 7 днів.
    for url, first in list(state["pending"].items()):
        if url in posted or any(f.url == url for f in found):
            state["pending"].pop(url, None)
            continue
        if (today - dt.date.fromisoformat(first)).days > 7:
            state["pending"].pop(url, None)
            continue
        p = parfumo.fetch(session, url)
        if p and p.image and (p.year or 0) >= min_year:
            state["pending"].pop(url, None)
            found.append(p)

    state["last_pid"] = max_pid
    found.sort(key=lambda p: p.pid)  # у каналі від старших до новіших
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="не надсилати в Telegram")
    ap.add_argument("--since-days", type=int, default=int(os.environ.get("SINCE_DAYS") or 0) or None,
                    help="опублікувати все за останні N днів (інакше: усе нове з минулого запуску)")
    ap.add_argument("--max-posts", type=int, default=int(os.environ.get("MAX_POSTS") or 200),
                    help="запобіжник від надто великої пачки")
    today = dt.date.today()
    ap.add_argument("--min-year", type=int, default=today.year if today.month > 1 else today.year - 1)
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
    tr = Translator()
    session = requests.Session()
    items = collect(session, state, args.min_year, args.since_days)
    print(f"Знайдено новинок: {len(items)}")
    if len(items) > args.max_posts:
        print(f"::warning::Новинок {len(items)}, публікую перші {args.max_posts}.")
        items = items[: args.max_posts]

    sent = 0
    for p in items:
        caption = build_caption(p, tr)
        if args.dry_run:
            print("=" * 60, f"\nФОТО: {p.image}\n{caption}\n")
            sent += 1
            continue
        try:
            telegram.send_photo(token, channel, p.image, caption)
        except telegram.ConfigError as e:
            telegram.diagnose(token, channel)
            print(f"::error::{e}. Перевірте секрет TELEGRAM_CHANNEL і що бот є адміністратором каналу.")
            break
        except Exception as e:  # одна невдача не зупиняє решту
            print(f"[error] {p.url}: {e}")
            continue
        state["posted"].append(p.url)
        save_state(state)  # зберігаємо після кожного поста, щоб не було дублів
        print(f"[ok] {p.brand} — {p.name}")
        sent += 1
        time.sleep(4)  # ліміт Telegram: ~20 повідомлень на хвилину в канал

    tr.save()
    if not args.dry_run:
        save_state(state)
    print(f"Готово: {sent} пост(ів).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
