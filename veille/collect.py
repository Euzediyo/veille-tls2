"""Collecte des articles : Google News, flux RSS directs et pages surveillées."""

from __future__ import annotations

import hashlib
import html
import logging
import re
import urllib.parse
import urllib.robotparser
from datetime import datetime, timezone

import feedparser
import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

USER_AGENT = "VeilleTLS/1.0 (+https://github.com/Euzediyo/veille-tls2)"
TIMEOUT = 20

_robots_cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def allowed_by_robots(url: str) -> bool:
    """Vrai si robots.txt du site autorise notre robot à lire cette adresse."""
    parts = urllib.parse.urlsplit(url)
    root = f"{parts.scheme}://{parts.netloc}"
    if root not in _robots_cache:
        rp = urllib.robotparser.RobotFileParser()
        try:
            resp = requests.get(root + "/robots.txt", headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
            if resp.status_code >= 400:
                rp = None  # pas de robots.txt : tout est permis
            else:
                rp.parse(resp.text.splitlines())
        except requests.RequestException:
            rp = None
        _robots_cache[root] = rp
    rp = _robots_cache[root]
    return rp is None or rp.can_fetch(USER_AGENT, url)


def item_id(url: str, title: str) -> str:
    return hashlib.sha1((url or title).encode("utf-8")).hexdigest()[:16]


def clean_text(raw: str, limit: int = 700) -> str:
    text = BeautifulSoup(raw or "", "html.parser").get_text(" ", strip=True)
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    return text[:limit]


def _entry_date(entry) -> str:
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def _fetch_feed(url: str):
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    resp.raise_for_status()
    return feedparser.parse(resp.content)


def google_news_url(query: str) -> str:
    q = urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={q}&hl=fr&gl=FR&ceid=FR:fr"


def collect_google_news(queries: list[str], report: list[str]) -> list[dict]:
    items = []
    for query in queries:
        try:
            feed = _fetch_feed(google_news_url(query))
        except requests.RequestException as exc:
            report.append(f"Google News « {query} » : échec ({exc.__class__.__name__})")
            continue
        for entry in feed.entries:
            title = entry.get("title", "")
            source = (entry.get("source") or {}).get("title", "")
            # Google News ajoute « - Nom du site » à la fin du titre.
            if source and title.endswith(" - " + source):
                title = title[: -len(source) - 3]
            items.append({
                "id": item_id(entry.get("link", ""), title),
                "titre": title.strip(),
                "url": entry.get("link", ""),
                "source": source or "Google News",
                "date": _entry_date(entry),
                "extrait": clean_text(entry.get("summary", "")),
                "origine": "google_news",
                "filtre": "aucun",
            })
        report.append(f"Google News « {query} » : {len(feed.entries)} résultats")
    return items


def collect_rss(feeds: list[dict], report: list[str]) -> list[dict]:
    items = []
    for feed_cfg in feeds:
        url, name = feed_cfg["url"], feed_cfg["nom"]
        if not allowed_by_robots(url):
            report.append(f"{name} : ignoré, le site refuse les robots (robots.txt)")
            continue
        try:
            feed = _fetch_feed(url)
        except requests.RequestException as exc:
            report.append(f"{name} : échec ({exc.__class__.__name__})")
            continue
        for entry in feed.entries:
            title = entry.get("title", "").strip()
            items.append({
                "id": item_id(entry.get("link", ""), title),
                "titre": title,
                "url": entry.get("link", ""),
                "source": name,
                "date": _entry_date(entry),
                "extrait": clean_text(entry.get("summary", "")),
                "origine": "rss",
                "filtre": feed_cfg.get("filtre", "aucun"),
            })
        report.append(f"{name} : {len(feed.entries)} articles")
    return items


def collect_pages(pages: list[dict], state: dict, report: list[str]) -> list[dict]:
    """Signale les liens apparus depuis le dernier passage sur des pages sans RSS.

    Au premier passage, les liens existants servent de référence et ne sont pas signalés.
    """
    items = []
    for page in pages:
        url, name = page["url"], page["nom"]
        if not allowed_by_robots(url):
            report.append(f"{name} : ignoré, le site refuse les robots (robots.txt)")
            continue
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as exc:
            report.append(f"{name} : échec ({exc.__class__.__name__})")
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["nav", "header", "footer", "script", "style"]):
            tag.decompose()
        must_contain = page.get("lien_contient", "")
        links = {}
        for a in soup.find_all("a", href=True):
            href = urllib.parse.urljoin(url, a["href"]).split("#")[0]
            label = a.get_text(" ", strip=True)
            if len(label) < 12 or (must_contain and must_contain not in href) or href == url:
                continue
            links.setdefault(href, label)
        known = set(state.get(url, []))
        first_run = url not in state
        new_links = [] if first_run else [h for h in links if h not in known]
        for href in new_links:
            items.append({
                "id": item_id(href, links[href]),
                "titre": links[href],
                "url": href,
                "source": name,
                "date": datetime.now(timezone.utc).isoformat(),
                "extrait": f"Nouveau contenu repéré sur la page « {name} ».",
                "origine": "page",
                "filtre": "aucun",
            })
        state[url] = sorted(known | set(links))
        if first_run:
            report.append(f"{name} : {len(links)} liens enregistrés comme référence")
        else:
            report.append(f"{name} : {len(new_links)} nouveaux liens")
    return items
