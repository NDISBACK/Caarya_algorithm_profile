"""Vercel entrypoint: re-exports the combined WSGI app from the repo root."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wsgi import app  # noqa: E402,F401
