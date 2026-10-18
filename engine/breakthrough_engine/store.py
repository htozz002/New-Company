"""SQLite store: every paper seen, every triage call, every opportunity and brief.

Keeping history means a paper is never paid for twice, and scores can be
compared across runs.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from .models import Paper

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    key TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    abstract TEXT NOT NULL,
    url TEXT,
    published TEXT,
    venue TEXT,
    authors TEXT,
    extra TEXT,
    first_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS triage (
    paper_key TEXT PRIMARY KEY REFERENCES papers(key),
    product_type TEXT,
    breakthrough_score INTEGER,
    buildability_score INTEGER,
    is_candidate INTEGER,
    reason TEXT,
    triaged_at TEXT NOT NULL,
    unmet_need_score INTEGER,
    need TEXT
);
CREATE TABLE IF NOT EXISTS ownership (
    paper_key TEXT PRIMARY KEY REFERENCES papers(key),
    status TEXT NOT NULL,              -- open | contested | owned | unknown
    owner TEXT,
    evidence TEXT,
    wedge TEXT,
    sources TEXT,                      -- JSON list of {title, url}
    checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origin TEXT NOT NULL,              -- discovery | idea | evaluate | need
    paper_key TEXT REFERENCES papers(key),
    idea_text TEXT,
    idea_plan TEXT,                    -- JSON, idea mode only
    landscape TEXT,
    landscape_sources TEXT,            -- JSON list of {title, url}
    evaluation TEXT,                   -- JSON from the judge
    composite REAL,
    verdict TEXT,
    brief TEXT,                        -- JSON from the designer
    report_path TEXT,
    status TEXT NOT NULL,              -- new | judged | designed | failed
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_opportunity_per_paper
    ON opportunities(paper_key) WHERE origin = 'discovery';
"""

# Columns added after the first release. Databases made before them get the
# columns on open; values in older rows stay empty.
ADDED_COLUMNS = {"triage": [("unmet_need_score", "INTEGER"), ("need", "TEXT")]}

