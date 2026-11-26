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
from html import escape

from . import catalog
from .post import build_caption, build_list, tier_of
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


DETAILED = {"люкс", "ніша"}          # окремий пост з фото
DAILY_DIGEST = {"дизайнерський", "арабська_парфумерія"}  # щоденний дайджест
TIER_ORDER = ["люкс", "ніша", "дизайнерський", "арабська_парфумерія", "масмаркет", "інді"]
UA_MONTHS = "січня лютого березня квітня травня червня липня серпня вересня жовтня листопада грудня".split()


def ua_date(d: dt.date) -> str:
    return f"{d.day} {UA_MONTHS[d.month - 1]}"


def kyiv_today() -> dt.date:
    from zoneinfo import ZoneInfo
    return dt.datetime.now(ZoneInfo("Europe/Kyiv")).date()


class Sender:
    """Надсилає в Telegram або друкує (dry-run)."""

    def __init__(self, token, channel, dry):
        self.token, self.channel, self.dry = token, channel, dry

    def photo(self, image, caption):
        if self.dry:
            print("=" * 60, f"\n[ФОТО] {image}\n{caption}\n")
        else:
            telegram.send_photo(self.token, self.channel, image, caption)
            time.sleep(4)  # ліміт Telegram: ~20 повідомлень на хвилину в канал

    def album(self, photos, caption=""):
        if not photos:
            return
        if self.dry:
            print("=" * 60, f"\n[АЛЬБОМ {len(photos)} фото] {caption}\n")
        else:
            telegram.send_album(self.token, self.channel, photos, caption)
            time.sleep(4)

    def text(self, text):
        if self.dry:
            print("=" * 60, f"\n{text}\n")
        else:
            telegram.send_message(self.token, self.channel, text)
            time.sleep(3)


def grouped(items: list[dict], tags: list[str]) -> list[tuple[dict, list[dict]]]:
    by: dict[str, list[dict]] = {}
    for it in items:
        by.setdefault(it["tier_tag"], []).append(it)
    out = []
    for tag in tags:
        if by.get(tag):
            out.append((tier_info(tag), sorted(by[tag], key=lambda x: (x["brand"].lower(), x["name"].lower()))))
    return out


def tier_info(tag: str) -> dict:
    from .tiers import PATH
    data = json.loads(PATH.read_text("utf-8"))
    for t in data.values():
        if t.get("tag") == tag:
            return t
    return data["_default"]


def weekly(state: dict, cat: dict, send: Sender, session, year: int, today: dt.date) -> None:
    """Неділя: зведення інді/масмаркету за тиждень і топ тижня."""
    week = state.get("weekly", [])
    if week:
        for i, part in enumerate(build_list(f"🗂 Інді та масмаркет за тиждень ({len(week)})",
                                            grouped(week, ["масмаркет", "інді"]))):
            send.text(part)
        state["weekly"] = []

    since = today - dt.timedelta(days=7)
    recent = {u: e for u, e in cat.items() if dt.date.fromisoformat(e["posted"]) > since}
    if not recent:
        return
    ranks = parfumo.popularity_ranks(session, year)
    top = sorted((ranks[u], u) for u in recent if u in ranks)[:10]
    if not top:
        return
    lines = [f"<b>🏆 Топ новинок тижня</b> ({ua_date(since + dt.timedelta(days=1))} – {ua_date(today)})", ""]
    for n, (_, u) in enumerate(top, 1):
        e = recent[u]
        t = tier_info(e["tier"])
        lines.append(f'{n}. <a href="{u}">{escape(e["brand"])} — {escape(e["name"])}</a> {t["label"].split()[0]}')
    lines += ["", "За популярністю на Parfumo серед новинок, що вийшли в каналі цього тижня."]
    send.album([recent[u]["image"] for _, u in top if recent[u].get("image")])
    send.text("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="не надсилати в Telegram")
    ap.add_argument("--since-days", type=int, default=int(os.environ.get("SINCE_DAYS") or 0) or None,
                    help="усе за останні N днів (інакше: усе нове з минулого запуску)")
    ap.add_argument("--max-posts", type=int, default=int(os.environ.get("MAX_POSTS") or 200),
                    help="запобіжник від надто великої пачки")
    ap.add_argument("--weekly", choices=["auto", "yes", "no"], default=os.environ.get("WEEKLY") or "auto",
                    help="недільні зведення: auto = лише в неділю")
    today = kyiv_today()
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
    state.setdefault("weekly", [])
    cat = catalog.load()
    tr = Translator()
    session = requests.Session()
    send = Sender(token, channel, args.dry_run)

    items = collect(session, state, args.min_year, args.since_days)
    print(f"Знайдено новинок: {len(items)}")
    if len(items) > args.max_posts:
        print(f"::warning::Новинок {len(items)}, беру перші {args.max_posts}.")
        items = items[: args.max_posts]

    detailed, digest = [], []
    for p in items:
        tier = tier_of(p.brand)
        notes_uk = tr.notes_list(p.top + p.heart + p.base + p.notes)
        cat[p.url] = catalog.entry(p, notes_uk, tier["tag"], today)
        row = {"url": p.url, "brand": p.brand, "name": p.name, "tier_tag": tier["tag"], "image": p.image}
        if tier["tag"] in DETAILED:
            detailed.append((p, notes_uk))
        elif tier["tag"] in DAILY_DIGEST:
            digest.append(row)
        else:
            state["weekly"].append(row)
        state["posted"].append(p.url)

    config_error = False
    try:
        # 1) Окремі пости для люксу й ніші.
        for p, notes_uk in detailed:
            similar = p.similar or catalog.similar_by_notes(cat, p.url, notes_uk)
            send.photo(p.image, build_caption(p, tr, similar))
            print(f"[ok] {p.brand} — {p.name}")
        # 2) Дайджест дня: альбом фото + список за тирами.
        if digest:
            send.album([d["image"] for d in digest if d["image"]][:10],
                       f"🆕 <b>Новинки дня, {ua_date(today)}</b>")
            parts = build_list(f"🆕 Новинки дня, {ua_date(today)}: {len(digest)}",
                               grouped(digest, TIER_ORDER))
            for part in parts:
                send.text(part)
        # 3) Неділя: зведення за тиждень і топ.
        if args.weekly == "yes" or (args.weekly == "auto" and today.weekday() == 6):
            weekly(state, cat, send, session, args.min_year, today)
    except telegram.ConfigError as e:
        telegram.diagnose(token, channel)
        print(f"::error::{e}. Перевірте секрет TELEGRAM_CHANNEL і що бот є адміністратором каналу.")
        config_error = True
        return 1
    finally:
        tr.save()
        if not args.dry_run and not config_error:
            save_state(state)
            catalog.save(cat)

    print(f"Готово: детальних {len(detailed)}, у дайджесті {len(digest)}, "
          f"у тижневе зведення {len(state['weekly'])}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
