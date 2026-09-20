"""Loads and indexes the taxonomy and the profile form schema.

Everything about roles, business services, value constructs and skills lives in
data/taxonomy.json so the admin portal can edit it without touching code. This
module turns that file into lookup tables the rest of the app uses, validates it
on load (a typo'd skill id should fail loudly at startup, not silently produce a
wrong score), and picks the cross-path skill battery.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from collections import Counter
from pathlib import Path

import db

BUNDLED_DATA_DIR = Path(__file__).resolve().parent / "data"
# With CAARYA_DATA_DIR set, editable data lives on that volume instead of next to the code.
DATA_DIR = Path(os.environ["CAARYA_DATA_DIR"]) / "data" if os.environ.get("CAARYA_DATA_DIR") else BUNDLED_DATA_DIR
TAXONOMY_PATH = DATA_DIR / "taxonomy.json"
SCHEMA_PATH = DATA_DIR / "profile_schema.json"
INSTITUTIONS_PATH = DATA_DIR / "institutions.json"



def bootstrap_data_dir() -> None:
    """Copy the bundled taxonomy/schema/institutions into DATA_DIR on first boot.

    Never overwrites: once an admin has edited the taxonomy on the volume, that copy wins.
    """
    if DATA_DIR == BUNDLED_DATA_DIR:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("taxonomy.json", "profile_schema.json", "institutions.json"):
        target = DATA_DIR / name
        if not target.exists():
            shutil.copy2(BUNDLED_DATA_DIR / name, target)


MIN_SIMILARITY = 0.05  # below this, two skills share too little to infer anything


class TaxonomyError(Exception):
    """Raised when taxonomy.json is internally inconsistent."""


class Taxonomy:
    """An indexed, validated view of taxonomy.json."""

    def __init__(self, raw: dict):
        self.raw = raw
        self.version = raw.get("version", 0)
        self.skills: dict[str, dict] = raw.get("skills", {})
        self.industries: list[str] = raw.get("industries", [])
        self.causes: list[str] = raw.get("causes", [])
        self.tool_stack: dict[str, list[str]] = raw.get("tool_stack", {})
        self.rating_scale: list[dict] = raw.get("rating_scale", [])

        self.roles: dict[str, dict] = {}
        self.services: dict[str, dict] = {}
        self.vcs: dict[str, dict] = {}
        self.service_of_vc: dict[str, str] = {}
        self.role_of_service: dict[str, str] = {}
        self._skill_vcs: dict[str, set[str]] = {}
        self._neighbours: dict[str, dict[str, float]] = {}
        self.warnings: list[str] = []
        self._index()
        self._validate()

    # ---------------------------------------------------------------- indexing

    def _index(self) -> None:
        for role in self.raw.get("roles", []):
            self.roles[role["id"]] = role
            for service in role.get("business_services", []):
                self.services[service["id"]] = service
                self.role_of_service[service["id"]] = role["id"]
                for vc in service.get("value_constructs", []):
                    self.vcs[vc["id"]] = vc
                    self.service_of_vc[vc["id"]] = service["id"]
                    for skill_id in vc_skill_ids(vc):
                        self._skill_vcs.setdefault(skill_id, set()).add(vc["id"])

    def _validate(self) -> None:
        if not self.roles:
            raise TaxonomyError("taxonomy.json defines no roles")

        problems: list[str] = []
        for vc_id, vc in self.vcs.items():
            for skill_id in vc_skill_ids(vc):
                if skill_id not in self.skills:
                    problems.append(f"{vc_id} references unknown skill '{skill_id}'")
            for skill_id in vc.get("technical_skills", []):
                if self.skills.get(skill_id, {}).get("type") != "technical":
                    problems.append(f"{vc_id} lists '{skill_id}' as technical but the registry disagrees")
            for skill_id in vc.get("transferable_skills", []):
                if self.skills.get(skill_id, {}).get("type") != "transferable":
                    problems.append(f"{vc_id} lists '{skill_id}' as transferable but the registry disagrees")

        # A skill nobody uses yet is untidy, not broken - the admin panel creates
        # skills before they are attached to anything. Surfaced as a warning so
        # the panel can show it, never as a reason to refuse to start.
        used = {s for vc in self.vcs.values() for s in vc_skill_ids(vc)}
        for orphan in sorted(set(self.skills) - used):
            self.warnings.append(f"skill '{orphan}' is not used by any value construct")

        if problems:
            raise TaxonomyError("taxonomy.json is inconsistent:\n  - " + "\n  - ".join(problems))

    # ---------------------------------------------------------------- archiving

    # Archived entities are kept in every index above on purpose: a profile
    # scored last term still references them by id, and its report has to be
    # able to print their names. They are filtered out of the `active_*` views,
    # which is what everything student-facing reads.

    @staticmethod
    def is_archived(entity: dict) -> bool:
        return bool(entity.get("archived"))

    def active_roles(self) -> list[dict]:
        return [r for r in self.raw.get("roles", []) if not self.is_archived(r)]

    def active_services_of_role(self, role_id: str) -> list[dict]:
        return [s for s in self.services_of_role(role_id) if not self.is_archived(s)]

    def active_vcs_of_service(self, service_id: str) -> list[dict]:
        return [vc for vc in self.vcs_of_service(service_id) if not self.is_archived(vc)]

    def active_skill(self, skill_id: str) -> bool:
        return skill_id in self.skills and not self.is_archived(self.skills[skill_id])

    # ----------------------------------------------------------------- lookups

    def skill_name(self, skill_id: str) -> str:
        return self.skills.get(skill_id, {}).get("name", skill_id)

    def skill_type(self, skill_id: str) -> str:
        return self.skills.get(skill_id, {}).get("type", "technical")

    def skill_payload(self, skill_id: str) -> dict:
        skill = self.skills.get(skill_id, {})
        return {
            "id": skill_id,
            "name": skill.get("name", skill_id),
            "type": skill.get("type", "technical"),
            "hint": skill.get("hint", ""),
        }

    def vcs_of_service(self, service_id: str) -> list[dict]:
        return self.services.get(service_id, {}).get("value_constructs", [])

    def services_of_role(self, role_id: str) -> list[dict]:
        return self.roles.get(role_id, {}).get("business_services", [])

    def role_of_vc(self, vc_id: str) -> str | None:
        service_id = self.service_of_vc.get(vc_id)
        return self.role_of_service.get(service_id) if service_id else None

    def skills_of_vcs(self, vc_ids: list[str]) -> list[str]:
        """Distinct skill ids across the given VCs, in a stable order."""
        seen: list[str] = []
        for vc_id in vc_ids:
            vc = self.vcs.get(vc_id)
            if not vc:
                continue
            for skill_id in vc_skill_ids(vc):
                if skill_id not in seen:
                    seen.append(skill_id)
        return seen

    def skill_frequency(self, role_id: str | None = None) -> Counter:
        """How many VCs each skill appears in - our proxy for how much a single
        rating tells us. A skill used by six VCs buys more information than one
        used by a single VC, so the battery prefers it."""
        counter: Counter = Counter()
        for vc_id, vc in self.vcs.items():
            if role_id and self.role_of_vc(vc_id) != role_id:
                continue
            counter.update(vc_skill_ids(vc))
        return counter

    # -------------------------------------------------------------- similarity

    def vcs_of_skill(self, skill_id: str) -> set[str]:
        return self._skill_vcs.get(skill_id, set())

    def similarity(self, a: str, b: str) -> float:
        """How related two skills are, as the share of value constructs that use
        both out of those that use either (Jaccard).

        This is the whole basis for saying anything about work we never asked
        about. `sql` and `data-modelling` sit in the same value construct, so a
        rating on one is real - if weak - evidence about the other. Two skills
        that never appear together tell us nothing, and score 0.
        """
        if a == b:
            return 1.0
        first, second = self.vcs_of_skill(a), self.vcs_of_skill(b)
        if not first or not second:
            return 0.0
        union = len(first | second)
        return len(first & second) / union if union else 0.0

    def neighbours(self, skill_id: str) -> dict[str, float]:
        """Every skill sharing at least one value construct with this one, and
        how strongly. Cached - the taxonomy doesn't change between requests."""
        if skill_id not in self._neighbours:
            related: dict[str, float] = {}
            for vc_id in self.vcs_of_skill(skill_id):
                for other in vc_skill_ids(self.vcs[vc_id]):
                    if other == skill_id or other in related:
                        continue
                    score = self.similarity(skill_id, other)
                    if score >= MIN_SIMILARITY:
                        related[other] = score
            self._neighbours[skill_id] = related
        return self._neighbours[skill_id]

    # ----------------------------------------------------------------- ratings

    def build_skill_set(self, role_id: str, service_ids: list[str], vc_ids: list[str]) -> dict:
        """The skills behind the value constructs a student chose - the first and
        only compulsory round of rating.

        Everything after this is chosen adaptively from their answers, in
        `scoring.next_question_batch`, so there is no fixed battery here any more.
        """
        return {
            "path": [self.skill_payload(s) for s in self.skills_of_vcs(vc_ids)],
            "rating_scale": self.rating_scale,
        }

    # -------------------------------------------------------------- public API

    def public_dict(self) -> dict:
        """What the wizard needs: the live tree only.

        Archived roles, services, value constructs and skills are stripped here
        so a student can never pick retired work, while the full tree stays
        available to the admin panel and to old reports resolving names by id.
        """
        public = dict(self.raw)
        public["roles"] = [
            {**role, "business_services": [
                {**service, "value_constructs": [
                    vc for vc in self.active_vcs_of_service(service["id"])
                ]}
                for service in self.active_services_of_role(role["id"])
            ]}
            for role in self.active_roles()
        ]
        public["skills"] = {k: v for k, v in self.skills.items() if not self.is_archived(v)}
        return public


