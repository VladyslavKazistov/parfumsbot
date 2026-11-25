"""Переклад нот і типу аромату українською.

Спершу шукаємо у словнику data/notes_uk.json. Невідомі ноти, якщо задано
ANTHROPIC_API_KEY, перекладає Claude, а результат дописується у словник,
щоб наступного разу не платити за той самий переклад. Без ключа невідомі
ноти лишаються англійською.
"""
from __future__ import annotations

import json
import os
import unicodedata
from pathlib import Path

DICT_PATH = Path(__file__).resolve().parent.parent / "data" / "notes_uk.json"
MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")

# Тип аромату з Parfumo ("smoky-leathery", "floral-fruity" тощо).
SCENT_WORDS = {
    "floral": "квітковий", "fruity": "фруктовий", "woody": "деревний",
    "spicy": "пряний", "sweet": "солодкий", "fresh": "свіжий", "citrus": "цитрусовий",
    "citrusy": "цитрусовий", "green": "зелений", "powdery": "пудровий",
    "oriental": "східний", "resinous": "смолистий", "leathery": "шкіряний",
    "smoky": "димний", "gourmand": "гурманський", "aquatic": "водний",
    "marine": "морський", "earthy": "землистий", "animalic": "анімалістичний",
    "creamy": "кремовий", "synthetic": "синтетичний", "chypre": "шипровий",
    "fougere": "фужерний", "aromatic": "ароматичний", "musky": "мускусний",
    "ambery": "амбровий", "balsamic": "бальзамічний", "herbal": "трав'яний",
}


# Уточнення походження/обробки, які прибираємо, щоб звести ноту до базової
# ("Italian bergamot" -> "Bergamot"): так фільтр за хештегом знаходить усі пости.
QUALIFIERS = {
    "absolute", "co2", "orpur", "resinoid", "concrete", "natureprint", "oil", "extract",
    "essence", "accord", "italian", "indian", "bulgarian", "turkish", "egyptian", "french",
    "calabrian", "sicilian", "madagascan", "madagascar", "comorian", "haitian", "indonesian",
    "cambodian", "laotian", "thai", "malayan", "mongolian", "chinese", "japanese", "omani",
    "ethiopian", "somali", "spanish", "moroccan", "tunisian", "mediterranean", "guatemala",
    "guatemalan", "brazilian", "paraguayan", "sri", "lankan", "ceylonese", "tahitian",
    "hawaiian", "australian", "virginia", "texas", "atlas", "swiss", "grasse", "may", "taif",
    "damask", "bourbon", "siam", "honduran", "caribbean", "nepalese", "vietnamese", "persian",
    "afghan", "kashmiri", "georgian", "russian", "ukrainian", "polish", "english", "scottish",
    "irish", "american", "canadian", "mexican", "peruvian", "venezuelan", "colombian",
}


def _base(note: str) -> str:
    words = [w for w in note.replace("-", " ").split() if w.lower() not in QUALIFIERS]
    return " ".join(words)


class Translator:
    def __init__(self) -> None:
        self.notes: dict[str, str] = json.loads(DICT_PATH.read_text("utf-8"))
        self._lower = {k.lower(): v for k, v in self.notes.items()}
        self.changed = False
        self._client = None
        if os.environ.get("ANTHROPIC_API_KEY"):
            import anthropic

            self._client = anthropic.Anthropic()

    def scent(self, scent: str | None) -> str | None:
        if not scent:
            return None
        parts = [SCENT_WORDS.get(w.lower(), w) for w in scent.split("-")]
        return "-".join(parts)

    def _lookup(self, note: str) -> str | None:
        note = note.replace("®", "").replace("™", "").strip()
        note = "".join(c for c in unicodedata.normalize("NFKD", note) if not unicodedata.combining(c))
        for key in (note, _base(note), _base(note).rstrip("s")):
            if key and key.lower() in self._lower:
                return self._lower[key.lower()]
        return None

    def notes_list(self, notes: list[str]) -> list[str]:
        missing = [n for n in notes if self._lookup(n) is None]
        if missing and self._client:
            self._learn(missing)
        out: list[str] = []
        for n in notes:
            uk = self._lookup(n) or n
            if uk not in out:  # "Rose" і "Turkish rose" -> одна нота
                out.append(uk)
        return out

    def _learn(self, missing: list[str]) -> None:
        """Перекладає невідомі ноти через Claude і зберігає їх у словник."""
        import anthropic

        prompt = (
            "Переклади назви парфумерних нот з англійської на українську так, як їх "
            "пишуть на fragrantica.ua. Власні назви та торгові марки (напр. Iso E Super, "
            "Petalia®) залиш як є. Відповідай лише JSON-об'єктом "
            '{"англійська назва": "український переклад"} без пояснень.\n\n'
            + "\n".join(missing)
        )
        try:
            resp = self._client.messages.create(
                model=MODEL,
                max_tokens=4000,
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIError as e:
            print(f"[translate] Claude недоступний, лишаю англійською: {e}")
            return
        if resp.stop_reason != "end_turn":
            print(f"[translate] неочікуваний stop_reason: {resp.stop_reason}")
            return
        text = next((b.text for b in resp.content if b.type == "text"), "")
        start, end = text.find("{"), text.rfind("}")
        try:
            learned = json.loads(text[start : end + 1])
        except ValueError:
            print(f"[translate] не вдалося розібрати відповідь: {text[:200]}")
            return
        for en, uk in learned.items():
            if isinstance(uk, str) and uk.strip():
                self.notes[en] = uk.strip()
                self._lower[en.lower()] = uk.strip()
                self.changed = True

    def save(self) -> None:
        if self.changed:
            DICT_PATH.write_text(
                json.dumps(dict(sorted(self.notes.items())), ensure_ascii=False, indent=1) + "\n",
                "utf-8",
            )
