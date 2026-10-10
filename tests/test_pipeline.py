"""Tests hors ligne : préfiltrage, notation de secours, analyse IA simulée et génération du site."""

import json
import types
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path

import yaml

from veille import analyze, prefilter, site, store

CONFIG = Path(__file__).resolve().parent.parent / "config"
PROFILE = yaml.safe_load((CONFIG / "profil.yaml").read_text(encoding="utf-8"))
SITE = yaml.safe_load((CONFIG / "site.yaml").read_text(encoding="utf-8"))


def item(i, titre, extrait="", filtre="aucun"):
    return {"id": f"id{i}", "titre": titre, "url": f"https://exemple.fr/{i}", "source": "Exemple",
            "date": "2026-10-09T06:00:00+00:00", "extrait": extrait, "origine": "rss", "filtre": filtre}


SAMPLE = [
    item(1, "Le CNAPS publie un décret sur la carte professionnelle des agents de télésurveillance"),
    item(2, "Recette de la tarte aux pommes"),
    item(3, "La CNIL sanctionne une mairie", "Une amende pour un traitement de données", filtre="mots_cles"),
    item(4, "Verisure annonce le rachat d'un concurrent"),
    item(5, "Le CNAPS publie un décret sur la carte professionnelle des agents de télésurveillance !"),
]


def test_dedup_and_prefilter():
    fresh = prefilter.deduplicate(SAMPLE, {})
    assert [it["id"] for it in fresh] == ["id1", "id2", "id3", "id4"]
    kept = prefilter.prefilter(fresh, PROFILE, 10)
    ids = [it["id"] for it in kept]
    assert "id2" not in ids          # exclusion « recette »
    assert "id3" in ids              # « CNIL » est un mot-clé du profil
    assert ids[0] == "id1"           # le plus de mots-clés en premier


def test_fallback_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    kept = prefilter.prefilter(prefilter.deduplicate(SAMPLE, {}), PROFILE, 10)
    report = []
    out = analyze.analyze(kept, PROFILE, "claude-haiku-5-5", report)
    assert len(out) == len(kept)
    assert all(0 <= it["score"] <= 65 for it in out)
    assert "mots-clés" in report[0]


