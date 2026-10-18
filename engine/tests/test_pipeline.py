"""End-to-end pipeline test with a stand-in for Claude.

The fake returns fixed, schema-shaped answers so the test checks the engine's
plumbing (storage, routing, scoring, reports), not the quality of any judgment.
"""

import re
from datetime import date

import sqlite3

from breakthrough_engine import prompts, report
from breakthrough_engine.config import Config
from breakthrough_engine.llm import Research
from breakthrough_engine.models import Paper
from breakthrough_engine.stages import design, ideate, judge, needs, ownership, triage
from breakthrough_engine.stages.judge import composite_score
from breakthrough_engine.store import Store


class FakeLLM:
    def __init__(self, score=8, owned=(), needs=False):
        self.score = score
        self.owned = set(owned)  # titles the ownership check finds owned
        self.needs = needs  # whether non-candidates show an unmet need
        self.calls = []
        self.prompts = []

    def research(self, name, system, prompt, **_):
        self.calls.append(name)
        self.prompts.append((name, prompt))
        return Research(text=f"{name} notes", sources=[{"title": "Example source", "url": "https://example.org/a"}])

    def structured(self, name, system, prompt, schema, **_):
        self.calls.append(name)
        self.prompts.append((name, prompt))
        if name == "triage":
            refs = re.findall(r'<research ref="(R\d+)"', prompt)
            # The first item is a strong device candidate, the rest are not.
            return {"items": [
                {"ref": r, "product_type": "device" if i == 0 else "drug", "breakthrough_score": 9 if i == 0 else 3,
                 "buildability_score": 8 if i == 0 else 2, "is_candidate": i == 0,
                 "unmet_need_score": 9 if self.needs and i > 0 else 0,
                 "need": "A widely used alert misses most cases." if self.needs and i > 0 else "", "reason": "test"}
                for i, r in enumerate(refs)
            ]}
        if name == "ownership_verdict":
            title = re.search(r"<title>(.*?)</title>", prompt).group(1)
            if title in self.owned:
                return {"status": "owned", "owner": "SpinoutCo", "evidence": "The lab's spinout sells it.",
                        "wedge": "A pediatric version."}
            return {"status": "open", "owner": "", "evidence": "Nobody found.", "wedge": ""}
        if name == "judge":
            return {
                "scores": {d: {"score": self.score, "rationale": "test"} for d in prompts.DIMENSION_GUIDE},
                "evidence_level": "human_pilot",
                "product_hypothesis": "A patch.",
                "competitors": [{"name": "ExampleCo", "what_they_do": "patches", "stage": "seed", "source_url": ""}],
                "kill_reasons": [],
                "verdict": "pursue",
                "summary": "Worth building.",
            }
        if name == "design":
            phase = {"name": "Prototype", "months": "0-3", "goal": "Works on bench", "deliverables": ["v1"],
                     "estimated_cost_usd": "$50K (estimate)", "exit_criteria": "Reads correctly"}
            return {
                "product_name": "Test Patch", "one_liner": "A patch that tests.", "problem": "p", "who_benefits": "w",
                "breakthrough_used": "b", "how_it_works": "h",
                "prototype_components": [{"component": "Sensor", "purpose": "sense", "off_the_shelf_option": "X"}],
                "build_plan": [phase], "validation_plan": "v", "regulatory_path": "510(k)", "ip_strategy": "i",
                "competitive_edge": "e", "business_model": "m", "funding_sources": ["NIH SBIR"],
                "team_needed": ["engineer"], "risks": [{"risk": "r", "mitigation": "m"}],
                "first_90_days": ["Start"], "kill_criteria": ["Fails"],
            }
        if name == "idea_plan":
            return {
                "problem": "p", "key_obstacle": "o", "why_unsolved": "w",
                "enabling_advances": [{"advance": "a", "source_url": "https://example.org/a"}],
                "approaches": [{"name": "A1", "mechanism": "m", "what_is_new": "n", "feasibility_now": "f",
                                "first_experiment": "e", "experiment_cost_and_time": "$10K, 2 months"}],
                "recommended_approach": "A1", "why_recommended": "simplest",
                "opportunity_title": "Proposed: a better patch", "opportunity_abstract": "Proposed approach.",
            }
        raise AssertionError(f"unexpected structured call {name}")


def make_store(tmp_path):
    return Store(str(tmp_path / "engine.db"))


