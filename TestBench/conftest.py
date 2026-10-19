"""BuoyUp Testbench — shared harness for adversarial / robustness test cases.

All test cases drive the real backend in-process through FastAPI's TestClient,
against a fresh isolated SQLite DB per test (no network, no real chain, no LLM).

SCORING CONVENTION (important):
    Every test case describes an ATTACK or an abuse attempt against BuoyUp.
    A test that PASSES  (green) = the system correctly RESISTED the attack  -> SECURE.
    A test that FAILS   (red)   = the attack SUCCEEDED                      -> VULNERABILITY.
    A test that ERRORS          = harness/setup problem                     -> INVESTIGATE.

    So: write each test so its asserts demand the *secure* outcome
    (e.g. `assert r.status_code == 403`, `assert limit_unchanged`).

DIFFICULTY: mark every test with exactly one of @pytest.mark.easy / .medium / .hard.
TITLE:      the first line of the test's docstring is used as the human-readable
            case title in the results sheet. Start it with a stable case id, e.g.
                '''AUTH-E1: login brute force is rate-limited after 5 tries.'''

Run:   ./run_testbench.sh         (from the Testbench/ folder)
Sheet: results/testbench_sheet.md  +  results/testbench_sheet.csv
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
from collections.abc import Iterator
from typing import Any

# --- locate the backend source and make `app` / `tests` importable ----------
_HERE = pathlib.Path(__file__).resolve().parent
_SRC = _HERE.parent / "BackEnd" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# --- configure the environment BEFORE any `app` module is imported ----------
_TEST_DIR = tempfile.mkdtemp(prefix="buoyup-testbench-")
os.environ["ENV_FILE"] = os.path.join(_TEST_DIR, "no.env")
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{_TEST_DIR}/test.db",
        "APP_ENV": "dev",
        "LOG_LEVEL": "WARNING",
        "LLM_ENABLED": "false",
        "GEMINI_API_KEY": "",
        "LLM_HOST": "",
        "LLM_API_KEY": "",
        "BUOYUP_AUTOPILOT": "false",
        "BUOYUP_CHAIN_BACKEND": "local",
        "BUOYUP_CHAIN_URL": "",
        "BUOYUP_CHAIN_TOKEN": "",
        "FACE_WARMUP": "false",
        "FACE_DATA_DIR": os.path.join(_TEST_DIR, "faces"),
        # Law retrieval lexical-only, as in BackEnd tests: no ~1 GB embedding-model download.
        "BUOYUP_RAG_DENSE": "0",
        # Older cases post /identity and /plan without a CCCD scan or the declaration;
        # 06_dossiers_bypass switches the real product checks on itself.
        "CCCD_OCR_REQUIRED": "false",
        "PLAN_DECLARATION_REQUIRED": "false",
        "UPLOAD_DIR": os.path.join(_TEST_DIR, "uploads"),
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.platform.db.init_db import reset_db  # noqa: E402
from app.platform.llm.base import NullProvider  # noqa: E402
from app.platform.llm.gemini import set_provider  # noqa: E402
from app.platform.seed import seed_buoyup  # noqa: E402

DEMO_PASSWORD = "BuoyUp@2026"
DEMO = {
    "seller": "lan@buoyup.vn",
    "officer": "officer@buoyup.vn",
    "admin": "admin@buoyup.vn",
    "webank": "webank@buoyup.vn",
    "cmb": "cmb@buoyup.vn",
}


def pytest_configure(config: Any) -> None:
    for name, desc in (
        ("easy", "easy attack: obvious, single-step"),
        ("medium", "medium attack: multi-step or requires some knowledge"),
        ("hard", "hard attack: subtle logic/crypto/race abuse"),
    ):
        config.addinivalue_line("markers", f"{name}: {desc}")


@pytest.fixture(autouse=True)
def clean_state() -> Iterator[None]:
    reset_db()
    set_provider(NullProvider())
    yield
    set_provider(NullProvider())


@pytest.fixture()
def bu_client() -> Iterator[TestClient]:
    """Fresh DB seeded with banks, params v4.0 and the demo users."""
    reset_db()
    seed_buoyup()
    from app.main import app

    with TestClient(app) as client:
        yield client


def login(client: TestClient, email: str, password: str = DEMO_PASSWORD) -> dict[str, str]:
    r = client.post("/v4/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, f"login failed for {email}: {r.text}"
    return {"Authorization": "Bearer " + r.json()["token"]}


def register_seller(client: TestClient, email: str, password: str = "abc12345") -> dict[str, str]:
    r = client.post("/v4/auth/register", json={"email": email, "password": password,
                                               "display_name": email.split("@")[0], "accept_terms": True})
    assert r.status_code == 201, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


# --- results recording: one row per test into results/raw_results.jsonl -----
_RESULTS: list[dict[str, Any]] = []


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: Any, call: Any):  # type: ignore[no-untyped-def]
    outcome = yield
    report = outcome.get_result()
    if report.when != "call":
        return
    marks = {m.name for m in item.iter_markers()}
    difficulty = next((d for d in ("easy", "medium", "hard") if d in marks), "unmarked")
    doc = (item.function.__doc__ or "").strip().splitlines()
    title = doc[0].strip() if doc else item.name
    rel = os.path.relpath(str(item.fspath), str(_HERE / "cases"))
    category = rel.split(os.sep)[0] if os.sep in rel else "misc"
    status = "PASS" if report.passed else ("FAIL" if report.failed else "SKIP")
    _RESULTS.append(
        {
            "category": category,
            "difficulty": difficulty,
            "case": title,
            "nodeid": item.nodeid,
            "secure": status == "PASS",   # PASS == system resisted == secure
            "status": status,             # PASS=resisted, FAIL=attack succeeded
            "duration_s": round(getattr(report, "duration", 0.0), 3),
        }
    )


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    out = _HERE / "results"
    out.mkdir(exist_ok=True)
    with open(out / "raw_results.jsonl", "w", encoding="utf-8") as fh:
        for row in _RESULTS:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
