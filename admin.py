"""The admin panel's API.

Owns the taxonomy that every student form reads. It is mounted only on
`admin_app.py`, never on the public student app, so the two are separate
programs that can be deployed and firewalled independently.

There is deliberately **no authentication here yet** - see the hook in
`admin_app.py`, which is the single place it goes when you add it.

Deleting is deliberate about consequences: anything a student has already been
scored on is archived rather than removed, so old reports keep working.
"""

from __future__ import annotations

import os

from flask import Blueprint, jsonify, request

import db
import taxonomy_store as store
from taxonomy_loader import load_taxonomy, vc_skill_ids
from taxonomy_store import StoreError

admin = Blueprint("admin", __name__)

# Which usage bucket and store kind each URL segment maps to.
KINDS = {
    "roles": ("role", "roles"),
    "services": ("service", "services"),
    "vcs": ("vc", "vcs"),
    "skills": ("skill", "skills"),
}


def _kind(segment: str) -> tuple[str, str]:
    if segment not in KINDS:
        raise StoreError(f"Unknown kind '{segment}'")
    return KINDS[segment]


def _body() -> dict:
    return request.get_json(silent=True) or {}


@admin.errorhandler(StoreError)
def _rejected(error: StoreError):
    return jsonify({"error": str(error)}), 400


# ------------------------------------------------------------------ reading


@admin.get("/api/admin/config")
def admin_config():
    """Where the student app lives, so the panel can link to it.

    The two are separate programs now and need not share a host, so this can no
    longer be hardcoded to "/".
    """
    return jsonify({"student_url": os.environ.get("CAARYA_STUDENT_URL", "http://localhost:5000")})


@admin.get("/api/admin/taxonomy")
def admin_taxonomy():
    """The whole tree including archived entities, with usage counts.

    Deliberately not `public_dict()` - the panel is the one place that needs to
    see what students can't.
    """
    tax = load_taxonomy(force=True)
    usage = db.taxonomy_usage()

    skill_vcs: dict[str, list[dict]] = {}
    for vc_id, vc in tax.vcs.items():
        for skill_id in vc_skill_ids(vc):
            skill_vcs.setdefault(skill_id, []).append({"id": vc_id, "name": vc.get("name", vc_id)})

    return jsonify({
        "taxonomy": tax.raw,
        "usage": usage,
        "skill_value_constructs": skill_vcs,
        "warnings": tax.warnings,
        "version": tax.version,
    })


@admin.get("/api/admin/profiles")
def admin_profiles():
    return jsonify({"profiles": db.list_profiles(limit=int(request.args.get("limit", 200)))})


@admin.get("/api/admin/profiles/<int:profile_id>")
def admin_profile(profile_id: int):
    """One student, for the company-view page.

    The admin reads the same stored profile the student app serves, but the page
    that renders it is locked to the company view - see `static/student.html`.
    """
    profile = db.get_profile(profile_id)
    if profile is None:
        return jsonify({"error": "No profile with that id"}), 404
    return jsonify(profile)


# ----------------------------------------------------------------- writing


@admin.post("/api/admin/roles")
def add_role():
    body = _body()
    if not (body.get("name") or "").strip():
        raise StoreError("A role needs a name")
    return jsonify({"id": store.create_role(body["name"], body.get("tagline", ""),
                                            body.get("description", ""))}), 201


@admin.post("/api/admin/services")
def add_service():
    body = _body()
    if not (body.get("name") or "").strip():
        raise StoreError("A business service needs a name")
    if not body.get("role_id"):
        raise StoreError("A business service has to belong to a role")
    return jsonify({"id": store.create_service(body["role_id"], body["name"],
                                               body.get("tagline", ""))}), 201


@admin.post("/api/admin/vcs")
def add_vc():
    body = _body()
    if not (body.get("name") or "").strip():
        raise StoreError("A value construct needs a name")
    if not body.get("service_id"):
        raise StoreError("A value construct has to belong to a business service")
    return jsonify({"id": store.create_vc(
        body["service_id"], body["name"], body.get("description", ""),
        body.get("technical_skills"), body.get("transferable_skills"))}), 201


@admin.post("/api/admin/skills")
def add_skill():
    body = _body()
    if not (body.get("name") or "").strip():
        raise StoreError("A skill needs a name")
    return jsonify({"id": store.create_skill(body["name"], body.get("type", ""),
                                             body.get("hint", ""))}), 201


@admin.patch("/api/admin/<segment>/<entity_id>")
def edit(segment: str, entity_id: str):
    kind, _ = _kind(segment)
    store.update(kind, entity_id, _body())
    return jsonify({"ok": True})


@admin.put("/api/admin/vcs/<vc_id>/skills")
def set_skills(vc_id: str):
    body = _body()
    store.set_vc_skills(vc_id, body.get("technical_skills") or [],
                        body.get("transferable_skills") or [])
    return jsonify({"ok": True})


@admin.post("/api/admin/<segment>/<entity_id>/restore")
def restore(segment: str, entity_id: str):
    kind, _ = _kind(segment)
    store.archive(kind, entity_id, archived=False)
    return jsonify({"ok": True, "archived": False})


@admin.delete("/api/admin/<segment>/<entity_id>")
def remove(segment: str, entity_id: str):
    """Archive if anyone has been scored on it, otherwise remove it properly.

    The caller doesn't choose: the data decides. Deleting something twelve
    students were assessed against would leave their reports unable to name
    what they were assessed on.
    """
    kind, bucket = _kind(segment)
    used_by = db.taxonomy_usage().get(bucket, {}).get(entity_id, 0)

    if used_by:
        store.archive(kind, entity_id, archived=True)
        return jsonify({
            "archived": True, "used_by": used_by,
            "message": f"Archived instead of deleted — {used_by} student profile"
                       f"{'s' if used_by > 1 else ''} "
                       f"{'reference' if used_by > 1 else 'references'} it. It's gone from "
                       f"the student form, and {'their' if used_by > 1 else 'that'} "
                       f"report{'s' if used_by > 1 else ''} still work"
                       f"{'' if used_by > 1 else 's'}.",
        })

    store.delete(kind, entity_id)
    return jsonify({"archived": False, "used_by": 0, "message": "Deleted."})
