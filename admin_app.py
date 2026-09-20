"""Caarya admin - a separate program from the student app.

Runs on its own port and serves only the taxonomy editor. The public app
(`app.py`) contains none of this code, so the two can be deployed and firewalled
independently: put this one behind a VPN, an SSO proxy, or simply don't expose
its port.

    python3 admin_app.py            # http://localhost:5001

They share the data on disk - `data/taxonomy.json` and `caarya.db` - so an edit
here is live for the next student who loads the form. That means both programs
need to run on the same machine, or at least the same volume.

    ⚠ There is no authentication yet. `_authenticate` below is the one hook
      where it goes; everything already routes through it.
"""

from __future__ import annotations

import os
import socket
import traceback
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

import db
from admin import admin as admin_blueprint
from taxonomy_loader import load_taxonomy

BASE_DIR = Path(__file__).resolve().parent
PORT = int(os.environ.get("CAARYA_ADMIN_PORT", "5001"))

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.register_blueprint(admin_blueprint)


@app.before_request
def _authenticate():
    """The single gate every admin request passes through.

    Open on purpose for now. To close it, return a 401/redirect from here when
    the request isn't signed in - nothing else needs to change, because every
    route in this program goes through this hook and the student app has no
    admin routes to protect in the first place.
    """
    return None


@app.get("/")
def admin_page():
    return send_from_directory(app.static_folder, "admin.html")


@app.get("/students/<int:profile_id>")
def student_page(profile_id: int):
    """A student's profile as a company sees it.

    Deliberately a different page from the student app's report: it is locked to
    the company view, with no way to switch to the personal one. An admin
    reviewing candidates should see what a recruiter sees, not the coaching
    written for the student.
    """
    return send_from_directory(app.static_folder, "student.html")


@app.get("/api/profiles")
def api_list_profiles():
    """Completed student profiles.

    Lives here rather than on the public app: it is every student's name,
    college and result in one response, which is not something a public server
    should hand out.
    """
    return jsonify({"profiles": db.list_profiles(limit=int(request.args.get("limit", 200)))})


@app.errorhandler(Exception)
def unhandled(error):
    if isinstance(error, HTTPException):
        return jsonify({"error": error.description}), error.code

    app.logger.exception("Unhandled error on %s %s", request.method, request.path)
    print("\n" + "-" * 70 + f"\n{request.method} {request.path} failed\n"
          + traceback.format_exc() + "-" * 70, flush=True)
    return jsonify({
        "error": "Something broke on the server — the full traceback is in the terminal running admin_app.py",
        "details": [f"{type(error).__name__}: {error}"],
    }), 500


def _check_port_is_free() -> None:
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        return
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind(("127.0.0.1", PORT))
    except OSError:
        print(f"\n  Port {PORT} is already taken, so the admin cannot start.\n"
              f"  Find it:   lsof -nP -iTCP:{PORT} -sTCP:LISTEN\n"
              f"  Or move:   CAARYA_ADMIN_PORT=5051 python3 admin_app.py\n")
        raise SystemExit(1)
    finally:
        probe.close()


if __name__ == "__main__":
    _check_port_is_free()
    db.init_db()
    tax = load_taxonomy(force=True)
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        student = os.environ.get("CAARYA_STUDENT_URL", "http://localhost:5000")
        print(f"  Caarya admin · taxonomy v{tax.version}\n"
              f"  http://127.0.0.1:{PORT}   (no authentication — don't expose this port)\n"
              f"  student app expected at {student}\n")
    app.run(host="127.0.0.1", port=PORT, debug=True)
