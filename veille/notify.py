"""E-mail du matin : envoie les articles les plus importants de l'édition du jour."""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from html import escape

from .site import fr_date, level


def send_digest(items: list[dict], site: dict, profile: dict, day: str, report: list[str]) -> None:
    user, password, to = (os.environ.get(k, "") for k in ("SMTP_USER", "SMTP_PASSWORD", "MAIL_TO"))
    if not (user and password and to):
        report.append("E-mail : non configuré, aucun envoi")
        return
    seuil = site.get("seuil_email", 70)
    top = sorted([it for it in items if it["score"] >= seuil], key=lambda it: -it["score"])
    if not top:
        report.append(f"E-mail : aucun article à {seuil} ou plus, aucun envoi")
        return

    lines, blocks = [], []
    for it in top:
        _, label = level(it["score"])
        cat = profile["categories"].get(it["categorie"], {}).get("nom", "Autre")
        lines.append(f"[{it['score']} {label}] {it['titre']}\n{it.get('resume', '')}\nPourquoi : {it['pourquoi']}\n{it['url']}\n")
        blocks.append(
            f"<p style='margin:0 0 4px;font:12px monospace;color:#56636f'>{it['score']} · {label} · {escape(cat)} · {escape(it['source'])}</p>"
            f"<p style='margin:0 0 6px;font-size:16px'><a href='{escape(it['url'])}'><b>{escape(it['titre'])}</b></a></p>"
            f"<p style='margin:0 0 6px'>{escape(it.get('resume', ''))}</p>"
            f"<p style='margin:0 0 20px;color:#56636f'><i>Pourquoi : {escape(it['pourquoi'])}</i></p>")

    msg = EmailMessage()
    msg["Subject"] = f"{site['titre']} · {len(top)} article(s) à lire · {fr_date(day)}"
    msg["From"] = user
    msg["To"] = to
    msg.set_content("\n".join(lines) + f"\nJournal complet : {site['url']}")
    msg.add_alternative(
        f"<div style='font-family:Arial,sans-serif;max-width:640px'>"
        f"<h2 style='margin:0 0 16px'>{escape(site['titre'])} · {fr_date(day)}</h2>{''.join(blocks)}"
        f"<p><a href='{escape(site['url'])}'>Lire le journal complet</a></p></div>", subtype="html")

    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    with smtplib.SMTP_SSL(host, int(os.environ.get("SMTP_PORT", "465")), timeout=30) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)
    report.append(f"E-mail : {len(top)} article(s) envoyés")