def vc_skill_ids(vc: dict) -> list[str]:
    """All skill ids on a value construct, technical first, de-duplicated.

    De-duplication matters: 'Write Database Queries' lists SQL twice in spirit
    (SQL and SQL querying both map to `sql`), and counting it twice would quietly
    double its weight in that VC's score.
    """
    ordered = list(vc.get("technical_skills", [])) + list(vc.get("transferable_skills", []))
    seen: list[str] = []
    for skill_id in ordered:
        if skill_id not in seen:
            seen.append(skill_id)
    return seen


_taxonomy: Taxonomy | None = None
_schema: dict | None = None
_institutions: dict | None = None


_taxonomy_fetched_at = 0.0
DB_RELOAD_SECONDS = 5   # in Postgres mode, `force` re-reads at most this often unless fresh=True


def read_taxonomy_text() -> str:
    """The taxonomy JSON from wherever it lives: Postgres if configured, else the file.

    The first Postgres boot seeds the table from the bundled file; after that the
    database copy is the source of truth and admin edits survive redeploys.
    """
    if db.use_postgres():
        body = db.get_document("taxonomy.json")
        if body is None:
            db.put_document("taxonomy.json", (BUNDLED_DATA_DIR / "taxonomy.json").read_text(encoding="utf-8"),
                            only_if_missing=True)
            body = db.get_document("taxonomy.json")
        return body
    return TAXONOMY_PATH.read_text(encoding="utf-8")


def load_taxonomy(force: bool = False, fresh: bool = False) -> Taxonomy:
    global _taxonomy, _taxonomy_fetched_at
    if _taxonomy is not None and force and db.use_postgres() and not fresh:
        force = time.monotonic() - _taxonomy_fetched_at > DB_RELOAD_SECONDS
    if _taxonomy is None or force:
        _taxonomy = Taxonomy(json.loads(read_taxonomy_text()))
        _taxonomy_fetched_at = time.monotonic()
    return _taxonomy


def load_schema(force: bool = False) -> dict:
    global _schema
    if _schema is None or force:
        with open(SCHEMA_PATH, encoding="utf-8") as handle:
            _schema = json.load(handle)
    return _schema


def load_institutions(force: bool = False) -> dict:
    """States and colleges for the two suggestion lists in the form.

    Deliberately separate from the taxonomy: the taxonomy is what the admin
    panel edits and what scoring runs on, while this is reference data that
    only ever fills a dropdown. Nothing validates against it - see the _note
    in the file.
    """
    global _institutions
    if _institutions is None or force:
        with open(INSTITUTIONS_PATH, encoding="utf-8") as handle:
            _institutions = json.load(handle)
    return _institutions
