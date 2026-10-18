"""Scout: pull new research from every configured source into the store."""

from __future__ import annotations

import hashlib
import logging
from datetime import date, timedelta

from .. import prompts
from ..config import Config
from ..llm import LLM
from ..models import Paper
from ..sources import biorxiv, clinicaltrials, europepmc, nih_reporter
from ..sources.http import SourceError
from ..store import Store

log = logging.getLogger(__name__)


def run(cfg: Config, store: Store, llm: LLM | None = None, today: date | None = None) -> dict:
    until = today or date.today()
    since = until - timedelta(days=cfg.lookback_days)
    found: dict[str, int] = {}
    errors: dict[str, str] = {}

    for source in cfg.sources:
        try:
            papers = fetch(source, cfg, since, until, llm)
        except SourceError as err:
            log.warning("source %s failed: %s", source, err)
            errors[source] = str(err)
            continue
        found[source] = store.add_papers(papers)
        log.info("%s: %d fetched, %d new", source, len(papers), found[source])
    return {"since": f"{since}", "until": f"{until}", "new_by_source": found, "errors": errors}


def fetch(source: str, cfg: Config, since: date, until: date, llm: LLM | None) -> list[Paper]:
    if source == "europepmc":
        return [p for topic in cfg.topics for p in europepmc.search(topic, since, until, cfg.max_per_topic)]
    if source in ("biorxiv", "medrxiv"):
        return biorxiv.recent(source, since, until, cfg.topics, cfg.max_preprints_scanned)
    if source == "clinicaltrials":
        return [p for topic in cfg.topics for p in clinicaltrials.search(topic, since, cfg.max_per_topic)]
    if source == "nih_reporter":
        return [p for topic in cfg.topics for p in nih_reporter.search(topic, since, until, cfg.max_per_topic)]
    if source == "web":
        if llm is None:
            raise SourceError("the web source needs the Claude API")
        return web_scout(cfg, llm, since, until)
    raise SourceError(f"unknown source {source!r}")


def web_scout(cfg: Config, llm: LLM, since: date, until: date) -> list[Paper]:
    """Find recent research through Claude's web search.

    Useful where the research APIs are unreachable: the searches run on
    Anthropic's side, so only the Claude API needs to be reachable.
    """
    notes = llm.research(
        "web_scout",
        prompts.ENGINE_SYSTEM,
        prompts.WEB_SCOUT_PROMPT.format(since=since, until=until, topics="; ".join(cfg.topics),
                                        limit=cfg.max_per_topic),
        effort=cfg.effort_triage,
        max_searches=cfg.max_web_searches,
    )
    sources = "\n".join(f"- {s['title']}: {s['url']}" for s in notes.sources)
    data = llm.structured(
        "web_scout_extract",
        prompts.ENGINE_SYSTEM,
        prompts.WEB_SCOUT_EXTRACT_PROMPT.format(notes=f"{notes.text}\n\nSources seen:\n{sources}"),
        prompts.WEB_SCOUT_SCHEMA,
        effort="low",
    )
    seen_urls = {s["url"] for s in notes.sources}
    papers = []
    for r in data["results"]:
        # Keep only results whose URL the search actually returned.
        if r["url"] not in seen_urls:
            continue
        papers.append(Paper(
            source="web", source_id=hashlib.sha1(r["url"].encode()).hexdigest()[:16], title=r["title"],
            abstract=r["summary"], url=r["url"], published=r["published"], venue=r["venue"], kind="paper",
        ))
    return papers
