"""NIH RePORTER: newly awarded NIH grants, often a year or more before the papers.

A grant shows what a lab is about to do, before any spinout forms around the
result. Small-business awards (SBIR and STTR) also name the company that holds
the work, which the ownership check can use.
"""

from __future__ import annotations

from datetime import date

from ..models import Paper
from .http import post_json

SEARCH_URL = "https://api.reporter.nih.gov/v2/projects/search"
PROJECT_URL = "https://reporter.nih.gov/project-details/{appl_id}"
PAGE_SIZE = 500  # the API's maximum

# Application types 1 (new) and 2 (competing renewal); yearly continuations of
# old grants are left out.
NEW_AWARD_TYPES = ["1", "2"]

# SBIR, STTR and commercialization-readiness activity codes.
SMALL_BUSINESS_CODES = {"R41", "R42", "R43", "R44", "U43", "U44", "SB1"}


def build_body(topic: str, since: date, until: date, offset: int, limit: int) -> dict:
    return {
        "criteria": {
            "advanced_text_search": {
                "operator": "and",
                "search_field": "projecttitle,terms,abstracttext",
                "search_text": topic,
            },
            "award_notice_date": {"from_date": f"{since:%Y-%m-%d}", "to_date": f"{until:%Y-%m-%d}"},
            "award_types": NEW_AWARD_TYPES,
            "exclude_subprojects": True,
        },
        "offset": offset,
        "limit": limit,
    }


def search(topic: str, since: date, until: date, limit: int = 50) -> list[Paper]:
    papers: list[Paper] = []
    offset = 0
    while len(papers) < limit:
        data = post_json(SEARCH_URL, build_body(topic, since, until, offset, min(PAGE_SIZE, limit - len(papers))))
        results = data.get("results") or []
        for result in results:
            paper = parse_project(result)
            if paper:
                papers.append(paper)
        offset += len(results)
        total = (data.get("meta") or {}).get("total")
        if not results or (total is not None and offset >= total):
            break
    return papers[:limit]


def parse_project(project: dict) -> Paper | None:
    title = " ".join((project.get("project_title") or "").split())
    abstract = " ".join((project.get("abstract_text") or "").split())
    appl_id = project.get("appl_id")
    if not title or not abstract or not appl_id:
        return None
    org = (project.get("organization") or {}).get("org_name") or ""
    activity = project.get("activity_code") or ""
    institute = (project.get("agency_ic_admin") or {}).get("abbreviation") or "NIH"
    amount = project.get("award_amount")
    small_business = activity in SMALL_BUSINESS_CODES
    pis = ", ".join(pi.get("full_name", "") for pi in project.get("principal_investigators") or [] if pi.get("full_name"))
    note = f"[New NIH grant: {institute} {activity} to {org or 'unknown organization'}"
    if isinstance(amount, (int, float)):
        note += f", ${amount:,.0f} this year"
    if small_business:
        note += ". Small-business award, so the organization is a company"
    return Paper(
        source="nih_reporter",
        source_id=str(appl_id),
        title=title,
        abstract=f"{abstract} {note}.]",
        url=PROJECT_URL.format(appl_id=appl_id),
        published=(project.get("award_notice_date") or "")[:10],
        venue=f"NIH {institute} {activity}: {org}".strip(": "),
        authors=pis or project.get("contact_pi_name") or "",
        kind="grant",
        extra={"project_num": project.get("project_num"), "activity_code": activity, "organization": org,
               "award_amount": amount, "small_business": small_business},
    )
