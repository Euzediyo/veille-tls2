"""Flash audio quotidien : l'IA écrit un court bulletin parlé à partir des articles du jour,
une voix de synthèse française le lit, et l'épisode est publié sur le site avec un flux podcast.

Les fichiers audio ne sont pas enregistrés dans le dépôt (ils le feraient grossir chaque jour) :
seule la liste des épisodes l'est (data/podcast.json). À chaque publication, les épisodes récents
sont récupérés sur le site en ligne puis republiés avec le nouveau.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime, time, timedelta
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape
from zoneinfo import ZoneInfo

import anthropic
import requests

from .site import MOIS, OUT

ROOT = Path(__file__).resolve().parent.parent
EPISODES = ROOT / "data" / "podcast.json"
KEEP_DAYS = 14
MAX_SUJETS = 6
BITRATE = 48_000  # débit des fichiers produits par la voix de synthèse (bits par seconde)
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def spoken_date(day: date) -> str:
    return f"{JOURS[day.weekday()]} {day.day} {MOIS[day.month - 1]}"


def select(articles: list[dict], today: date) -> list[dict]:
    """Sujets du flash : les articles importants de l'édition du jour, à défaut les meilleurs."""
    pool = [it for it in articles if it["edition"] == today.isoformat() and it["categorie"] != "hors_sujet"]
    pool.sort(key=lambda it: it["score"], reverse=True)
    chosen = [it for it in pool if it["score"] >= 50][:MAX_SUJETS]
    return chosen if len(chosen) >= 3 else [it for it in pool if it["score"] >= 30][:3]


SYSTEM = """Tu présentes « le flash Veille TLS », un bulletin audio quotidien destiné aux
responsables et aux opérateurs de centres de télésurveillance. Ton texte sera lu tel quel par
une voix de synthèse.

Règles :
- Français, ton de radio d'information : clair, posé, phrases courtes.
- Entre 300 et 450 mots, soit environ trois minutes.
- Commence par : « Bonjour, nous sommes le {date}. Voici le flash Veille TLS. »
- Traite les sujets dans l'ordre reçu. Pour chacun : ce qui se passe, pourquoi c'est important
  pour un centre de télésurveillance, et l'action recommandée quand il y en a une. Cite la
  source (« selon ... »). Enchaîne les sujets avec des transitions naturelles.
- Termine par : « Retrouvez le détail et les liens sur le site Veille TLS. Bonne journée. »
- Uniquement les informations fournies : n'invente aucun chiffre, aucune date, aucun nom.
- Texte brut uniquement : pas de titres, de listes, de markdown, d'émojis ni d'adresses web.
  Écris les nombres et les dates comme on les prononce quand c'est plus naturel."""


def _topic_block(it: dict, cats: dict) -> str:
    lines = [f"Titre : {it['titre']}", f"Source : {it['source']}",
             f"Catégorie : {cats.get(it['categorie'], {}).get('nom', 'Autre')}", f"Score : {it['score']}"]
    for key, name in (("resume", "Résumé"), ("pourquoi", "Pourquoi c'est important"), ("action", "Action recommandée")):
        if it.get(key):
            lines.append(f"{name} : {it[key]}")
    return "\n".join(lines)


def fallback_script(items: list[dict], day: date) -> str:
    """Bulletin de secours sans IA : lecture des titres et des résumés."""
    parts = [f"Bonjour, nous sommes le {spoken_date(day)}. Voici le flash Veille TLS."]
    ordinals = ["Premier sujet", "Deuxième sujet", "Troisième sujet", "Quatrième sujet", "Cinquième sujet", "Sixième sujet"]
    for n, it in enumerate(items):
        parts.append(f"{ordinals[n]}, selon {it['source']} : {it['titre'].rstrip('.')}.")
        if it.get("resume"):
            parts.append(it["resume"])
        if it.get("action"):
            parts.append(f"Action recommandée : {it['action'].rstrip('.')}.")
    parts.append("Retrouvez le détail et les liens sur le site Veille TLS. Bonne journée.")
    return "\n\n".join(parts)


