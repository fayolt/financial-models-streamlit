"""Repo-root conftest: ensure `app/` and `models/` are importable for tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
