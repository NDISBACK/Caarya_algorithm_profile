"""The only thing that writes data/taxonomy.json.

Every mutation follows the same shape: copy the current file, apply the change
to the copy, hand the copy to `Taxonomy(...)` - which is already the validator -
and write only if it constructs cleanly. A broken taxonomy is never written,
because a broken taxonomy takes the student form down with it.

Two rules the admin panel depends on:

  * **IDs are immutable.** They are generated from the name on creation and never
    change again, because every stored profile references them. Renaming changes
    a label, never an identity.
  * **Archiving, not deleting, for anything in use.** An archived entity vanishes
    from the student form but stays in the file so an old report can still print
    its name.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from datetime import date, datetime
from pathlib import Path

from taxonomy_loader import TAXONOMY_PATH, Taxonomy, load_taxonomy, vc_skill_ids

BACKUP_DIR = TAXONOMY_PATH.parent / "backups"
KEEP_BACKUPS = 40

KINDS = ("role", "service", "vc", "skill")


class StoreError(Exception):
    """A rejected edit. The message is written for the person making it."""


# ------------------------------------------------------------------- helpers


def slug_id(name: str, existing: set[str], prefix: str = "") -> str:
    """A readable, stable id derived from the name, unique within `existing`."""
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "item"
    if prefix and not base.startswith(prefix):
        base = f"{prefix}{base}"
    candidate = base
    suffix = 2
    while candidate in existing:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def read_raw() -> dict:
    with open(TAXONOMY_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def _all_ids(raw: dict) -> set[str]:
    ids = set(raw.get("skills", {}))
    for role in raw.get("roles", []):
        ids.add(role["id"])
        for service in role.get("business_services", []):
            ids.add(service["id"])
            for vc in service.get("value_constructs", []):
                ids.add(vc["id"])
    return ids


def _find(raw: dict, kind: str, entity_id: str):
    """Returns (entity, parent_list) so callers can edit or remove in place."""
    if kind == "skill":
        skills = raw.get("skills", {})
        return (skills.get(entity_id), skills)

    for role in raw.get("roles", []):
        if kind == "role" and role["id"] == entity_id:
            return role, raw["roles"]
        for service in role.get("business_services", []):
            if kind == "service" and service["id"] == entity_id:
                return service, role["business_services"]
            for vc in service.get("value_constructs", []):
                if kind == "vc" and vc["id"] == entity_id:
                    return vc, service["value_constructs"]
    return None, None


def _require(raw: dict, kind: str, entity_id: str):
    entity, parent = _find(raw, kind, entity_id)
    if entity is None:
        raise StoreError(f"No {kind} with id '{entity_id}'")
    return entity, parent


# --------------------------------------------------------------------- write


def save(raw: dict, label: str = "") -> Taxonomy:
    """Validate, back up, write atomically, and make the change live."""
    try:
        taxonomy = Taxonomy(json.loads(json.dumps(raw)))       # validate a copy
    except Exception as error:                                 # noqa: BLE001
        raise StoreError(f"That change would break the taxonomy — {error}") from error

    raw["version"] = int(raw.get("version", 0)) + 1
    raw["updated_at"] = date.today().isoformat()

    if TAXONOMY_PATH.exists():
        BACKUP_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(TAXONOMY_PATH, BACKUP_DIR / f"taxonomy-{stamp}{('-' + label) if label else ''}.json")
        backups = sorted(BACKUP_DIR.glob("taxonomy-*.json"))
        for stale in backups[:-KEEP_BACKUPS]:
            stale.unlink()

    # Written to a temp file in the same directory, then swapped in: a crash
    # mid-write leaves the old file intact rather than a half-written one.
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=TAXONOMY_PATH.parent, delete=False, suffix=".tmp")
    try:
        json.dump(raw, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    finally:
        handle.close()
    os.replace(handle.name, TAXONOMY_PATH)

    # Force the reload so the edit is live even when CAARYA_RELOAD=0.
    return load_taxonomy(force=True)


# -------------------------------------------------------------------- create


def create_role(name: str, tagline: str = "", description: str = "") -> str:
    raw = read_raw()
    role_id = slug_id(name, _all_ids(raw))
    raw.setdefault("roles", []).append({
        "id": role_id, "name": name.strip(), "tagline": tagline.strip(),
        "description": description.strip(), "business_services": [],
    })
    save(raw, "role-add")
    return role_id


def create_service(role_id: str, name: str, tagline: str = "") -> str:
    raw = read_raw()
    role, _ = _require(raw, "role", role_id)
    service_id = slug_id(name, _all_ids(raw))
    role.setdefault("business_services", []).append({
        "id": service_id, "name": name.strip(), "tagline": tagline.strip(),
        "value_constructs": [],
    })
    save(raw, "service-add")
    return service_id


def create_vc(service_id: str, name: str, description: str = "",
              technical: list[str] | None = None,
              transferable: list[str] | None = None) -> str:
    raw = read_raw()
    service, _ = _require(raw, "service", service_id)
    vc_id = slug_id(name, _all_ids(raw), prefix="vc-")
    service.setdefault("value_constructs", []).append({
        "id": vc_id, "name": name.strip(), "description": description.strip(),
        "technical_skills": list(technical or []),
        "transferable_skills": list(transferable or []),
    })
    save(raw, "vc-add")
    return vc_id


def create_skill(name: str, skill_type: str, hint: str = "") -> str:
    if skill_type not in ("technical", "transferable"):
        raise StoreError("A skill must be either technical or transferable")
    raw = read_raw()
    skill_id = slug_id(name, _all_ids(raw))
    raw.setdefault("skills", {})[skill_id] = {
        "name": name.strip(), "type": skill_type, "hint": hint.strip(),
    }
    save(raw, "skill-add")
    return skill_id


# -------------------------------------------------------------------- update


EDITABLE = {
    "role": {"name", "tagline", "description"},
    "service": {"name", "tagline"},
    "vc": {"name", "description"},
    "skill": {"name", "hint"},
}


def update(kind: str, entity_id: str, changes: dict) -> None:
    """Edit labels. `id` and a skill's `type` are deliberately not editable."""
    if kind not in EDITABLE:
        raise StoreError(f"Unknown kind '{kind}'")
    if "id" in changes and changes["id"] != entity_id:
        raise StoreError(
            "An id can't be changed once it exists — student profiles reference it. "
            "Rename it instead; the label is what people see.")

    raw = read_raw()
    entity, _ = _require(raw, kind, entity_id)
    for field, value in changes.items():
        if field in EDITABLE[kind]:
            entity[field] = value.strip() if isinstance(value, str) else value
    save(raw, f"{kind}-edit")


