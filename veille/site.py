"""Génération du site statique public (dossier site/) : application de lecture, flux RSS,
calendrier des échéances, mentions légales et fichiers d'installation sur téléphone."""

from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape
from zoneinfo import ZoneInfo

from .icons import write_icons

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site"
ASSETS = Path(__file__).resolve().parent / "assets"
REPO = "https://github.com/Euzediyo/veille-tls2"
REPO_ACTIONS = REPO + "/actions/workflows/journal.yml"

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]

LEVELS = [(90, "Critique"), (70, "Important"), (50, "Intéressant"), (30, "Veille")]
PUBLIC_FIELDS = ("id", "titre", "url", "source", "date", "edition", "categorie", "score",
                 "resume", "pourquoi", "action", "echeance", "payant")
FONTS = ("https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@500;600;700"
         "&family=Barlow:wght@400;500;600&family=JetBrains+Mono:wght@400;600"
         "&family=Newsreader:opsz,wght@6..72,500;6..72,700&family=Public+Sans:wght@400;500;600;700&display=swap")


def label(score: int) -> str:
    for threshold, name in LEVELS:
        if score >= threshold:
            return name
    return "Ignoré"


def head(title: str, site: dict, description: str = "") -> str:
    v = site.get("_version", "")
    return f"""<!doctype html>
<html lang="fr" data-layout="journal">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{escape(title)}</title>
<meta name="description" content="{escape(description or site['sous_titre'])}">
<meta name="theme-color" content="#070c14">
<script>try{{var d=document.documentElement;d.dataset.theme=localStorage.getItem("veilletls.theme")||(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light")}}catch(e){{}}</script>
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
  <p><a href="index.html">Journal</a> · <a href="feed.xml">Flux RSS</a> · <a href="podcast.xml">Podcast</a> · <a href="essentiel.html">L'essentiel (texte)</a> · <a href="mentions-legales.html">Mentions légales et méthode</a></p>
</footer>"""


def index_html(site: dict, profile: dict, updated: str, ics_url: str) -> str:
    config = {
        "categories": [{"key": k, "nom": c["nom"], "priorite": c["priorite"]} for k, c in profile["categories"].items()],
        "updated": updated,
        "ics": ics_url,
        "podcast": site["url"].rstrip("/") + "/podcast.xml",
        "avis": REPO + "/issues/new",
    }
    return head(site["titre"], site) + f"""
<body>
<header class="bar home">
  <div class="bar-in">
    <a class="scan-btn" href="{REPO_ACTIONS}" target="_blank" rel="noopener" title="Lancer une collecte immédiate (réservé à l'administrateur, compte GitHub requis)">Scan immédiat</a>
    <button type="button" class="theme-btn" id="theme-btn" aria-label="Changer de mode"><svg class="i-sun" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg><svg class="i-moon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg><span id="theme-t">Mode clair</span></button>
  </div>
  <div class="mast"><a href="index.html">{escape(site['titre'])}</a><p>{escape(site['sous_titre'])}</p><p class="mast-d"><span id="mast-d"></span> · Dernière collecte : <span id="last">--</span></p></div>
</header>

<nav class="tabs" role="tablist" aria-label="Vues">
  <button type="button" class="tab" role="tab" data-view="journal">Journal <em id="t-journal-n" title="non lus">0</em></button>
  <button type="button" class="tab" role="tab" data-view="semaine">La semaine</button>
  <button type="button" class="tab" role="tab" data-view="favoris">Favoris <em id="t-favoris-n">0</em></button>
  <button type="button" class="tab" role="tab" data-view="echeances">Échéances <em id="t-echeances-n" title="à venir">0</em></button>
  <button type="button" class="tab" role="tab" data-view="archives">Archives</button>
</nav>

<div class="shell">
  <main class="main">
    <nav class="rail" id="rail" aria-label="Catégories"></nav>
    <div class="tools" id="tools">
      <label class="search"><svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M11 11l4 4" stroke="currentColor" stroke-width="1.6"/></svg>
        <input id="q" type="search" placeholder="Rechercher : R31, levée de doute, convention collective…" aria-label="Rechercher" autocomplete="off"></label>
      <select id="period" aria-label="Période"><option value="1">Dernière édition</option><option value="7" selected>7 jours</option><option value="30">30 jours</option><option value="100000">Tout</option></select>
      <select id="min" aria-label="Score minimum"><option value="30">Score ≥ 30</option><option value="50">Score ≥ 50</option><option value="70">Score ≥ 70</option><option value="90">Score ≥ 90</option></select>
      <div class="seg" id="readf" role="group" aria-label="Afficher"><button type="button" data-rf="unread" aria-pressed="true">Non lus <em id="rf-unread">0</em></button><button type="button" data-rf="read" aria-pressed="false">Lus <em id="rf-read">0</em></button><button type="button" data-rf="all" aria-pressed="false">Tous</button></div>
      <button type="button" class="btn" id="ack-all">Tout marquer comme lu</button>
      <button type="button" class="btn ghost" id="unmask" hidden></button>
      <span class="daychip" id="daychip" hidden><span id="daychip-t"></span><button type="button" id="daychip-x" aria-label="Revenir à toutes les éditions">✕</button></span>
    </div>
    <div class="feed" id="v-journal"><div class="feed" id="feed"></div></div>
    <div class="feed" id="v-semaine" hidden></div>
    <div class="feed" id="v-echeances" hidden></div>
    <div id="v-archives" hidden></div>
  </main>
  <aside class="side" id="side" aria-label="En complément">
    <section class="flash" id="flash" aria-label="Flash audio" hidden></section>
    <section class="box" id="side-due" hidden></section>
    <section class="box" id="side-week" hidden></section>
  </aside>
</div>
<div class="toast" id="toast" role="status" hidden></div>
{footer(site)}
<script>window.VEILLE = {json.dumps(config, ensure_ascii=False)};</script>
<script src="app.js?v={site.get('_version', '')}"></script>
</body>
</html>
"""


