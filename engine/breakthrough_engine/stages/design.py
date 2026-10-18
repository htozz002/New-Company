"""Design: turn the best judged opportunities into product briefs."""

from __future__ import annotations

import json
import logging

from .. import prompts, report
from ..config import Config
from ..llm import LLM, LLMError
from ..store import Store

log = logging.getLogger(__name__)


def run(cfg: Config, store: Store, llm: LLM, limit: int | None = None) -> dict:
    ready = [o for o in store.opportunities(status="judged", min_composite=cfg.design_min_composite)
             if o["verdict"] != "drop"][: limit or cfg.max_designed]
    designed = failed = 0
    for opp in ready:
        if design_one(opp["id"], cfg, store, llm):
            designed += 1
        else:
            failed += 1
    return {"designed": designed, "failed": failed}


def design_one(opp_id: int, cfg: Config, store: Store, llm: LLM) -> bool:
    opp = store.get_opportunity(opp_id)
    paper = store.get_paper(opp["paper_key"])
    try:
        brief = llm.structured(
            "design",
            prompts.ENGINE_SYSTEM,
            prompts.DESIGN_PROMPT.format(
                subject=paper.as_prompt_block(),
                evaluation=json.dumps(opp["evaluation"], indent=2),
                landscape=opp["landscape"] or "(none)",
            ),
            prompts.DESIGN_SCHEMA,
            effort=cfg.effort_design,
        )
    except LLMError as err:
        log.warning("designing opportunity %d failed: %s", opp_id, err)
        store.update_opportunity(opp_id, error=str(err))
        return False
    store.update_opportunity(opp_id, brief=brief, status="designed")
    path = report.write_brief(store.get_opportunity(opp_id), paper, cfg.output_dir)
    store.update_opportunity(opp_id, report_path=str(path))
    return True
