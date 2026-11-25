"""Збір новинок із Parfumo.com."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

BASE = "https://www.parfumo.com"
RECENT_URL = f"{BASE}/Recently_added"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept-Language": "en",
}
# Заглушка, яку Parfumo показує, коли фото флакона ще немає.
PLACEHOLDER_IMAGE = "/assets/images/perfume_bottle/"
PERFUME_URL_RE = re.compile(r"^https://www\.parfumo\.com/Perfumes/([^/]+)/([^/?#]+)$")


@dataclass
class Perfume:
    url: str
    name: str
    brand: str
    year: int | None
    gender: str | None  # "women", "men", "unisex"
    scent: str | None  # напр. "smoky-leathery"
    image: str | None
    top: list[str] = field(default_factory=list)
    heart: list[str] = field(default_factory=list)
    base: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # якщо піраміди немає, лише список нот
    perfumers: list[str] = field(default_factory=list)
    limited: bool = False


def _get(session: requests.Session, url: str) -> str:
    resp = session.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def _list_urls(session: requests.Session, url: str) -> list[str]:
    soup = BeautifulSoup(_get(session, url), "html.parser")
    urls: list[str] = []
    for a in soup.select("div.name a[href]"):
        href = a["href"].split("?")[0].split("#")[0]
        if PERFUME_URL_RE.match(href) and href not in urls:
            urls.append(href)
    return urls


def candidate_urls(session: requests.Session, year: int, popular_pages: int = 5) -> list[str]:
    """Кандидати на пост, від найважливіших.

    1) Найпопулярніші релізи поточного року: помітні новинки великих брендів
       першими потрапляють у канал.
    2) Нещодавно додані в базу (свіжі, але часто маловідомі бренди).
    Уже опубліковане відсіюється за data/posted.json.
    """
    urls: list[str] = []
    for page in range(1, popular_pages + 1):
        for u in _list_urls(session, f"{BASE}/Release_Years/{year}?o=nr_desc&current_page={page}"):
            if u not in urls:
                urls.append(u)
        time.sleep(1)
    for u in _list_urls(session, RECENT_URL):
        if u not in urls:
            urls.append(u)
    return urls


def _notes(block) -> list[str]:
    return [s.get_text(strip=True) for s in block.select("span.clickable_note_img")]


def parse_perfume(html: str, url: str) -> Perfume:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one("h1.p_name_h1")
    brand_el = h1.select_one('[itemprop="brand"] [itemprop="name"]') if h1 else None
    brand = brand_el.get_text(strip=True) if brand_el else ""
    name = ""
    if h1:
        name = "".join(t for t in h1.find_all(string=True, recursive=False)).strip()

    year = None
    if h1:
        m = re.search(r"\b(19|20)\d{2}\b", h1.get_text(" "))
        if m:
            year = int(m.group(0))

    desc_el = soup.select_one('[itemprop="description"]')
    desc = desc_el.get_text(" ", strip=True) if desc_el else ""
    gender = None
    if "for women and men" in desc:
        gender = "unisex"
    elif "for women" in desc:
        gender = "women"
    elif "for men" in desc:
        gender = "men"
    m = re.search(r"The scent is ([^.]+)\.", desc)
    scent = m.group(1).strip() if m else None

    og = soup.select_one('meta[property="og:image"]')
    image = og["content"] if og and og.get("content") else None
    if image and PLACEHOLDER_IMAGE in image:
        image = None

    p = Perfume(
        url=url, name=name, brand=brand, year=year, gender=gender, scent=scent,
        image=image, limited=bool(soup.select_one(".label_a.limited")),
    )
    for block in soup.select(".pyramid_block"):
        cls = block.get("class", [])
        if "nb_t" in cls:
            p.top = _notes(block)
        elif "nb_m" in cls:
            p.heart = _notes(block)
        elif "nb_b" in cls:
            p.base = _notes(block)
        else:
            p.notes += _notes(block)
    if not (p.top or p.heart or p.base or p.notes):
        nl = soup.select_one(".notes_list")
        if nl:
            p.notes = _notes(nl)

    for a in soup.select('a[href*="/Perfumers/"]'):
        href = a["href"].rstrip("/")
        if href.endswith("/Perfumers"):
            continue  # пункт меню
        label = a.select_one(".label_a")
        if label:
            label.extract()
        who = a.get_text(strip=True)
        if who and who not in p.perfumers:
            p.perfumers.append(who)
    return p


def fetch_new(session: requests.Session, min_year: int, skip: set[str], delay: float = 1.5):
    """Повертає ще не опубліковані аромати, випущені не раніше min_year."""
    for url in candidate_urls(session, min_year):
        if url in skip:
            continue
        time.sleep(delay)  # не навантажуємо сайт
        try:
            p = parse_perfume(_get(session, url), url)
        except requests.RequestException as e:
            print(f"[parfumo] пропускаю {url}: {e}")
            continue
        if p.year and p.year >= min_year:
            yield p
