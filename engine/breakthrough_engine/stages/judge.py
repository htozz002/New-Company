"""Judge: research the landscape around a candidate, then score it."""

from __future__ import annotations

import logging

from .. import prompts
from ..config import Config
from ..llm import LLM, LLMError
from ..models import Paper
from ..store import Store
from . import ownership

log = logging.getLogger(__name__)


def run(cfg: Config, store: Store, llm: LLM, limit: int | None = None) -> dict:
    papers = store.candidates_to_judge(cfg.allowed_types, cfg.triage_threshold, limit or cfg.max_judged)
    judged = failed = 0
    for paper in papers:
        # A paper whose judging failed last run keeps its opportunity and is retried.
        opp_id = store.discovery_opportunity_id(paper.key) or store.create_opportunity("discovery", paper_key=paper.key)
        check = ownership.context_block(store.get_ownership(paper.key))
        if judge_one(opp_id, paper, cfg, store, llm, extra_context=check):
            judged += 1
        else:
            failed += 1
    return {"judged": judged, "failed": failed}


def judge_one(opp_id: int, paper: Paper, cfg: Config, store: Store, llm: LLM, extra_context: str = "") -> bool:
    subject = paper.as_prompt_block() + (f"\n\n{extra_context}" if extra_context else "")
    try:
        landscape = llm.research(
            "landscape",
            prompts.ENGINE_SYSTEM,
            prompts.LANDSCAPE_PROMPT.format(subject=subject),
            effort=cfg.effort_judge,
            max_searches=cfg.max_web_searches,
        )
        store.update_opportunity(opp_id, landscape=landscape.text, landscape_sources=landscape.sources)
        evaluation = llm.structured(
            "judge",
            prompts.ENGINE_SYSTEM,
            prompts.JUDGE_PROMPT.format(dimensions=prompts.dimension_lines(), subject=subject,
                                        landscape=landscape.text or "(no research returned)"),
            prompts.JUDGE_SCHEMA,
            effort=cfg.effort_judge,
        )
    except LLMError as err:
        log.warning("judging %s failed: %s", paper.key, err)
        store.update_opportunity(opp_id, status="failed", error=str(err))
        return False
    composite = composite_score(evaluation["scores"], cfg.weights)
    store.update_opportunity(opp_id, evaluation=evaluation, composite=composite,
                             verdict=evaluation["verdict"], status="judged")
    return True


def composite_score(scores: dict, weights: dict) -> float:
    """Weighted 0-100 score from the 0-10 dimension scores."""
    total = sum(weights[d] * max(0, min(10, scores[d]["score"])) for d in weights)
    return round(total * 10, 1)
