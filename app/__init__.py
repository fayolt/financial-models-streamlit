"""Auto-load .env from the repo root so env-var defaults work in dev."""
from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ENV_FILE = _REPO_ROOT / ".env"

if _ENV_FILE.exists():
    try:
        from dotenv import load_dotenv

        load_dotenv(_ENV_FILE, override=False)
    except ImportError:
        # python-dotenv missing — fine, env vars must be exported manually.
        pass
