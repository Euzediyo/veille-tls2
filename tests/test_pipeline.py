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
         "pertinence": "directe", "urgence": "a_anticiper", "statut": "texte_publie", "perimetre": "france",
         "qui_concerne": "Entreprises autorisées par le CNAPS", "verifications": "",
         "action": "Prévenir les opérateurs", "echeance_date": "2027-03-01", "echeance_libelle": "Entrée en vigueur",
         "echeance_precision": "jour", "echeance_periode": "", "echeance_type": "obligation",
         "echeance_justification": "le décret entre en vigueur le 1er mars 2027"},
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
    assert out["id1"]["echeance"] == {"date": "2027-03-01", "precision": "jour", "periode": "", "type": "obligation",
                                      "libelle": "Entrée en vigueur", "justification": "le décret entre en vigueur le 1er mars 2027",
                                      "source": "Exemple", "url": "https://exemple.fr/1"}
    assert out["id1"]["urgence"] == "a_anticiper" and out["id1"]["qui_concerne"].startswith("Entreprises")
    assert out["id1"]["contenu"] == "titre"            # aucun extrait ni texte lu : constaté, pas estimé par l'IA
    assert "inconnu" not in out
    assert out["id4"]["analyse_par"] == "mots-clés"   # absent de la réponse : notation de secours


