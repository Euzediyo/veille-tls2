"""Génération du site statique public (dossier site/) : application de lecture, flux RSS,
calendrier des échéances, mentions légales et fichiers d'installation sur téléphone."""

from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape
from zoneinfo import ZoneInfo

from .icons import write_icons

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site"
ASSETS = Path(__file__).resolve().parent / "assets"
REPO_ACTIONS = "https://github.com/Euzediyo/veille-tls2/actions/workflows/journal.yml"

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]

LEVELS = [(90, "Critique"), (70, "Important"), (50, "Intéressant"), (30, "Veille")]
PUBLIC_FIELDS = ("id", "titre", "url", "source", "date", "edition", "categorie", "score",
                 "resume", "pourquoi", "action", "echeance")
FONTS = ("https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@500;600;700"
         "&family=Barlow:wght@400;500;600&family=JetBrains+Mono:wght@400;600&display=swap")


def label(score: int) -> str:
    for threshold, name in LEVELS:
        if score >= threshold:
            return name
    return "Ignoré"


def head(title: str, site: dict, description: str = "") -> str:
    v = site.get("_version", "")
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{escape(title)}</title>
<meta name="description" content="{escape(description or site['sous_titre'])}">
<meta name="theme-color" content="#070c14">
<link rel="manifest" href="manifest.webmanifest">
<link rel="icon" href="icon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="icon-192.png">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="{escape(site['titre'])}">
<link rel="alternate" type="application/rss+xml" title="{escape(site['titre'])}" href="feed.xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="{FONTS}">
<link rel="stylesheet" href="style.css?v={v}">
</head>"""


def footer(site: dict) -> str:
    return f"""<footer class="foot">
  <p>Résumés et scores rédigés automatiquement par une IA à partir du titre et de l'extrait public de chaque article. Lisez toujours la source avant d'agir.</p>
  <p><a href="index.html">Journal</a> · <a href="feed.xml">Flux RSS</a> · <a href="mentions-legales.html">Mentions légales et méthode</a></p>
</footer>"""


def index_html(site: dict, profile: dict, updated: str, ics_url: str) -> str:
    config = {
        "categories": [{"key": k, "nom": c["nom"], "priorite": c["priorite"]} for k, c in profile["categories"].items()],
        "updated": updated,
        "ics": ics_url,
    }
    return head(site["titre"], site) + f"""
<body>
<div class="boot" id="boot" aria-hidden="true"><pre></pre></div>
<header class="bar">
  <div class="bar-in">
    <a class="logo" href="index.html"><span class="radar" aria-hidden="true"></span>
      <span class="logo-t">VEILLE<b>//</b>TLS<small>POSTE DE VEILLE · TÉLÉSURVEILLANCE</small></span></a>
    <div class="status"><span class="on">Système en ligne</span><span>Dernière collecte : <span id="last">--</span></span></div>
    <div class="bar-r">
      <span class="clock" id="clock" aria-hidden="true">--:--:--</span>
      <a class="scan-btn" href="{REPO_ACTIONS}" target="_blank" rel="noopener" title="Lancer une collecte immédiate (réservé à l'administrateur, compte GitHub requis)">
        <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><circle cx="7" cy="7" r="6" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M7 7L7 1" stroke="currentColor" stroke-width="1.5"/></svg><span>Scan immédiat</span></a>
    </div>
  </div>
  <div class="ticker" id="ticker"><b>ALERTES</b><div class="track" id="ticker-track"></div></div>
</header>

<nav class="tabs" role="tablist" aria-label="Vues">
  <button type="button" class="tab" role="tab" data-view="journal">Journal <em id="t-journal-n" title="non lus">0</em></button>
  <button type="button" class="tab" role="tab" data-view="favoris">Favoris <em id="t-favoris-n">0</em></button>
  <button type="button" class="tab" role="tab" data-view="echeances">Échéances <em id="t-echeances-n" title="à venir">0</em></button>
  <button type="button" class="tab" role="tab" data-view="archives">Archives</button>
</nav>

