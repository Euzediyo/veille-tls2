"""Lecture du début de chaque article retenu, pour donner à l'IA plus que le titre et repérer
les articles réservés aux abonnés.

Le texte lu sert uniquement à l'analyse : il n'est ni enregistré ni publié. Le fichier robots.txt
de chaque site est respecté ; un article illisible garde simplement son extrait d'origine.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup

from .collect import USER_AGENT, allowed_by_robots

TIMEOUT = 15
MAX_CHARS = 2500
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 " + USER_AGENT
PAYWALL_PHRASES = ("réservé aux abonnés", "article réservé", "cet article est réservé", "contenu réservé aux abonnés",
                   "abonnez-vous pour lire", "pour lire la suite de cet article", "la suite est réservée")


def _json_ld_free(soup: BeautifulSoup) -> bool | None:
    """Valeur de isAccessibleForFree déclarée par le site (balisage utilisé par la presse pour Google)."""
    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text()
        for match in re.finditer(r'"isAccessibleForFree"\s*:\s*"?(true|false)"?', raw, re.I):
            return match.group(1).lower() == "true"
    return None


def read_page(html: str) -> tuple[str, bool | None]:
    """Texte du début de l'article et indication « payant » (None si on ne sait pas)."""
    soup = BeautifulSoup(html, "html.parser")
    free = _json_ld_free(soup)
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside", "form", "figure"]):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    paragraphs = [p.get_text(" ", strip=True) for p in root.find_all("p")]
    text = re.sub(r"\s+", " ", " ".join(p for p in paragraphs if len(p) > 60)).strip()
    if not text:
        meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
        text = (meta.get("content") or "").strip() if meta else ""
    paid = None if free is None else not free
    body = root.get_text(" ", strip=True).lower()
    marked = any(p in body for p in PAYWALL_PHRASES) or root.select_one('[class*="paywall"], [id*="paywall"]') is not None
    if marked and paid is None:
        paid = True
    return text[:MAX_CHARS], paid


def enrich_one(item: dict, paid_sources: set[str]) -> dict:
    """Lit le début de l'article. Les liens Google Actualités ne sont pas suivis : le robots.txt de
    Google l'interdit aux robots. Pour eux, seule la liste des sources payantes s'applique."""
    known_paid = item.get("source", "").strip().lower() in paid_sources or None
    url = item["url"]
    if "news.google.com" in url or not allowed_by_robots(url):
        return {**item, "payant": known_paid}
    try:
        res = requests.get(url, headers={"User-Agent": BROWSER_UA, "Accept-Language": "fr-FR,fr;q=0.9"}, timeout=TIMEOUT)
        res.raise_for_status()
        if "html" not in res.headers.get("Content-Type", "html"):
            return {**item, "payant": known_paid}
        text, paid = read_page(res.text)
    except requests.RequestException:
        return {**item, "payant": known_paid}
    out = {**item, "payant": paid or known_paid}
    if len(text) > len(item.get("extrait") or ""):
        out["texte"] = text
    return out


def enrich(items: list[dict], paid_sources: list[str], report: list[str]) -> list[dict]:
    if not items:
        return items
    paid = {s.strip().lower() for s in paid_sources}
    with ThreadPoolExecutor(max_workers=8) as pool:
        result = list(pool.map(lambda it: enrich_one(it, paid), items))
    read = sum(1 for it in result if it.get("texte"))
    locked = sum(1 for it in result if it.get("payant"))
    report.append(f"Lecture : {read} articles lus sur {len(items)} ; {locked} réservés aux abonnés")
    return result
