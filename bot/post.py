"""Формування тексту поста (HTML для Telegram)."""
from __future__ import annotations

from functools import partial
from html import escape as _escape

escape = partial(_escape, quote=False)

from .parfumo import Perfume
from .translate import Translator

GENDER_UK = {"women": "для жінок", "men": "для чоловіків", "unisex": "унісекс"}
CAPTION_LIMIT = 1024  # ліміт Telegram для підпису до фото


def _join(items: list[str]) -> str:
    return ", ".join(escape(i) for i in items)


def build_caption(p: Perfume, tr: Translator) -> str:
    title = f"<b>{escape(p.brand)} — {escape(p.name)}</b>"
    lines = [f"✨ {title}", ""]

    facts = []
    if p.gender:
        facts.append(GENDER_UK[p.gender])
    if p.year:
        facts.append(f"{p.year} рік")
    if p.limited:
        facts.append("лімітований випуск")
    if facts:
        lines.append("Новий аромат, " + ", ".join(facts) + ".")
    scent = tr.scent(p.scent)
    if scent:
        lines.append(f"Характер: {escape(scent)}.")
    if p.perfumers:
        label = "Парфумер" if len(p.perfumers) == 1 else "Парфумери"
        lines.append(f"{label}: {_join(p.perfumers)}")

    pyramid = []
    if p.top:
        pyramid.append(f"🔝 <b>Верхні ноти:</b> {_join(tr.notes_list(p.top))}")
    if p.heart:
        pyramid.append(f"💗 <b>Ноти серця:</b> {_join(tr.notes_list(p.heart))}")
    if p.base:
        pyramid.append(f"🌳 <b>Базові ноти:</b> {_join(tr.notes_list(p.base))}")
    if not pyramid and p.notes:
        pyramid.append(f"🌿 <b>Ноти:</b> {_join(tr.notes_list(p.notes))}")
    if pyramid:
        lines += [""] + pyramid

    footer = f'\n\n<a href="{_escape(p.url)}">Джерело: Parfumo</a>'
    text = "\n".join(lines)
    if len(text) + len(footer) > CAPTION_LIMIT:
        text = text[: CAPTION_LIMIT - len(footer) - 1].rsplit("\n", 1)[0] + "…"
    return text + footer
