import os
import sys

# Add the project root to sys.path so `app` package can be imported
# regardless of where this script is invoked from
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import uvicorn

# ── Use in-memory SQLite for local testing ──
# WARNING: All match data is lost when the server stops or reloads.
# This is fine for throwaway local testing, but NOT for real matches.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

# Initialize database before starting the server
from app.database import init_db

init_db()

# Use import string for reload support
# reload=False to avoid address-in-use conflict on macOS with stat reloader
uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