def write_script(items: list[dict], profile: dict, model: str, day: date, report: list[str]) -> str:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return fallback_script(items, day)
    prompt = "Sujets du jour :\n\n" + "\n\n".join(_topic_block(it, profile["categories"]) for it in items)
    try:
        response = anthropic.Anthropic().messages.create(
            model=model,
            max_tokens=4000,
            system=SYSTEM.replace("{date}", spoken_date(day)),
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as exc:
        report.append(f"Podcast : texte de secours ({exc.__class__.__name__})")
        return fallback_script(items, day)
    text = next((b.text for b in response.content if b.type == "text"), "").strip()
    if response.stop_reason != "end_turn" or len(text) < 200:
        report.append(f"Podcast : texte de secours (réponse {response.stop_reason})")
        return fallback_script(items, day)
    return text


def synthesize(text: str, path: Path, voice: str) -> None:
    """Lecture du texte par une voix de synthèse gratuite (service de Microsoft Edge)."""
    import edge_tts

    asyncio.run(edge_tts.Communicate(text, voice).save(str(path)))


def load_episodes() -> list[dict]:
    if EPISODES.exists():
        return json.loads(EPISODES.read_text(encoding="utf-8"))
    return []


def save_episodes(episodes: list[dict]) -> None:
    EPISODES.write_text(json.dumps(episodes, ensure_ascii=False, indent=1), encoding="utf-8")


def make_episode(articles: list[dict], profile: dict, site_cfg: dict, today: date, report: list[str]) -> None:
    """Crée l'épisode du jour dans site/podcast/ et l'ajoute à data/podcast.json."""
    items = select(articles, today)
    if not items:
        report.append("Podcast : aucun sujet aujourd'hui, pas d'épisode")
        return
    text = write_script(items, profile, site_cfg["modele"], today, report)
    folder = OUT / "podcast"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"podcast/{today.isoformat()}.mp3"
    try:
        synthesize(text, OUT / name, site_cfg.get("podcast_voix", "fr-FR-HenriNeural"))
    except Exception as exc:  # service non officiel : une panne ne doit pas bloquer le journal
        report.append(f"Podcast : voix de synthèse indisponible ({exc.__class__.__name__}), pas d'épisode")
        return
    size = (OUT / name).stat().st_size
    episode = {"date": today.isoformat(), "titre": f"Flash du {spoken_date(today)}", "fichier": name,
               "octets": size, "duree": round(size * 8 / BITRATE), "sujets": [it["titre"] for it in items], "texte": text}
    episodes = [e for e in load_episodes() if e["date"] != episode["date"]] + [episode]
    save_episodes(episodes)
    report.append(f"Podcast : épisode de {episode['duree'] // 60} min {episode['duree'] % 60:02d} s sur {len(items)} sujets")


def publish(site_cfg: dict, today: date, report: list[str]) -> list[dict]:
    """Remet les épisodes récents dans site/podcast/ et écrit le flux podcast. Renvoie les épisodes publiés."""
    cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
    episodes = [e for e in load_episodes() if e["date"] > cutoff]
    save_episodes(episodes)
    base = site_cfg["url"].rstrip("/") + "/"
    (OUT / "podcast").mkdir(parents=True, exist_ok=True)
    published = []
    for ep in sorted(episodes, key=lambda e: e["date"], reverse=True):
        target = OUT / ep["fichier"]
        if not target.exists():
            try:
                res = requests.get(base + ep["fichier"], timeout=60)
                res.raise_for_status()
                target.write_bytes(res.content)
            except requests.RequestException:
                report.append(f"Podcast : épisode du {ep['date']} introuvable en ligne, retiré du flux")
                continue
        published.append(ep)
    (OUT / "podcast.xml").write_text(feed(published, site_cfg), encoding="utf-8")
    (OUT / "podcast.json").write_text(json.dumps(
        [{k: ep[k] for k in ("date", "titre", "fichier", "duree", "sujets")} for ep in published],
        ensure_ascii=False), encoding="utf-8")
    return published


def feed(episodes: list[dict], site_cfg: dict) -> str:
    base = site_cfg["url"].rstrip("/") + "/"
    items = []
    for ep in episodes:
        day = date.fromisoformat(ep["date"])
        pub = format_datetime(datetime.combine(day, time(6, 30), ZoneInfo("Europe/Paris")))
        desc = "Au sommaire : " + " ; ".join(ep["sujets"]) + "."
        items.append(f"""<item><title>{xml_escape(ep['titre'])}</title><guid isPermaLink="false">veille-tls-{ep['date']}</guid>
<pubDate>{pub}</pubDate><description>{xml_escape(desc)}</description>
<enclosure url="{xml_escape(base + ep['fichier'])}" length="{ep['octets']}" type="audio/mpeg"/>
<itunes:duration>{ep['duree']}</itunes:duration></item>""")
    return f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"><channel>
<title>{xml_escape(site_cfg['titre'])} · le flash audio</title><link>{xml_escape(base)}</link>
<description>Chaque matin, trois minutes sur l'actualité de la télésurveillance et de la sécurité privée. Bulletin rédigé par une IA et lu par une voix de synthèse.</description>
<language>fr</language><itunes:author>{xml_escape(site_cfg['editeur'])}</itunes:author>
<itunes:image href="{xml_escape(base)}icon-512.png"/><itunes:explicit>false</itunes:explicit>
<itunes:category text="News"/>
{chr(10).join(items)}
</channel></rss>
"""
