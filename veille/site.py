"""Génération du site statique public (dossier site/), du flux RSS et des mentions légales."""

from __future__ import annotations

import json
import shutil
from collections import defaultdict
from datetime import date, datetime, timezone
from email.utils import format_datetime
from html import escape
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site"
ASSETS = Path(__file__).resolve().parent / "assets"

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]

LEVELS = [  # (seuil, clé css, libellé)
    (90, "crit", "Critique"),
    (70, "imp", "Important"),
    (50, "int", "Intéressant"),
    (30, "veil", "Veille"),
]


def level(score: int):
    for threshold, css, label in LEVELS:
        if score >= threshold:
            return css, label
    return "ign", "Ignoré"


def fr_date(iso: str, weekday: bool = True) -> str:
    d = date.fromisoformat(iso[:10])
    text = f"{d.day} {MOIS[d.month - 1]} {d.year}"
    return f"{JOURS[d.weekday()]} {text}" if weekday else text


def page(title: str, body: str, site: dict, depth: int = 0, description: str = "") -> str:
    up = "../" * depth
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(description or site['sous_titre'])}">
<link rel="alternate" type="application/rss+xml" title="{escape(site['titre'])}" href="{up}feed.xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@600;800&family=Source+Sans+3:wght@400;600&family=JetBrains+Mono:wght@500&display=swap">
<link rel="stylesheet" href="{up}style.css">
</head>
<body>
<header class="top">
  <a class="brand" href="{up}index.html">{escape(site['titre'])}</a>
  <nav><a href="{up}index.html">Aujourd'hui</a><a href="{up}archives.html">Archives et recherche</a><a href="{up}feed.xml">Flux RSS</a></nav>
</header>
<main>
{body}
</main>
<footer class="foot">
  <p>Résumés rédigés automatiquement par une IA à partir du titre et de l'extrait public de chaque article. Lisez toujours la source avant d'agir.</p>
  <p><a href="{up}mentions-legales.html">Mentions légales et méthode</a></p>
</footer>
<script src="{up}app.js"></script>
</body>
</html>
"""


def card(item: dict, profile: dict) -> str:
    css, label = level(item["score"])
    cat = profile["categories"].get(item["categorie"], {}).get("nom", "Autre")
    resume = f"<p class=\"resume\">{escape(item['resume'])}</p>" if item.get("resume") else ""
    return f"""<article class="card lvl-{css}" data-cat="{escape(item['categorie'])}">
  <div class="meta"><span class="pill">{item['score']} · {label}</span><span>{escape(cat)}</span><span>{escape(item['source'])}</span><span>{fr_date(item['date'], weekday=False)}</span></div>
  <h3><a href="{escape(item['url'])}" rel="noopener" target="_blank">{escape(item['titre'])}</a></h3>
  {resume}
  <p class="why"><span>Pourquoi ce score</span> {escape(item['pourquoi'])}</p>
</article>"""


def filters(items: list[dict], profile: dict) -> str:
    counts = defaultdict(int)
    for it in items:
        counts[it["categorie"]] += 1
    chips = [f'<button type="button" class="chip on" data-filter="all">Tout <b>{len(items)}</b></button>']
    for key, cat in profile["categories"].items():
        if counts[key]:
            chips.append(f'<button type="button" class="chip" data-filter="{key}">{escape(cat["nom"])} <b>{counts[key]}</b></button>')
    return f'<div class="chips" role="toolbar" aria-label="Filtrer par catégorie">{"".join(chips)}</div>'


def edition_body(day: str, items: list[dict], profile: dict, prev: str | None, depth: int) -> str:
    seuil = profile.get("seuil_publication", 30)
    shown = sorted([it for it in items if it["score"] >= seuil], key=lambda it: -it["score"])
    up = "../" * depth
    head = f"""<section class="hero">
  <p class="eyebrow">Édition du {fr_date(day)}</p>
  <h1>Ce qu'un centre de télésurveillance doit savoir aujourd'hui</h1>
  <p class="counts">{summary_line(shown)}</p>