# Paper sources created together with their own opportunity, never screened.
OWN_OPPORTUNITY_SOURCES = ("idea", "need", "manual")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._add_missing_columns()

    def _add_missing_columns(self) -> None:
        for table, columns in ADDED_COLUMNS.items():
            have = {row["name"] for row in self.db.execute(f"PRAGMA table_info({table})")}
            for name, kind in columns:
                if name not in have:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # papers ---------------------------------------------------------------

    def add_papers(self, papers: list[Paper]) -> int:
        """Insert papers not seen before. Returns how many were new."""
        new = 0
        for p in papers:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO papers VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (p.key, p.source, p.source_id, p.kind, p.title, p.abstract, p.url, p.published,
                 p.venue, p.authors, json.dumps(p.extra), _now()),
            )
            new += cur.rowcount
        self.db.commit()
        return new

    def get_paper(self, key: str) -> Paper | None:
        row = self.db.execute("SELECT * FROM papers WHERE key = ?", (key,)).fetchone()
        return _paper(row) if row else None

    def untriaged_papers(self, limit: int | None = None) -> list[Paper]:
        # Ideas, needs and hand-picked papers already have their own opportunity,
        # so screening them would judge them twice.
        sql = ("SELECT p.* FROM papers p LEFT JOIN triage t ON t.paper_key = p.key "
               f"WHERE t.paper_key IS NULL AND p.source NOT IN ({_marks(OWN_OPPORTUNITY_SOURCES)}) "
               "ORDER BY p.published DESC")
        rows = self.db.execute(sql + (f" LIMIT {int(limit)}" if limit else ""), OWN_OPPORTUNITY_SOURCES).fetchall()
        return [_paper(r) for r in rows]

    # triage ---------------------------------------------------------------

    def save_triage(self, paper_key: str, item: dict) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO triage (paper_key, product_type, breakthrough_score, buildability_score, "
            "is_candidate, reason, triaged_at, unmet_need_score, need) VALUES (?,?,?,?,?,?,?,?,?)",
            (paper_key, item["product_type"], item["breakthrough_score"], item["buildability_score"],
             int(item["is_candidate"]), item["reason"], _now(), item.get("unmet_need_score", 0), item.get("need", "")),
        )
        self.db.commit()

    def candidates_to_judge(self, allowed_types: list[str], threshold: float, limit: int) -> list[Paper]:
        """Triage survivors not yet judged (or whose judging failed), best first.

        Papers the ownership check found already owned are left out; papers it
        has not checked are kept.
        """
        rows = self.db.execute(
            f"""SELECT p.* FROM ({_SURVIVORS.format(marks=_marks(allowed_types))}) p
                LEFT JOIN opportunities o ON o.paper_key = p.key AND o.origin = 'discovery'
                LEFT JOIN ownership w ON w.paper_key = p.key
                WHERE (o.id IS NULL OR o.status = 'failed') AND (w.status IS NULL OR w.status != 'owned')
                ORDER BY p.triage_rank DESC, p.published DESC
                LIMIT ?""",
            (*allowed_types, threshold, limit),
        ).fetchall()
        return [_paper(r) for r in rows]

    def candidates_to_check(self, allowed_types: list[str], threshold: float, limit: int) -> list[Paper]:
        """Triage survivors with no ownership check and no opportunity yet, best first."""
        rows = self.db.execute(
            f"""SELECT p.* FROM ({_SURVIVORS.format(marks=_marks(allowed_types))}) p
                LEFT JOIN opportunities o ON o.paper_key = p.key AND o.origin = 'discovery'
                LEFT JOIN ownership w ON w.paper_key = p.key
                WHERE o.id IS NULL AND w.paper_key IS NULL
                ORDER BY p.triage_rank DESC, p.published DESC
                LIMIT ?""",
            (*allowed_types, threshold, limit),
        ).fetchall()
        return [_paper(r) for r in rows]

    def needs_to_explore(self, threshold: int, limit: int) -> list[tuple[Paper, str]]:
        """Items that showed an unmet need and have not been sent to idea mode yet, strongest first."""
        rows = self.db.execute(
            """SELECT p.*, t.need AS need_text FROM papers p JOIN triage t ON t.paper_key = p.key
               LEFT JOIN papers n ON n.key = 'need:' || p.key
               WHERE t.unmet_need_score >= ? AND n.key IS NULL
               ORDER BY t.unmet_need_score DESC, p.published DESC
               LIMIT ?""",
            (threshold, limit),
        ).fetchall()
        return [(_paper(r), r["need_text"] or "") for r in rows]

    def triage_counts(self) -> dict:
        row = self.db.execute(
            "SELECT COUNT(*) AS triaged, COALESCE(SUM(is_candidate), 0) AS candidates FROM triage").fetchone()
        return dict(row)

    # ownership ------------------------------------------------------------

    def save_ownership(self, paper_key: str, result: dict, sources: list[dict]) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO ownership VALUES (?,?,?,?,?,?,?)",
            (paper_key, result["status"], result["owner"], result["evidence"], result["wedge"],
             json.dumps(sources), _now()),
        )
        self.db.commit()

    def get_ownership(self, paper_key: str) -> dict | None:
        row = self.db.execute("SELECT * FROM ownership WHERE paper_key = ?", (paper_key,)).fetchone()
        return _ownership(row) if row else None

    def owned(self) -> list[tuple[Paper, dict]]:
        """Papers the ownership check screened out, newest check first."""
        rows = self.db.execute(
            "SELECT * FROM ownership WHERE status = 'owned' ORDER BY checked_at DESC, paper_key").fetchall()
        return [(self.get_paper(r["paper_key"]), _ownership(r)) for r in rows]

    # opportunities --------------------------------------------------------

    def create_opportunity(self, origin: str, paper_key: str | None = None, idea_text: str | None = None,
                           idea_plan: dict | None = None) -> int:
        cur = self.db.execute(
            "INSERT INTO opportunities (origin, paper_key, idea_text, idea_plan, status, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (origin, paper_key, idea_text, json.dumps(idea_plan) if idea_plan else None, "new", _now(), _now()),
        )
        self.db.commit()
        return cur.lastrowid

    def discovery_opportunity_id(self, paper_key: str) -> int | None:
        row = self.db.execute("SELECT id FROM opportunities WHERE paper_key = ? AND origin = 'discovery'",
                              (paper_key,)).fetchone()
        return row["id"] if row else None

    def update_opportunity(self, opp_id: int, **fields) -> None:
        for key in ("landscape_sources", "evaluation", "brief", "idea_plan"):
            if key in fields and not isinstance(fields[key], str) and fields[key] is not None:
                fields[key] = json.dumps(fields[key])
        fields["updated_at"] = _now()
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE opportunities SET {cols} WHERE id = ?", (*fields.values(), opp_id))
        self.db.commit()

    def get_opportunity(self, opp_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM opportunities WHERE id = ?", (opp_id,)).fetchone()
        return _opportunity(row) if row else None

    def opportunities(self, status: str | None = None, min_composite: float | None = None) -> list[dict]:
        sql, args = "SELECT * FROM opportunities WHERE 1=1", []
        if status:
            sql += " AND status = ?"
            args.append(status)
        if min_composite is not None:
            sql += " AND composite >= ?"
            args.append(min_composite)
        sql += " ORDER BY composite DESC NULLS LAST, id DESC"
        return [_opportunity(r) for r in self.db.execute(sql, args).fetchall()]


# Triage survivors: candidates of an allowed type whose average triage score
# meets the threshold. Takes the allowed types, then the threshold.
_SURVIVORS = """SELECT p.*, t.breakthrough_score + t.buildability_score AS triage_rank
    FROM papers p JOIN triage t ON t.paper_key = p.key
    WHERE t.is_candidate = 1 AND t.product_type IN ({marks})
      AND (t.breakthrough_score + t.buildability_score) / 2.0 >= ?"""


def _marks(values: list) -> str:
    return ",".join("?" * len(values))


def _ownership(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["sources"] = json.loads(data["sources"] or "[]")
    return data


def _paper(row: sqlite3.Row) -> Paper:
    return Paper(
        source=row["source"], source_id=row["source_id"], title=row["title"], abstract=row["abstract"],
        url=row["url"] or "", published=row["published"] or "", venue=row["venue"] or "",
        authors=row["authors"] or "", kind=row["kind"], extra=json.loads(row["extra"] or "{}"),
    )


def _opportunity(row: sqlite3.Row) -> dict:
    opp = dict(row)
    for key in ("idea_plan", "landscape_sources", "evaluation", "brief"):
        if opp.get(key):
            opp[key] = json.loads(opp[key])
    return opp
