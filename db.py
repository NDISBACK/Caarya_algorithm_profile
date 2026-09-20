"""SQLite persistence.

The columns are the fields the company-matching dashboard will filter on
(availability, location, graduation year, role). Everything else is stored as
JSON in the same row: it is read back whole for the report and there is no
reason to pay for a column per question when the questions are meant to change
from the admin portal.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# CAARYA_DATA_DIR moves all mutable state (this DB, data/*.json, backups) onto a
# volume - needed wherever the code directory is read-only or thrown away on deploy.
STORAGE_DIR = Path(os.environ["CAARYA_DATA_DIR"]) if os.environ.get("CAARYA_DATA_DIR") else None
DB_PATH = (STORAGE_DIR or Path(__file__).resolve().parent) / "caarya.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS students (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    full_name          TEXT NOT NULL,
    preferred_name     TEXT,
    email              TEXT NOT NULL,
    phone              TEXT,
    city               TEXT,
    state              TEXT,
    college            TEXT,
    degree             TEXT,
    branch             TEXT,
    grad_year          INTEGER,
    score_type         TEXT,
    score_value        TEXT,
    identity_json      TEXT NOT NULL DEFAULT '{}',
    academics_json     TEXT NOT NULL DEFAULT '{}',
    languages_json     TEXT NOT NULL DEFAULT '[]',
    certifications_json TEXT NOT NULL DEFAULT '[]',
    portfolio_json     TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS experience (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id      INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,          -- work | project | competition | leadership
    position        INTEGER NOT NULL DEFAULT 0,
    organisation    TEXT,
    title           TEXT,
    engagement_type TEXT,
    start_date      TEXT,
    end_date        TEXT,
    ongoing         INTEGER NOT NULL DEFAULT 0,
    description     TEXT,
    tech_json       TEXT NOT NULL DEFAULT '[]',
    link            TEXT,
    extra_json      TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS profiles (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id            INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    created_at            TEXT NOT NULL,
    taxonomy_version      INTEGER,
    role_id               TEXT,
    role_fit              REAL,
    verdict               TEXT,
    engagement_types_json TEXT NOT NULL DEFAULT '[]',
    hours_per_week        TEXT,
    earliest_start        TEXT,
    work_mode             TEXT,
    relocate              TEXT,
    stipend_expectation   TEXT,
    selections_json       TEXT NOT NULL DEFAULT '{}',
    motivation_json       TEXT NOT NULL DEFAULT '{}',
    availability_json     TEXT NOT NULL DEFAULT '{}',
    work_style_json       TEXT NOT NULL DEFAULT '{}',
    world_json            TEXT NOT NULL DEFAULT '{}',
    tool_stack_json       TEXT NOT NULL DEFAULT '{}',
    ratings_json          TEXT NOT NULL DEFAULT '{}',
    report_json           TEXT NOT NULL DEFAULT '{}',
    details_json          TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_experience_student ON experience(student_id);
CREATE INDEX IF NOT EXISTS idx_profiles_student ON profiles(student_id);
CREATE INDEX IF NOT EXISTS idx_profiles_role ON profiles(role_id);
"""

# Where each repeatable list lives in the submitted payload (step id, field id),
# and the `kind` it is stored under. The wizard keys its data by step id, so a
# list can sit in a step named after something else - projects and competitions
# are both collected on the "projects" step.
EXPERIENCE_SOURCES = [
    ("work_experience", "work_experience", "work"),
    ("projects", "projects", "project"),
    ("projects", "competitions", "competition"),
    ("leadership", "leadership", "leadership"),
]

EXPERIENCE_KINDS = {kind for _, _, kind in EXPERIENCE_SOURCES}