def test_site_build(tmp_path, monkeypatch):
    monkeypatch.setattr(site, "OUT", tmp_path / "site")
    monkeypatch.setattr(store, "DATA", tmp_path)
    store.save_collect_time(datetime(2026, 10, 9, 6, 45, tzinfo=ZoneInfo("Europe/Paris")))
    arts = [
        {**SAMPLE[0], "edition": "2026-10-08", "categorie": "reglementation", "score": 94, "resume": "R<script>",
         "pourquoi": "P", "action": "Former les opérateurs",
         "echeance": {"date": "2027-04-01", "precision": "jour", "type": "obligation", "libelle": "Entrée en vigueur"}},
        {**SAMPLE[3], "edition": "2026-10-09", "categorie": "marche", "score": 55, "resume": "R", "pourquoi": "P",
         "echeance": {"date": "2026-11-01", "libelle": "Ancienne échéance approximative"}},   # analyse d'avant la précision des dates
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
    # Interface : « Scan immédiat » rangé dans le menu Administration, sélecteur de presse discret,
    # choix de la vue mémorisé, lien d'évitement pour le clavier.
    admin = index[index.index('<details class="admin"'):index.index("</details>")]
    assert "Scan immédiat" in admin and "ne protège rien" in admin and index.count("Scan immédiat") == 1
    assert 'data-press="all"' in index and 'data-density="compacte"' in index and 'href="#contenu"' in index
    assert 'localStorage.getItem("veilletls.vue")' in index
    # Présentation « Rubriques » : rubriques sous le titre, recherche et filtres rangés derrière un bouton.
    assert 'class="rub"' in index and 'id="rail"' in index and 'id="cat-sel"' not in index
    assert index.index('id="filt-btn"') < index.index("</header>") < index.index('id="tools"')
    assert 'getItem("veilletls.vue")||"compacte"' in index
    ics = (out / "echeances.ics").read_text(encoding="utf-8")
    assert "DTSTART;VALUE=DATE:20270401" in ics and ics.count("BEGIN:VEVENT") == 1   # l'ancienne date non vérifiée n'y est pas
    assert public[0]["echeance"]["precision"] == "a_verifier"
    assert "<rss" in (out / "feed.xml").read_text(encoding="utf-8")
    assert json.loads((out / "manifest.webmanifest").read_text(encoding="utf-8"))["display"] == "standalone"
    assert "__VERSION__" not in (out / "sw.js").read_text(encoding="utf-8")
    for name in ("icon-192.png", "icon-512.png", "icon.svg", "style.css", "mentions-legales.html"):
        assert (out / name).exists()


def test_deadline_validation():
    it = {"source": "S", "url": "u"}
    def due(**kw):
        a = {"echeance_libelle": "X", "echeance_type": "obligation", "echeance_precision": "jour", "echeance_date": "",
             "echeance_periode": "", "echeance_justification": "", "statut": "texte_publie", **kw}
        return analyze._deadline(a, it)
    assert due(echeance_date="2027-01-15")["date"] == "2027-01-15"
    # Mois seul : jamais transformé en « premier du mois ».
    assert {k: due(echeance_precision="mois", echeance_date="2026-11-01")[k] for k in ("date", "precision")} == {"date": "2026-11", "precision": "mois"}
    assert {k: due(echeance_date="2026-11")[k] for k in ("date", "precision")} == {"date": "2026-11", "precision": "mois"}   # « jour » sans jour
    assert due(echeance_precision="periode", echeance_date="2027-01", echeance_periode="début 2027")["periode"] == "début 2027"
    assert due(echeance_date="janvier")["precision"] == "inconnue"
    assert due(echeance_type="aucune") is None and due(echeance_libelle="") is None
    # Une proposition ne crée pas d'obligation.
    assert due(echeance_date="2027-01-01", statut="proposition")["type"] == "annonce_non_confirmee"


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
    assert [it["id"] for it in podcast.select(arts, date(2026, 10, 9), PROFILE)] == ["id1", "id3"]  # pas de remplissage sous 50

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


def test_international_sources_and_prompt():
    from veille import collect
    assert collect.google_news_url("a b") == "https://news.google.com/rss/search?q=a%20b&hl=fr&gl=FR&ceid=FR:fr"
    assert collect.google_news_url("x", "US:en").endswith("&hl=en-US&gl=US&ceid=US:en")
    assert collect.google_news_url("x", "BE:fr").endswith("&hl=fr-BE&gl=BE&ceid=BE:fr")
    sources = yaml.safe_load((CONFIG / "sources.yaml").read_text(encoding="utf-8"))
    assert all(q["requete"] and ":" in q["edition"] for q in sources["international"]["google_news"])
    block = analyze._article_block({**SAMPLE[0], "international": True})
    assert "Portée : internationale" in block and "Portée" not in analyze._article_block(SAMPLE[0])
    assert "Presse internationale" in analyze.build_system_prompt(PROFILE)


def test_podcast_voice_retry(tmp_path, monkeypatch):
    import asyncio
    import sys
    from veille import podcast
    calls = {"n": 0}

    class Flaky:
        def __init__(self, text, voice):
            pass

        async def stream(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("handshake")
            yield {"type": "audio", "data": b"son"}

    monkeypatch.setitem(sys.modules, "edge_tts", types.SimpleNamespace(Communicate=Flaky))
    monkeypatch.setattr(podcast, "RETRY_WAIT", 0)
    out = tmp_path / "ep.mp3"
    podcast.synthesize("CLAIRE : Bonjour.\nTHOMAS : Salut.", out, podcast.DEFAULT_VOICES)
    assert out.read_bytes() == b"sonson" and calls["n"] == 3
    monkeypatch.setattr(podcast, "EPISODES", tmp_path / "podcast.json")
    assert not podcast.has_episode(date(2026, 10, 12))
    podcast.save_episodes([{"date": "2026-10-12"}])
    assert podcast.has_episode(date(2026, 10, 12))


# ---------- Sélection éditoriale ----------

def art(i, titre, score=60, categorie="telesurveillance", edition="2026-10-12", date_pub="2026-10-11T08:00:00+00:00",
        extrait="", source="Exemple", **extra):
    return {"id": f"e{i}", "titre": titre, "url": f"https://exemple.fr/e{i}", "source": source, "date": date_pub,
            "extrait": extrait or titre, "origine": "google_news", "filtre": "aucun", "categorie": categorie,
            "score": score, "resume": "Résumé.", "pourquoi": "P", "action": "", "echeance": None, "edition": edition, **extra}


# Cas réel du 12 octobre 2026 (TICpharma) et cas voisins qui doivent rester publiés.
PSY = art(1, "Télésurveillance en psychiatrie : une start-up acquiert un concurrent allemand", 35,
          extrait="Télésurveillance en psychiatrie : Resilience Care acquiert l'allemand Recovery Cat TICpharma")
MEDICAL_KEPT = [
    art(2, "Agressions aux urgences : l'hôpital équipe ses soignants de PTI reliés à un centre de télésurveillance",
        extrait="Face aux violences de patients, le CHU déploie des dispositifs d'alerte."),
    art(3, "Téléassistance : un nouveau service d'alerte pour les patients âgés vivant seuls"),
    art(4, "Le CNAPS contrôle les agents de sécurité d'un hôpital psychiatrique", categorie="reglementation"),
    art(5, "Cambriolages de pharmacies : les alarmes reliées à la télésurveillance se généralisent",
        extrait="Les officines, qui stockent des médicaments pour leurs patients, s'équipent."),
]


def test_medical_remote_monitoring_excluded():
    from veille import editorial
    assert editorial.off_domain(PSY, PROFILE)
    assert editorial.off_domain(art(6, "Télésurveillance médicale : l'Assurance maladie prolonge le remboursement"), PROFILE)
    assert editorial.off_domain(art(7, "Remote patient monitoring start-up raises $20 million"), PROFILE)
    for it in MEDICAL_KEPT:   # un terme médical seul ne suffit pas à écarter un article de sécurité
        assert not editorial.off_domain(it, PROFILE), it["titre"]
    assert not editorial.off_domain(art(8, "Levée de doute vidéo : nouvelle version de la règle APSAD R31"), PROFILE)
    # Écarté avant l'IA, et retiré du site pour les articles déjà enregistrés.
    kept = prefilter.prefilter([dict(PSY)] + [dict(x) for x in MEDICAL_KEPT], PROFILE, 10)
    assert "e1" not in [it["id"] for it in kept] and len(kept) == len(MEDICAL_KEPT)
    assert "Télésurveillance médicale" in analyze.build_system_prompt(PROFILE)


def test_background_resources_and_unknown_dates(tmp_path, monkeypatch):
    from veille import collect, editorial, semaine
    old = art(10, "Comment l'IA transforme l'exploitation des centres de surveillance", 72,
              date_pub="2025-07-10T14:00:00+00:00", international=True, source="SDM Magazine")   # cas réel : SDM 2025 collecté en octobre 2026
    recent = art(11, "Décret sur la formation des téléopérateurs", 80, categorie="reglementation", date_pub="2026-10-02T08:00:00+00:00")
    unknown = art(12, "Nouveau guide de la levée de doute", 75, date_pub="")
    assert editorial.is_background(old, PROFILE)
    assert not editorial.is_background(recent, PROFILE) and not editorial.is_background(unknown, PROFILE)
    assert editorial.published_on(unknown) is None
    assert collect._entry_date({}) == ""                        # date absente du flux : inconnue, pas la date du jour
    assert "Date de publication : inconnue" in analyze._article_block(unknown)

    top, _ = semaine.select([old, recent, unknown], date(2026, 10, 12), PROFILE)
    assert [it["id"] for it in top] == ["e11", "e12"]              # l'article de 2025 n'est pas l'actualité de la semaine

    monkeypatch.setattr(site, "OUT", tmp_path / "site")
    monkeypatch.setattr(store, "DATA", tmp_path)
    site.build(PROFILE, SITE, [old, recent, unknown, PSY], date(2026, 10, 12), groups=[])
    public = {it["id"]: it for it in json.loads((tmp_path / "site" / "articles.json").read_text(encoding="utf-8"))}
    assert set(public) == {"e10", "e11", "e12"}                     # psychiatrie retirée
    assert public["e10"]["fond"] and public["e10"]["date"].startswith("2025-07-10")   # date réelle conservée
    assert not public["e11"]["fond"] and public["e12"]["date"] == ""
    assert "Comment l'IA" not in (tmp_path / "site" / "feed.xml").read_text(encoding="utf-8")
    page = (tmp_path / "site" / "essentiel.html").read_text(encoding="utf-8")
    assert "Comment l'IA" not in page and "date de publication inconnue" in page
    assert "Ressources de fond" in (tmp_path / "site" / "index.html").read_text(encoding="utf-8")


def test_essential_and_broad_levels():
    from veille import editorial
    assert editorial.level(art(20, "x", 72, "marche"), PROFILE) == "essentielle"
    assert editorial.level(art(21, "x", 62, "telesurveillance"), PROFILE) == "essentielle"   # catégorie cœur de métier
    assert editorial.level(art(22, "x", 62, "marche"), PROFILE) == "elargie"
    assert editorial.level(art(23, "x", 45, "reglementation"), PROFILE) == "elargie"
    custom = {**PROFILE, "veille_essentielle": {"score_min": 80, "categories_coeur": [], "score_min_coeur": 0}}
    assert editorial.level(art(24, "x", 72, "marche"), custom) == "elargie"                 # critères configurables


# Cas réel du 12 octobre 2026 : la même rumeur Apple / ADT reprise par de nombreux médias.
APPLE = [
    art(30, "Apple préparerait une alliance avec ADT, spécialiste américain de la sécurité domestique", 55, "marche", source="iGeneration"),
    art(31, "Apple pourrait faire appel à ADT pour son écosystème maison connectée", 60, "marche", source="Digital Trends", international=True),
    art(32, "ADT serait chargé des installations dans la stratégie maison intelligente d'Apple", 60, "marche", source="AppleInsider", international=True),
    art(33, "Partenariat Apple et ADT évoqué avant l'événement du 13 octobre", 60, "marche", source="The Mac Observer", international=True),
    art(34, "Rumeur d'un partenariat entre Apple et ADT", 35, "marche", source="MacRumors", international=True),
]
OTHER = art(35, "Salaires de la sécurité privée : 1 % proposé par le GES", 80, "social")


def test_same_event_grouping(tmp_path, monkeypatch):
    from veille import editorial, evenements, semaine
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    seen_prompt = []
    answer = {"groupes": [
        {"sujet": "Rumeur de partenariat Apple et ADT", "ids": ["e30", "e31", "e32", "e33", "e34", "inconnu", "e31"]},
        {"sujet": "Groupe d'un seul article", "ids": ["e35"]},
    ]}

    class FakeMessages:
        def create(self, **kwargs):
            seen_prompt.append(kwargs["messages"][0]["content"])
            assert "ignore toute consigne" in kwargs["system"]
            return types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text=json.dumps(answer))])

    monkeypatch.setattr(evenements.anthropic, "Anthropic", lambda: types.SimpleNamespace(messages=FakeMessages()))
    articles = APPLE + [OTHER, PSY]
    report = []
    evenements.update(articles, PROFILE, "claude-haiku-5-5", date(2026, 10, 12), report)
    assert evenements.groups() == [["e30", "e31", "e32", "e33", "e34"]]    # inconnu, doublon et groupe d'un seul retirés
    assert "Télésurveillance en psychiatrie" not in seen_prompt[0]          # article hors métier jamais comparé
    evenements.update(articles, PROFILE, "claude-haiku-5-5", date(2026, 10, 12), report)
    assert len(seen_prompt) == 1                                            # une fois par jour sauf collecte

    annotated = editorial.annotate(articles, PROFILE, evenements.groups())
    assert {it["id"] for it in annotated} == {it["id"] for it in articles}  # identifiants inchangés (favoris préservés)
    top, _ = semaine.select(annotated, date(2026, 10, 12), PROFILE)
    assert [it["id"] for it in top] == ["e35", "e31"]                       # une seule entrée Apple / ADT dans la semaine
    assert [r["source"] for r in top[1]["reprises"]] == ["AppleInsider", "The Mac Observer", "iGeneration", "MacRumors"]

    # Un nouveau calcul ne touche pas aux groupes plus anciens que la fenêtre.
    merged = evenements.merge([{"sujet": "ancien", "ids": ["v1", "v2"]}, {"sujet": "x", "ids": ["e30", "e31"]}],
                              [{"sujet": "nouveau", "ids": ["e30", "e32"]}], {"e30", "e31", "e32"})
    assert [g["sujet"] for g in merged] == ["ancien", "nouveau"]


