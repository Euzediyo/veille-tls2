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

from . import analyze, avis, collect, editorial, enrich, evenements, notify, podcast, prefilter, semaine, site, store

CONFIG = Path(__file__).resolve().parent.parent / "config"
MAX_DEADLINE_CHECKS = 40


def load_yaml(name: str) -> dict:
    return yaml.safe_load((CONFIG / name).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", action="store_true", help="régénérer seulement le site")
    parser.add_argument("--semaine", action="store_true", help="mettre à jour le résumé de la semaine même sans collecte")
    parser.add_argument("--reanalyser", type=int, metavar="JOURS", default=0,
                        help="relire et réanalyser les articles des derniers jours (après un changement de consignes)")
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

    # Échéances enregistrées avant la précision des dates : relues et réanalysées une fois, pour ne pas
    # présenter comme vérifiée une date peut-être approximative (« premier du mois » par défaut).
    if os.environ.get("ANTHROPIC_API_KEY"):
        old = [it for it in store.load_articles() if editorial.unverified_deadline(it)][:MAX_DEADLINE_CHECKS]
        if old:
            redone = analyze.analyze(enrich.enrich(old, sources.get("sources_payantes") or [], report), profile,
                                     site_cfg["modele"], report, learned)
            redone = [it for it in redone if it.get("analyse_par") == site_cfg["modele"]]  # jamais remplacé par les mots-clés
            store.replace_articles(redone)
            report.append(f"Échéances : {len(redone)} anciennes dates réanalysées sur {len(old)}")

    if not args.site:
        raw = collect.collect_google_news(sources.get("google_news") or [], report)
        raw += collect.collect_rss(sources.get("rss") or [], report)
        pages_state = store.load_pages_state()
        raw += collect.collect_pages(sources.get("pages") or [], pages_state, report)
        store.save_pages_state(pages_state)
        intl = sources.get("international") or {}
        raw += collect.collect_google_news(intl.get("google_news") or [], report, international=True)
        raw += collect.collect_rss(intl.get("rss") or [], report, international=True)

        seen = store.load_seen()
        fresh = prefilter.deduplicate(raw, seen)
        # La presse internationale a son propre plafond : elle ne prend pas la place des sources françaises.
        candidates = prefilter.prefilter([it for it in fresh if not it.get("international")], profile, site_cfg.get("max_articles_ia", 120))
        foreign = prefilter.prefilter([it for it in fresh if it.get("international")], profile, site_cfg.get("max_articles_international", 40))
        report.append(f"Collecte : {len(raw)} articles, {len(fresh)} nouveaux, {len(candidates) + len(foreign)} envoyés à l'analyse"
                      f" (dont {len(foreign)} internationaux)")
        candidates += foreign

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
        store.save_collect_time(datetime.now(ZoneInfo("Europe/Paris")))
        store.save_seen(seen, fresh, today)

        try:
            notify.send_digest(analysed, site_cfg, profile, today.isoformat(), report)
        except Exception as exc:  # un e-mail raté ne doit pas bloquer la publication
            report.append(f"E-mail : échec ({exc.__class__.__name__}: {exc})")

    articles = store.load_articles()
    try:
        # Après une collecte, les groupes sont recalculés ; une simple republication le fait au plus une fois par jour.
        evenements.update(articles, profile, site_cfg["modele"], today, report, force=not args.site)
    except Exception as exc:  # le regroupement ne doit pas bloquer la publication
        report.append(f"Regroupement : échec ({exc.__class__.__name__}: {exc})")
    groups = evenements.groups()
    # Ressources de fond, niveau de veille et événement commun, calculés à chaque publication.
    articles = editorial.annotate(articles, profile, groups)
    if not args.site or args.semaine:
        try:
            semaine.update(articles, profile, site_cfg["modele"], today, report)
        except Exception as exc:  # le résumé de la semaine ne doit pas bloquer la publication
            report.append(f"Semaine : échec ({exc.__class__.__name__}: {exc})")
    site.build(profile, site_cfg, articles, today, groups)
    report.append("Site : régénéré")
    try:
        # Un épisode manqué (voix de synthèse en panne) est refait à la publication suivante.
        if not args.site or not podcast.has_episode(today):
            podcast.make_episode(articles, profile, site_cfg, today, report)
        podcast.publish(site_cfg, today, report)
    except Exception as exc:  # le flash audio ne doit jamais bloquer la publication du journal
        report.append(f"Podcast : échec ({exc.__class__.__name__}: {exc})")
    if site.comptes(site_cfg):
        report.append(site.ping_comptes(site_cfg))
    store.save_report(report, today)
    print("\n".join(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