def flatten_experience(payload: dict) -> dict[str, list]:
    """Pull the repeatable lists out of the step-keyed payload.

    Shared with the scoring layer's evidence check so both read the submission
    the same way - a mismatch here would silently mean "this student listed no
    projects" and quietly change their report.
    """
    out: dict[str, list] = {}
    for step_id, field_id, _kind in EXPERIENCE_SOURCES:
        step = payload.get(step_id)
        entries = step.get(field_id) if isinstance(step, dict) else None
        out[field_id] = [e for e in (entries or []) if isinstance(e, dict)]
    return out


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Open the database, creating the schema if it isn't there.

    sqlite3.connect happily creates an empty file when the database is missing,
    so a deleted or never-initialised database looks like a working connection
    right up until the first query fails with "no such table". Checking here
    means the app heals itself instead of serving 500s.
    """
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Checked on every connection rather than cached: the case this exists for is
    # the database disappearing while the server is running, and a cache would
    # remember it as fine right up until the query fails.
    missing = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='students'"
    ).fetchone()[0] == 0
    if missing:
        conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()
    return conn


def init_db(path: Path | str = DB_PATH) -> None:
    """Explicit setup at startup. connect() does the same lazily, so this is
    really just a place for startup to fail loudly if the database is unusable."""
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns that a database created by an earlier version is missing.

    `CREATE TABLE IF NOT EXISTS` does nothing to a table that already exists, so
    without this a developer who ran an older build gets a working insert and a
    500 on the next read - which is exactly as confusing as it sounds.
    """
    for table, column, ddl in (
        ("profiles", "details_json", "TEXT NOT NULL DEFAULT '{}'"),
    ):
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if existing and column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def save_profile(payload: dict, report: dict, path: Path | str = DB_PATH) -> int:
    """Write the core submission.

    The core flow now carries everything a student enjoys filling in - contact,
    links, education, experience, choices and ratings. Only availability and fit
    are left for the follow-up on the report page, so almost all of this lands
    in one go.
    """
    identity = payload.get("identity", {})
    academics = payload.get("academics", {})
    langs = payload.get("languages_certs", {})
    portfolio = payload.get("portfolio", {})
    selections = payload.get("selections", {})
    now = _now()

    with connect(path) as conn:
        cursor = conn.execute(
            """INSERT INTO students (
                   created_at, updated_at, full_name, preferred_name, email, phone, city, state,
                   college, degree, branch, grad_year, score_type, score_value,
                   identity_json, academics_json, languages_json, certifications_json,
                   portfolio_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                now, now,
                identity.get("full_name", ""), identity.get("preferred_name"), identity.get("email", ""),
                identity.get("phone"), identity.get("city"), identity.get("state"),
                academics.get("college"), academics.get("degree"), academics.get("branch"),
                _as_int(academics.get("graduation_year")), academics.get("score_type"),
                academics.get("score_value"),
                _dumps(identity), _dumps(academics), _dumps(langs.get("languages", [])),
                _dumps(langs.get("certifications", [])), _dumps(portfolio),
            ),
        )
        student_id = cursor.lastrowid

        _write_experience(conn, student_id, payload)

        cursor = conn.execute(
            """INSERT INTO profiles (
                   student_id, created_at, taxonomy_version, role_id, role_fit, verdict,
                   selections_json, ratings_json, tool_stack_json, report_json)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                student_id, now, report.get("taxonomy_version"), selections.get("role_id"),
                (report.get("role_fit") or {}).get("score"), (report.get("verdict") or {}).get("code"),
                _dumps(selections), _dumps(payload.get("ratings", {})),
                _dumps(payload.get("tool_stack", {})), _dumps(report),
            ),
        )
        return cursor.lastrowid