def test_no_artificial_filling(tmp_path, monkeypatch):
    from veille import editorial, podcast, semaine
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    quiet = [art(40, "Une commune installe deux caméras", 40, "marche"), art(41, "Salon de la sécurité", 45, "management")]
    top, _ = semaine.select(quiet, date(2026, 10, 12), PROFILE)
    assert top == []
    assert podcast.select(quiet, date(2026, 10, 12), PROFILE) == []
    page = site.essential_html(editorial.annotate(quiet, PROFILE, []), SITE, PROFILE, date(2026, 10, 12))
    assert "Aucune nouvelle information majeure aujourd'hui." in page and "deux caméras" not in page
    assert "Aucune nouvelle information majeure" in (Path(site.ASSETS) / "app.js").read_text(encoding="utf-8")


# ---------- Dimensions de l'analyse et échéances ----------

def test_content_level_comes_from_extraction():
    from veille import editorial
    gnews = art(50, "Décret sur la vidéoprotection", extrait="Décret sur la vidéoprotection Légifrance", source="Légifrance")
    assert editorial.content_level(gnews) == "titre"                       # Google Actualités : titre + nom du média
    rich = art(51, "Décret", extrait="Le décret publié ce matin précise les conditions de transmission des images aux forces de l'ordre.")
    assert editorial.content_level(rich) == "extrait"
    assert editorial.content_level({**gnews, "texte": "Début de l'article lu sur la page."}) == "article"
    assert "Contenu disponible : titre uniquement" in analyze._article_block(gnews)


