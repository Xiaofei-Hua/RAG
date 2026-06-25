"""
FastAPI Application for Enterprise RAG Platform

Provides REST API and WebSocket endpoints for:
- Chat/conversation
- Document management
- Session management
- System monitoring
"""

import hashlib
import os
import time

# Browser E2E fake injection (gated, production no-op). When RAG_E2E_FAKES=1 is
# set (only by the Playwright webServer command), install deterministic fakes
# into THIS process so tests run without Ollama/Milvus and stay hermetic. See
# web/AGENTS.md §3 and tests/e2e_ui/_fakes.py. Runs before the app is built so
# patched getters are picked up at first use. PYTEST_RUN=1 only skips the F05
# startup guard below — it does NOT inject fakes.
if os.getenv("RAG_E2E_FAKES", "") == "1":
    from tests.e2e_ui._fakes import install as _install_e2e_fakes

    _install_e2e_fakes()
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.middleware.error_handler import ErrorHandlerMiddleware
from api.middleware.tracing import TracingMiddleware
from api.routers import admin, chat, documents, feedback, retrieval, sessions
from core.prompts.aircraft_prompts import GENERATE_SYSTEM_PROMPT
from utils.log_utils import log


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Handles startup and shutdown events.
    """
    # Startup
    log.info("=" * 50)
    log.info("Enterprise RAG Platform Starting...")
    log.info("=" * 50)

    # Production hardening gate (F05): refuse to start in a wide-open
    # configuration. Admin endpoints fall open to loopback-adjacent callers when
    # ADMIN_API_KEY is unset, and the CORS default is localhost-only — both are
    # fine for local dev but unsafe in production. We raise (uvicorn logs once
    # and exits non-zero) rather than sys.exit so a misconfigured container does
    # not restart-loop. Skipped under PYTEST_RUN=1 (set by tests/conftest.py at
    # collection time, before this lifespan runs).
    _DEFAULT_CORS = "http://localhost:5173,http://127.0.0.1:5173"
    _is_test = os.getenv("PYTEST_RUN", "") == "1"
    _admin_key_set = bool(os.getenv("ADMIN_API_KEY", "").strip())
    _origins_default = os.getenv("ALLOWED_ORIGINS", _DEFAULT_CORS) == _DEFAULT_CORS
    if (not _is_test) and (not _admin_key_set) and _origins_default:
        raise RuntimeError(
            "Refusing to start: production-unsafe configuration. "
            "Set ADMIN_API_KEY and a production ALLOWED_ORIGINS, "
            "or set PYTEST_RUN=1 for the test suite. "
            "(Deploy note: use restart_policy.condition=on-failure with max-attempts.)"
        )

    # Initialize core components (lazy)
    from core.fallback.circuit_breaker import get_llm_circuit, get_retriever_circuit
    from core.memory.redis_memory import get_session_memory

    # Pre-initialize session memory
    _ = get_session_memory()

    # Log circuit breaker status
    llm_circuit = get_llm_circuit()
    retriever_circuit = get_retriever_circuit()

    log.info(f"LLM Circuit: {llm_circuit.state.value}")
    log.info(f"Retriever Circuit: {retriever_circuit.state.value}")
    prompt_sig = hashlib.sha1(GENERATE_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]
    log.info(f"PHM Prompt Profile: phm_diagnosis_v1 (sig={prompt_sig})")

    from agent.harness import get_agent_harness

    await get_agent_harness().astart()

    from utils.env_utils import RERANKER_ENABLED, RERANKER_WARMUP

    if RERANKER_ENABLED and RERANKER_WARMUP:
        from core.retrieval.reranker import get_reranker

        loaded = await get_reranker().aload()
        log.info(f"Reranker warmup: {'ready' if loaded else 'degraded'}")

    log.info("Startup complete!")

    yield

    # Shutdown
    log.info("Shutting down...")

    # Close connections
    from core.memory.redis_memory import get_session_memory

    memory = get_session_memory()
    await memory.close()

    from agent.harness import get_agent_harness

    await get_agent_harness().aclose()

    # Release the hybrid retriever's parallel-retrieval thread pool (F11 —
    # previously a class-level executor with no closer, leaking for the process
    # lifetime; it is now instance-scoped and shut down here).
    try:
        from core.retrieval.hybrid_retriever import get_hybrid_retriever

        get_hybrid_retriever().close()
    except Exception as e:  # noqa: BLE001
        log.debug(f"Hybrid retriever close skipped: {e}")

    # Close the LLMJudge singleton's SQLite verdict-cache connection. The judge
    # is lazily instantiated by the grounding guardrail / PII guardrail / eval
    # flywheel; without this close the connection leaks on every shutdown
    # (surfaced as ResourceWarning: unclosed database).
    try:
        from agent.eval.judge import reset_judge

        reset_judge()
    except Exception as e:  # noqa: BLE001
        log.debug(f"Judge close skipped: {e}")

    # Close the agent-memory / feedback SQLite singletons. They share
    # agent_memory.db; without these closes their connections leak on shutdown.
    try:
        from agent.memory.store import reset_memory_store

        reset_memory_store()
    except Exception as e:  # noqa: BLE001
        log.debug(f"Memory store close skipped: {e}")
    try:
        from agent.feedback.collector import reset_feedback_collector

        reset_feedback_collector()
    except Exception as e:  # noqa: BLE001
        log.debug(f"Feedback collector close skipped: {e}")
    try:
        from agent.feedback.escalation import reset_escalation_manager

        reset_escalation_manager()
    except Exception as e:  # noqa: BLE001
        log.debug(f"Escalation manager close skipped: {e}")
    try:
        from documents.parent_store import reset_parent_store

        reset_parent_store()
    except Exception as e:  # noqa: BLE001
        log.debug(f"Parent store close skipped: {e}")
    try:
        from documents.document_registry import reset_document_registry

        reset_document_registry()
    except Exception as e:  # noqa: BLE001
        log.debug(f"Document registry close skipped: {e}")

    log.info("Shutdown complete")


def create_app() -> FastAPI:
    """
    Build the FastAPI application (F16 — app factory).

    Centralises ALL app construction — CORS, middleware, routers, OTEL
    instrumentation, health/info routes, and the static frontend mount/SPA
    catch-all — so tests can build the app in-process and (in a follow-up) inject
    singletons via ``app.dependency_overrides`` instead of monkeypatching source
    modules. The module-level ``app = create_app()`` below preserves the
    ``uvicorn api.main:app`` entrypoint.
    """
    application = FastAPI(
        title="Enterprise RAG Platform",
        description="企业级RAG智能平台API",
        version="1.0.0",
        lifespan=lifespan,
        root_path=os.getenv("APP_ROOT_PATH", ""),
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS middleware.
    #
    # ``allow_origins=["*"]`` combined with ``allow_credentials=True`` is an
    # invalid and insecure combination per the CORS spec (browsers reject it,
    # and it signals a credential leak if any auth is ever added). Origins are
    # driven by the ``ALLOWED_ORIGINS`` env var (comma-separated). When unset, a
    # safe local-dev default is used; production deployments MUST set it
    # explicitly.
    _default_origins = "http://localhost:5173,http://127.0.0.1:5173"
    _allowed_origins = [
        o.strip() for o in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()
    ]
    # ``allow_credentials`` is only meaningful with a concrete origin list
    # (never with "*"); keep it on so cookies/auth headers work in production.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Custom middleware
    application.add_middleware(TracingMiddleware)
    application.add_middleware(ErrorHandlerMiddleware)

    # Include routers
    application.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
    application.include_router(documents.router, prefix="/api/documents", tags=["Documents"])
    application.include_router(sessions.router, prefix="/api/sessions", tags=["Sessions"])
    application.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
    application.include_router(feedback.router, prefix="/api/feedback", tags=["Feedback"])
    application.include_router(retrieval.router, prefix="/api/retrieval", tags=["Retrieval"])

    from core.tracing import instrument_fastapi

    instrument_fastapi(application)

    # Health check endpoint
    @application.get("/health", tags=["Health"])
    async def health_check():
        """Health check endpoint."""
        from core.fallback.circuit_breaker import get_llm_circuit, get_retriever_circuit

        llm_circuit = get_llm_circuit()
        retriever_circuit = get_retriever_circuit()

        return {
            "status": "healthy",
            "timestamp": time.time(),
            "circuits": {
                "llm": llm_circuit.state.value,
                "retriever": retriever_circuit.state.value,
            },
        }

    # API information endpoint
    @application.get("/api", tags=["Root"])
    async def api_info():
        """Return API information."""
        return {
            "name": "Enterprise RAG Platform",
            "version": "1.0.0",
            "docs": "/docs",
            "health": "/health",
        }

    # Serve the production frontend when `npm run build` has created web/dist.
    web_dist_dir = Path(
        os.getenv("WEB_DIST_DIR", Path(__file__).resolve().parents[1] / "web" / "dist")
    ).resolve()
    web_index = web_dist_dir / "index.html"

    if web_index.is_file():
        assets_dir = web_dist_dir / "assets"
        if assets_dir.is_dir():
            application.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

        @application.get("/{full_path:path}", include_in_schema=False)
        async def frontend(full_path: str):
            """Serve static files and fall back to the Vue SPA entry point."""
            if full_path == "api" or full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="API endpoint not found")
            requested = (web_dist_dir / full_path).resolve()
            if requested.is_relative_to(web_dist_dir) and requested.is_file():
                return FileResponse(requested)
            return FileResponse(web_index)
    else:

        @application.get("/", tags=["Root"])
        async def root():
            """Return API information when the frontend has not been built."""
            return await api_info()

    return application


# Module-level app for `uvicorn api.main:app`. Built via the factory so the
# in-process test client and uvicorn share one construction path.
app = create_app()

# Browser E2E: wire session-memory dependency overrides now that `app` exists.
# No-op unless RAG_E2E_FAKES=1 (install() ran above); pairs with the import-time
# hook at the top of this module. See tests/e2e_ui/_fakes.py.
if os.getenv("RAG_E2E_FAKES", "") == "1":
    from tests.e2e_ui._fakes import wire_overrides as _wire_e2e_overrides

    _wire_e2e_overrides(app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
