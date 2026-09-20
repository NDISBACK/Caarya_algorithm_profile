"""Caarya student profiling - the public app.

Serves the wizard, hands it the taxonomy and form schema, computes the fit report
on submission, and stores the result for the company-matching dashboard to read.

This app is meant to face the internet, so it contains no administrative code at
all - the taxonomy editor is a separate program, `admin_app.py`, which is not
reachable from here. Absence is a better guarantee than a guard.
"""

from __future__ import annotations

import hashlib
import os
import socket
import traceback
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

import db
import scoring
from taxonomy_loader import load_institutions, load_schema, load_taxonomy
from validators import validate_details, validate_submission

BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__, static_folder="static", static_url_path="/static")

# Reload the data files on every request in debug so editing taxonomy.json or
# profile_schema.json shows up on refresh - the admin portal will eventually do
# exactly this, and it is the thing you most want to iterate on quickly.
RELOAD_DATA = os.environ.get("CAARYA_RELOAD", "1") == "1"
PORT = int(os.environ.get("CAARYA_PORT", "5000"))
STARTED_AT = datetime.now().isoformat(timespec="seconds")


def _fingerprint() -> str:
    """A short hash of the source files, so /api/health changes when the code does."""
    digest = hashlib.sha256()
    for name in sorted(("app.py", "scoring.py", "taxonomy_loader.py", "db.py", "validators.py")):
        digest.update((BASE_DIR / name).read_bytes())
    return digest.hexdigest()[:12]


def taxonomy():
    return load_taxonomy(force=RELOAD_DATA)


def schema():
    return load_schema(force=RELOAD_DATA)


def institutions():
    return load_institutions(force=RELOAD_DATA)


# ------------------------------------------------------------------ pages

@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/report/<int:profile_id>")
def report_page(profile_id: int):
    return send_from_directory(app.static_folder, "report.html")


# -------------------------------------------------------------------- api

@app.get("/api/health")
def api_health():
    """Which build is actually answering.

    Worth having because the most confusing failure in local development is a
    stale server still holding the port: the browser talks to old code against an
    old database and nothing in the UI says so.
    """
    return jsonify({
        "ok": True,
        "started_at": STARTED_AT,
        "pid": os.getpid(),
        "taxonomy_version": taxonomy().version,
        "schema_version": schema().get("version"),
        "code_fingerprint": _fingerprint(),
    })


@app.get("/api/taxonomy")
def api_taxonomy():
    return jsonify(taxonomy().public_dict())


@app.get("/api/profile-schema")
def api_schema():
    return jsonify(schema())


@app.get("/api/institutions")
def api_institutions():
    """Suggestions for the state and college fields. Not a constraint - a
    student may type anything, and it is stored as typed."""
    return jsonify(institutions())


def _clean_selections(tax, payload: dict) -> tuple[dict | None, tuple]:
    """Keep only selections that exist in the taxonomy, so a stale draft or a
    hand-rolled request can't steer the scoring."""
    selections = payload.get("selections", payload)
    role_id = selections.get("role_id")
    if role_id not in tax.roles:
        return None, (jsonify({"error": "Unknown role"}), 400)

    valid_services = {s["id"] for s in tax.active_services_of_role(role_id)}
    service_ids = [s for s in selections.get("service_ids", []) if s in valid_services]
    vc_ids = [v for v in selections.get("vc_ids", []) if tax.service_of_vc.get(v) in valid_services]
    if not service_ids or not vc_ids:
        return None, (jsonify({"error": "Pick at least one business service and one value construct"}), 400)

    return {"role_id": role_id, "service_ids": service_ids, "vc_ids": vc_ids}, ()


@app.post("/api/skill-set")
def api_skill_set():
    """Round zero: the skills behind the work the student picked."""
    tax = taxonomy()
    selections, error = _clean_selections(tax, request.get_json(silent=True) or {})
    if selections is None:
        return error
    return jsonify(tax.build_skill_set(
        selections["role_id"], selections["service_ids"], selections["vc_ids"]))


@app.post("/api/skill-set/next")
def api_skill_set_next():
    """The next few skills worth asking about, chosen from the answers so far.

    Stateless: the client sends everything rated to date and gets back either the
    next batch or `done`, so a refresh mid-round costs nothing.
    """
    payload = request.get_json(silent=True) or {}
    tax = taxonomy()
    selections, error = _clean_selections(tax, payload)
    if selections is None:
        return error

    ratings = payload.get("ratings", {})
    if not isinstance(ratings, dict):
        return jsonify({"error": "Ratings must be an object of skill id to 1-5"}), 400

    # Drop anything that isn't a usable rating rather than letting it reach the
    # scoring maths - a stale draft or a hand-rolled request shouldn't 500.
    clean: dict[str, int] = {}
    for skill_id, value in ratings.items():
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if skill_id in tax.skills and 1 <= number <= 5:
            clean[skill_id] = number

    return jsonify(scoring.next_question_batch(tax, selections, clean))