def paper(i):
    return Paper(source="biorxiv", source_id=f"10.1101/{i}", title=f"Finding {i}", abstract="Synthetic abstract.",
                 url=f"https://doi.org/10.1101/{i}", published=f"2026-10-1{i}", kind="preprint")


def test_discovery_pipeline_end_to_end(tmp_path):
    cfg = Config(db_path=str(tmp_path / "engine.db"), output_dir=str(tmp_path / "out"), triage_batch_size=2)
    store = make_store(tmp_path)
    assert store.add_papers([paper(1), paper(2), paper(3)]) == 3
    assert store.add_papers([paper(1)]) == 0  # duplicates are ignored

    llm = FakeLLM()
    t = triage.run(cfg, store, llm)
    assert t["screened"] == 3 and t["candidates"] == 2  # first item of each batch of 2

    j = judge.run(cfg, store, llm)
    assert j == {"judged": 2, "failed": 0}
    assert judge.run(cfg, store, llm) == {"judged": 0, "failed": 0}  # never judged twice

    d = design.run(cfg, store, llm, limit=1)
    assert d == {"designed": 1, "failed": 0}

    designed = store.opportunities(status="designed")[0]
    assert designed["composite"] == 80.0
    text = (tmp_path / "out").rglob("*.md").__next__().read_text()
    assert "# Test Patch" in text and "Score 80/100" in text and "[Example source](https://example.org/a)" in text


def test_low_scores_are_not_designed(tmp_path):
    cfg = Config(db_path=str(tmp_path / "engine.db"), output_dir=str(tmp_path / "out"))
    store = make_store(tmp_path)
    store.add_papers([paper(1)])
    llm = FakeLLM(score=4)
    triage.run(cfg, store, llm)
    judge.run(cfg, store, llm)
    assert design.run(cfg, store, llm) == {"designed": 0, "failed": 0}


def test_idea_mode(tmp_path):
    cfg = Config(db_path=str(tmp_path / "engine.db"), output_dir=str(tmp_path / "out"))
    store = make_store(tmp_path)
    llm = FakeLLM()
    opp_id = ideate.run("A patch that warns of dehydration in the elderly", cfg, store, llm)

    opp = store.get_opportunity(opp_id)
    assert opp["origin"] == "idea" and opp["status"] == "designed"
    assert opp["idea_plan"]["recommended_approach"] == "A1"
    assert llm.calls == ["idea_research", "idea_plan", "landscape", "judge", "design"]
    assert "The breakthrough this idea needs" in open(opp["report_path"]).read()


def test_failed_judging_is_retried(tmp_path):
    from breakthrough_engine.llm import LLMError

    class FlakyLLM(FakeLLM):
        fail = True

        def research(self, name, *args, **kwargs):
            if name == "landscape" and self.fail:
                raise LLMError("temporary outage")
            return super().research(name, *args, **kwargs)

    cfg = Config(db_path=str(tmp_path / "engine.db"), output_dir=str(tmp_path / "out"))
    store = make_store(tmp_path)
    store.add_papers([paper(1)])
    llm = FlakyLLM()
    triage.run(cfg, store, llm)
    assert judge.run(cfg, store, llm) == {"judged": 0, "failed": 1}
    llm.fail = False
    assert judge.run(cfg, store, llm) == {"judged": 1, "failed": 0}
    assert len(store.opportunities()) == 1


def test_composite_weights():
    cfg = Config()
    perfect = {d: {"score": 10} for d in cfg.weights}
    assert composite_score(perfect, cfg.weights) == 100.0
    assert abs(sum(cfg.weights.values()) - 1.0) < 1e-9


def test_easy_to_copy_product_stays_below_design_bar():
    # The October 2026 scan's top score: a randomized trial of an LLM tool that is
    # easy to build and lightly regulated, but that Epic and funded startups
    # already sell. It scored 63.5 under the old weights and was still dropped.
    scores = {"breakthrough": 4, "evidence": 9, "impact": 5, "buildability": 9, "winnability": 2,
              "regulatory": 8, "capital_efficiency": 6, "funding_fit": 5}
    scored = {d: {"score": v} for d, v in scores.items()}
    cfg = Config()
    assert composite_score(scored, cfg.weights) < cfg.design_min_composite
    assert cfg.weights["winnability"] == max(cfg.weights.values())