def legal_html(site: dict, profile: dict) -> str:
    return head(f"Mentions légales · {site['titre']}", site) + f"""
<body>
<header class="bar"><div class="bar-in"><a class="logo" href="index.html"><span class="logo-t">Veille TLS</span></a></div></header>
<main class="prose">
<h1>Mentions légales et méthode</h1>
<h2>Éditeur</h2>
<p>{escape(site['editeur'])}<br>Contact : {escape(site['contact'])}</p>
<h2>Hébergement</h2>
<p>{escape(site['hebergeur'])}</p>
<h2>Contenus et droits d'auteur</h2>
<p>Ce journal ne reproduit aucun article. Pour chaque information, il publie un titre, un résumé court rédigé automatiquement par une intelligence artificielle avec ses propres mots, le nom de la source et un lien vers l'article original. Les textes officiels (lois, décrets, arrêtés, décisions de justice) peuvent être cités plus largement.</p>
<p>Pour rédiger ces résumés, le programme lit le début des articles quand le site l'autorise (fichier robots.txt). Ce texte sert uniquement à l'analyse : il n'est ni conservé ni publié. Les articles réservés aux abonnés sont signalés comme tels.</p>
<p>Le flash audio quotidien est rédigé par la même IA à partir de ces résumés, sous la forme d'un dialogue entre deux animateurs fictifs, lu par des voix de synthèse. Il ne reprend aucun texte d'article.</p>
<p>Un éditeur qui souhaite le retrait d'un résumé peut écrire à l'adresse de contact ci-dessus : il sera retiré rapidement.</p>
<h2>Comment ce journal est fait</h2>
<p>Chaque matin, un programme collecte les publications récentes de Google Actualités, de flux RSS et de pages surveillées, sur six domaines : réglementation, APSAD / CNPP, social et RH, télésurveillance, secteur et marché, management et exploitation. Une IA (modèle {escape(site['modele'])}) attribue à chaque article un score de pertinence de 0 à 100 du point de vue d'un responsable de centre de télésurveillance, explique ce score, propose une action pour les articles importants et repère les échéances. Les articles notés sous {profile.get('seuil_publication', 30)} ou jugés hors sujet ne sont pas publiés.</p>
<p>L'IA ne lit que le titre et l'extrait public de chaque article : elle peut se tromper. Vérifiez toujours la source avant de prendre une décision.</p>
<h2>Données personnelles</h2>
<p>Ce site ne dépose aucun cookie et ne collecte aucune donnée sur ses lecteurs. Les articles lus, les favoris et les articles masqués sont mémorisés uniquement dans votre navigateur.</p>
</main>
{footer(site)}
</body>
</html>
"""


