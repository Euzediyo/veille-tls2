"""Analyse des articles par l'IA : catégorie, résumé, score de pertinence et justification."""

from __future__ import annotations

import json
import logging
import os
from datetime import date

import anthropic

from .prefilter import keyword_hits

log = logging.getLogger(__name__)

BATCH_SIZE = 10


def build_system_prompt(profile: dict) -> str:
    cats = "\n".join(
        f"- {key} : {c['nom']} (priorité {c['priorite']}). {c['description'].strip()}"
        for key, c in profile["categories"].items()
    )
    bareme = "\n".join(f"- {lo}–{hi} {label} : {desc}" for lo, hi, label, desc in profile["bareme"])
    return f"""Tu rédiges le journal de veille quotidien d'un lecteur précis.

Lecteur : {profile['lecteur'].strip()}

Question clé à te poser pour chaque article : {profile['question_cle'].strip()}

Catégories :
{cats}
- hors_sujet : l'article ne relève d'aucune catégorie.

Barème du score de pertinence (0 à 100) :
{bareme}

Pour chaque article reçu, renvoie :
- categorie : la clé de la catégorie la plus adaptée.
- score : entier de 0 à 100 selon le barème, du point de vue de ce lecteur.
  Les textes officiels et les évolutions de référentiels qui s'appliquent à la
  télésurveillance méritent un score élevé. Les faits divers (un cambriolage, une
  agression) sont en général sous 30, sauf s'ils révèlent un enjeu pour les centres.
- titre : un titre clair en français, sans le nom du site.
- resume : un résumé en français, écrit avec tes propres mots, qui permet de comprendre
  l'essentiel sans ouvrir l'article : les faits, les acteurs, les chiffres et les dates utiles.
  Quatre à six phrases (70 à 120 mots) quand l'extrait est assez riche ; plus court s'il est
  maigre. Ne recopie jamais de phrase de l'article (droit d'auteur). Si tu ne disposes que du
  titre, dis-le sobrement en une phrase et n'invente aucun détail.
- pourquoi : une ou deux phrases qui expliquent le score pour ce lecteur, en nommant
  l'impact concret (procédures, formation des opérateurs, obligations, planning, outils...).
- action : si le score est d'au moins 70, une action concrète et courte que le responsable
  du centre peut mener (ex. « Mettre à jour la procédure de levée de doute vidéo »,
  « Informer les opérateurs lors du prochain briefing »). Sinon, chaîne vide.
- echeance_date et echeance_libelle : si l'article mentionne une date future qui crée une
  obligation ou un changement (entrée en vigueur, fin de consultation, date limite), la date
  au format AAAA-MM-JJ et un libellé court (ex. « Entrée en vigueur du décret formation »).
  Si le jour exact n'est pas connu, prends le premier jour du mois. Sinon, chaînes vides.

Tu ne connais l'article que par son titre et son extrait (parfois le début du texte) : base-toi
uniquement sur eux."""


SCHEMA = {
    "type": "object",
    "properties": {
        "analyses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "categorie": {"type": "string", "enum": [
                        "reglementation", "apsad", "social", "telesurveillance",
                        "marche", "management", "hors_sujet"]},
                    "score": {"type": "integer"},
                    "titre": {"type": "string"},
                    "resume": {"type": "string"},
                    "pourquoi": {"type": "string"},
                    "action": {"type": "string"},
                    "echeance_date": {"type": "string"},
                    "echeance_libelle": {"type": "string"},
                },
                "required": ["id", "categorie", "score", "titre", "resume", "pourquoi",
                             "action", "echeance_date", "echeance_libelle"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["analyses"],
    "additionalProperties": False,
}


def _article_block(item: dict) -> str:
    return (
        f"<article id=\"{item['id']}\">\n"
        f"Titre : {item['titre']}\nSource : {item['source']}\nDate : {item['date'][:10]}\n"
        f"Extrait : {item.get('texte') or item['extrait'] or '(aucun extrait disponible)'}\n</article>"
    )


