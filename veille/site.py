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

from . import editorial, evenements, store
from .icons import write_icons

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site"
ASSETS = Path(__file__).resolve().parent / "assets"
REPO = "https://github.com/Euzediyo/veille-tls2"
REPO_ACTIONS = REPO + "/actions/workflows/journal.yml"

MOIS = editorial.MOIS

PUBLIC_FIELDS = ("id", "titre", "url", "source", "date", "edition", "categorie", "score",
                 "resume", "pourquoi", "action", "echeance", "payant", "international", "fond", "niveau", "groupe",
                 "pertinence", "urgence", "statut", "perimetre", "qui_concerne", "verifications", "contenu")
FONTS = ("https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@500;600;700"
         "&family=Barlow:wght@400;500;600&family=JetBrains+Mono:wght@400;600"
         "&family=Newsreader:opsz,wght@6..72,500;6..72,700&family=Public+Sans:wght@400;500;600;700&display=swap")


def dims(it: dict) -> str:
    """Dimensions de l'analyse (pertinence, urgence, statut, périmètre), séparées du score."""
    return " · ".join(editorial.LABELS[k][it[k]] for k in ("pertinence", "urgence", "statut", "perimetre") if it.get(k))


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
<script>try{{var d=document.documentElement;d.dataset.theme=localStorage.getItem("veilletls.theme")||(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light");d.dataset.density=localStorage.getItem("veilletls.vue")||"compacte"}}catch(e){{}}</script>
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
  <p>Résumés et taux de pertinence rédigés automatiquement par une IA à partir du titre et de l'extrait public de chaque article. Lisez toujours la source avant d'agir.</p>
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
<a class="skip" href="#contenu">Aller au contenu</a>
<header class="bar home">
  <div class="mast-row">
    <details class="admin" id="admin">
      <summary><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg><span class="adm-t">Administration</span></summary>
      <div class="admin-p">
        <a href="{REPO_ACTIONS}" target="_blank" rel="noopener">Scan immédiat<small>Ouvre GitHub pour lancer une collecte</small></a>
        <p>Ce menu range simplement les outils de l'administrateur : il ne protège rien. C'est GitHub qui vérifie l'accès (compte autorisé requis).</p>
      </div>
    </details>
    <div class="mast"><a href="index.html">{escape(site['titre'])}</a><p><span class="mast-s">{escape(site['sous_titre'])}</span><span class="mast-d"><span id="mast-d"></span> · Dernière collecte : <span id="last">--</span></span></p></div>
    <div class="mast-r"><button type="button" class="btn find" id="filt-btn" aria-expanded="false" aria-controls="tools"><svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M11 11l4 4" stroke="currentColor" stroke-width="1.6"/></svg><span class="find-t">Rechercher</span><em id="filt-n" hidden></em></button>
    <button type="button" class="theme-btn" id="theme-btn" aria-label="Changer de mode"><svg class="i-sun" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg><svg class="i-moon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg><span id="theme-t">Mode clair</span></button></div>
  </div>
</header>

<div class="navbar">
<nav class="rub" aria-label="Rubriques"><div class="rail" id="rail"></div></nav>
<nav class="tabs" aria-label="Vues">
  <button type="button" class="tab" data-view="journal"><svg class="ti" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 5h13v14H6a2 2 0 0 1-2-2z"/><path d="M17 8h3v9a2 2 0 0 1-2 2"/><path d="M7 9h7M7 12h7M7 15h4"/></svg><span>Journal</span> <em id="t-journal-n" title="Articles non lus, au total">0</em></button>
  <button type="button" class="tab" data-view="semaine"><svg class="ti" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg><span><span class="d-only">La </span>Semaine</span></button>
  <button type="button" class="tab" data-view="favoris"><svg class="ti" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z"/></svg><span>Favoris</span> <em id="t-favoris-n" title="Favoris enregistrés">0</em></button>
  <button type="button" class="tab" data-view="echeances"><svg class="ti" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2M9 2h6"/></svg><span>Échéances</span> <em id="t-echeances-n" title="Échéances à venir">0</em></button>
  <button type="button" class="tab" data-view="fond"><svg class="ti" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 4.5A1.5 1.5 0 0 1 5.5 3H11v17H5.5A1.5 1.5 0 0 1 4 18.5z"/><path d="M20 4.5A1.5 1.5 0 0 0 18.5 3H13v17h5.5a1.5 1.5 0 0 0 1.5-1.5z"/></svg><span><span class="d-only">Ressources de fond</span><span class="m-only">Ressources</span></span> <em id="t-fond-n" title="Ressources non lues">0</em></button>
  <button type="button" class="tab" data-view="archives"><svg class="ti" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9M10 13h4"/></svg><span>Archives</span></button>
</nav>

</div>

<div class="shell">
  <main class="main" id="contenu" tabindex="-1">
    <div class="tools" id="tools" aria-label="Rechercher et affiner">
      <label class="search"><svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M11 11l4 4" stroke="currentColor" stroke-width="1.6"/></svg>
        <input id="q" type="search" placeholder="Rechercher : R31, levée de doute, convention collective…" aria-label="Rechercher" autocomplete="off"></label>
      <div class="sel2"><select id="period" aria-label="Période"><option value="1">Dernière édition</option><option value="7" selected>7 jours</option><option value="30">30 jours</option><option value="100000">Toute la période</option></select>
      <select id="min" aria-label="Pertinence minimum"><option value="30">Pertinence ≥ 30 %</option><option value="50">Pertinence ≥ 50 %</option><option value="70">Pertinence ≥ 70 %</option><option value="90">Pertinence ≥ 90 %</option></select></div>
      <div class="row2">
        <div class="seg" id="press" role="group" aria-label="Presse"><span class="seg-l" aria-hidden="true">Presse</span><button type="button" data-press="all" aria-pressed="true">Toute <em id="pr-all">0</em></button><button type="button" data-press="fr" aria-pressed="false">Française <em id="pr-fr">0</em></button><button type="button" data-press="intl" aria-pressed="false">Internationale <em id="pr-intl">0</em></button></div>
        <div class="seg" id="readf" role="group" aria-label="Lecture"><button type="button" data-rf="unread" aria-pressed="true">Non lus <em id="rf-unread">0</em></button><button type="button" data-rf="read" aria-pressed="false">Lus <em id="rf-read">0</em></button><button type="button" data-rf="all" aria-pressed="false">Tous</button></div>
        <div class="seg" id="density" role="group" aria-label="Présentation des articles"><span class="seg-l" aria-hidden="true">Vue</span><button type="button" data-density="compacte" aria-pressed="false" aria-label="Vue compacte">Compacte</button><button type="button" data-density="detaillee" aria-pressed="true" aria-label="Vue détaillée">Détaillée</button></div>
        <div class="seg" id="level" role="group" aria-label="Niveau de veille"><span class="seg-l" aria-hidden="true">Veille</span><button type="button" data-level="essentielle" aria-pressed="true" title="Impact direct, forte pertinence métier">Essentielle <em id="lv-essentielle">0</em></button><button type="button" data-level="elargie" aria-pressed="false" title="Avec les informations indirectes et la culture du secteur">Élargie <em id="lv-elargie">0</em></button></div>
        <button type="button" class="btn" id="ack-all"><span class="d-only">Tout marquer comme lu</span><span class="m-only">✓ Tout lu</span></button>
        <button type="button" class="btn ghost" id="unmask" hidden></button>
      </div>
    </div>
    <div class="active" id="active" hidden></div>
    <section class="ess" id="ess" aria-labelledby="ess-h" hidden></section>
    <div class="feed" id="v-journal">
      <h2 class="rub-h" id="rub-h" hidden></h2>
      <p class="count" id="count" role="status"></p>
      <div class="feed" id="feed"></div></div>
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
<p>Chaque matin, un programme collecte les publications récentes de Google Actualités, de flux RSS et de pages surveillées, sur six domaines : réglementation, APSAD / CNPP, social et RH, télésurveillance, secteur et marché, management et exploitation. Une IA (modèle {escape(site['modele'])}) attribue à chaque article un taux de pertinence de 0 à 100 % du point de vue d'un responsable de centre de télésurveillance, explique ce taux, propose une action pour les articles importants et repère les échéances. Les articles sous {profile.get('seuil_publication', 30)} % ou jugés hors sujet ne sont pas publiés.</p>
<p>La <b>veille essentielle</b>, affichée par défaut, réunit les articles à impact direct ou à forte pertinence métier ; la <b>veille élargie</b> y ajoute les informations indirectes et la culture du secteur. Quand plusieurs médias reprennent la même information ou la même rumeur, une seule fiche est publiée, avec les autres sources consultables : ces reprises ne valent pas confirmations indépendantes. Un article publié plus de {profile.get('ressources_de_fond_jours', 30)} jours avant sa découverte est rangé dans les « Ressources de fond », avec sa date réelle, et n'est pas présenté comme une actualité. Le suivi médical à distance (télésurveillance de patients) n'est pas retenu, sauf lien avec la sécurité.</p>
<p>Le taux de pertinence ne dit pas l'urgence : chaque article est aussi qualifié séparément par sa pertinence métier (directe, indirecte, faible), son urgence (action immédiate, à anticiper, information), son statut (texte publié, proposition, négociation, annonce, rumeur) et son périmètre (France, Union européenne, autre pays). Le contenu réellement lu (début de l'article, extrait ou titre seul) est constaté par le programme, pas estimé par l'IA. Une échéance n'est jamais affichée plus précise que sa source : un mois seul reste « date à confirmer », et seules les dates exactes vont au calendrier.</p>
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
    day = editorial.published_on(it)
    when = f"publié le {day.day} {MOIS[day.month - 1]} {day.year}" if day else "date de publication inconnue"
    lines = [f"<h3>{escape(it['titre'])}</h3>",
             f"<p><b>{escape(cat)}</b> · score {it['score']} %" + (f" · {escape(dims(it))}" if dims(it) else "") + f" · {escape(it['source'])} · {when}"
             + (" · réservé aux abonnés" if it.get("payant") else "") + "</p>"]
    if it.get("resume"):
        lines.append(f"<p>{escape(it['resume'])}</p>")
    lines.append(f"<p>Pourquoi c'est important : {escape(it['pourquoi'])}</p>")
    if it.get("contenu"):
        lines.append(f"<p>Contenu analysé : {editorial.CONTENT_LABELS[it['contenu']]}.</p>")
    if it.get("qui_concerne"):
        lines.append(f"<p>Qui est concerné ? {escape(it['qui_concerne'])}</p>")
    if it.get("action"):
        lines.append(f"<p>Action recommandée : {escape(it['action'])}</p>")
    if it.get("verifications"):
        lines.append(f"<p>À vérifier : {escape(it['verifications'])}</p>")
    due = editorial.deadline(it)
    if due:
        kind = editorial.DEADLINE_TYPES.get(due["type"], "À vérifier")
        lines.append(f"<p>Échéance ({escape(kind.lower())}) : {escape(editorial.deadline_text(due))}, {escape(due['libelle'])}</p>")
    if it.get("reprises"):
        names = ", ".join(escape(r["source"]) for r in it["reprises"])
        lines.append(f"<p>Même information reprise par : {names} (reprises, pas des confirmations indépendantes).</p>")
    lines.append(f'<p>Source : <a href="{escape(it["url"])}">{escape(it["url"])}</a></p>')
    return "\n".join(lines)


def essential_html(items: list[dict], site: dict, profile: dict, today: date) -> str:
    """Page en texte simple des articles importants, à donner à un outil comme NotebookLM."""
    latest = max((it["edition"] for it in items), default=today.isoformat())
    week_start = (date.fromisoformat(latest) - timedelta(days=6)).isoformat()
    # Veille essentielle uniquement, hors ressources de fond, une fiche par événement, sans remplissage.
    news = sorted([it for it in items if not it.get("fond") and it.get("niveau", editorial.level(it, profile)) == "essentielle"],
                  key=lambda it: -it["score"])
    day_items = editorial.collapse([it for it in news if it["edition"] == latest])
    week_items = editorial.collapse([it for it in news if it["edition"] >= week_start])[:15]
    d = date.fromisoformat(latest)
    def section(title: str, rows: list[dict], empty: str) -> str:
        body = "\n".join(_essential_item(it, profile) for it in rows) or f"<p>{empty}</p>"
        return f"<h2>{title}</h2>\n{body}"
    return head(f"L'essentiel · {site['titre']}", site, "Les articles importants du jour et de la semaine, en texte simple") + f"""
<body>
<main class="prose">
<h1>{escape(site['titre'])} : l'essentiel</h1>
<p>Édition du {d.day} {MOIS[d.month - 1]} {d.year}. Sélection des articles les plus importants pour un centre de télésurveillance, résumés par une IA. Page prévue pour être lue par un outil comme NotebookLM ou imprimée.</p>
{section("L'essentiel du jour", day_items, "Aucune nouvelle information majeure aujourd'hui.")}
{section("L'essentiel de la semaine", week_items, "Aucune nouvelle information majeure cette semaine.")}
</main>
{footer(site)}
</body>
</html>
"""


def feed_xml(items: list[dict], site: dict, profile: dict) -> str:
    entries = sorted([it for it in items if it["score"] >= 50 and not it.get("fond")],
                     key=lambda it: it["edition"] + (it.get("date") or ""), reverse=True)[:100]
    rows = []
    for it in entries:
        cat = profile["categories"].get(it["categorie"], {}).get("nom", "Autre")
        desc = f"[{cat} · score {it['score']} %" + (f" · {dims(it)}" if dims(it) else "") + f"] {it.get('resume', '')} Pourquoi : {it['pourquoi']}"
        if it.get("action"):
            desc += f" Action recommandée : {it['action']}"
        pub = format_datetime(datetime.fromisoformat(it.get("date") or it["edition"] + "T06:00:00+00:00"))
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
    """Calendrier : une seule fois chaque échéance, et seulement les dates exactes (un mois seul ou
    une date non vérifiée n'y figurent pas, pour ne pas inventer de jour)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    events = []
    for due, it in editorial.unique_deadlines(items):
        if due["precision"] != "jour":
            continue
        day = date.fromisoformat(due["date"])
        summary = ("Non confirmé : " if due["type"] == "annonce_non_confirmee" else "") + due["libelle"]
        desc = " ".join(x for x in (f"{editorial.DEADLINE_TYPES.get(due['type'], '')}.",
                                    f"Source : {due['source']}.", due.get("justification", ""),
                                    it.get("action", ""), due["url"]) if x)
        events.append("\r\n".join([
            "BEGIN:VEVENT", f"UID:{it['id']}@veille-tls", f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
            f"SUMMARY:{_ics_text(summary)}", f"DESCRIPTION:{_ics_text(desc)}",
            f"URL:{due['url']}", "END:VEVENT"]))
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


def build(profile: dict, site: dict, articles: list[dict], today: date, groups: list[list[str]] | None = None) -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    for name in ("style.css", "app.js"):
        shutil.copy(ASSETS / name, OUT / name)
    write_icons(OUT)

    now = datetime.now(ZoneInfo("Europe/Paris"))
    # Numéro de version ajouté aux liens : force les navigateurs à recharger la mise en forme à chaque publication.
    site = {**site, "_version": now.strftime("%Y%m%d%H%M")}
    # Heure de la dernière vraie collecte : une simple republication du site ne la change pas.
    collected = (store.load_collect_time() or now).astimezone(ZoneInfo("Europe/Paris"))
    updated = f"{collected.day} {MOIS[collected.month - 1]} à {collected:%Hh%M}"
    ics_url = site["url"].rstrip("/") + "/echeances.ics"

    articles = editorial.annotate(articles, profile, evenements.groups() if groups is None else groups)
    # Échéances complétées : précision de la date (« a_verifier » pour une ancienne analyse), type, source.
    public = [{**{k: it.get(k) for k in PUBLIC_FIELDS}, "echeance": editorial.deadline(it)}
              for it in articles if editorial.publishable(it, profile)]
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