def test_ai_response_parsing(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    kept = prefilter.prefilter(prefilter.deduplicate(SAMPLE, {}), PROFILE, 10)
    payload = {"analyses": [
        {"id": "id1", "categorie": "reglementation", "score": 140, "titre": "Décret carte pro",
         "resume": "Un décret modifie la carte.", "pourquoi": "Impact direct sur le centre.",
         "action": "Prévenir les opérateurs", "echeance_date": "2027-03-01", "echeance_libelle": "Entrée en vigueur"},
        {"id": "inconnu", "categorie": "marche", "score": 50, "titre": "x", "resume": "", "pourquoi": "",
         "action": "", "echeance_date": "", "echeance_libelle": ""},
    ]}

    class FakeMessages:
        def create(self, **kwargs):
            assert kwargs["model"] == "claude-haiku-5-5"
            assert kwargs["output_config"]["format"]["type"] == "json_schema"
            return types.SimpleNamespace(
                stop_reason="end_turn",
                content=[types.SimpleNamespace(type="text", text=json.dumps(payload))],
                usage=types.SimpleNamespace(input_tokens=100, cache_read_input_tokens=0, output_tokens=50))

    monkeypatch.setattr(analyze.anthropic, "Anthropic", lambda: types.SimpleNamespace(messages=FakeMessages()))
    out = {it["id"]: it for it in analyze.analyze(kept, PROFILE, "claude-haiku-5-5", [])}
    assert out["id1"]["score"] == 100 and out["id1"]["analyse_par"] == "claude-haiku-5-5"
    assert out["id1"]["action"] == "Prévenir les opérateurs"
    assert out["id1"]["echeance"] == {"date": "2027-03-01", "libelle": "Entrée en vigueur"}
    assert "inconnu" not in out
    assert out["id4"]["analyse_par"] == "mots-clés"   # absent de la réponse : notation de secours


def test_site_build(tmp_path, monkeypatch):
    monkeypatch.setattr(site, "OUT", tmp_path / "site")
    monkeypatch.setattr(store, "DATA", tmp_path)
    store.save_collect_time(datetime(2026, 10, 9, 6, 45, tzinfo=ZoneInfo("Europe/Paris")))
    arts = [
        {**SAMPLE[0], "edition": "2026-10-08", "categorie": "reglementation", "score": 94, "resume": "R<script>",
         "pourquoi": "P", "action": "Former les opérateurs", "echeance": {"date": "2027-04-01", "libelle": "Entrée en vigueur"}},
        {**SAMPLE[3], "edition": "2026-10-09", "categorie": "marche", "score": 55, "resume": "R", "pourquoi": "P"},
        {**SAMPLE[2], "edition": "2026-10-09", "categorie": "reglementation", "score": 10, "resume": "", "pourquoi": "P"},
        {**SAMPLE[1], "edition": "2026-10-09", "categorie": "hors_sujet", "score": 40, "resume": "", "pourquoi": "P"},
    ]
    site.build(PROFILE, SITE, arts, date(2026, 10, 9))
    out = tmp_path / "site"
    public = json.loads((out / "articles.json").read_text(encoding="utf-8"))
    assert [it["id"] for it in public] == ["id4", "id1"]          # score 10 et hors sujet non publiés, plus récent d'abord
    assert public[1]["resume"] == "R<script>"                       # échappé côté navigateur, pas dans le JSON
    index = (out / "index.html").read_text(encoding="utf-8")
    assert '"key": "reglementation"' in index and "app.js" in index
    assert '"updated": "9 octobre à 06h45"' in index                # heure de la dernière vraie collecte, pas de la republication
    ics = (out / "echeances.ics").read_text(encoding="utf-8")
    assert "DTSTART;VALUE=DATE:20270401" in ics and ics.count("BEGIN:VEVENT") == 1
    assert "<rss" in (out / "feed.xml").read_text(encoding="utf-8")
    assert json.loads((out / "manifest.webmanifest").read_text(encoding="utf-8"))["display"] == "standalone"
    assert "__VERSION__" not in (out / "sw.js").read_text(encoding="utf-8")
    for name in ("icon-192.png", "icon-512.png", "icon.svg", "style.css", "mentions-legales.html"):
        assert (out / name).exists()


def test_deadline_validation():
    assert analyze._deadline({"echeance_date": "2027-01-01", "echeance_libelle": "X"}) == {"date": "2027-01-01", "libelle": "X"}
    assert analyze._deadline({"echeance_date": "janvier", "echeance_libelle": "X"}) is None
    assert analyze._deadline({"echeance_date": "", "echeance_libelle": ""}) is None


def test_replace_articles(tmp_path, monkeypatch):
    from veille import store
    monkeypatch.setattr(store, "DATA", tmp_path)
    store.add_articles([{**SAMPLE[0], "score": 20, "analyse_par": "mots-clés"}], date(2026, 10, 9))
    store.replace_articles([{**SAMPLE[0], "score": 92, "analyse_par": "claude-haiku-5-5"}])
    arts = store.load_articles(days=3, today=date(2026, 10, 10))
    assert len(arts) == 1 and arts[0]["score"] == 92 and arts[0]["edition"] == "2026-10-09"


def test_podcast(tmp_path, monkeypatch):
    from veille import podcast
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(podcast, "OUT", tmp_path / "site")
    monkeypatch.setattr(podcast, "EPISODES", tmp_path / "podcast.json")
    monkeypatch.setattr(podcast, "synthesize", lambda text, path, voice: path.write_bytes(b"\0" * 1_080_000))
    (tmp_path / "podcast.json").write_text(json.dumps([
        {"date": "2026-10-08", "titre": "Flash d'hier", "fichier": "podcast/2026-10-08.mp3", "octets": 9, "duree": 1, "sujets": ["A"], "texte": ""},
        {"date": "2026-09-01", "titre": "Trop ancien", "fichier": "podcast/2026-09-01.mp3", "octets": 9, "duree": 1, "sujets": ["B"], "texte": ""},
    ]), encoding="utf-8")

    def fake_get(url, timeout):
        raise podcast.requests.ConnectionError("hors ligne")
    monkeypatch.setattr(podcast.requests, "get", fake_get)

    arts = [{**SAMPLE[i], "edition": "2026-10-09", "categorie": cat, "score": score, "resume": "Résumé.", "pourquoi": "P", "action": ""}
            for i, (cat, score) in enumerate([("reglementation", 92), ("hors_sujet", 80), ("marche", 55), ("social", 40)])]
    assert [it["id"] for it in podcast.select(arts, date(2026, 10, 9))] == ["id1", "id3", "id4"]  # complété jusqu'à 3 sujets

    report = []
    podcast.make_episode(arts, PROFILE, SITE, date(2026, 10, 9), report)
    published = podcast.publish(SITE, date(2026, 10, 9), report)
    assert [ep["date"] for ep in published] == ["2026-10-09"]          # hier introuvable en ligne, septembre expiré
    assert published[0]["duree"] == 180 and "vendredi 9 octobre" in published[0]["texte"]
    saved = json.loads((tmp_path / "podcast.json").read_text(encoding="utf-8"))
    assert [ep["date"] for ep in saved] == ["2026-10-08", "2026-10-09"]  # gardé pour une prochaine tentative
    xml = (tmp_path / "site" / "podcast.xml").read_text(encoding="utf-8")
    assert 'podcast/2026-10-09.mp3" length="1080000" type="audio/mpeg"' in xml
    assert json.loads((tmp_path / "site" / "podcast.json").read_text(encoding="utf-8"))[0]["fichier"] == "podcast/2026-10-09.mp3"


def test_podcast_voice_failure(tmp_path, monkeypatch):
    from veille import podcast
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(podcast, "OUT", tmp_path / "site")
    monkeypatch.setattr(podcast, "EPISODES", tmp_path / "podcast.json")

    def broken(text, path, voice):
        raise OSError("service indisponible")
    monkeypatch.setattr(podcast, "synthesize", broken)
    arts = [{**SAMPLE[0], "edition": "2026-10-09", "categorie": "reglementation", "score": 92, "resume": "", "pourquoi": "P", "action": ""}]
    report = []
    podcast.make_episode(arts, PROFILE, SITE, date(2026, 10, 9), report)
    assert not (tmp_path / "podcast.json").exists() and "indisponible" in report[-1]


def test_podcast_script_ai(monkeypatch):
    from veille import podcast
    calls = {}

    class FakeMessages:
        def create(self, **kw):
            calls.update(kw)
            text = "\n".join(f"{'CLAIRE' if i % 2 else 'THOMAS'} : Réplique {i}." for i in range(8))
            return types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text=text)])

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(podcast.anthropic, "Anthropic", lambda: types.SimpleNamespace(messages=FakeMessages()))
    arts = [{**SAMPLE[0], "categorie": "reglementation", "score": 92, "resume": "R", "pourquoi": "P", "action": "Former"}]
    text = podcast.write_script(arts, PROFILE, "claude-haiku-5-5", date(2026, 10, 9), [])
    assert text.startswith("THOMAS : Réplique 0.") and "vendredi 9 octobre" in calls["system"]
    assert "Action recommandée : Former" in calls["messages"][0]["content"]


