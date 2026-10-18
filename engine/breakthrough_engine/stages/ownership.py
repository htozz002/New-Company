"""Ownership check: a second screen, before judging, for work someone already owns.

In the October 2026 scan, 8 of 11 judged opportunities turned out to belong to
the lab's own spinout or a funded company. A few web searches per triage
survivor find that before the expensive judging research runs.
"""

from __future__ import annotations

import logging

from .. import prompts
from ..config import Config
from ..llm import LLM, LLMError
from ..models import Paper
from ..store import Store

log = logging.getLogger(__name__)


def run(cfg: Config, store: Store, llm: LLM, limit: int | None = None) -> dict:
    papers = store.candidates_to_check(cfg.allowed_types, cfg.triage_threshold, limit or cfg.max_ownership_checks)
    counts = {"checked": 0, "owned": 0, "failed": 0}
    for paper in papers:
        try:
            result, sources = check(paper, cfg, llm)
        except LLMError as err:
            # An unchecked paper can still be judged; the check is retried next run.
            log.warning("ownership check of %s failed: %s", paper.key, err)
            counts["failed"] += 1
            continue
        store.save_ownership(paper.key, result, sources)
        counts["checked"] += 1
        counts["owned"] += int(result["status"] == "owned")
    return counts


def check(paper: Paper, cfg: Config, llm: LLM) -> tuple[dict, list[dict]]:
    subject = paper.as_prompt_block()
    notes = llm.research(
        "ownership",
        prompts.ENGINE_SYSTEM,
        prompts.OWNERSHIP_PROMPT.format(subject=subject),
        effort=cfg.effort_ownership,
        max_searches=cfg.ownership_searches,
    )
    result = llm.structured(
        "ownership_verdict",
        prompts.ENGINE_SYSTEM,
        prompts.OWNERSHIP_VERDICT_PROMPT.format(subject=subject, notes=notes.text or "(no notes returned)"),
        prompts.OWNERSHIP_SCHEMA,
        effort="low",
    )
    return result, notes.sources


def context_block(check: dict | None) -> str:
    """The check's findings, for the judge to start from."""
    if not check:
        return ""
    lines = [f"Owner or closest company: {check['owner'] or 'none found'}", f"Evidence: {check['evidence']}"]
    if check["wedge"]:
        lines.append(f"Adjacent product a new company could own: {check['wedge']}")
    return f'<ownership_check status="{check["status"]}">\n' + "\n".join(lines) + "\n</ownership_check>"
