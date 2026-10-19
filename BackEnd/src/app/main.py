"""BuoyUp v4 API: five agents, the fixed credit algorithm, partner banks and the FISCO BCOS chain.

Run: ``uvicorn app.main:app`` from BackEnd/src (see HANDOVER.md). Serves the web UI in
FINTACHATHONS/Frontend at /app (pages in /app/giaodien/) when that folder exists.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api import router as buoyup_router
from app.platform.errors import error_body
from app.platform import audit, i18n, ledger_key as ledger
from app.platform.config import settings
from app.platform.db.init_db import init_db
from app.platform.llm.gemini import get_provider
from app.platform.seed import seed_buoyup


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    audit.configure_logging()
    try:
        ledger.check_key_configured()
    except ledger.LedgerKeyMissing as exc:
        audit.logger.error("startup_refused", reason=str(exc))
        raise
    from app.agents import llm_tools

    llm_tools.check_independence_at_startup()
    init_db()
    seed_buoyup()
    provider = get_provider()
    audit.logger.info(
        "startup",
        version=__version__,
        app_env=settings.app_env,
        execution_mode=settings.execution_mode,
        llm_provider=provider.name,
        llm_model=provider.model,
        llm_available=provider.available(),
    )
    from app.autopilot import loop as autopilot
    from app.blockchain import chain, chain_sync

    if chain.mode() == "remote":  # banks' terms and keys from the chain service; not fatal when it is down
        def _sync() -> None:
            from app.platform.db.session import session_scope

            with session_scope() as session:
                chain_sync.sync_catalog(session, actor="startup")

        async def _sync_in_background() -> None:  # the server answers at once; the sync lands shortly after
            try:
                await asyncio.to_thread(_sync)
                audit.logger.info("chain_catalog_synced", **{k: v for k, v in chain_sync.last_sync().items()
                                                             if k in ("banks", "keys", "changed")})
            except Exception as exc:  # noqa: BLE001 - the app still serves; staff can sync again by hand
                chain_sync.note_failure(exc)
                audit.logger.error("chain_catalog_sync_failed", error=str(exc)[:300])

        sync_task = asyncio.create_task(_sync_in_background())

    def _warm_rag() -> None:  # load the law index and the embedding model before the first review needs them
        from app.core import rag

        for j in rag.available():
            audit.logger.info("rag_ready", jurisdiction=j, mode=rag.mode(j), model=rag.MODEL,
                              passages=len(rag.index(j).passages))

    asyncio.get_running_loop().run_in_executor(None, _warm_rag)
    if settings.face_auth_enabled and settings.face_warmup:  # buffalo_l loads (or downloads) off the event loop
        from app.api import face

        face_task = asyncio.create_task(asyncio.to_thread(face.warmup))

    task = asyncio.create_task(autopilot.loop()) if autopilot.enabled() else None
    if task is not None:
        audit.logger.info("autopilot_started", agent4_every=settings.buoyup_agent4_interval_seconds,
                          agent5_every=settings.buoyup_agent5_interval_seconds)
    yield
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    audit.logger.info("shutdown")


app = FastAPI(
    title="BuoyUp API",
    version=__version__,
    description="BuoyUp v4: cho vay người bán TMĐT, năm agent, nhiều ngân hàng cùng cấp vốn, FISCO BCOS.",
    lifespan=lifespan,
)


# The browser UI is a separate origin when it is served from GitHub Pages.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-request-id"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Tag every request with an id so its log lines can be correlated."""
    request_id = request.headers.get("x-request-id") or audit.new_request_id()
    audit.set_request_id(request_id)
    i18n.set_lang(request.headers.get("x-bu-lang"))
    response = await call_next(request)
    response.headers["x-request-id"] = request_id

    # Chrome's Private Network Access blocks a public HTTPS page (e.g. the UI on
    # GitHub Pages) from calling a private address (this API on localhost)
    # unless the preflight opts in explicitly.
    if request.headers.get("access-control-request-private-network"):
        response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        details = detail.get("details")
        if details is None and request.url.path.startswith("/v4/"):
            details = {}
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(detail["code"], detail.get("message", ""), details),
            headers=getattr(exc, "headers", None),
        )
    return JSONResponse(
        status_code=exc.status_code, content=error_body("HTTP_ERROR", str(detail))
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    fields = "; ".join(
        f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()[:5]
    )
    if request.url.path.startswith("/v4/"):
        first = exc.errors()[0] if exc.errors() else {}
        loc = [str(p) for p in first.get("loc", []) if p not in ("body", "query", "path")]
        return JSONResponse(
            status_code=400,
            content=error_body(
                "VALIDATION_ERROR",
                "Dữ liệu gửi lên không hợp lệ.",
                {"field": ".".join(loc), "errors": fields},
            ),
        )
    return JSONResponse(
        status_code=422, content=error_body("INVALID_REQUEST", fields or "Invalid request")
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Never leak an internal stack trace to a client (plan section 32)."""
    if "database is locked" in str(exc):  # another long write is running: ask the client to retry shortly
        audit.logger.warning("db_busy", path=request.url.path)
        return JSONResponse(status_code=503, content=error_body(
            "BUSY", "Hệ thống đang xử lý một thao tác khác của hồ sơ này. Vui lòng đợi vài giây rồi thử lại."))
    audit.logger.error(
        "unhandled_exception",
        path=request.url.path,
        error_type=type(exc).__name__,
        error=str(exc),
    )
    return JSONResponse(
        status_code=500,
        content=error_body("INTERNAL_ERROR", "An internal error occurred."),
    )


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict:
    """Liveness for Docker / load balancers (no database, no LLM call)."""
    return {"ok": True, "version": __version__}


app.include_router(buoyup_router)

@app.get("/app", include_in_schema=False)
@app.get("/app/", include_in_schema=False)
def app_root() -> RedirectResponse:
    """Declared before the static mount, which would otherwise answer /app/ itself."""
    return RedirectResponse(url="/app/giaodien/index.html")


# Serve the static UI from the API itself when it is present (same origin: no CORS, no
# mixed content). Mounted last so it can never shadow an API route.
class _RevalidatedStatic(StaticFiles):
    """UI files carry ETags but no Cache-Control, so browsers guessed a freshness and kept old CSS/JS
    after an update. no-cache keeps the cached copy but revalidates it (a cheap 304) on every load."""

    # Cloudflare in front of buoyup.app replaces that header with its own Browser Cache TTL (4 h) on
    # CSS/JS, but leaves HTML uncached. So every local CSS/JS link in a page gets ?v=<file mtime>:
    # a changed file gets a new URL and the browser fetches it at once.
    _ASSET = re.compile(r'(\b(?:src|href)=")([^":?#]+\.(?:js|css))(")')

    def file_response(self, full_path, stat_result, scope, status_code=200):
        if str(full_path).endswith(".html") and status_code == 200:
            base = Path(full_path).parent

            def versioned(m: re.Match) -> str:
                try:
                    v = int((base / m.group(2)).stat().st_mtime)
                except OSError:
                    return m.group(0)
                return f"{m.group(1)}{m.group(2)}?v={v}{m.group(3)}"

            html = self._ASSET.sub(versioned, Path(full_path).read_text(encoding="utf-8"))
            return HTMLResponse(html, status_code=status_code, headers={"Cache-Control": "no-cache"})
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["Cache-Control"] = "no-cache"
        return response


_frontend = Path(settings.frontend_dir)
if _frontend.is_dir():
    app.mount("/app", _RevalidatedStatic(directory=str(_frontend), html=True), name="app")
    audit.logger.info("frontend_mounted", path=str(_frontend), url="/app/giaodien/")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Bare host → BuoyUp home page; API docs when the UI is not shipped."""
    return RedirectResponse(url="/app/giaodien/index.html" if _frontend.is_dir() else "/docs")