def test_dialogue(monkeypatch, tmp_path):
    import sys
    from veille import podcast
    text = "CLAIRE : Bonjour à tous.\n\n**Thomas** : Bonjour Claire.\nSuite de la phrase.\nNarrateur : ignoré ?\nCLAIRE :"
    assert podcast.parse_dialogue(text) == [("CLAIRE", "Bonjour à tous."),
                                            ("THOMAS", "Bonjour Claire. Suite de la phrase. Narrateur : ignoré ?")]
    assert {h for h, _ in podcast.parse_dialogue(podcast.fallback_script(SAMPLE[:3], date(2026, 10, 9)))} == {"CLAIRE", "THOMAS"}

    spoken = []

    class FakeCommunicate:
        def __init__(self, line, voice):
            spoken.append(voice)

        async def stream(self):
            yield {"type": "audio", "data": b"ab"}
            yield {"type": "WordBoundary"}

    monkeypatch.setitem(sys.modules, "edge_tts", types.SimpleNamespace(Communicate=FakeCommunicate))
    podcast.synthesize(text, tmp_path / "a.mp3", {"CLAIRE": "voix-f", "THOMAS": "voix-m"})
    assert spoken == ["voix-f", "voix-m"] and (tmp_path / "a.mp3").read_bytes() == b"abab"


