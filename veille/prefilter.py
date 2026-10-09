"""Dédoublonnage et préfiltrage par mots-clés, avant tout appel à l'IA."""

from __future__ import annotations

import re
import unicodedata


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", text)


def _title_key(title: str) -> str:
    return " ".join(normalize(title).split())[:80]


def keyword_hits(item: dict, profile: dict) -> dict[str, int]:
    """Nombre de mots-clés trouvés par catégorie dans le titre et l'extrait."""
    haystack = " " + " ".join(normalize(item["titre"] + " " + item["extrait"]).split()) + " "
    hits = {}
    for key, cat in profile["categories"].items():
        count = 0
        for kw in cat["mots_cles"]:
            needle = " " + " ".join(normalize(str(kw)).split()) + " "
            if needle.strip() and needle in haystack:
                count += 1
        if count:
            hits[key] = count
    return hits


def is_excluded(item: dict, profile: dict) -> bool:
    text = normalize(item["titre"])
    return any(normalize(word).strip() in text for word in profile.get("exclusions", []))


def deduplicate(items: list[dict], seen: dict) -> list[dict]:
    """Retire les articles déjà traités (même lien ou même titre)."""
    out, titles = [], set()
    for item in items:
        tkey = _title_key(item["titre"])
        if not item["titre"] or item["id"] in seen or ("t:" + tkey) in seen or tkey in titles:
            continue
        titles.add(tkey)
        out.append(item)
    return out


def prefilter(items: list[dict], profile: dict, limit: int) -> list[dict]:
    """Garde les candidats plausibles, les plus prometteurs d'abord, dans la limite donnée."""
    kept = []
    for item in items:
        if is_excluded(item, profile):
            continue
        hits = keyword_hits(item, profile)
        if item.get("filtre") == "mots_cles" and not hits:
            continue
        item["mots_cles_trouves"] = hits
        kept.append(item)
    kept.sort(key=lambda it: sum(it["mots_cles_trouves"].values()), reverse=True)
    return kept[:limit]
