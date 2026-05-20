"""
Test fixtures. Points logiq.db at an isolated SQLite file per session and
makes sure src/ is on sys.path so `from logiq.api import app` works whether
pytest is launched from the repo root or elsewhere.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

_TMP = Path(tempfile.mkdtemp(prefix="logiq_test_"))
os.environ["LOGIQ_DB_PATH"] = str(_TMP / "logiq.db")
# Keep uploads / reports for tests inside the same tempdir, not the real repo.
os.environ["LOGIQ_BASE_DIR"] = str(_TMP)
(_TMP / "data" / "uploads").mkdir(parents=True, exist_ok=True)
(_TMP / "reports").mkdir(parents=True, exist_ok=True)
(_TMP / "web").mkdir(parents=True, exist_ok=True)


@pytest.fixture(scope="session")
def app():
    # Create the core schema (fleets / airframes / flights / features /
    # anomalies). The API only initializes the auxiliary tables at boot;
    # the main schema is normally created by `py -m logiq.db`.
    from logiq.db import init_schema
    init_schema()
    from logiq.api import app as fastapi_app
    return fastapi_app


@pytest.fixture(scope="session")
def client(app):
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c