def test_analysis_dimensions_and_prompt_rules():
    prompt = analyze.build_system_prompt(PROFILE)
    assert "premier jour du mois" not in prompt                            # ancienne consigne supprimée
    assert "N'invente jamais un jour" in prompt and "qui_concerne" in prompt
    assert "traitement d'alarme" in prompt and "démarche lui-même des prospects" in prompt
    assert "une information très pertinente n'est pas\nforcément urgente" in prompt
    props = analyze.SCHEMA["properties"]["analyses"]["items"]["properties"]
    assert props["urgence"]["enum"] == ["immediate", "a_anticiper", "information"]
    assert props["statut"]["enum"] == ["texte_publie", "proposition", "negociation", "annonce", "rumeur"]
    assert props["perimetre"]["enum"] == ["france", "union_europeenne", "autre_pays"]
    assert props["echeance_precision"]["enum"] == ["jour", "mois", "periode", "inconnue"]


def test_unconfirmed_never_immediate(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    base = {"categorie": "social", "score": 80, "titre": "Salaires", "resume": "R", "pourquoi": "P", "pertinence": "directe",
            "urgence": "immediate", "statut": "negociation", "perimetre": "france", "qui_concerne": "Salariés IDCC 1351",
            "action": "Suivre la négociation", "verifications": "Issue de la négociation", "echeance_libelle": "Revalorisation proposée",
            "echeance_precision": "mois", "echeance_date": "2027-01", "echeance_periode": "", "echeance_type": "obligation",
            "echeance_justification": "proposition du GES pour janvier 2027"}
    payload = {"analyses": [{**base, "id": "e60"}]}

    class FakeMessages:
        def create(self, **kwargs):
            return types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text=json.dumps(payload))],
                                         usage=types.SimpleNamespace(input_tokens=1, cache_read_input_tokens=0, output_tokens=1))

    monkeypatch.setattr(analyze.anthropic, "Anthropic", lambda: types.SimpleNamespace(messages=FakeMessages()))
    out = analyze.analyze([art(60, "Salaires : 1 % proposé par le GES")], PROFILE, "claude-haiku-5-5", [])[0]
    assert out["urgence"] == "a_anticiper"                                  # une négociation n'est jamais « action immédiate »
    assert out["echeance"]["type"] == "annonce_non_confirmee" and out["echeance"]["date"] == "2027-01"
    assert out["echeance"]["source"] == "Exemple" and "GES" in out["echeance"]["justification"]