def set_vc_skills(vc_id: str, technical: list[str], transferable: list[str]) -> None:
    """Attach skills to a value construct.

    The type of each skill is checked here rather than left to the validator, so
    the panel can say which skill is wrong instead of surfacing a wall of text.
    """
    raw = read_raw()
    vc, _ = _require(raw, "vc", vc_id)
    skills = raw.get("skills", {})

    for group, expected in ((technical, "technical"), (transferable, "transferable")):
        for skill_id in group:
            if skill_id not in skills:
                raise StoreError(f"No skill with id '{skill_id}'")
            if skills[skill_id].get("type") != expected:
                raise StoreError(
                    f"'{skills[skill_id].get('name', skill_id)}' is a "
                    f"{skills[skill_id].get('type')} skill, so it can't go in the {expected} list")

    vc["technical_skills"] = list(dict.fromkeys(technical))
    vc["transferable_skills"] = list(dict.fromkeys(transferable))
    save(raw, "vc-skills")


# ------------------------------------------------------------ archive/delete


def archive(kind: str, entity_id: str, archived: bool = True) -> None:
    raw = read_raw()
    entity, _ = _require(raw, kind, entity_id)
    if archived:
        entity["archived"] = True
    else:
        entity.pop("archived", None)
    save(raw, f"{kind}-{'archive' if archived else 'restore'}")


def delete(kind: str, entity_id: str) -> None:
    """Remove outright. Callers archive instead when the thing is in use."""
    raw = read_raw()
    entity, parent = _require(raw, kind, entity_id)

    if kind == "skill":
        using = [vc_id for vc_id, vc in _walk_vcs(raw) if entity_id in vc_skill_ids(vc)]
        if using:
            raise StoreError(
                f"That skill is still attached to {len(using)} value construct"
                f"{'s' if len(using) > 1 else ''}. Detach it first.")
        parent.pop(entity_id)
    else:
        parent.remove(entity)

    save(raw, f"{kind}-delete")


def _walk_vcs(raw: dict):
    for role in raw.get("roles", []):
        for service in role.get("business_services", []):
            for vc in service.get("value_constructs", []):
                yield vc["id"], vc