def test_read_page_and_paywall():
    from veille import enrich
    paid = """<html><head><script type="application/ld+json">{"@type":"NewsArticle","isAccessibleForFree":"False"}</script></head>
    <body><nav>Menu Déjà abonné ?</nav><article><p>Le décret publié ce matin modifie les règles de formation des opérateurs de télésurveillance.</p>
    <p>court</p></article></body></html>"""
    text, payant = enrich.read_page(paid)
    assert payant is True and text.startswith("Le décret publié") and "court" not in text and "Menu" not in text

    marked = "<html><body><article><p>" + "Un long paragraphe sur la sécurité privée et ses évolutions. " * 3 + \
             "</p><div class='paywall-box'>Abonnez-vous pour lire la suite</div></article></body></html>"
    assert enrich.read_page(marked)[1] is True

    free = """<html><head><meta name="description" content="Résumé de la page."></head><body><p>bref</p></body></html>"""
    assert enrich.read_page(free) == ("Résumé de la page.", None)
    gnews = {**SAMPLE[0], "url": "https://news.google.com/rss/articles/abc", "source": "AEF info"}
    assert enrich.enrich_one(gnews, {"aef info"})["payant"] is True       # lien Google : pas de lecture, liste des sources


def test_text_not_stored_and_essential_page(tmp_path, monkeypatch):
    from veille import store
    monkeypatch.setattr(store, "DATA", tmp_path)
    store.add_articles([{**SAMPLE[0], "texte": "texte complet de l'article", "payant": True}], date(2026, 10, 9))
    saved = json.loads((tmp_path / "articles" / "2026-10.json").read_text(encoding="utf-8"))
    assert "texte" not in saved[0] and saved[0]["payant"] is True

    assert "texte complet" in analyze._article_block({**SAMPLE[0], "texte": "texte complet"})
    arts = [{**SAMPLE[0], "edition": "2026-10-09", "categorie": "reglementation", "score": 92, "resume": "Résumé long.",
             "pourquoi": "P", "action": "Former", "echeance": None, "payant": True},
            {**SAMPLE[3], "edition": "2026-10-05", "categorie": "marche", "score": 75, "resume": "R", "pourquoi": "P", "action": "", "echeance": None}]
    page = site.essential_html(arts, SITE, PROFILE, date(2026, 10, 9))
    day, week = page.split("L'essentiel de la semaine</h2>")
    assert "carte professionnelle" in day and "Verisure" not in day.split("L'essentiel du jour</h2>")[1]
    assert "Verisure" in week and "réservé aux abonnés" in day and "Action recommandée : Former" in day