def keyword_fallback(item: dict, profile: dict, reason: str) -> dict:
    """Notation de secours quand l'IA n'est pas disponible : simple comptage de mots-clés."""
    hits = item.get("mots_cles_trouves") or keyword_hits(item, profile)
    weights = {"très haute": 18, "haute": 15, "moyenne": 12}
    best, score = "hors_sujet", 0
    for key, count in hits.items():
        value = min(65, 20 + count * weights.get(profile["categories"][key]["priorite"], 12))
        if value > score:
            best, score = key, value
    return {
        "categorie": best,
        "score": score,
        "titre": item["titre"],
        "resume": "",
        "pourquoi": f"Score estimé par mots-clés ({reason}).",
        "action": "",
        "echeance": None,
        "analyse_par": "mots-clés",
    }


def _deadline(a: dict) -> dict | None:
    """Échéance proposée par l'IA, gardée seulement si la date est valide."""
    raw = (a.get("echeance_date") or "").strip()
    try:
        day = date.fromisoformat(raw)
    except ValueError:
        return None
    label = (a.get("echeance_libelle") or "").strip()
    return {"date": day.isoformat(), "libelle": label} if label else None


def analyze(items: list[dict], profile: dict, model: str, report: list[str]) -> list[dict]:
    if not items:
        return []
    if not os.environ.get("ANTHROPIC_API_KEY"):
        report.append("IA : aucune clé API configurée, notation par mots-clés uniquement")
        return [{**it, **keyword_fallback(it, profile, "IA non configurée")} for it in items]

    client = anthropic.Anthropic()
    system = [{"type": "text", "text": build_system_prompt(profile), "cache_control": {"type": "ephemeral"}}]
    results, tokens_in, tokens_out = [], 0, 0

    for start in range(0, len(items), BATCH_SIZE):
        batch = items[start:start + BATCH_SIZE]
        by_id = {it["id"]: it for it in batch}
        prompt = "Analyse ces articles :\n\n" + "\n\n".join(_article_block(it) for it in batch)
        try:
            response = client.messages.create(
                model=model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            )
        except anthropic.APIStatusError as exc:
            report.append(f"IA : erreur {exc.status_code} sur un lot, notation par mots-clés pour ce lot")
            results += [{**it, **keyword_fallback(it, profile, "erreur IA")} for it in batch]
            continue
        except anthropic.APIConnectionError:
            report.append("IA : connexion impossible sur un lot, notation par mots-clés pour ce lot")
            results += [{**it, **keyword_fallback(it, profile, "erreur IA")} for it in batch]
            continue

        tokens_in += response.usage.input_tokens + (response.usage.cache_read_input_tokens or 0)
        tokens_out += response.usage.output_tokens
        analyses = []
        if response.stop_reason not in ("refusal", "max_tokens"):
            text = next((b.text for b in response.content if b.type == "text"), "")
            try:
                analyses = json.loads(text)["analyses"]
            except (json.JSONDecodeError, KeyError):
                analyses = []
        else:
            report.append(f"IA : réponse incomplète ({response.stop_reason}) sur un lot")

        done = set()
        for a in analyses:
            item = by_id.get(a.get("id"))
            if not item or a["id"] in done:
                continue
            done.add(a["id"])
            results.append({**item,
                            "categorie": a["categorie"],
                            "score": max(0, min(100, int(a["score"]))),
                            "titre": a["titre"].strip() or item["titre"],
                            "resume": a["resume"].strip(),
                            "pourquoi": a["pourquoi"].strip(),
                            "action": a["action"].strip() if a["score"] >= 70 else "",
                            "echeance": _deadline(a),
                            "analyse_par": model})
        for item_id_, item in by_id.items():
            if item_id_ not in done:
                results.append({**item, **keyword_fallback(item, profile, "article non analysé par l'IA")})

    report.append(f"IA : {len(items)} articles analysés, {tokens_in} jetons lus, {tokens_out} jetons écrits")
    return results
