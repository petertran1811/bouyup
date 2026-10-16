"""Shared fixtures for the BuoyUp v4 tests.

The environment is configured *before* any ``app`` module is imported, because
``app.platform.config.settings`` is built at import time. These variables take precedence
over BackEnd/API_config/.env, so a test run never touches the real database, never calls
the real model and never writes to the team's FISCO BCOS service.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from typing import Any

_TEST_DIR = tempfile.mkdtemp(prefix="buoyup-tests-")
os.environ["ENV_FILE"] = os.path.join(_TEST_DIR, "no.env")  # ignore the developer's .env

os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{_TEST_DIR}/test.db",
        "APP_ENV": "dev",
        "LOG_LEVEL": "WARNING",
        # No LLM by default: every test asserts deterministic behaviour unless
        # it injects its own fake provider.
        "LLM_ENABLED": "false",
        "GEMINI_API_KEY": "",
        "LLM_HOST": "",
        "LLM_API_KEY": "",
        # Agents 4/5 never run on their own during tests; tests call autopilot.run_* directly.
        "BUOYUP_AUTOPILOT": "false",
        # Never reach the team's chain service from tests (.env may select it); the remote
        # tests install a mock client themselves.
        "BUOYUP_CHAIN_BACKEND": "local",
        "BUOYUP_CHAIN_URL": "",
        "BUOYUP_CHAIN_TOKEN": "",
        # Law retrieval runs lexical-only in tests (fast, no model download); the dense side has its own
        # opt-in check (BUOYUP_RAG_EVAL_DENSE=1).
        "BUOYUP_RAG_DENSE": "0",
        # Face tests install a fake engine; never load buffalo_l or touch Reid/data.
        "FACE_WARMUP": "false",
        "FACE_DATA_DIR": os.path.join(_TEST_DIR, "faces"),
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.platform.db.init_db import reset_db  # noqa: E402
from app.platform.llm.base import NullProvider  # noqa: E402
from app.platform.llm.gemini import set_provider  # noqa: E402
from app.platform.seed import seed_buoyup  # noqa: E402


@pytest.fixture(autouse=True)
def full_limit_unless_seed(request: pytest.FixtureRequest) -> Iterator[None]:
    """Most tests check the algorithm's computed limit (chị Lan 200.000); the seed-loan fraction is
    tested on its own (``@pytest.mark.seed_loan``). Runs before the database is seeded."""
    from app.core.params import DEFAULT_PARAMS

    saved = list(DEFAULT_PARAMS["seed"]["ratio"])
    if request.node.get_closest_marker("seed_loan") is None:
        DEFAULT_PARAMS["seed"]["ratio"] = [1.0, 1.0, 1.0]
    yield
    DEFAULT_PARAMS["seed"]["ratio"] = saved


@pytest.fixture(autouse=True)
def clean_state(full_limit_unless_seed: None) -> Any:
    """Fresh database and no model for every test."""
    reset_db()
    set_provider(NullProvider())
    yield
    set_provider(NullProvider())


@pytest.fixture()
def bu_client() -> Iterator[TestClient]:
    """Fresh database with banks, params v4.0 and demo users."""
    reset_db()
    seed_buoyup()
    from app.main import app

    with TestClient(app) as client:
        yield client


DEMO_PASSWORD = "BuoyUp@2026"


def login(client: TestClient, email: str, password: str = DEMO_PASSWORD) -> dict[str, str]:
    r = client.post("/v4/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def as_seller(bu_client: TestClient) -> dict[str, str]:
    return login(bu_client, "lan@buoyup.vn")


@pytest.fixture()
def as_officer(bu_client: TestClient) -> dict[str, str]:
    return login(bu_client, "officer@buoyup.vn")


@pytest.fixture()
def as_admin(bu_client: TestClient) -> dict[str, str]:
    return login(bu_client, "admin@buoyup.vn")


@pytest.fixture()
def as_webank(bu_client: TestClient) -> dict[str, str]:
    return login(bu_client, "webank@buoyup.vn")
