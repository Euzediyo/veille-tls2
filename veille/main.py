"""Passage quotidien : collecter, dédoublonner, préfiltrer, analyser, publier, prévenir.

Usage : python -m veille.main            (passage complet)
        python -m veille.main --site     (régénère seulement le site à partir des données)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import analyze, collect, notify, prefilter, site, store

CONFIG = Path(__file__).resolve().parent.parent / "config"


def load_yaml(name: str) -> dict:
    return yaml.safe_load((CONFIG / name).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", action="store_true", help="régénérer seulement le site")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    profile, sources, site_cfg = load_yaml("profil.yaml"), load_yaml("sources.yaml"), load_yaml("site.yaml")
    today = datetime.now(ZoneInfo("Europe/Paris")).date()
    report: list[str] = []

    if not args.site:
        raw = collect.collect_google_news(sources.get("google_news") or [], report)
        raw += collect.collect_rss(sources.get("rss") or [], report)
        pages_state = store.load_pages_state()
        raw += collect.collect_pages(sources.get("pages") or [], pages_state, report)
        store.save_pages_state(pages_state)

        seen = store.load_seen()
        fresh = prefilter.deduplicate(raw, seen)
        candidates = prefilter.prefilter(fresh, profile, site_cfg.get("max_articles_ia", 120))
        report.append(f"Collecte : {len(raw)} articles, {len(fresh)} nouveaux, {len(candidates)} envoyés à l'analyse")

        analysed = analyze.analyze(candidates, profile, site_cfg["modele"], report)

        # Articles récents notés par mots-clés faute d'IA : ils sont analysés dès que l'IA est disponible.
        if os.environ.get("ANTHROPIC_API_KEY"):
            pending = [it for it in store.load_articles(days=3, today=today) if it.get("analyse_par") == "mots-clés"]
            pending = [it for it in pending if it["id"] not in {a["id"] for a in analysed}][: site_cfg.get("max_articles_ia", 120)]
            if pending:
                report.append(f"Rattrapage : {len(pending)} articles récents notés par mots-clés")
                store.replace_articles(analyze.analyze(pending, profile, site_cfg["modele"], report))
        store.add_articles(analysed, today)
        store.save_seen(seen, fresh, today)

        try:
            notify.send_digest(analysed, site_cfg, profile, today.isoformat(), report)
        except Exception as exc:  # un e-mail raté ne doit pas bloquer la publication
            report.append(f"E-mail : échec ({exc.__class__.__name__}: {exc})")

    site.build(profile, site_cfg, store.load_articles(), today)
    report.append("Site : régénéré")
    store.save_report(report, today)
    print("\n".join(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
