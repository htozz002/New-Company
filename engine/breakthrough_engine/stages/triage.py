"""Triage: a fast, cheap screen of every new item, in batches."""

from __future__ import annotations

import logging

from .. import prompts
from ..config import Config
from ..llm import LLM, LLMError
from ..models import Paper
from ..store import Store

log = logging.getLogger(__name__)


def run(cfg: Config, store: Store, llm: LLM, limit: int | None = None) -> dict:
    papers = store.untriaged_papers(limit)
    screened = candidates = failed_batches = 0
    for start in range(0, len(papers), cfg.triage_batch_size):
        batch = papers[start:start + cfg.triage_batch_size]
        try:
            results = screen(batch, cfg, llm)
        except LLMError as err:
            log.warning("triage batch failed: %s", err)
            failed_batches += 1
            continue
        for paper, item in results:
            store.save_triage(paper.key, item)
            screened += 1
            candidates += int(item["is_candidate"])
    return {"screened": screened, "candidates": candidates, "failed_batches": failed_batches,
            "remaining": len(papers) - screened}


def screen(batch: list[Paper], cfg: Config, llm: LLM) -> list[tuple[Paper, dict]]:
    refs = {f"R{i + 1}": p for i, p in enumerate(batch)}
    items = "\n\n".join(p.as_prompt_block(ref) for ref, p in refs.items())
    data = llm.structured(
        "triage",
        prompts.ENGINE_SYSTEM,
        prompts.TRIAGE_PROMPT.format(n=len(batch), items=items),
        prompts.TRIAGE_SCHEMA,
        effort=cfg.effort_triage,
    )
    out = []
    for item in data["items"]:
        paper = refs.pop(item["ref"], None)
        if paper is None:
            continue
        item["breakthrough_score"] = _clamp(item["breakthrough_score"])
        item["buildability_score"] = _clamp(item["buildability_score"])
        out.append((paper, item))
    if refs:
        # Items the model skipped stay untriaged and are retried next run.
        log.info("triage skipped %d items: %s", len(refs), ", ".join(refs))
    return out


def _clamp(value: int) -> int:
    return max(0, min(10, int(value)))
