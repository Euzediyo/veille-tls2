"""Lecture du début de chaque article retenu, pour donner à l'IA plus que le titre et repérer
les articles réservés aux abonnés.

Le texte lu sert uniquement à l'analyse : il n'est ni enregistré ni publié. Le fichier robots.txt
de chaque site est respecté ; un article illisible garde simplement son extrait d'origine.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup

from .collect import USER_AGENT, allowed_by_robots

TIMEOUT = 15
MAX_CHARS = 2500
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 " + USER_AGENT
PAYWALL_PHRASES = ("réservé aux abonnés", "article réservé", "cet article est réservé", "contenu réservé aux abonnés",
                   "abonnez-vous pour lire", "pour lire la suite de cet article", "la suite est réservée")


def decode_google_news(url: str) -> str:
    """Adresse réelle de l'article derrière un lien Google Actualités (le lien d'origine sinon)."""
    parts = urllib.parse.urlsplit(url)
    segments = parts.path.split("/")
    if parts.netloc != "news.google.com" or "articles" not in segments:
        return url
    gid = segments[-1]
    page = requests.get(f"https://news.google.com/rss/articles/{gid}", headers={"User-Agent": BROWSER_UA}, timeout=TIMEOUT)
    page.raise_for_status()
    div = BeautifulSoup(page.text, "html.parser").select_one("c-wiz > div[jscontroller]")
    if div is None or not div.get("data-n-a-sg"):
        return url
    inner = ('["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
             f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{gid}",{div["data-n-a-ts"]},"{div["data-n-a-sg"]}"]')
    body = "f.req=" + urllib.parse.quote(json.dumps([[["Fbv4je", inner, None, "generic"]]]))
    res = requests.post("https://news.google.com/_/DotsSplashUi/data/batchexecute", data=body, timeout=TIMEOUT,
                        headers={"User-Agent": BROWSER_UA, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
    res.raise_for_status()
    rows = json.loads(res.text.split("\n\n", 1)[1])
    real = json.loads(rows[0][2])[1]
    return real if isinstance(real, str) and real.startswith("http") else url


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


def enrich_one(item: dict) -> dict:
    url = item["url"]
    try:
        url = decode_google_news(url)
    except (requests.RequestException, ValueError, IndexError, KeyError, TypeError):
        pass
    if "news.google.com" in url or not allowed_by_robots(url):
        return {**item, "url": url}
    try:
        res = requests.get(url, headers={"User-Agent": BROWSER_UA, "Accept-Language": "fr-FR,fr;q=0.9"}, timeout=TIMEOUT)
        res.raise_for_status()
        if "html" not in res.headers.get("Content-Type", "html"):
            return {**item, "url": url}
        text, paid = read_page(res.text)
    except requests.RequestException:
        return {**item, "url": url}
    out = {**item, "url": res.url or url, "payant": paid}
    if len(text) > len(item.get("extrait") or ""):
        out["texte"] = text
    return out


def enrich(items: list[dict], report: list[str]) -> list[dict]:
    if not items:
        return items
    with ThreadPoolExecutor(max_workers=8) as pool:
        result = list(pool.map(enrich_one, items))
    read = sum(1 for it in result if it.get("texte"))
    paid = sum(1 for it in result if it.get("payant"))
    report.append(f"Lecture : {read} articles lus sur {len(items)}, dont {paid} réservés aux abonnés")
    return result