</section>"""
    if not shown:
        return head + '<p class="empty">Aucun article pertinent dans cette édition.</p>' + _prev_link(prev, up)
    groups = []
    for threshold, css, label in LEVELS:
        sub = [it for it in shown if level(it["score"])[0] == css]
        if not sub:
            continue
        cards = "\n".join(card(it, profile) for it in sub)
        if css == "veil":
            groups.append(f'<details class="group"><summary><h2>{label} <small>{len(sub)}</small></h2></summary>{cards}</details>')
        else:
            groups.append(f'<section class="group"><h2>{label} <small>{len(sub)}</small></h2>{cards}</section>')
    return head + filters(shown, profile) + "\n".join(groups) + _prev_link(prev, up)


def _prev_link(prev: str | None, up: str) -> str:
    if not prev:
        return ""
    return f'<p class="prev"><a href="{up}editions/{prev}.html">Édition précédente : {fr_date(prev)}</a></p>'


def summary_line(items: list[dict]) -> str:
    parts = []
    for threshold, css, label in LEVELS:
        n = sum(1 for it in items if level(it["score"])[0] == css)
        if n:
            parts.append(f'<span class="dot-{css}">{n} {label.lower()}{"s" if n > 1 else ""}</span>')
    return " ".join(parts) or "Aucun article retenu"


def feed(items: list[dict], site: dict, profile: dict) -> str:
    entries = sorted([it for it in items if it["score"] >= 50], key=lambda it: it["edition"] + it["date"], reverse=True)[:100]
    now = format_datetime(datetime.now(timezone.utc))
    rows = []
    for it in entries:
        _, label = level(it["score"])
        cat = profile["categories"].get(it["categorie"], {}).get("nom", "Autre")
        desc = f"[{it['score']} · {label} · {cat}] {it.get('resume', '')} Pourquoi : {it['pourquoi']}"
        pub = format_datetime(datetime.fromisoformat(it["date"]))
        rows.append(f"""<item><title>{xml_escape(it['titre'])}</title><link>{xml_escape(it['url'])}</link>
<guid isPermaLink="false">{it['id']}</guid><pubDate>{pub}</pubDate><category>{xml_escape(cat)}</category>
<source url="{xml_escape(it['url'])}">{xml_escape(it['source'])}</source><description>{xml_escape(desc)}</description></item>""")
    return f"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
<title>{xml_escape(site['titre'])}</title><link>{xml_escape(site['url'])}</link>
<description>{xml_escape(site['sous_titre'])} (articles notés 50 et plus)</description>
<language>fr</language><lastBuildDate>{now}</lastBuildDate>
{chr(10).join(rows)}
</channel></rss>
"""


def archives_body(by_day: dict[str, list[dict]], profile: dict) -> str:
    seuil = profile.get("seuil_publication", 30)
    rows = []
    for day in sorted(by_day, reverse=True):
        shown = [it for it in by_day[day] if it["score"] >= seuil]
        rows.append(f'<li><a href="editions/{day}.html">{fr_date(day)}</a><span>{summary_line(shown)}</span></li>')
    cats = json.dumps({k: c["nom"] for k, c in profile["categories"].items()}, ensure_ascii=False)
    return f"""<section class="hero"><p class="eyebrow">Archives</p><h1>Rechercher dans le journal</h1></section>
<form class="search" id="search-form" role="search">
  <label for="q">Mot-clé</label>
  <input id="q" type="search" placeholder="Ex. levée de doute, R31, convention collective" autocomplete="off">
  <label for="min">Score minimum</label>
  <select id="min"><option value="30">30 Veille</option><option value="50">50 Intéressant</option><option value="70" selected>70 Important</option><option value="90">90 Critique</option></select>
</form>
<div id="results" data-cats='{escape(cats)}'></div>
<h2 class="arch-title">Toutes les éditions</h2>
<ul class="editions">{"".join(rows)}</ul>"""


