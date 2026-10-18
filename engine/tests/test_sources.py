"""Parser tests against synthetic records shaped like each API's responses."""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from breakthrough_engine.config import Config
from breakthrough_engine.sources import biorxiv, clinicaltrials, europepmc, nih_reporter
from breakthrough_engine.stages import scout
from breakthrough_engine.store import Store

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


def test_nih_reporter_parses_new_grants(monkeypatch):
    bodies = []

    def fake_post_json(url, body, **_):
        bodies.append(body)
        return load("nih_reporter_search.json")

    monkeypatch.setattr(nih_reporter, "post_json", fake_post_json)
    grants = nih_reporter.search("wearable sensor", date(2026, 10, 10), date(2026, 10, 17), limit=10)

    assert len(bodies) == 1  # the page held every result the API reported
    criteria = bodies[0]["criteria"]
    assert criteria["award_notice_date"] == {"from_date": "2026-10-10", "to_date": "2026-10-17"}
    assert criteria["advanced_text_search"]["search_text"] == "wearable sensor"
    assert criteria["award_types"] == ["1", "2"]

    assert [g.source_id for g in grants] == ["90000001", "90000002"]
    sbir = grants[0]
    assert sbir.kind == "grant" and sbir.key == "nih_reporter:90000001"
    assert sbir.title == "A wearable patch to detect early heart failure decompensation"
    assert sbir.published == "2026-10-14"
    assert sbir.url == "https://reporter.nih.gov/project-details/90000001"
    assert sbir.venue == "NIH NHLBI R43: EXAMPLE SENSORS, INC."
    assert sbir.authors == "Ada Example, Ben Example"
    assert sbir.extra["small_business"] is True
    assert "Small-business award, so the organization is a company" in sbir.abstract
    assert "$305,000" in sbir.abstract

    university = grants[1]
    assert university.extra["small_business"] is False
    assert university.authors == "LAB, CARA"
    assert "Small-business" not in university.abstract


def test_cli_runs_without_the_claude_sdk():
    # The weekly database pull runs scout where the anthropic package can't be installed.
    code = "import sys; sys.modules['anthropic'] = None; from breakthrough_engine import cli; cli.main(['config'])"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_scout_looks_back_a_month_for_nih_grants(monkeypatch, tmp_path):
    windows = []
    monkeypatch.setattr(nih_reporter, "search", lambda topic, since, until, limit: windows.append((since, until)) or [])
    cfg = Config(db_path=str(tmp_path / "engine.db"), topics=["biosensor"], sources=["nih_reporter"], lookback_days=7)
    scout.run(cfg, Store(cfg.db_path), today=date(2026, 10, 18))
    assert windows == [(date(2026, 9, 18), date(2026, 10, 18))]
