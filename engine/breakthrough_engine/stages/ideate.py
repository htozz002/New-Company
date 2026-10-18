"""Ideate: idea mode. Research an idea, find the breakthrough it needs, then judge and design it."""

from __future__ import annotations

import hashlib
import json
import logging

from .. import prompts
from ..config import Config
from ..llm import LLM, LLMError
from ..models import Paper
from ..store import Store
from . import design, judge

log = logging.getLogger(__name__)


def run(idea: str, cfg: Config, store: Store, llm: LLM, design_it: bool = True, source: Paper | None = None) -> int:
    """Returns the new opportunity's id. Raises LLMError if research or planning fails.

    `source` is the study an unmet need came from (see stages/needs.py); the
    opportunity is then recorded as a need and linked to that study.
    """
    idea_block = f"<idea>\n{idea}\n</idea>"
    research = llm.research(
        "idea_research",
        prompts.ENGINE_SYSTEM,
        prompts.IDEA_RESEARCH_PROMPT.format(idea=idea),
        effort=cfg.effort_ideate,
        max_searches=cfg.max_web_searches,
    )
    plan = llm.structured(
        "idea_plan",
        prompts.ENGINE_SYSTEM,
        prompts.IDEA_PLAN_PROMPT.format(idea=idea, research=research.text),
        prompts.IDEA_PLAN_SCHEMA,
        effort=cfg.effort_ideate,
    )
    extra = {"idea": idea, "research_sources": research.sources}
    if source:
        extra.update(need_source=source.key, need_source_title=source.title, need_source_url=source.url)
    paper = Paper(
        source="need" if source else "idea",
        # A need is keyed by its study, so the same study is never explored twice.
        source_id=source.key if source else hashlib.sha1(idea.encode()).hexdigest()[:16],
        title=plan["opportunity_title"],
        abstract=plan["opportunity_abstract"],
        kind="idea",
        extra=extra,
    )
    store.add_papers([paper])
    opp_id = store.create_opportunity("need" if source else "idea", paper_key=paper.key, idea_text=idea,
                                      idea_plan=plan)

    context = f"{idea_block}\n<breakthrough_plan>\n{json.dumps(plan, indent=2)}\n</breakthrough_plan>"
    if judge.judge_one(opp_id, paper, cfg, store, llm, extra_context=context) and design_it:
        design.design_one(opp_id, cfg, store, llm)
    return opp_id


def evaluate(title: str, text: str, url: str, cfg: Config, store: Store, llm: LLM, design_it: bool = True) -> int:
    """Run one specific piece of research (pasted or from a file) through judge and design."""
    paper = Paper(source="manual", source_id=hashlib.sha1((title + text).encode()).hexdigest()[:16],
                  title=title, abstract=text, url=url, kind="paper")
    store.add_papers([paper])
    opp_id = store.create_opportunity("evaluate", paper_key=paper.key)
    if judge.judge_one(opp_id, paper, cfg, store, llm) and design_it:
        design.design_one(opp_id, cfg, store, llm)
    return opp_id


__all__ = ["run", "evaluate", "LLMError"]
