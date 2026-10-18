"""ClinicalTrials.gov: newly registered human studies, a sign a technology is reaching people."""

from __future__ import annotations

from datetime import date

from ..models import Paper
from .http import SourceError, get_json

STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"


def search(topic: str, since: date, limit: int = 50) -> list[Paper]:
    params = {
        "query.term": topic,
        "filter.advanced": f"AREA[StudyFirstPostDate]RANGE[{since:%Y-%m-%d},MAX]",
        "pageSize": min(100, limit),
        "format": "json",
    }
    try:
        data = get_json(STUDIES_URL, params)
        date_filtered_by_api = True
    except SourceError:
        # Fall back to filtering dates here if the API rejects the expression.
        params.pop("filter.advanced")
        data = get_json(STUDIES_URL, params)
        date_filtered_by_api = False

    studies: list[Paper] = []
    while True:
        for study in data.get("studies") or []:
            paper = parse_study(study)
            if paper and (date_filtered_by_api or paper.published >= f"{since:%Y-%m-%d}"):
                studies.append(paper)
        token = data.get("nextPageToken")
        if not token or len(studies) >= limit:
            break
        data = get_json(STUDIES_URL, {**params, "pageToken": token})
    return studies[:limit]


def parse_study(study: dict) -> Paper | None:
    proto = study.get("protocolSection") or {}
    ident = proto.get("identificationModule") or {}
    nct = ident.get("nctId")
    title = ident.get("officialTitle") or ident.get("briefTitle") or ""
    summary = (proto.get("descriptionModule") or {}).get("briefSummary") or ""
    if not nct or not title or not summary:
        return None
    status = proto.get("statusModule") or {}
    sponsor = ((proto.get("sponsorCollaboratorsModule") or {}).get("leadSponsor") or {})
    interventions = (proto.get("armsInterventionsModule") or {}).get("interventions") or []
    conditions = (proto.get("conditionsModule") or {}).get("conditions") or []
    phases = (proto.get("designModule") or {}).get("phases") or []
    intervention_text = "; ".join(f"{i.get('type', '?')}: {i.get('name', '?')}" for i in interventions)
    abstract = (
        f"{' '.join(summary.split())} "
        f"[Conditions: {', '.join(conditions) or 'n/a'}. Interventions: {intervention_text or 'n/a'}. "
        f"Phase: {', '.join(phases) or 'n/a'}. Status: {status.get('overallStatus', 'n/a')}.]"
    )
    return Paper(
        source="clinicaltrials",
        source_id=nct,
        title=" ".join(title.split()),
        abstract=abstract,
        url=f"https://clinicaltrials.gov/study/{nct}",
        published=(status.get("studyFirstPostDateStruct") or status.get("startDateStruct") or {}).get("date", ""),
        venue=f"ClinicalTrials.gov ({sponsor.get('class', 'sponsor')}: {sponsor.get('name', 'unknown')})",
        authors=sponsor.get("name", ""),
        kind="trial",
        extra={"intervention_types": sorted({i.get("type", "") for i in interventions}), "phases": phases},
    )
