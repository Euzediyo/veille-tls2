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

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]

# Libellés des dimensions de l'analyse, pour le site, la synthèse et le podcast.
LABELS = {
    "pertinence": {"directe": "pertinence directe", "indirecte": "pertinence indirecte", "faible": "pertinence faible"},
    "urgence": {"immediate": "action immédiate", "a_anticiper": "à anticiper", "information": "information"},
    "statut": {"texte_publie": "texte publié", "proposition": "proposition", "negociation": "négociation",
               "annonce": "annonce", "rumeur": "rumeur"},
    "perimetre": {"france": "France", "union_europeenne": "Union européenne", "autre_pays": "autre pays"},
}
DEADLINE_TYPES = {"obligation": "Obligation", "consultation": "Consultation", "evenement": "Événement",
                  "annonce_non_confirmee": "Annonce non confirmée", "": "À vérifier"}


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


# ---------- Contenu réellement lu ----------

CONTENT_LABELS = {"article": "début de l'article analysé", "extrait": "extrait uniquement", "titre": "titre uniquement"}


def content_level(item: dict) -> str:
    """Ce qui a réellement été lu, d'après l'extraction (pas d'après l'IA) : « article » si le début
    de l'article a pu être lu, « extrait » si la source fournit un vrai extrait, « titre » sinon."""
    if item.get("texte"):
        return "article"
    if item.get("origine") == "page":
        return "titre"
    rest = _padded(item.get("extrait") or "")
    for part in (item.get("titre", ""), item.get("source", "")):
        needle = " ".join(normalize(part).split())
        if needle:
            rest = rest.replace(f" {needle} ", " ")
    return "extrait" if len(rest.strip()) >= 60 else "titre"


# ---------- Échéances ----------

def deadline(it: dict) -> dict | None:
    """Échéance d'un article, complétée pour la publication. Une échéance enregistrée avant la
    précision des dates n'est pas présentée comme vérifiée : sa précision devient « a_verifier »
    jusqu'à sa réanalyse."""
    due = it.get("echeance")
    if not due or not due.get("libelle"):
        return None
    out = {"type": "", "periode": "", "justification": "", **due}
    out.setdefault("precision", "a_verifier")
    out["source"] = due.get("source") or it.get("source", "")
    out["url"] = due.get("url") or it.get("url", "")
    out["cle"] = deadline_key(out, it.get("groupe"))
    return out


def deadline_key(due: dict, group: str | None = None) -> str:
    """Clé de dédoublonnage : même date (ou même mois) et même libellé, une fois normalisés. Pour des
    articles qui relatent le même événement, même date suffit : leurs libellés varient souvent."""
    when = due.get("date") or due.get("periode") or "?"
    if group:
        return f"{when}|groupe:{group}"
    words = [w for w in normalize(due.get("libelle", "")).split() if len(w) > 2][:8]
    return when + "|" + " ".join(words)


def unverified_deadline(it: dict) -> bool:
    """Échéance enregistrée sans précision de date : à réanalyser."""
    return bool(it.get("echeance")) and "precision" not in it["echeance"]


def deadline_text(due: dict) -> str:
    """Date d'une échéance, telle qu'elle est connue : jamais plus précise que la source."""
    raw, precision = due.get("date") or "", due.get("precision")
    if precision == "jour" and len(raw) == 10:
        d = date.fromisoformat(raw)
        return f"{d.day} {MOIS[d.month - 1]} {d.year}"
    if precision == "mois" and len(raw) >= 7:
        return f"{MOIS[int(raw[5:7]) - 1].capitalize()} {raw[:4]} — date à confirmer"
    if precision == "periode":
        return f"{due.get('periode') or raw} (période approximative)"
    if precision == "a_verifier" and len(raw) == 10:
        d = date.fromisoformat(raw)
        return f"{d.day} {MOIS[d.month - 1]} {d.year} (date non vérifiée, à réanalyser)"
    return "date inconnue"


def describe(it: dict) -> list[str]:
    """Lignes décrivant les dimensions d'un article (pour la synthèse et le podcast)."""
    lines = []
    dims = [LABELS[k].get(it.get(k) or "") for k in ("pertinence", "urgence", "statut", "perimetre")]
    if any(dims):
        lines.append("Pertinence : {} ; urgence : {} ; statut : {} ; périmètre : {}".format(*[d or "non précisé" for d in dims]))
    if it.get("contenu"):
        lines.append(f"Contenu réellement lu : {CONTENT_LABELS[it['contenu']]}")
    if it.get("qui_concerne"):
        lines.append(f"Qui est concerné : {it['qui_concerne']}")
    if it.get("verifications"):
        lines.append(f"À vérifier : {it['verifications']}")
    due = deadline(it)
    if due:
        kind = DEADLINE_TYPES.get(due["type"], "À vérifier")
        lines.append(f"Échéance ({kind.lower()}) : {deadline_text(due)}, {due['libelle']}")
    return lines


def deadline_between(due: dict, start: str, end: str) -> bool:
    """L'échéance tombe-t-elle entre deux dates ? Un mois compte s'il chevauche la période."""
    raw = due.get("date") or ""
    if len(raw) == 10:
        return start <= raw <= end
    if len(raw) == 7:
        return start[:7] <= raw <= end[:7]
    return False


def unique_deadlines(items: list[dict]) -> list[tuple[dict, dict]]:
    """Une seule fois chaque échéance (même date, même libellé), avec l'article qui la justifie le
    mieux (texte publié et meilleur score d'abord). Renvoie des couples (échéance, article)."""
    best: dict[str, tuple[dict, dict]] = {}
    for it in sorted(items, key=lambda it: (it.get("statut") != "texte_publie", -it.get("score", 0))):
        due = deadline(it)
        if due and due["cle"] not in best:
            best[due["cle"]] = (due, it)
    return sorted(best.values(), key=lambda pair: pair[0].get("date") or "9999")