@app.post("/api/profile")
def api_create_profile():
    payload = request.get_json(silent=True) or {}
    tax = taxonomy()

    errors = validate_submission(payload, schema(), tax)
    if errors:
        return jsonify({"error": "Some answers need another look", "details": errors}), 400

    report = scoring.build_report(
        tax,
        payload.get("selections", {}),
        payload.get("ratings", {}),
        profile=_evidence_view(payload),
    )
    profile_id = db.save_profile(payload, report)
    return jsonify({"profile_id": profile_id, "report": report}), 201


@app.patch("/api/profile/<int:profile_id>/details")
def api_update_details(profile_id: int):
    """Save the optional follow-up section and recompute the report.

    Recomputing matters: the experience and projects a student adds here are what
    the evidence check reads, so finishing this section genuinely moves the
    confidence attached to their scores rather than just filling a database.
    """
    payload = request.get_json(silent=True) or {}
    tax = taxonomy()

    errors = validate_details(payload, schema())
    if errors:
        return jsonify({"error": "Some answers need another look", "details": errors}), 400

    stored = db.get_profile(profile_id)
    if stored is None:
        return jsonify({"error": "No profile with that id"}), 404

    # Evidence comes from what was stored in the main flow - experience, projects
    # and the tool stack are collected before the report now, so rebuilding the
    # report from this patch alone would score it as though the student had none.
    report = scoring.build_report(
        tax, stored["selections"], stored["ratings"], profile=_stored_evidence(stored, payload)
    )
    if not db.update_profile_details(profile_id, payload, report):
        return jsonify({"error": "No profile with that id"}), 404

    return jsonify({"profile_id": profile_id, "report": report})


@app.get("/api/profile/<int:profile_id>")
def api_get_profile(profile_id: int):
    profile = db.get_profile(profile_id)
    if profile is None:
        return jsonify({"error": "No profile with that id"}), 404
    return jsonify(profile)


def _evidence_view(payload: dict) -> dict:
    """Flatten a fresh submission into the shape scoring's evidence check expects."""
    return {
        **db.flatten_experience(payload),
        "tool_stack": payload.get("tool_stack", {}),
        "certifications": payload.get("languages_certs", {}).get("certifications", []),
        "motivation": payload.get("motivation", {}),
    }


def _stored_evidence(stored: dict, details: dict) -> dict:
    """The same shape, rebuilt from what is already in the database."""
    experience = stored.get("experience", {})
    return {
        "work_experience": experience.get("work", []),
        "projects": experience.get("project", []),
        "competitions": experience.get("competition", []),
        "leadership": experience.get("leadership", []),
        "tool_stack": stored.get("tool_stack") or {},
        "certifications": stored.get("student", {}).get("certifications", []),
        "motivation": details.get("motivation") or stored.get("motivation") or {},
    }


@app.errorhandler(Exception)
def unhandled(error):
    """Return failures as JSON and log the traceback.

    Without this Flask answers an API call with an HTML error page, the client
    reports "500 with no readable body", and nobody can see what actually broke.
    """
    if isinstance(error, HTTPException):
        return jsonify({"error": error.description}), error.code

    app.logger.exception("Unhandled error on %s %s", request.method, request.path)
    detail = f"{type(error).__name__}: {error}"
    print("\n" + "-" * 70 + f"\n{request.method} {request.path} failed\n"
          + traceback.format_exc() + "-" * 70, flush=True)
    return jsonify({
        "error": "Something broke on the server — the full traceback is in the terminal running app.py",
        "details": [detail],
    }), 500


def _check_port_is_free() -> None:
    """Refuse to start quietly behind something else.

    If another copy of this app is already on the port, Flask exits and the
    browser keeps talking to the old process - serving old code against an old
    database, with no sign anything is wrong. On macOS the usual culprit is
    AirPlay Receiver, which also listens on 5000.
    """
    # Werkzeug's reloader binds the socket in the parent and hands the fd to the
    # child, which re-runs this file - so checking in the child would trip on our
    # own server and kill it on every code change.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        return

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind(("127.0.0.1", PORT))
    except OSError:
        print(f"\n  Port {PORT} is already taken, so this server cannot start.\n"
              f"  Whatever is on it will keep answering your browser with older code.\n\n"
              f"  Find it:   lsof -nP -iTCP:{PORT} -sTCP:LISTEN\n"
              f"  Stop it:   pkill -f 'python3 app.py'\n"
              f"  Or move:   CAARYA_PORT=5050 python3 app.py\n\n"
              f"  On macOS, System Settings > General > AirDrop & Handoff >\n"
              f"  AirPlay Receiver also uses port 5000.\n")
        raise SystemExit(1)
    finally:
        probe.close()


if __name__ == "__main__":
    _check_port_is_free()
    db.init_db()                       # creates the database, and migrates an older one
    tax = load_taxonomy(force=True)    # fail loudly at startup if the taxonomy is broken
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        print(f"  Caarya profiling · students · build {_fingerprint()} · taxonomy v{tax.version}\n"
              f"  http://127.0.0.1:{PORT}\n")
    app.run(host="127.0.0.1", port=PORT, debug=True)
