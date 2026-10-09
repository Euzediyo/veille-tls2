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

from . import analyze, avis, collect, enrich, notify, podcast, prefilter, site, store

CONFIG = Path(__file__).resolve().parent.parent / "config"


def load_yaml(name: str) -> dict:
    return yaml.safe_load((CONFIG / name).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", action="store_true", help="régénérer seulement le site")
    parser.add_argument("--reanalyser", type=int, metavar="JOURS", default=0,
                        help="relire et réanalyser les articles des derniers jours (après un changement de consignes)")
    parser.add_argument("--lettre", action="store_true", help="envoyer la lettre de la semaine aujourd'hui, quel que soit le jour")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    profile, sources, site_cfg = load_yaml("profil.yaml"), load_yaml("sources.yaml"), load_yaml("site.yaml")
    today = datetime.now(ZoneInfo("Europe/Paris")).date()
    report: list[str] = []

    # Avis « non pertinent » envoyés depuis le site : ils guident l'IA dès ce passage.
    avis.collect(report, today.isoformat())
    learned = avis.prompt_block(avis.load(), profile)

    if args.reanalyser and os.environ.get("ANTHROPIC_API_KEY"):
        recent = store.load_articles(days=args.reanalyser, today=today)[: site_cfg.get("max_articles_ia", 120)]
        report.append(f"Réanalyse : {len(recent)} articles des {args.reanalyser} derniers jours")
        store.replace_articles(analyze.analyze(enrich.enrich(recent, sources.get("sources_payantes") or [], report), profile, site_cfg["modele"], report, learned))

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

        candidates = enrich.enrich(candidates, sources.get("sources_payantes") or [], report)
        analysed = analyze.analyze(candidates, profile, site_cfg["modele"], report, learned)

        # Articles récents notés par mots-clés faute d'IA : ils sont analysés dès que l'IA est disponible.
        if os.environ.get("ANTHROPIC_API_KEY"):
            pending = [it for it in store.load_articles(days=3, today=today) if it.get("analyse_par") == "mots-clés"]
            pending = [it for it in pending if it["id"] not in {a["id"] for a in analysed}][: site_cfg.get("max_articles_ia", 120)]
            if pending:
                report.append(f"Rattrapage : {len(pending)} articles récents notés par mots-clés")
                store.replace_articles(analyze.analyze(pending, profile, site_cfg["modele"], report, learned))
        store.add_articles(analysed, today)
        store.save_seen(seen, fresh, today)

        try:
            notify.send_digest(analysed, site_cfg, profile, today.isoformat(), report)
        except Exception as exc:  # un e-mail raté ne doit pas bloquer la publication
            report.append(f"E-mail : échec ({exc.__class__.__name__}: {exc})")

    articles = store.load_articles()
    site.build(profile, site_cfg, articles, today)
    report.append("Site : régénéré")
    if not args.site or args.lettre:
        try:
            notify.send_weekly(articles, site_cfg, profile, today, report, force=args.lettre)
        except Exception as exc:  # un e-mail raté ne doit pas bloquer la publication
            report.append(f"Lettre de la semaine : échec ({exc.__class__.__name__}: {exc})")
    try:
        if not args.site:
            podcast.make_episode(articles, profile, site_cfg, today, report)
        podcast.publish(site_cfg, today, report)
    except Exception as exc:  # le flash audio ne doit jamais bloquer la publication du journal
        report.append(f"Podcast : échec ({exc.__class__.__name__}: {exc})")
    store.save_report(report, today)
    print("\n".join(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
