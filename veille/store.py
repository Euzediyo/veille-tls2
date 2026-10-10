"""Stockage des articles et de l'état entre deux passages, dans le dossier data/."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from .prefilter import _title_key

DATA = Path(__file__).resolve().parent.parent / "data"
SEEN_DAYS = 60


def _read(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def load_seen() -> dict:
    return _read(DATA / "seen.json", {})


def save_seen(seen: dict, items: list[dict], today: date) -> None:
    for item in items:
        seen[item["id"]] = today.isoformat()
        seen["t:" + _title_key(item["titre"])] = today.isoformat()
    limit = (today - timedelta(days=SEEN_DAYS)).isoformat()
    _write(DATA / "seen.json", {k: v for k, v in seen.items() if v >= limit})


def load_pages_state() -> dict:
    return _read(DATA / "pages.json", {})


def save_pages_state(state: dict) -> None:
    _write(DATA / "pages.json", state)


def _storable(item: dict) -> dict:
    """Le texte lu sur la page de l'article sert seulement à l'analyse : il n'est jamais enregistré."""
    return {k: v for k, v in item.items() if k != "texte"}


def add_articles(items: list[dict], today: date) -> None:
    path = DATA / "articles" / f"{today:%Y-%m}.json"
    existing = _read(path, [])
    known = {it["id"] for it in existing}
    for item in items:
        if item["id"] not in known:
            existing.append({**_storable(item), "edition": today.isoformat()})
    _write(path, existing)


def replace_articles(items: list[dict]) -> None:
    """Remplace des articles déjà stockés (même identifiant), par exemple après une nouvelle analyse."""
    by_id = {it["id"]: it for it in items}
    for path in sorted((DATA / "articles").glob("*.json")):
        existing = _read(path, [])
        if any(it["id"] in by_id for it in existing):
            _write(path, [{**_storable(by_id[it["id"]]), "edition": it["edition"]} if it["id"] in by_id else it for it in existing])


def load_articles(days: int | None = None, today: date | None = None) -> list[dict]:
    items = []
    for path in sorted((DATA / "articles").glob("*.json")):
        items += _read(path, [])
    if days is not None and today is not None:
        limit = (today - timedelta(days=days)).isoformat()
        items = [it for it in items if it["edition"] >= limit]
    return items


def save_collect_time(when: datetime) -> None:
    _write(DATA / "derniere-collecte.json", {"heure": when.isoformat(timespec="minutes")})


def load_collect_time() -> datetime | None:
    value = _read(DATA / "derniere-collecte.json", {}).get("heure")
    return datetime.fromisoformat(value) if value else None


def save_report(report: list[str], today: date) -> None:
    _write(DATA / "dernier-passage.json", {"date": today.isoformat(), "journal": report})
