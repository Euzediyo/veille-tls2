"""Retrouver l'adresse de l'article d'origine derrière un lien Google Actualités.

Les liens Google Actualités ne sont pas suivis (le robots.txt de Google l'interdit aux robots). Le
flux donne en revanche le site de l'éditeur. On cherche donc l'article chez l'éditeur lui-même, par
son titre, dans ce que le site publie pour les moteurs et les lecteurs de flux :
- le plan de site « actualités » (sitemap news) annoncé dans son robots.txt ;
- les flux RSS annoncés sur sa page d'accueil.
Chaque lecture respecte le robots.txt du site. Rien n'est trouvé : l'article garde son lien Google.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from xml.etree import ElementTree

import feedparser
import requests
from bs4 import BeautifulSoup

from .collect import TIMEOUT, USER_AGENT, _robots_cache, allowed_by_robots

MAX_BYTES = 8_000_000
MAX_SITEMAPS = 4
MAX_FEEDS = 3
MATCH = 0.9


def normalize(title: str) -> str:
    text = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _get(url: str) -> bytes | None:
    if not allowed_by_robots(url):
        return None
    try:
        res = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, stream=True)
        if res.status_code >= 400:
            return None
        body = res.raw.read(MAX_BYTES + 1, decode_content=True)
        return None if len(body) > MAX_BYTES else body
    except (requests.RequestException, OSError):
        return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_sitemap(body: bytes) -> tuple[list[str], list[tuple[str, str]]]:
    """(sous-plans à lire, [(titre, adresse)]) d'un plan de site, index ou plan « actualités »."""
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return [], []
    children, entries = [], []
    for node in root:
        name = _local(node.tag)
        loc = next((c.text.strip() for c in node.iter() if _local(c.tag) == "loc" and c.text), "")
        if name == "sitemap" and loc:
            children.append(loc)
        elif name == "url" and loc:
            title = next((c.text.strip() for c in node.iter() if _local(c.tag) == "title" and c.text), "")
            if title:
                entries.append((title, loc))
    return children, entries


def _news_first(urls: list[str]) -> list[str]:
    news = [u for u in urls if re.search(r"news|actu", u, re.I)]
    return news[:MAX_SITEMAPS]


def _sitemaps(root: str) -> list[tuple[str, str]]:
    allowed_by_robots(root + "/")  # charge le robots.txt du site
    rp = _robots_cache.get(root)
    listed = (rp.site_maps() if rp else None) or []
    out, todo, seen = [], _news_first(listed), set()
    while todo and len(seen) < MAX_SITEMAPS * 2:
        url = todo.pop(0)
        if url in seen:
            continue
        seen.add(url)
        body = _get(url)
        if not body:
            continue
        children, entries = parse_sitemap(body)
        out += entries
        todo += _news_first(children) or children[:1]
    return out


def _feeds(root: str) -> list[tuple[str, str]]:
    body = _get(root + "/")
    if not body:
        return []
    soup = BeautifulSoup(body, "html.parser")
    links = [urllib.parse.urljoin(root + "/", l.get("href"))
             for l in soup.find_all("link", rel="alternate", href=True)
             if "rss" in (l.get("type") or "") or "atom" in (l.get("type") or "")]
    out = []
    for url in links[:MAX_FEEDS]:
        feed = _get(url)
        if feed:
            out += [(e.get("title", ""), e.get("link", "")) for e in feedparser.parse(feed).entries if e.get("link")]
    return out


def site_index(root: str) -> dict[str, str]:
    """Titre normalisé → adresse, pour les articles récents d'un site."""
    index = {}
    for title, url in _sitemaps(root) + _feeds(root):
        key = normalize(title)
        if key and urllib.parse.urlsplit(url).scheme in ("http", "https"):
            index.setdefault(key, url)
    return index


def find(titles: list[str], index: dict[str, str]) -> str | None:
    for title in titles:
        key = normalize(title)
        if len(key) < 15:
            continue
        if key in index:
            return index[key]
        close = difflib.get_close_matches(key, list(index), n=1, cutoff=MATCH)
        if close:
            return index[close[0]]
    return None


def root_of(site: str) -> str:
    parts = urllib.parse.urlsplit(site or "")
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme in ("http", "https") and parts.netloc else ""


def candidates(item: dict) -> list[str]:
    """Titres possibles de l'article : le titre collecté, et l'extrait Google (« titre  Nom du site »)."""
    out = [item.get("titre", "")]
    extract, source = item.get("extrait") or "", item.get("source") or ""
    if source and extract.endswith(source):
        out.append(extract[: -len(source)].strip())
    return [t for t in out if t]


def resolve(items: list[dict]) -> dict[str, str]:
    """Identifiant d'article Google Actualités → adresse de l'article chez l'éditeur."""
    wanted = [it for it in items if "news.google.com" in it.get("url", "") and root_of(it.get("site", ""))]
    roots = sorted({root_of(it["site"]) for it in wanted})
    with ThreadPoolExecutor(max_workers=8) as pool:
        indexes = dict(zip(roots, pool.map(site_index, roots)))
    found = {}
    for it in wanted:
        url = find(candidates(it), indexes.get(root_of(it["site"])) or {})
        if url:
            found[it["id"]] = url
    return found
