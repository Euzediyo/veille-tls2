"""Avis « non pertinent » du lecteur, pour que l'IA apprenne ce qu'elle doit éviter de lui présenter.

Sur le site, le bouton « Non pertinent » d'un article ouvre un ticket GitHub pré-rempli. Chaque
matin, avant l'analyse, les tickets ouverts par le propriétaire du dépôt sont lus puis refermés :
l'article concerné est retiré du site, et il rejoint la liste des exemples (data/avis.json) que
l'IA reçoit avec ses consignes. Les tickets écrits par d'autres comptes sont ignorés.
"""

from __future__ import annotations

import os
import re

import requests

from .store import DATA, _read, _write, load_articles, replace_articles

AVIS = DATA / "avis.json"
KEEP = 60
TITLE_PREFIX = "non pertinent"
API = "https://api.github.com"


def load() -> list[dict]:
    return _read(AVIS, [])


def parse_issue(body: str) -> tuple[str, str]:
    """Identifiant de l'article et raison facultative écrite par le lecteur."""
    found = re.search(r"Identifiant\s*:\s*(\S+)", body or "")
    reason = re.search(r"Pourquoi[^:\n]*:\s*(.*)", body or "", re.S)
    text = re.sub(r"\s+", " ", reason.group(1)).strip()[:300] if reason else ""
    return (found.group(1) if found else ""), text


def _session(token: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                      "X-GitHub-Api-Version": "2022-11-28"})
    return s


def collect(report: list[str], today_iso: str) -> None:
    """Lit les avis envoyés depuis le site, met à jour data/avis.json et les articles concernés."""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    owner = (os.environ.get("GITHUB_REPOSITORY_OWNER") or "").lower()
    if not (token and repo and owner):
        return
    gh = _session(token)
    try:
        res = gh.get(f"{API}/repos/{repo}/issues", params={"state": "open", "per_page": 100}, timeout=30)
        res.raise_for_status()
    except requests.RequestException as exc:
        report.append(f"Avis : lecture impossible ({exc.__class__.__name__})")
        return
    issues = [i for i in res.json() if "pull_request" not in i
              and i["title"].lower().startswith(TITLE_PREFIX) and i["user"]["login"].lower() == owner]
    if not issues:
        return

    articles = {it["id"]: it for it in load_articles()}
    avis = load()
    known = {a["id"] for a in avis}
    changed = []
    for issue in issues:
        art_id, reason = parse_issue(issue.get("body") or "")
        art = articles.get(art_id)
        if art:
            if art_id not in known:
                # Seules les informations du journal sont reprises, jamais le texte libre du ticket hormis la raison.
                avis.append({"id": art_id, "titre": art["titre"], "source": art["source"],
                             "categorie": art["categorie"], "score": art["score"], "raison": reason, "date": today_iso})
                known.add(art_id)
            if not art.get("non_pertinent"):
                changed.append({**art, "non_pertinent": True})
            message = "Merci, c'est noté : l'article est retiré du site et l'IA en tiendra compte dès le prochain passage."
        else:
            message = "Article introuvable dans le journal : avis ignoré."
        try:
            gh.post(f"{API}/repos/{repo}/issues/{issue['number']}/comments", json={"body": message}, timeout=30)
            gh.patch(f"{API}/repos/{repo}/issues/{issue['number']}",
                     json={"state": "closed", "state_reason": "completed" if art else "not_planned"}, timeout=30)
        except requests.RequestException:
            pass
    if changed:
        replace_articles(changed)
    _write(AVIS, avis[-KEEP:])
    report.append(f"Avis : {len(issues)} « non pertinent » reçu(s), {len(avis[-KEEP:])} exemples transmis à l'IA")


def prompt_block(avis: list[dict], profile: dict) -> str:
    """Paragraphe ajouté aux consignes de l'IA."""
    if not avis:
        return ""
    cats = profile["categories"]
    lines = []
    for a in avis[-KEEP:]:
        cat = cats.get(a["categorie"], {}).get("nom", a["categorie"])
        line = f"- « {a['titre']} » ({a['source']}, {cat}, noté {a['score']})"
        if a.get("raison"):
            line += f" : {a['raison']}"
        lines.append(line)
    return ("\n\nPréférences apprises : le lecteur a jugé ces articles non pertinents pour lui, malgré la "
            "note que tu leur avais donnée (une raison est parfois précisée) :\n" + "\n".join(lines) +
            "\nDonne une note nettement plus basse aux articles du même genre (même type de sujet, même "
            "angle, même sorte de source). Garde toutefois une note élevée à un article qui annonce un "
            "changement concret et nouveau pour un centre de télésurveillance (texte officiel, référentiel, "
            "convention collective).")
