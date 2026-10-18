"""Europe PMC: journal papers (it mirrors PubMed) plus preprints, searchable by topic."""

from __future__ import annotations

from datetime import date

from ..models import Paper
from .http import get_json

SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def build_query(topic: str, since: date, until: date) -> str:
    return f'({topic}) AND FIRST_PDATE:[{since:%Y-%m-%d} TO {until:%Y-%m-%d}] AND HAS_ABSTRACT:y'


def search(topic: str, since: date, until: date, limit: int = 50) -> list[Paper]:
    papers: list[Paper] = []
    cursor = "*"
    while len(papers) < limit:
        data = get_json(
            SEARCH_URL,
            {
                "query": build_query(topic, since, until),
                "format": "json",
                "resultType": "core",
                "pageSize": min(100, limit - len(papers)),
                "cursorMark": cursor,
            },
        )
        results = (data.get("resultList") or {}).get("result") or []
        for result in results:
            paper = parse_result(result)
            if paper:
                papers.append(paper)
        next_cursor = data.get("nextCursorMark")
        if not results or not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
    return papers[:limit]


def parse_result(result: dict) -> Paper | None:
    title = (result.get("title") or "").strip()
    abstract = (result.get("abstractText") or "").strip()
    if not title or not abstract:
        return None
    src = result.get("source") or "MED"
    rid = str(result.get("id") or result.get("pmid") or "")
    doi = result.get("doi") or ""
    journal = ((result.get("journalInfo") or {}).get("journal") or {}).get("title") or ""
    is_preprint = src == "PPR"
    venue = journal or (result.get("bookOrReportDetails") or {}).get("publisher") or ("preprint" if is_preprint else "")
    return Paper(
        source="europepmc",
        source_id=f"{src}:{rid}",
        title=_strip_tags(title),
        abstract=_strip_tags(abstract),
        url=f"https://doi.org/{doi}" if doi else f"https://europepmc.org/article/{src}/{rid}",
        published=result.get("firstPublicationDate") or "",
        venue=venue,
        authors=result.get("authorString") or "",
        kind="preprint" if is_preprint else "paper",
        extra={"doi": doi, "cited_by": result.get("citedByCount", 0)},
    )


def _strip_tags(text: str) -> str:
    # Abstracts arrive with HTML such as <h4>Background</h4> and <i>. A tag
    # becomes a space so section headings don't run into the next word.
    out, depth = [], 0
    for ch in text:
        if ch == "<":
            depth += 1
        elif ch == ">" and depth:
            depth -= 1
            out.append(" ")
        elif not depth:
            out.append(ch)
    return " ".join("".join(out).split())