def legal_body(site: dict, profile: dict) -> str:
    return f"""<section class="hero"><p class="eyebrow">Informations</p><h1>Mentions légales et méthode</h1></section>
<div class="prose">
<h2>Éditeur</h2>
<p>{escape(site['editeur'])}<br>Contact : {escape(site['contact'])}</p>
<h2>Hébergement</h2>
<p>{escape(site['hebergeur'])}</p>
<h2>Contenus et droits d'auteur</h2>
<p>Ce journal ne reproduit aucun article. Pour chaque information, il publie un titre, un résumé court rédigé automatiquement par une intelligence artificielle avec ses propres mots, le nom de la source et un lien vers l'article original. Les textes officiels (lois, décrets, arrêtés, décisions de justice) peuvent être cités plus largement.</p>
<p>Un éditeur qui souhaite le retrait d'un résumé peut écrire à l'adresse de contact ci-dessus : il sera retiré rapidement.</p>
<h2>Comment ce journal est fait</h2>
<p>Chaque matin, un programme collecte les publications récentes de Google Actualités, de flux RSS et de pages surveillées, sur six domaines : réglementation, APSAD / CNPP, social et RH, télésurveillance, secteur et marché, management et exploitation. Une IA (modèle {escape(site['modele'])}) attribue à chaque article un score de pertinence de 0 à 100 du point de vue d'un responsable de centre de télésurveillance, et explique ce score. Les articles notés sous {profile.get('seuil_publication', 30)} ne sont pas publiés.</p>
<p>L'IA ne lit que le titre et l'extrait public de chaque article : elle peut se tromper. Vérifiez toujours la source avant de prendre une décision.</p>
<h2>Données personnelles</h2>
<p>Ce site ne dépose aucun cookie et ne collecte aucune donnée sur ses lecteurs.</p>
</div>"""


def build(profile: dict, site: dict, articles: list[dict], today: date) -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "editions").mkdir(parents=True)
    shutil.copy(ASSETS / "style.css", OUT / "style.css")
    shutil.copy(ASSETS / "app.js", OUT / "app.js")

    by_day: dict[str, list[dict]] = defaultdict(list)
    for it in articles:
        by_day[it["edition"]].append(it)
    days = sorted(by_day)

    for i, day in enumerate(days):
        prev = days[i - 1] if i else None
        html = page(f"{site['titre']} · {fr_date(day)}", edition_body(day, by_day[day], profile, prev, 1), site, depth=1)
        (OUT / "editions" / f"{day}.html").write_text(html, encoding="utf-8")

    if days:
        latest = days[-1]
        body = edition_body(latest, by_day[latest], profile, days[-2] if len(days) > 1 else None, 0)
    else:
        body = f"""<section class="hero"><p class="eyebrow">{fr_date(today.isoformat())}</p>
<h1>Le journal démarre</h1><p class="counts">La première édition paraîtra après le prochain passage quotidien.</p></section>"""
    (OUT / "index.html").write_text(page(site["titre"], body, site), encoding="utf-8")
    (OUT / "archives.html").write_text(page(f"Archives · {site['titre']}", archives_body(by_day, profile), site), encoding="utf-8")
    (OUT / "mentions-legales.html").write_text(page(f"Mentions légales · {site['titre']}", legal_body(site, profile), site), encoding="utf-8")
    (OUT / "feed.xml").write_text(feed(articles, site, profile), encoding="utf-8")

    seuil = profile.get("seuil_publication", 30)
    public = [{k: it[k] for k in ("titre", "url", "source", "date", "edition", "categorie", "score", "resume", "pourquoi")}
              for it in articles if it["score"] >= seuil]
    (OUT / "articles.json").write_text(json.dumps(public, ensure_ascii=False), encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
