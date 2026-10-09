"""Tests hors ligne : préfiltrage, notation de secours, analyse IA simulée et génération du site."""

import json
import types
from datetime import date
from pathlib import Path

import yaml

from veille import analyze, prefilter, site

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
         "resume": "Un décret modifie la carte.", "pourquoi": "Impact direct sur le centre."},
        {"id": "inconnu", "categorie": "marche", "score": 50, "titre": "x", "resume": "", "pourquoi": ""},
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
    assert "inconnu" not in out
    assert out["id4"]["analyse_par"] == "mots-clés"   # absent de la réponse : notation de secours


def test_site_build(tmp_path, monkeypatch):
    monkeypatch.setattr(site, "OUT", tmp_path / "site")
    arts = [
        {**SAMPLE[0], "edition": "2026-10-08", "categorie": "reglementation", "score": 94, "resume": "R<script>", "pourquoi": "P"},
        {**SAMPLE[3], "edition": "2026-10-09", "categorie": "marche", "score": 55, "resume": "R", "pourquoi": "P"},
        {**SAMPLE[2], "edition": "2026-10-09", "categorie": "reglementation", "score": 10, "resume": "", "pourquoi": "P"},
    ]
    site.build(PROFILE, SITE, arts, date(2026, 10, 9))
    out = tmp_path / "site"
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "Verisure" in index and "CNIL sanctionne" not in index   # score 10 non publié
    assert "&lt;script&gt;" in (out / "editions" / "2026-10-08.html").read_text(encoding="utf-8")
    assert "2026-10-08.html" in index                                # lien vers l'édition précédente
    assert len(json.loads((out / "articles.json").read_text(encoding="utf-8"))) == 2
    assert "<rss" in (out / "feed.xml").read_text(encoding="utf-8")
