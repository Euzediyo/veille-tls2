"""E-mails : l'alerte du matin (articles importants du jour, pour l'administrateur) et la lettre
de la semaine (les articles les plus importants des sept derniers jours, pour toute l'équipe).

Les adresses des destinataires sont gardées dans les secrets GitHub, jamais dans le dépôt public.
La lettre est envoyée en copie cachée : les destinataires ne voient pas les adresses des autres.
"""

from __future__ import annotations

import os
import smtplib
from datetime import date, timedelta
from email.message import EmailMessage
from html import escape

from .site import MOIS, label

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def fr_date(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {MOIS[d.month - 1]} {d.year}"


def addresses(raw: str) -> list[str]:
    """Liste d'adresses séparées par des virgules, des points-virgules ou des retours à la ligne."""
    out = []
    for part in raw.replace(";", ",").replace("\n", ",").split(","):
        part = part.strip()
        if "@" in part and part.lower() not in (a.lower() for a in out):
            out.append(part)
    return out


def _blocks(items: list[dict], profile: dict) -> tuple[str, str]:
    """Version texte et version HTML de la liste d'articles."""
    lines, blocks = [], []
    for it in items:
        lvl = label(it["score"])
        cat = profile["categories"].get(it["categorie"], {}).get("nom", "Autre")
        action = f"Action recommandée : {it['action']}\n" if it.get("action") else ""
        lock = " (réservé aux abonnés)" if it.get("payant") else ""
        lines.append(f"[{it['score']} {lvl}] {it['titre']}{lock}\n{it.get('resume', '')}\nPourquoi : {it['pourquoi']}\n{action}{it['url']}\n")
        blocks.append(
            f"<p style='margin:0 0 4px;font:12px monospace;color:#56636f'>{it['score']} · {lvl} · {escape(cat)} · {escape(it['source'])}"
            + (" · 🔒 réservé aux abonnés" if it.get("payant") else "") + "</p>"
            f"<p style='margin:0 0 6px;font-size:16px'><a href='{escape(it['url'])}'><b>{escape(it['titre'])}</b></a></p>"
            f"<p style='margin:0 0 6px'>{escape(it.get('resume', ''))}</p>"
            f"<p style='margin:0 0 6px;color:#56636f'><i>Pourquoi : {escape(it['pourquoi'])}</i></p>"
            + (f"<p style='margin:0 0 6px'><b>Action recommandée :</b> {escape(it['action'])}</p>" if it.get("action") else "")
            + "<div style='height:14px'></div>")
    return "\n".join(lines), "".join(blocks)


def _send(subject: str, text: str, html: str, recipients: list[str]) -> None:
    user, password = os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = user
    msg["Bcc"] = ", ".join(recipients)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    with smtplib.SMTP_SSL(host, int(os.environ.get("SMTP_PORT", "465")), timeout=30) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)


def _configured() -> bool:
    return bool(os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD"))


def send_digest(items: list[dict], site: dict, profile: dict, day: str, report: list[str]) -> None:
    """Alerte du matin, envoyée à MAIL_TO seulement."""
    to = addresses(os.environ.get("MAIL_TO", ""))
    if not (_configured() and to) or not site.get("email_quotidien", True):
        return
    seuil = site.get("seuil_email", 70)
    top = sorted([it for it in items if it["score"] >= seuil and it["categorie"] != "hors_sujet"], key=lambda it: -it["score"])
    if not top:
        report.append(f"E-mail du matin : aucun article à {seuil} ou plus, aucun envoi")
        return
    text, html = _blocks(top, profile)
    _send(f"{site['titre']} · {len(top)} article(s) à lire · {fr_date(day)}",
          text + f"\nJournal complet : {site['url']}",
          f"<div style='font-family:Arial,sans-serif;max-width:640px'><h2 style='margin:0 0 16px'>{escape(site['titre'])} · {fr_date(day)}</h2>"
          f"{html}<p><a href='{escape(site['url'])}'>Lire le journal complet</a></p></div>", to)
    report.append(f"E-mail du matin : {len(top)} article(s) envoyés")


def weekly_selection(articles: list[dict], site: dict, today: date) -> tuple[list[dict], list[dict]]:
    """Articles les plus importants des sept dernières éditions, et échéances des 60 prochains jours."""
    start = (today - timedelta(days=6)).isoformat()
    pool = [it for it in articles if it["edition"] >= start and it["categorie"] != "hors_sujet" and not it.get("non_pertinent")]
    top = sorted([it for it in pool if it["score"] >= site.get("lettre_seuil", 50)], key=lambda it: (-it["score"], it["edition"]))
    top = top[: site.get("lettre_articles", 10)]
    horizon = (today + timedelta(days=60)).isoformat()
    seen, due = set(), []
    for it in sorted([it for it in articles if it.get("echeance") and not it.get("non_pertinent")], key=lambda it: it["echeance"]["date"]):
        key = (it["echeance"]["date"], it["echeance"]["libelle"])
        if today.isoformat() <= it["echeance"]["date"] <= horizon and key not in seen:
            seen.add(key)
            due.append(it)
    return top, due


def send_weekly(articles: list[dict], site: dict, profile: dict, today: date, report: list[str], force: bool = False) -> None:
    """Lettre de la semaine, envoyée le jour choisi à MAIL_TO et aux adresses de LETTRE_TO."""
    jour = (site.get("lettre_jour") or "lundi").strip().lower()
    if not force and JOURS[today.weekday()] != jour:
        return
    to = addresses(os.environ.get("MAIL_TO", "") + "," + os.environ.get("LETTRE_TO", ""))
    if not (_configured() and to):
        report.append("Lettre de la semaine : e-mail non configuré, aucun envoi")
        return
    top, due = weekly_selection(articles, site, today)
    if not top:
        report.append("Lettre de la semaine : aucun article important cette semaine, aucun envoi")
        return
    text, html = _blocks(top, profile)
    week = f"semaine du {fr_date((today - timedelta(days=6)).isoformat())} au {fr_date(today.isoformat())}"
    due_text = "".join(f"- {fr_date(it['echeance']['date'])} : {it['echeance']['libelle']}\n" for it in due)
    due_html = "".join(f"<li><b>{fr_date(it['echeance']['date'])}</b> : {escape(it['echeance']['libelle'])}</li>" for it in due)
    footer = ("Vous recevez cette lettre de veille de votre centre de télésurveillance. "
              "Pour ne plus la recevoir, répondez simplement à ce message.")
    _send(f"{site['titre']} · la lettre de la semaine · {fr_date(today.isoformat())}",
          f"{site['titre']} : les {len(top)} articles à retenir, {week}\n\n{text}"
          + (f"\nÉchéances à venir :\n{due_text}" if due else "") + f"\nJournal complet : {site['url']}\n\n{footer}",
          f"<div style='font-family:Arial,sans-serif;max-width:640px'>"
          f"<h2 style='margin:0 0 4px'>{escape(site['titre'])} · la lettre de la semaine</h2>"
          f"<p style='margin:0 0 18px;color:#56636f'>Les {len(top)} articles à retenir, {week}.</p>{html}"
          + (f"<h3 style='margin:8px 0 6px'>Échéances à venir</h3><ul style='margin:0 0 16px'>{due_html}</ul>" if due else "")
          + f"<p><a href='{escape(site['url'])}'>Lire le journal complet</a></p>"
          f"<p style='font-size:12px;color:#8a96a3'>{escape(footer)}</p></div>", to)
    report.append(f"Lettre de la semaine : {len(top)} articles envoyés à {len(to)} destinataire(s)")
