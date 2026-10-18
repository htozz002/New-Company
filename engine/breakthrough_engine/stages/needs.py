"""Needs: send documented failures of existing products to idea mode.

A study showing that a widely used product or standard of care fails patients
is not a breakthrough, so triage would drop it. It still points at an open
field, so idea mode researches what could close the gap and the result is
judged like any other opportunity.
"""

from __future__ import annotations

import logging

from .. import prompts
from ..config import Config
from ..llm import LLM, LLMError
from ..models import Paper
from ..store import Store
from . import ideate

log = logging.getLogger(__name__)


def run(cfg: Config, store: Store, llm: LLM, limit: int | None = None) -> dict:
    found = store.needs_to_explore(cfg.need_threshold, limit or cfg.max_needs)
    explored = failed = 0
    for paper, need in found:
        try:
            # Design is left to the design stage, so a need meets the same bar as a discovery.
            ideate.run(idea_text(paper, need, cfg), cfg, store, llm, design_it=False, source=paper)
            explored += 1
        except LLMError as err:
            log.warning("exploring the need in %s failed: %s", paper.key, err)
            failed += 1
    return {"explored": explored, "failed": failed}


def idea_text(paper: Paper, need: str, cfg: Config) -> str:
    return prompts.NEED_IDEA.format(
        need=need or "(see the study below)",
        kinds=", ".join(t.replace("_", " ") for t in cfg.allowed_types),
        title=paper.title, venue=paper.venue or "venue unknown", published=paper.published or "date unknown",
        url=paper.url, abstract=paper.abstract,
    )
