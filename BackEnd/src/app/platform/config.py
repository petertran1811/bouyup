"""Application configuration.

Every tunable number of the MVP lives here so that policy thresholds, guardrails
and model names can be changed without touching business logic.
"""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# FINTACHATHONS/BackEnd/src/app/platform/config.py → BackEnd/src
BASE_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = BASE_DIR.parent
# .env lives in BackEnd/API_config/ (ENV_FILE overrides; Docker passes variables directly).
ENV_FILE = Path(os.environ.get("ENV_FILE") or (BACKEND_DIR / "API_config" / ".env"))

# The mock connectors read their world from here, and onboarding writes a new
# seller's profile into it. Overridable so a test run operates on a throwaway
# copy instead of rewriting the repository's seed files.

# Section 32: execution mode must be an allowlisted value, hard fail otherwise.
ALLOWED_EXECUTION_MODES = ("mock",)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Unset means production: no demo accounts, no demo keys, strict ledger key.
    # Local runs get APP_ENV=dev from .env (see .env.example).
    app_env: str = "production"
    log_level: str = "INFO"
    # HMAC key of the local ledger (see platform/ledger_key.py); the process environment wins.
    credit_ledger_key: str = ""

    # Browsers block cross-origin XHR unless the API says otherwise. The MVP
    # has no auth, so a wildcard grants nothing the API did not already expose
    # to anyone who can reach it; lock this down before any real deployment.
    cors_allow_origins: list[str] = ["*"]
    # The static UI is served from here when the directory exists, which makes
    # local testing same-origin (no CORS, no mixed content).
    frontend_dir: str = str(BACKEND_DIR.parent / "Frontend")

    # --- LLM ---------------------------------------------------------------
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    # Gemini quota is enforced per model and per time window, so an exhausted
    # model says nothing about the next one. These are tried in order when the
    # primary returns 429 (or is unavailable to this key).
    gemini_fallback_models: list[str] = [
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3-flash-preview",
        "gemini-3.1-flash-lite",
        "gemini-flash-latest",
    ]
    # How long a rate-limited model sits out before it is tried again.
    gemini_quota_cooldown_seconds: float = 900.0
    llm_enabled: bool = True
    llm_timeout_seconds: float = 30.0
    # An OpenAI-compatible endpoint (a model served by vLLM). When LLM_HOST is
    # set it is used instead of Gemini.
    llm_host: str = ""
    llm_port: str = ""
    llm_model_name: str = ""
    llm_api_key: str = ""

    # --- BuoyUp v4 ----------------------------------------------------------
    # Demo accounts are seeded only when app_env is dev or demo.
    buoyup_demo_password: str = "BuoyUp@2026"
    buoyup_session_hours: int = 12
    # Chain backend: "local" (FISCO simulation, default) or "remote" (the BuoyUp
    # Chain service at BUOYUP_CHAIN_URL, e.g. https://fs.buoyup.app; token optional
    # when the service runs without apiToken).
    buoyup_chain_backend: str = "local"
    buoyup_chain_url: str = ""
    buoyup_chain_token: str = ""
    buoyup_chain_timeout_seconds: float = 10.0
    # Optional second model for Agent 3 (same OpenAI-compatible endpoint).
    llm_agent3_model_name: str = ""
    # FATE standalone service; empty = scenario data (simulated).
    fate_url: str = ""
    # Autopilot (app/buoyup/autopilot.py): Agent 4 monitors open loans every N seconds and
    # Agent 5 post-audits every M seconds (sooner after a real outcome). Never on in tests.
    buoyup_autopilot: bool = True
    buoyup_agent4_interval_seconds: int = 300
    buoyup_agent5_interval_seconds: int = 21600
    # Agent 5 §6/§8: below this many samples in a segment no prudence change is proposed. The demo's
    # synthetic backtest has 20 rows: set 20 only to show the proposal flow (labelled synthetic).
    buoyup_agent5_min_sample: int = 30

    # Review item 2: in production Agent 3 must run on another model than Agent 2 (startup check).
    agent3_require_distinct_model: bool = True

    # --- face authentication (BackEnd/src/Reid, InsightFace buffalo_l) ------
    face_auth_enabled: bool = True
    # While the model is loaded, /auth/register refuses sign-ups without a finished face scan.
    face_required_at_signup: bool = True
    # buffalo_l is downloaded into <face_model_root>/models/buffalo_l on first load (~330 MB).
    face_model_root: str = str(BASE_DIR / "Reid")
    # One folder per user: ArcFace templates + aligned 112x112 crops.
    face_data_dir: str = str(BASE_DIR / "Reid" / "data")
    face_save_crops: bool = True
    face_det_size: int = 320
    # Cosine similarity on ArcFace w600k_r50 embeddings; also the duplicate-face bar at sign-up.
    face_match_threshold: float = 0.45
    # Load the model at startup in the background so the first camera frame is fast.
    face_warmup: bool = True

    # --- persistence -------------------------------------------------------
    database_url: str = "sqlite:///./buoyup.db"

    # --- execution ---------------------------------------------------------
    execution_mode: str = "mock"

    @field_validator("execution_mode")
    @classmethod
    def _validate_execution_mode(cls, value: str) -> str:
        normalised = value.strip().lower()
        if normalised not in ALLOWED_EXECUTION_MODES:
            raise ValueError(
                f"EXECUTION_MODE={value!r} is not allowed. "
                f"Allowed values: {', '.join(ALLOWED_EXECUTION_MODES)}"
            )
        return normalised

    @property
    def llm_base_url(self) -> str:
        """``http://host:port/v1`` of the OpenAI-compatible endpoint, or "" when unset."""
        host = self.llm_host.strip().rstrip("/")
        if not host or not self.llm_model_name.strip():
            return ""
        if "://" not in host:
            host = f"http://{host}"
        if self.llm_port.strip():
            host = f"{host}:{self.llm_port.strip()}"
        return host if host.endswith("/v1") else f"{host}/v1"

    @property
    def use_llm(self) -> bool:
        """True when an LLM call may be attempted at all."""
        return self.llm_enabled and bool(self.llm_base_url or self.gemini_api_key.strip())

    @property
    def masked_api_key(self) -> str:
        """Never log the raw key (section 20/32)."""
        key = (self.llm_api_key if self.llm_base_url else self.gemini_api_key).strip()
        if not key:
            return "<unset>"
        if len(key) < 16:  # too short to show both ends without giving most of it away
            return f"{key[:2]}..."
        return f"{key[:6]}...{key[-4:]}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