def _write_experience(conn: sqlite3.Connection, student_id: int, payload: dict) -> None:
    """Replace this student's experience rows from a step-keyed payload."""
    conn.execute("DELETE FROM experience WHERE student_id = ?", (student_id,))
    lists = flatten_experience(payload)
    known = {"organisation", "title", "engagement_type", "start_date", "end_date",
             "ongoing", "description", "tech", "link"}
    for _step_id, field_id, kind in EXPERIENCE_SOURCES:
        for position, entry in enumerate(lists[field_id]):
            conn.execute(
                """INSERT INTO experience (
                       student_id, kind, position, organisation, title, engagement_type,
                       start_date, end_date, ongoing, description, tech_json, link, extra_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    student_id, kind, position,
                    entry.get("organisation") or entry.get("name"),
                    entry.get("title") or entry.get("role"),
                    entry.get("engagement_type") or entry.get("kind"),
                    entry.get("start_date") or entry.get("period") or entry.get("year"),
                    entry.get("end_date"),
                    1 if entry.get("ongoing") else 0,
                    entry.get("description") or entry.get("outcome"),
                    _dumps(entry.get("tech") or []),
                    entry.get("link"),
                    _dumps({k: v for k, v in entry.items() if k not in known}),
                ),
            )


def update_profile_details(profile_id: int, payload: dict, report: dict,
                           path: Path | str = DB_PATH) -> bool:
    """Apply the optional follow-up: availability, location and fit.

    Experience and education no longer arrive here - they are collected in the
    main flow - so this touches only the matching data and the recomputed report.
    """
    engagement = payload.get("engagement", {})
    location = payload.get("location_comp", {})

    with connect(path) as conn:
        row = conn.execute("SELECT student_id FROM profiles WHERE id = ?", (profile_id,)).fetchone()
        if row is None:
            return False

        conn.execute("UPDATE students SET updated_at = ? WHERE id = ?", (_now(), row["student_id"]))
        conn.execute(
            """UPDATE profiles SET
                   role_fit = ?, verdict = ?, engagement_types_json = ?, hours_per_week = ?,
                   earliest_start = ?, work_mode = ?, relocate = ?, stipend_expectation = ?,
                   motivation_json = ?, availability_json = ?, work_style_json = ?,
                   world_json = ?, report_json = ?, details_json = ?
               WHERE id = ?""",
            (
                (report.get("role_fit") or {}).get("score"), (report.get("verdict") or {}).get("code"),
                _dumps(engagement.get("engagement_types", [])), engagement.get("hours_per_week"),
                engagement.get("earliest_start"), location.get("work_mode"), location.get("relocate"),
                location.get("stipend_expectation"), _dumps(payload.get("motivation", {})),
                _dumps(engagement), _dumps(payload.get("work_style", {})),
                _dumps(payload.get("world", {})), _dumps(report), _dumps(payload), profile_id,
            ),
        )
        return True


def get_profile(profile_id: int, path: Path | str = DB_PATH) -> dict | None:
    """The stored profile, reassembled. This is what the company dashboard reads."""
    with connect(path) as conn:
        row = conn.execute(
            """SELECT p.*, s.full_name, s.preferred_name, s.email, s.phone, s.city, s.state,
                      s.college, s.degree, s.branch, s.grad_year, s.score_type, s.score_value,
                      s.identity_json, s.academics_json, s.languages_json, s.certifications_json,
                      s.portfolio_json, s.created_at AS student_created_at
               FROM profiles p JOIN students s ON s.id = p.student_id
               WHERE p.id = ?""",
            (profile_id,),
        ).fetchone()
        if row is None:
            return None

        experience = conn.execute(
            "SELECT * FROM experience WHERE student_id = ? ORDER BY kind, position",
            (row["student_id"],),
        ).fetchall()

    grouped: dict[str, list[dict]] = {kind: [] for kind in EXPERIENCE_KINDS}
    for entry in experience:
        item = dict(entry)
        item["tech"] = json.loads(item.pop("tech_json") or "[]")
        item.update(json.loads(item.pop("extra_json") or "{}"))
        item["ongoing"] = bool(item["ongoing"])
        grouped.setdefault(item["kind"], []).append(item)

    columns = set(row.keys())

    def loads(key: str, default):
        if key not in columns:
            return default
        return json.loads(row[key]) if row[key] else default

    return {
        "profile_id": row["id"],
        "created_at": row["created_at"],
        "student": {
            "full_name": row["full_name"], "preferred_name": row["preferred_name"],
            "email": row["email"], "phone": row["phone"], "city": row["city"], "state": row["state"],
            "college": row["college"], "degree": row["degree"], "branch": row["branch"],
            "grad_year": row["grad_year"], "score_type": row["score_type"], "score_value": row["score_value"],
            "identity": loads("identity_json", {}), "academics": loads("academics_json", {}),
            "languages": loads("languages_json", []), "certifications": loads("certifications_json", []),
            "portfolio": loads("portfolio_json", {}),
        },
        "experience": grouped,
        "selections": loads("selections_json", {}),
        "motivation": loads("motivation_json", {}),
        "availability": loads("availability_json", {}),
        "location": {
            "work_mode": row["work_mode"], "relocate": row["relocate"],
            "stipend_expectation": row["stipend_expectation"],
        },
        "work_style": loads("work_style_json", {}),
        "world": loads("world_json", {}),
        "tool_stack": loads("tool_stack_json", {}),
        "ratings": loads("ratings_json", {}),
        "report": loads("report_json", {}),
        "details": loads("details_json", {}),
        "details_complete": bool(loads("details_json", {})),
    }


def list_profiles(limit: int = 50, path: Path | str = DB_PATH) -> list[dict]:
    """Lightweight listing - the seed of the company-side dashboard."""
    with connect(path) as conn:
        rows = conn.execute(
            """SELECT p.id, p.created_at, p.role_id, p.role_fit, p.verdict, p.hours_per_week,
                      p.work_mode, s.full_name, s.college, s.grad_year, s.city, s.state
               FROM profiles p JOIN students s ON s.id = p.student_id
               ORDER BY p.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def taxonomy_usage(path: Path | str = DB_PATH) -> dict[str, dict[str, int]]:
    """How many submitted profiles reference each taxonomy id.

    This is what lets the admin panel say "12 students picked this" before
    someone deletes it. Counted in Python rather than SQL because the ids live
    inside JSON columns and the profile count is small - a scan is cheaper to
    read than a pile of json_each joins.
    """
    counts = {"roles": {}, "services": {}, "vcs": {}, "skills": {}}

    def bump(bucket: str, key: str) -> None:
        if key:
            counts[bucket][key] = counts[bucket].get(key, 0) + 1

    with connect(path) as conn:
        rows = conn.execute("SELECT selections_json, ratings_json FROM profiles").fetchall()

    for row in rows:
        try:
            selections = json.loads(row["selections_json"] or "{}")
            ratings = json.loads(row["ratings_json"] or "{}")
        except (TypeError, ValueError):
            continue
        bump("roles", selections.get("role_id"))
        for service_id in selections.get("service_ids") or []:
            bump("services", service_id)
        for vc_id in selections.get("vc_ids") or []:
            bump("vcs", vc_id)
        for skill_id in ratings:
            bump("skills", skill_id)

    return counts