def test_owned_candidates_are_not_judged(tmp_path):
    cfg = Config(db_path=str(tmp_path / "engine.db"), output_dir=str(tmp_path / "out"), triage_batch_size=1)
    store = make_store(tmp_path)
    store.add_papers([paper(1), paper(2), paper(3)])
    llm = FakeLLM(owned={"Finding 2"})
    assert triage.run(cfg, store, llm)["candidates"] == 3

    assert ownership.run(cfg, store, llm) == {"checked": 3, "owned": 1, "failed": 0}
    assert ownership.run(cfg, store, llm) == {"checked": 0, "owned": 0, "failed": 0}  # never checked twice

    assert judge.run(cfg, store, llm) == {"judged": 2, "failed": 0}
    assert store.discovery_opportunity_id("biorxiv:10.1101/2") is None
    landscape_prompts = [p for name, p in llm.prompts if name == "landscape"]
    assert all('<ownership_check status="open">' in p for p in landscape_prompts)

    owned = store.owned()
    assert [(p.title, c["owner"]) for p, c in owned] == [("Finding 2", "SpinoutCo")]
    board = report.leaderboard(store.opportunities(), {}, owned)
    assert "## Already owned" in board and "[Finding 2](https://doi.org/10.1101/2)" in board
    assert "A pediatric version." in board


def test_unmet_need_goes_to_idea_mode(tmp_path):
    cfg = Config(db_path=str(tmp_path / "engine.db"), output_dir=str(tmp_path / "out"))
    store = make_store(tmp_path)
    store.add_papers([paper(1), paper(2)])
    llm = FakeLLM(needs=True)
    assert triage.run(cfg, store, llm)["unmet_needs"] == 1

    assert needs.run(cfg, store, llm) == {"explored": 1, "failed": 0}
    assert needs.run(cfg, store, llm) == {"explored": 0, "failed": 0}  # each study is explored once
    assert triage.run(cfg, store, llm)["screened"] == 0  # the need's own record is not screened again
    assert llm.calls[-4:] == ["idea_research", "idea_plan", "landscape", "judge"]
    idea_prompt = next(p for name, p in llm.prompts if name == "idea_research")
    assert "A widely used alert misses most cases." in idea_prompt

    opp = store.opportunities(status="judged")[0]
    assert opp["origin"] == "need" and opp["paper_key"].startswith("need:biorxiv:")
    source_key = store.get_paper(opp["paper_key"]).extra["need_source"]
    assert store.get_paper(source_key).title in idea_prompt

    # A need meets the same design bar as a discovery.
    assert design.run(cfg, store, llm) == {"designed": 1, "failed": 0}
    brief = open(store.get_opportunity(opp["id"])["report_path"]).read()
    assert "**Unmet need found in:**" in brief and "origin: need" in brief


def test_old_database_gets_new_columns(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE triage (paper_key TEXT PRIMARY KEY, product_type TEXT, breakthrough_score INTEGER,
            buildability_score INTEGER, is_candidate INTEGER, reason TEXT, triaged_at TEXT NOT NULL);
        INSERT INTO triage VALUES ('biorxiv:10.1101/1', 'device', 9, 8, 1, 'old row', '2026-10-01T00:00:00+00:00');
    """)
    old.commit()
    old.close()

    store = Store(str(path))
    store.add_papers([paper(1), paper(2)])
    store.save_triage("biorxiv:10.1101/2", {"product_type": "drug", "breakthrough_score": 2, "buildability_score": 2,
                                           "is_candidate": False, "unmet_need_score": 8, "need": "A gap.",
                                           "reason": "new row"})
    assert [(p.key, need) for p, need in store.needs_to_explore(7, 5)] == [("biorxiv:10.1101/2", "A gap.")]
    assert [p.key for p in store.candidates_to_judge(["device"], 6.0, 5)] == ["biorxiv:10.1101/1"]


def test_web_scout_keeps_only_urls_it_saw(tmp_path):
    from breakthrough_engine.stages import scout

    class WebLLM(FakeLLM):
        def structured(self, name, system, prompt, schema, **_):
            assert name == "web_scout_extract"
            return {"results": [
                {"title": "Real", "url": "https://example.org/a", "published": "2026-10-15", "venue": "J", "summary": "s"},
                {"title": "Invented", "url": "https://made-up.example/x", "published": "", "venue": "", "summary": "s"},
            ]}

    papers = scout.web_scout(Config(), WebLLM(), date(2026, 10, 10), date(2026, 10, 17))
    assert [p.title for p in papers] == ["Real"]
