"""Engine settings. Defaults live here; a JSON file can override any field."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

DEFAULT_MODEL = "claude-opus-5-5"

# Search topics for discovery mode. Weighted toward things a company can build:
# devices, diagnostics, sensing, software. Edit freely.
DEFAULT_TOPICS = [
    "wearable sensor",
    "point-of-care diagnostic",
    "non-invasive monitoring",
    "biosensor",
    "first-in-human device",
    "non-invasive neuromodulation",
    "focused ultrasound therapy",
    "microneedle",
    "digital biomarker",
    "implantable bioelectronics",
    "lab-on-a-chip",
    "machine learning diagnosis prospective validation",
]

# Score dimensions, each scored 0-10 by the judge. Weights sum to 1.0 and turn
# the scores into a 0-100 composite. Buildability and winnability are weighted
# up because the company wants near-term products it can win with.
DEFAULT_WEIGHTS = {
    "breakthrough": 0.15,
    "evidence": 0.15,
    "impact": 0.15,
    "buildability": 0.20,
    "winnability": 0.10,
    "regulatory": 0.10,
    "capital_efficiency": 0.10,
    "funding_fit": 0.05,
}

# Product types the triage stage keeps. Drugs and biologics are left out by
# default: they need wet labs and a decade of trials.
DEFAULT_ALLOWED_TYPES = ["device", "diagnostic", "software", "platform_tool"]


@dataclass
class Config:
    model: str = DEFAULT_MODEL
    db_path: str = "engine.db"
    output_dir: str = "output"

    # Scout
    topics: list[str] = field(default_factory=lambda: list(DEFAULT_TOPICS))
    sources: list[str] = field(default_factory=lambda: ["europepmc", "biorxiv", "medrxiv", "clinicaltrials"])
    lookback_days: int = 7
    max_per_topic: int = 50
    max_preprints_scanned: int = 1500

    # Triage
    triage_batch_size: int = 15
    triage_threshold: float = 6.0
    allowed_types: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_TYPES))

    # Judge and design
    max_judged: int = 10
    max_designed: int = 3
    design_min_composite: float = 60.0
    max_web_searches: int = 8
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    # Effort per stage (low | medium | high | xhigh | max). Triage runs on many
    # abstracts, so it stays cheap; the judgment stages get more thought.
    effort_triage: str = "low"
    effort_judge: str = "high"
    effort_design: str = "high"
    effort_ideate: str = "high"

    @classmethod
    def load(cls, path: str | None) -> "Config":
        cfg = cls()
        if not path:
            return cfg
        data = json.loads(Path(path).read_text())
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"Unknown config keys: {sorted(unknown)}")
        for key, value in data.items():
            setattr(cfg, key, value)
        if set(cfg.weights) != set(DEFAULT_WEIGHTS):
            raise ValueError(f"weights must cover exactly these dimensions: {sorted(DEFAULT_WEIGHTS)}")
        total = sum(cfg.weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"weights must sum to 1.0, got {total}")
        return cfg

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)