<div class="shell">
  <nav class="rail" id="rail" aria-label="Catégories"></nav>
  <main class="main">
    <section class="kpis" aria-label="Synthèse">
      <div class="kpi un"><b id="k-unread">0</b><span>Non lus</span></div>
      <div class="kpi p1"><b id="k-p1">0</b><span>Critiques non lus</span></div>
      <div class="kpi p2"><b id="k-p2">0</b><span>Importants non lus</span></div>
      <div class="kpi"><b id="k-today">0</b><span>Dernière édition</span></div>
    </section>
    <div class="tools" id="tools">
      <label class="search"><svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M11 11l4 4" stroke="currentColor" stroke-width="1.6"/></svg>
        <input id="q" type="search" placeholder="Rechercher : R31, levée de doute, convention collective…" aria-label="Rechercher" autocomplete="off"></label>
      <select id="period" aria-label="Période"><option value="1">Dernière édition</option><option value="7" selected>7 jours</option><option value="30">30 jours</option><option value="100000">Tout</option></select>
      <select id="min" aria-label="Score minimum"><option value="30">Score ≥ 30</option><option value="50">Score ≥ 50</option><option value="70">Score ≥ 70</option><option value="90">Score ≥ 90</option></select>
      <label class="toggle"><input type="checkbox" id="hide-read"> Masquer les lus</label>
      <button type="button" class="btn" id="ack-all">Tout acquitter</button>
      <span class="daychip" id="daychip" hidden><span id="daychip-t"></span><button type="button" id="daychip-x" aria-label="Revenir à toutes les éditions">✕</button></span>
    </div>
    <div class="feed" id="v-journal"><div class="feed" id="feed"></div></div>
    <div class="feed" id="v-echeances" hidden></div>
    <div id="v-archives" hidden></div>
  </main>
</div>
{footer(site)}
<script>window.VEILLE = {json.dumps(config, ensure_ascii=False)};</script>
<script src="app.js?v={site.get('_version', '')}"></script>
</body>
</html>
"""


def legal_html(site: dict, profile: dict) -> str:
    return head(f"Mentions légales · {site['titre']}", site) + f"""
<body>
<header class="bar"><div class="bar-in"><a class="logo" href="index.html"><span class="radar" aria-hidden="true"></span><span class="logo-t">VEILLE<b>//</b>TLS</span></a></div></header>
<main class="prose">
<h1>Mentions légales et méthode</h1>
<h2>Éditeur</h2>
<p>{escape(site['editeur'])}<br>Contact : {escape(site['contact'])}</p>
<h2>Hébergement</h2>
<p>{escape(site['hebergeur'])}</p>
<h2>Contenus et droits d'auteur</h2>
<p>Ce journal ne reproduit aucun article. Pour chaque information, il publie un titre, un résumé court rédigé automatiquement par une intelligence artificielle avec ses propres mots, le nom de la source et un lien vers l'article original. Les textes officiels (lois, décrets, arrêtés, décisions de justice) peuvent être cités plus largement.</p>
<p>Un éditeur qui souhaite le retrait d'un résumé peut écrire à l'adresse de contact ci-dessus : il sera retiré rapidement.</p>
<h2>Comment ce journal est fait</h2>
<p>Chaque matin, un programme collecte les publications récentes de Google Actualités, de flux RSS et de pages surveillées, sur six domaines : réglementation, APSAD / CNPP, social et RH, télésurveillance, secteur et marché, management et exploitation. Une IA (modèle {escape(site['modele'])}) attribue à chaque article un score de pertinence de 0 à 100 du point de vue d'un responsable de centre de télésurveillance, explique ce score, propose une action pour les articles importants et repère les échéances. Les articles notés sous {profile.get('seuil_publication', 30)} ne sont pas publiés.</p>
<p>L'IA ne lit que le titre et l'extrait public de chaque article : elle peut se tromper. Vérifiez toujours la source avant de prendre une décision.</p>
<h2>Données personnelles</h2>
<p>Ce site ne dépose aucun cookie et ne collecte aucune donnée sur ses lecteurs. Les articles lus et les favoris sont mémorisés uniquement dans votre navigateur.</p>
</main>
{footer(site)}
</body>
</html>
"""


def feed_xml(items: list[dict], site: dict, profile: dict) -> str:
    entries = sorted([it for it in items if it["score"] >= 50], key=lambda it: it["edition"] + it["date"], reverse=True)[:100]
    rows = []
    for it in entries:
        cat = profile["categories"].get(it["categorie"], {}).get("nom", "Autre")
        desc = f"[{it['score']} · {label(it['score'])} · {cat}] {it.get('resume', '')} Pourquoi : {it['pourquoi']}"
        if it.get("action"):
            desc += f" Action recommandée : {it['action']}"
        pub = format_datetime(datetime.fromisoformat(it["date"]))
        rows.append(f"""<item><title>{xml_escape(it['titre'])}</title><link>{xml_escape(it['url'])}</link>