def _essential_item(it: dict, profile: dict) -> str:
    cat = profile["categories"].get(it["categorie"], {}).get("nom", "Autre")
    day = date.fromisoformat(it["edition"])
    lines = [f"<h3>{escape(it['titre'])}</h3>",
             f"<p><b>{escape(cat)}</b> · score {it['score']} ({label(it['score'])}) · {escape(it['source'])} · {day.day} {MOIS[day.month - 1]} {day.year}"
             + (" · réservé aux abonnés" if it.get("payant") else "") + "</p>"]
    if it.get("resume"):
        lines.append(f"<p>{escape(it['resume'])}</p>")
    lines.append(f"<p>Pourquoi c'est important : {escape(it['pourquoi'])}</p>")
    if it.get("action"):
        lines.append(f"<p>Action recommandée : {escape(it['action'])}</p>")
    if it.get("echeance"):
        due = date.fromisoformat(it["echeance"]["date"])
        lines.append(f"<p>Échéance : {due.day} {MOIS[due.month - 1]} {due.year}, {escape(it['echeance']['libelle'])}</p>")
    lines.append(f'<p>Source : <a href="{escape(it["url"])}">{escape(it["url"])}</a></p>')
    return "\n".join(lines)


def essential_html(items: list[dict], site: dict, profile: dict, today: date) -> str:
    """Page en texte simple des articles importants, à donner à un outil comme NotebookLM."""
    latest = max((it["edition"] for it in items), default=today.isoformat())
    week_start = (date.fromisoformat(latest) - timedelta(days=6)).isoformat()
    day_items = sorted([it for it in items if it["edition"] == latest and it["score"] >= 50], key=lambda it: -it["score"])
    week = sorted([it for it in items if it["edition"] >= week_start], key=lambda it: -it["score"])
    week_items = [it for it in week if it["score"] >= 70] or week[:10]
    if len(week_items) < 5:
        week_items = [it for it in week if it["score"] >= 50][:15]
    d = date.fromisoformat(latest)
    def section(title: str, rows: list[dict]) -> str:
        body = "\n".join(_essential_item(it, profile) for it in rows) or "<p>Aucun article important sur cette période.</p>"
        return f"<h2>{title}</h2>\n{body}"
    return head(f"L'essentiel · {site['titre']}", site, "Les articles importants du jour et de la semaine, en texte simple") + f"""
<body>
<main class="prose">
<h1>{escape(site['titre'])} : l'essentiel</h1>
<p>Édition du {d.day} {MOIS[d.month - 1]} {d.year}. Sélection des articles les plus importants pour un centre de télésurveillance, résumés par une IA. Page prévue pour être lue par un outil comme NotebookLM ou imprimée.</p>
{section("L'essentiel du jour", day_items)}
{section("L'essentiel de la semaine", week_items)}
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


def weeks_public(public: list[dict]) -> list[dict]:
    """Résumés de la semaine (data/semaines.json), du plus récent au plus ancien, limités aux articles publiés."""
    path = ROOT / "data" / "semaines.json"
    if not path.exists():
        return []
    ids = {it["id"] for it in public}
    weeks = json.loads(path.read_text(encoding="utf-8"))
    return [{**w, "articles": [i for i in w["articles"] if i in ids], "echeances": [i for i in w["echeances"] if i in ids]}
            for w in sorted(weeks, key=lambda w: w["lundi"], reverse=True)]


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
    public = [{k: it.get(k) for k in PUBLIC_FIELDS} for it in articles
              if it["score"] >= seuil and it["categorie"] != "hors_sujet" and not it.get("non_pertinent")]
    public.sort(key=lambda it: (it["edition"], it["score"]), reverse=True)

    (OUT / "index.html").write_text(index_html(site, profile, updated, ics_url), encoding="utf-8")
    (OUT / "mentions-legales.html").write_text(legal_html(site, profile), encoding="utf-8")
    (OUT / "articles.json").write_text(json.dumps(public, ensure_ascii=False), encoding="utf-8")
    (OUT / "semaines.json").write_text(json.dumps(weeks_public(public), ensure_ascii=False), encoding="utf-8")
    (OUT / "feed.xml").write_text(feed_xml(public, site, profile), encoding="utf-8")
    (OUT / "essentiel.html").write_text(essential_html(public, site, profile, today), encoding="utf-8")
    (OUT / "echeances.ics").write_text(ics(public, site), encoding="utf-8", newline="")
    (OUT / "manifest.webmanifest").write_text(manifest(site), encoding="utf-8")
    (OUT / "sw.js").write_text(service_worker(now.strftime("%Y%m%d%H%M")), encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