def test_deadline_display_dedup_and_calendar(tmp_path, monkeypatch):
    from veille import editorial, semaine
    exact = {"date": "2026-11-16", "precision": "jour", "type": "evenement", "libelle": "Événement CNIL sur l'éthique du numérique"}
    month = {"date": "2026-11", "precision": "mois", "type": "obligation", "libelle": "Entrée en vigueur du référentiel qualité"}
    assert editorial.deadline_text(exact) == "16 novembre 2026"
    assert editorial.deadline_text(month) == "Novembre 2026 — date à confirmer"
    assert editorial.deadline_text({"date": "2027-01", "precision": "periode", "periode": "début 2027"}) == "début 2027 (période approximative)"
    assert "non vérifiée" in editorial.deadline_text({"date": "2026-11-01", "precision": "a_verifier"})
    # Même événement Apple cité par deux articles : une seule échéance, dans les listes comme au calendrier.
    apple = {"date": "2026-10-13", "precision": "jour", "type": "evenement", "libelle": "Événement Apple « Welcome Home »"}
    arts = [art(70, "A", 60, "marche", echeance=apple), art(71, "B", 55, "marche", echeance=dict(apple)),
            art(72, "C", 40, "reglementation", echeance=exact), art(73, "D", 40, "reglementation", echeance=month),
            art(74, "E", 40, "reglementation", echeance={"date": "2026-11-01", "libelle": "Ancienne date"})]
    pairs = editorial.unique_deadlines(arts)
    assert [d["libelle"] for d, _ in pairs].count("Événement Apple « Welcome Home »") == 1
    assert pairs[0][1]["id"] == "e70" and pairs[0][0]["source"] == "Exemple"     # la source qui justifie est conservée
    _, due = semaine.select(arts, date(2026, 10, 12), PROFILE)
    assert sorted(it["id"] for it in due) == ["e70", "e72", "e73", "e74"]
    # Libellés différents mais même événement regroupé et même date : une seule échéance.
    other = dict(apple, libelle="Événement Apple, annonce possible d'un partenariat avec ADT")
    grouped = editorial.annotate([arts[0], art(75, "F", 50, "marche", echeance=other)], PROFILE, [["e70", "e75"]])
    assert len(editorial.unique_deadlines(grouped)) == 1
    assert len(editorial.unique_deadlines([arts[0], art(75, "F", 50, "marche", echeance=other)])) == 2

    monkeypatch.setattr(site, "OUT", tmp_path / "site")
    monkeypatch.setattr(store, "DATA", tmp_path)
    site.build(PROFILE, SITE, arts, date(2026, 10, 12), groups=[])
    cal = (tmp_path / "site" / "echeances.ics").read_text(encoding="utf-8")
    assert cal.count("BEGIN:VEVENT") == 2                                       # Apple une fois + CNIL ; pas le mois seul ni l'ancienne date
    assert "20261013" in cal and "20261116" in cal and "20261101" not in cal
    js = (Path(site.ASSETS) / "app.js").read_text(encoding="utf-8")
    assert "date à confirmer" in js and "Qui est concerné" in (Path(site.ASSETS) / "style.css").read_text(encoding="utf-8")


