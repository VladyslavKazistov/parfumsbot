"""Каталог опублікованих ароматів (data/catalog.json).

Потрібен для пошуку в особистих повідомленнях бота, підбору схожих ароматів
за нотами та недільного топу.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .parfumo import Perfume

PATH = Path(__file__).resolve().parent.parent / "data" / "catalog.json"


def load() -> dict[str, dict]:
    if PATH.exists():
        return json.loads(PATH.read_text("utf-8"))
    return {}


def save(cat: dict[str, dict]) -> None:
    PATH.write_text(json.dumps(cat, ensure_ascii=False, indent=0) + "\n", "utf-8")


def entry(p: Perfume, notes_uk: list[str], tier: str, posted: dt.date) -> dict:
    return {
        "brand": p.brand,
        "name": p.name,
        "tier": tier,
        "notes": notes_uk,
        "notes_en": p.top + p.heart + p.base + p.notes,
        "perfumers": p.perfumers,
        "image": p.image,
        "pid": p.pid,
        "posted": posted.isoformat(),
    }


def similar_by_notes(cat: dict[str, dict], url: str, notes_uk: list[str], k: int = 3) -> list[str]:
    """Найближчі за спільними нотами (коефіцієнт Жаккара), без того самого бренду-аромату."""
    mine = set(notes_uk)
    if len(mine) < 3:
        return []
    scored = []
    for u, e in cat.items():
        if u == url:
            continue
        other = set(e.get("notes", []))
        if not other:
            continue
        common = mine & other
        if len(common) < 3:
            continue
        scored.append((len(common) / len(mine | other), f"{e['brand']} {e['name']}"))
    scored.sort(reverse=True)
    return [name for score, name in scored[:k] if score >= 0.3]
