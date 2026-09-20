"""One WSGI entrypoint for both programs, for hosts with a single persistent disk.

Serves the student app and the admin app from one process so they share
`caarya.db` and `data/` (a Render disk attaches to one service only). The two
apps stay separate code; this only routes by path:

    /admin, /students/<id>, /api/admin/*, /api/profiles  ->  admin_app
    everything else                                       ->  app (student)

    gunicorn wsgi:app --workers 1
"""

import os

# Deployment defaults; anything set in the environment wins.
# With Postgres, CAARYA_RELOAD=1 is what makes an admin edit visible on every server
# instance (load_taxonomy re-reads at most every few seconds); files never change, so 0 otherwise.
os.environ.setdefault("CAARYA_RELOAD", "1" if os.environ.get("DATABASE_URL") else "0")
os.environ.setdefault("CAARYA_STUDENT_URL", "/")
os.environ["CAARYA_ADMIN_REQUIRE_AUTH"] = "1"   # deployed: no password means no admin, never an open one
if os.environ.get("VERCEL") and not os.environ.get("DATABASE_URL"):
    # Vercel's filesystem is read-only apart from /tmp, and /tmp is not shared or durable.
    os.environ.setdefault("CAARYA_DATA_DIR", "/tmp/caarya")

import db  # noqa: E402
from taxonomy_loader import bootstrap_data_dir, load_taxonomy  # noqa: E402

if db.STORAGE_DIR and not db.use_postgres():
    db.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
bootstrap_data_dir()
db.init_db()
load_taxonomy(force=True, fresh=True)

from admin_app import app as admin_app  # noqa: E402
from app import app as student_app  # noqa: E402

_ADMIN_PREFIXES = ("/students/", "/api/admin/")


def app(environ, start_response):
    path = environ.get("PATH_INFO", "/")
    if path.rstrip("/") == "/admin":
        environ["PATH_INFO"] = "/"
        return admin_app(environ, start_response)
    if path.startswith(_ADMIN_PREFIXES) or path == "/api/profiles":
        return admin_app(environ, start_response)
    return student_app(environ, start_response)