<guid isPermaLink="false">{it['id']}</guid><pubDate>{pub}</pubDate><category>{xml_escape(cat)}</category>
<source url="{xml_escape(it['url'])}">{xml_escape(it['source'])}</source><description>{xml_escape(desc)}</description></item>""")
    return f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
<title>{xml_escape(site['titre'])}</title><link>{xml_escape(site['url'])}</link>
<description>{xml_escape(site['sous_titre'])} (articles notés 50 et plus)</description>
<language>fr</language><lastBuildDate>{format_datetime(datetime.now(timezone.utc))}</lastBuildDate>
{chr(10).join(rows)}
</channel></rss>
"""


def _ics_text(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics(items: list[dict], site: dict) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    events = []
    for it in items:
        due = it.get("echeance")
        if not due:
            continue
        day = date.fromisoformat(due["date"])
        desc = f"{it['titre']} ({it['source']}). {it.get('action', '')} {it['url']}".strip()
        events.append("\r\n".join([
            "BEGIN:VEVENT", f"UID:{it['id']}@veille-tls", f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
            f"SUMMARY:{_ics_text(due['libelle'])}", f"DESCRIPTION:{_ics_text(desc)}",
            f"URL:{it['url']}", "END:VEVENT"]))
    return "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Veille TLS//FR", "CALSCALE:GREGORIAN",
                        f"X-WR-CALNAME:{_ics_text(site['titre'])} · échéances", *events, "END:VCALENDAR"]) + "\r\n"


def manifest(site: dict) -> str:
    return json.dumps({
        "name": site["titre"], "short_name": site["titre"], "description": site["sous_titre"],
        "lang": "fr", "start_url": "./", "scope": "./", "display": "standalone",
        "background_color": "#070c14", "theme_color": "#070c14",
        "icons": [
            {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
    }, ensure_ascii=False, indent=1)


def service_worker(version: str) -> str:
    return (ASSETS / "sw.js").read_text(encoding="utf-8").replace("__VERSION__", version)


def build(profile: dict, site: dict, articles: list[dict], today: date) -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    for name in ("style.css", "app.js"):
        shutil.copy(ASSETS / name, OUT / name)
    write_icons(OUT)

    now = datetime.now(ZoneInfo("Europe/Paris"))
    # Numéro de version ajouté aux liens : force les navigateurs à recharger la mise en forme à chaque publication.
    site = {**site, "_version": now.strftime("%Y%m%d%H%M")}
    updated = f"{now.day} {MOIS[now.month - 1]} à {now:%Hh%M}"
    ics_url = site["url"].rstrip("/") + "/echeances.ics"

    seuil = profile.get("seuil_publication", 30)
    public = [{k: it.get(k) for k in PUBLIC_FIELDS} for it in articles if it["score"] >= seuil]
    public.sort(key=lambda it: (it["edition"], it["score"]), reverse=True)

    (OUT / "index.html").write_text(index_html(site, profile, updated, ics_url), encoding="utf-8")
    (OUT / "mentions-legales.html").write_text(legal_html(site, profile), encoding="utf-8")
    (OUT / "articles.json").write_text(json.dumps(public, ensure_ascii=False), encoding="utf-8")
    (OUT / "feed.xml").write_text(feed_xml(public, site, profile), encoding="utf-8")
    (OUT / "echeances.ics").write_text(ics(public, site), encoding="utf-8", newline="")
    (OUT / "manifest.webmanifest").write_text(manifest(site), encoding="utf-8")
    (OUT / "sw.js").write_text(service_worker(now.strftime("%Y%m%d%H%M")), encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
