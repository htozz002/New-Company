"""Parser tests against synthetic records shaped like each API's responses."""

import json
from datetime import date
from pathlib import Path

from breakthrough_engine.sources import biorxiv, clinicaltrials, europepmc

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def test_europepmc_parses_papers_and_preprints(monkeypatch):
    data = load("europepmc_search.json")
    calls = []

    def fake_get_json(url, params=None, **_):
        calls.append(params)
        return data if len(calls) == 1 else {"resultList": {"result": []}, "nextCursorMark": params["cursorMark"]}

    monkeypatch.setattr(europepmc, "get_json", fake_get_json)
    papers = europepmc.search("wearable sensor", date(2026, 10, 10), date(2026, 10, 17), limit=10)

    assert [p.kind for p in papers] == ["paper", "preprint"]
    first = papers[0]
    assert first.title == "A soft wearable ultrasound patch for continuous bladder monitoring"
    assert first.abstract.startswith("Background Synthetic")
    assert first.url == "https://doi.org/10.1000/example.wearable.2026"
    assert first.venue == "Example Journal of Devices"
    assert papers[1].venue == "medRxiv"
    assert "FIRST_PDATE:[2026-10-10 TO 2026-10-17]" in calls[0]["query"]


def test_biorxiv_filters_by_topic_and_keeps_latest_version(monkeypatch):
    monkeypatch.setattr(biorxiv, "get_json", lambda url, **_: load("biorxiv_details.json"))
    papers = biorxiv.recent("biorxiv", date(2026, 10, 10), date(2026, 10, 17), ["wearable sensor"])

    assert len(papers) == 1
    assert papers[0].extra["version"] == "2"
    assert papers[0].kind == "preprint"
    assert papers[0].key == "biorxiv:10.1101/2026.10.01.000001"


def test_clinicaltrials_parses_device_study(monkeypatch):
    monkeypatch.setattr(clinicaltrials, "get_json", lambda url, params=None, **_: load("clinicaltrials_studies.json"))
    studies = clinicaltrials.search("wearable", date(2026, 10, 10))

    assert len(studies) == 1
    study = studies[0]
    assert study.source_id == "NCT09000001"
    assert study.kind == "trial"
    assert "DEVICE: Fluid patch" in study.abstract
    assert study.published == "2026-10-13"
    assert study.url == "https://clinicaltrials.gov/study/NCT09000001"
