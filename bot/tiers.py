"""Тир аромату за сегментом бренду (data/brand_tiers.json).

Від вищого до нижчого: Люкс > Ніша > Дизайнерський > Арабська парфумерія > Масмаркет.
Невідомі бренди потрапляють в «Інді» (здебільшого маленькі незалежні марки).
Список брендів можна доповнювати прямо у JSON.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "data" / "brand_tiers.json"


def _norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "", s)


class Tiers:
    def __init__(self) -> None:
        data = json.loads(PATH.read_text("utf-8"))
        self.default = data.pop("_default")
        self.by_brand: dict[str, dict] = {}
        for tier in data.values():
            for b in tier["brands"]:
                self.by_brand.setdefault(_norm(b), tier)

    def of(self, brand: str) -> dict:
        return self.by_brand.get(_norm(brand), self.default)