def test_feedback_issues(tmp_path, monkeypatch):
    from veille import avis, store
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(avis, "AVIS", tmp_path / "avis.json")
    art = {"id": "a1", "titre": "Cambriolage à Lyon", "source": "Le Progrès", "categorie": "telesurveillance",
           "score": 55, "edition": "2026-10-09"}
    store.add_articles([art], date(2026, 10, 9))
    issues = [
        {"number": 1, "title": "Non pertinent : Cambriolage à Lyon", "user": {"login": "Euzediyo"},
         "body": "Identifiant : a1\nTitre : x\n\nPourquoi (facultatif, une phrase) : fait divers sans enjeu"},
        {"number": 2, "title": "Non pertinent : spam", "user": {"login": "inconnu"}, "body": "Identifiant : a1"},
    ]
    calls = []

    class Resp:
        def __init__(self, data=None): self.data = data
        def raise_for_status(self): pass
        def json(self): return self.data

    class Session:
        headers = {}
        def get(self, url, **kw): return Resp(issues)
        def post(self, url, **kw): calls.append(("post", url)); return Resp()
        def patch(self, url, **kw): calls.append(("patch", url, kw["json"]["state"])); return Resp()

    monkeypatch.setattr(avis, "_session", lambda token: Session())
    for k, v in {"GITHUB_TOKEN": "t", "GITHUB_REPOSITORY": "Euzediyo/veille-tls2", "GITHUB_REPOSITORY_OWNER": "Euzediyo"}.items():
        monkeypatch.setenv(k, v)
    report = []
    avis.collect(report, "2026-10-10")
    saved = avis.load()
    assert [a["id"] for a in saved] == ["a1"] and saved[0]["raison"] == "fait divers sans enjeu"
    assert store.load_articles()[0]["non_pertinent"] is True
    assert ("patch", "https://api.github.com/repos/Euzediyo/veille-tls2/issues/1", "closed") in calls
    assert not any("/issues/2" in c[1] for c in calls)  # ticket d'un autre compte ignoré
    from veille.analyze import build_system_prompt
    prompt = build_system_prompt(PROFILE, avis.prompt_block(saved, PROFILE))
    assert "Cambriolage à Lyon" in prompt and "fait divers sans enjeu" in prompt


def test_weekly_summary(tmp_path, monkeypatch):
    from veille import semaine, store
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(semaine, "WEEKS", tmp_path / "semaines.json")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    arts = [
        {"id": "a", "titre": "Décret CNAPS", "source": "Légifrance", "categorie": "reglementation", "score": 92, "edition": "2026-10-09",
         "pourquoi": "p", "echeance": {"date": "2026-11-01", "libelle": "Entrée en vigueur"}},
        {"id": "b", "titre": "Semaine d'avant", "source": "S", "categorie": "marche", "score": 80, "edition": "2026-10-04", "pourquoi": "p"},
        {"id": "c", "titre": "Masqué", "source": "S", "categorie": "marche", "score": 85, "edition": "2026-10-08", "pourquoi": "p", "non_pertinent": True},
        {"id": "d", "titre": "Faible", "source": "S", "categorie": "marche", "score": 40, "edition": "2026-10-08", "pourquoi": "p"},
    ]
    report = []
    semaine.update(arts, PROFILE, "modele", date(2026, 10, 9), report)
    w = semaine.load()[0]
    assert w["lundi"] == "2026-10-05" and w["en_cours"] and w["articles"] == ["a"] and w["echeances"] == ["a"]
    assert w["titre"] == "Semaine du 5 au 11 octobre 2026" and w["synthese"] == ""
    semaine.update(arts, PROFILE, "modele", date(2026, 10, 12), report)  # lundi suivant : la semaine précédente est terminée
    weeks = semaine.load()
    assert [x["lundi"] for x in weeks] == ["2026-10-05", "2026-10-12"] and not weeks[0]["en_cours"]
    assert semaine.label(date(2026, 9, 28)) == "Semaine du 28 septembre au 4 octobre 2026"
