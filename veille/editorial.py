"""Sélection éditoriale appliquée à chaque publication, y compris aux articles déjà enregistrés :
articles hors métier (télésurveillance médicale), ressources de fond (articles anciens découverts
tardivement), niveaux de lecture (veille essentielle ou élargie) et regroupement des articles qui
relatent le même événement.

Rien n'est réécrit dans data/articles : les identifiants, les favoris et l'état lu / non lu des
lecteurs restent valables quand les réglages changent.
"""

from __future__ import annotations

from datetime import date, datetime

from .prefilter import normalize

BACKGROUND_DAYS = 30


def _padded(text: str) -> str:
    return " " + " ".join(normalize(text).split()) + " "


def _found(haystack: str, terms: list) -> bool:
    for term in terms or []:
        needle = " ".join(normalize(str(term)).split())
        if needle and f" {needle} " in haystack:
            return True
    return False


def off_domain(item: dict, profile: dict) -> bool:
    """Télésurveillance médicale sans lien avec la sécurité : terme médical présent, aucun terme de sécurité.

    On lit le titre et l'extrait d'origine, pas le résumé de l'IA (qui peut expliquer, par exemple,
    que l'article « n'a pas de lien avec la levée de doute »).
    """
    rule = profile.get("hors_metier_medical") or {}
    haystack = _padded(f"{item.get('titre', '')} {item.get('extrait', '')}")
    return _found(haystack, rule.get("termes_medicaux")) and not _found(haystack, rule.get("termes_securite"))


def published_on(item: dict) -> date | None:
    """Date de publication donnée par la source, ou None si elle est inconnue."""
    try:
        return datetime.fromisoformat(item.get("date") or "").date()
    except ValueError:
        return None


def is_background(item: dict, profile: dict) -> bool:
    """Article ancien découvert tardivement : ressource de fond, pas une actualité."""
    published = published_on(item)
    if not published or not item.get("edition"):
        return False
    age = (date.fromisoformat(item["edition"]) - published).days
    return age > profile.get("ressources_de_fond_jours", BACKGROUND_DAYS)


def level(item: dict, profile: dict) -> str:
    """« essentielle » (impact direct, forte pertinence métier) ou « elargie » (information indirecte)."""
    rule = profile.get("veille_essentielle") or {}
    if item["score"] >= rule.get("score_min", 70):
        return "essentielle"
    if item["categorie"] in (rule.get("categories_coeur") or []) and item["score"] >= rule.get("score_min_coeur", 60):
        return "essentielle"
    return "elargie"


def publishable(item: dict, profile: dict) -> bool:
    return (item["score"] >= profile.get("seuil_publication", 30) and item["categorie"] != "hors_sujet"
            and not item.get("non_pertinent") and not off_domain(item, profile))


def annotate(articles: list[dict], profile: dict, groups: list[list[str]]) -> list[dict]:
    """Copies des articles avec « fond », « niveau » et « groupe » (identifiant commun aux articles
    qui relatent le même événement, absent pour un article seul)."""
    key = {}
    for ids in groups:
        if len(ids) > 1:
            for i in ids:
                key[i] = min(ids)
    out = []
    for it in articles:
        extra = {"fond": is_background(it, profile), "niveau": level(it, profile)}
        if it["id"] in key:
            extra["groupe"] = key[it["id"]]
        out.append({**it, **extra})
    return out


def collapse(items: list[dict]) -> list[dict]:
    """Une seule fiche par événement : la première de la liste (la mieux classée) devient la fiche
    principale, les autres sont rangées dans « reprises ». L'ordre de la liste est conservé."""
    out, principal = [], {}
    for it in items:
        g = it.get("groupe")
        if g and g in principal:
            principal[g]["reprises"].append(it)
            continue
        copy = {**it, "reprises": []}
        if g:
            principal[g] = copy
        out.append(copy)
    return out