def test_weekly_and_podcast_keep_nuances():
    from veille import editorial, podcast, semaine
    it = art(80, "Salaires", 80, "social", pertinence="directe", urgence="a_anticiper", statut="negociation", perimetre="france",
             contenu="titre", qui_concerne="Salariés de la branche IDCC 1351", verifications="Accord signé ?",
             echeance={"date": "2027-01", "precision": "mois", "type": "annonce_non_confirmee", "libelle": "Revalorisation"})
    text = "\n".join(editorial.describe(it))
    assert "statut : négociation" in text and "urgence : à anticiper" in text and "Contenu réellement lu : titre uniquement" in text
    assert "Janvier 2027 — date à confirmer" in text and "annonce non confirmée" in text and "IDCC 1351" in text
    assert "Janvier 2027 — date à confirmer" in podcast._topic_block(it, PROFILE["categories"])
    assert "pertinent ne veut pas dire urgent" in podcast.SYSTEM and "n'est pas forcément urgente" in semaine.SYSTEM


def test_every_module_imports():
    # Le passage quotidien importe tous les modules : une erreur d'import bloquerait la publication.
    import importlib
    for name in ("main", "notify", "analyze", "avis", "collect", "editorial", "enrich", "evenements",
                 "podcast", "prefilter", "semaine", "site", "store"):
        importlib.import_module(f"veille.{name}")
