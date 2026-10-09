"""Résumé de la semaine publié sur le site : une synthèse rédigée par l'IA, les articles à retenir
et les échéances à venir.

La semaine va du lundi au dimanche. Chaque passage met à jour la semaine en cours ; le premier
passage d'une nouvelle semaine termine le résumé de la précédente. Les résumés sont gardés dans
data/semaines.json.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import anthropic

from .site import MOIS
from .store import DATA, _read, _write

WEEKS = DATA / "semaines.json"
TOP = 10

SYSTEM = """Tu rédiges la synthèse hebdomadaire du journal « Veille TLS », destinée aux responsables
et aux opérateurs de centres de télésurveillance.

À partir des articles de la semaine (classés du plus important au moins important), écris
un texte de 120 à 200 mots, en deux ou trois paragraphes :
- ce qu'il faut retenir de la semaine, en regroupant les sujets qui vont ensemble ;
- ce que cela change concrètement pour un centre de télésurveillance ;
- les actions ou échéances à ne pas manquer, s'il y en a.

Règles : uniquement les informations fournies, sans rien inventer ; cite le média ou
l'organisme quand c'est utile ; vouvoiement ; texte brut, sans titre, sans liste, sans markdown
ni émoji, paragraphes séparés par une ligne vide."""


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def label(start: date) -> str:
    end = start + timedelta(days=6)
    if start.month == end.month:
        return f"Semaine du {start.day} au {end.day} {MOIS[end.month - 1]} {end.year}"
    return f"Semaine du {start.day} {MOIS[start.month - 1]} au {end.day} {MOIS[end.month - 1]} {end.year}"


def select(articles: list[dict], start: date, seuil: int = 50) -> tuple[list[dict], list[dict]]:
    """Articles à retenir de la semaine et échéances des 60 jours suivant sa fin."""
    end = start + timedelta(days=6)
    pool = [it for it in articles if start.isoformat() <= it["edition"] <= end.isoformat()
            and it["categorie"] != "hors_sujet" and not it.get("non_pertinent")]
    top = sorted([it for it in pool if it["score"] >= seuil], key=lambda it: (-it["score"], it["edition"]))[:TOP]
    seen, due = set(), []
    horizon = (end + timedelta(days=60)).isoformat()
    for it in sorted((it for it in articles if it.get("echeance") and not it.get("non_pertinent")
                      and it["categorie"] != "hors_sujet"), key=lambda it: it["echeance"]["date"]):
        key = (it["echeance"]["date"], it["echeance"]["libelle"].lower())
        if start.isoformat() <= it["echeance"]["date"] <= horizon and key not in seen:
            seen.add(key)
            due.append(it)
    return top, due


def write_synthesis(items: list[dict], profile: dict, model: str, report: list[str]) -> str:
    if not items or not os.environ.get("ANTHROPIC_API_KEY"):
        return ""
    cats = profile["categories"]
    blocks = []
    for it in items:
        lines = [f"Titre : {it['titre']}", f"Source : {it['source']}",
                 f"Catégorie : {cats.get(it['categorie'], {}).get('nom', 'Autre')}", f"Score : {it['score']}"]
        for key, name in (("resume", "Résumé"), ("pourquoi", "Pourquoi c'est important"), ("action", "Action recommandée")):
            if it.get(key):
                lines.append(f"{name} : {it[key]}")
        if it.get("echeance"):
            lines.append(f"Échéance : {it['echeance']['date']} ({it['echeance']['libelle']})")
        blocks.append("\n".join(lines))
    try:
        response = anthropic.Anthropic().messages.create(
            model=model, max_tokens=3000, system=SYSTEM,
            messages=[{"role": "user", "content": "Articles de la semaine :\n\n" + "\n\n".join(blocks)}])
    except anthropic.APIError as exc:
        report.append(f"Semaine : synthèse indisponible ({exc.__class__.__name__})")
        return ""
    if response.stop_reason != "end_turn":
        return ""
    return next((b.text for b in response.content if b.type == "text"), "").strip()


def build_week(articles: list[dict], profile: dict, model: str, start: date, today: date, report: list[str]) -> dict:
    top, due = select(articles, start, profile.get("seuil_semaine", 50))
    # La synthèse s'appuie sur un peu plus d'articles que la liste affichée.
    pool = select(articles, start, 30)[0] if len(top) < 5 else top
    return {"lundi": start.isoformat(), "titre": label(start),
            "en_cours": today <= start + timedelta(days=6),
            "maj": today.isoformat(),
            "synthese": write_synthesis(pool, profile, model, report),
            "articles": [it["id"] for it in top],
            "echeances": [it["id"] for it in due]}


def update(articles: list[dict], profile: dict, model: str, today: date, report: list[str]) -> None:
    """Met à jour la semaine en cours et termine la précédente si besoin."""
    weeks = {w["lundi"]: w for w in _read(WEEKS, [])}
    current = monday(today)
    previous = (current - timedelta(days=7)).isoformat()
    if previous in weeks and weeks[previous].get("en_cours"):
        weeks[previous] = build_week(articles, profile, model, current - timedelta(days=7), today, report)
    weeks[current.isoformat()] = build_week(articles, profile, model, current, today, report)
    _write(WEEKS, sorted(weeks.values(), key=lambda w: w["lundi"]))
    report.append(f"Semaine : résumé mis à jour ({len(weeks[current.isoformat()]['articles'])} articles à retenir)")


def load() -> list[dict]:
    return _read(WEEKS, [])
