"""bioRxiv and medRxiv: the newest preprints, often months before journals.

The API lists everything posted in a date window and has no keyword search, so
records are filtered here against the topic terms.
"""

from __future__ import annotations

from datetime import date

from ..models import Paper
from .http import get_json

DETAILS_URL = "https://api.biorxiv.org/details/{server}/{start}/{end}/{cursor}"


def recent(server: str, since: date, until: date, topics: list[str], max_scanned: int = 1500) -> list[Paper]:
    terms = _terms(topics)
    papers: list[Paper] = []
    cursor, scanned = 0, 0
    while scanned < max_scanned:
        url = DETAILS_URL.format(server=server, start=f"{since:%Y-%m-%d}", end=f"{until:%Y-%m-%d}", cursor=cursor)
        data = get_json(url)
        collection = data.get("collection") or []
        if not collection:
            break
        for record in collection:
            paper = parse_record(record, server)
            if paper and matches(paper, terms):
                papers.append(paper)
        scanned += len(collection)
        cursor += len(collection)
        total = _int((data.get("messages") or [{}])[0].get("total"))
        if total is not None and cursor >= total:
            break
    return _latest_versions(papers)


def parse_record(record: dict, server: str) -> Paper | None:
    title = (record.get("title") or "").strip()
    abstract = (record.get("abstract") or "").strip()
    doi = record.get("doi") or ""
    if not title or not abstract or not doi:
        return None
    return Paper(
        source=server,
        source_id=doi,
        title=" ".join(title.split()),
        abstract=" ".join(abstract.split()),
        url=f"https://doi.org/{doi}",
        published=record.get("date") or "",
        venue=f"{record.get('server') or server} ({record.get('category') or 'uncategorized'})",
        authors=record.get("authors") or "",
        kind="preprint",
        extra={"version": record.get("version"), "category": record.get("category"), "published_doi": record.get("published")},
    )


def matches(paper: Paper, terms: list[list[str]]) -> bool:
    """A topic matches when every word of it appears in the title or abstract."""
    text = f"{paper.title} {paper.abstract}".lower()
    return any(all(word in text for word in words) for words in terms)


def _terms(topics: list[str]) -> list[list[str]]:
    return [[w for w in t.lower().replace("-", " ").split() if len(w) > 2] for t in topics]


def _latest_versions(papers: list[Paper]) -> list[Paper]:
    by_doi: dict[str, Paper] = {}
    for p in papers:
        prev = by_doi.get(p.source_id)
        if prev is None or (_int(p.extra.get("version")) or 0) > (_int(prev.extra.get("version")) or 0):
            by_doi[p.source_id] = p
    return list(by_doi.values())


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
