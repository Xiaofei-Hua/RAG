"""
FastAPI Application for Enterprise RAG Platform

Provides REST API and WebSocket endpoints for:
- Chat/conversation
- Document management
- Session management
- System monitoring
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import hashlib
import os
from pathlib import Path
import time

from utils.log_utils import log
from api.routers import chat, documents, sessions, admin, feedback, retrieval
from api.middleware.tracing import TracingMiddleware
from api.middleware.error_handler import ErrorHandlerMiddleware
from core.prompts.aircraft_prompts import GENERATE_SYSTEM_PROMPT


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

    # Initialize core components (lazy)
    from core.memory.redis_memory import get_session_memory
    from core.fallback.circuit_breaker import get_llm_circuit, get_retriever_circuit

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

    log.info("Shutdown complete")


# Create FastAPI application
app = FastAPI(
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
# invalid and insecure combination per the CORS spec (browsers reject it, and
# it signals a credential leak if any auth is ever added). Origins are now
# driven by the ``ALLOWED_ORIGINS`` env var (comma-separated). When unset, a
# safe local-dev default is used; production deployments MUST set it
# explicitly.
_default_origins = "http://localhost:5173,http://127.0.0.1:5173"
_allowed_origins = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", _default_origins).split(",")
    if o.strip()
]
# ``allow_credentials`` is only meaningful with a concrete origin list (never
# with "*"); keep it on so cookies/auth headers work in production once set.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Custom middleware
app.add_middleware(TracingMiddleware)
app.add_middleware(ErrorHandlerMiddleware)

# Include routers
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(documents.router, prefix="/api/documents", tags=["Documents"])
app.include_router(sessions.router, prefix="/api/sessions", tags=["Sessions"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(feedback.router, prefix="/api/feedback", tags=["Feedback"])
app.include_router(retrieval.router, prefix="/api/retrieval", tags=["Retrieval"])

from core.tracing import instrument_fastapi
instrument_fastapi(app)


# Health check endpoint
@app.get("/health", tags=["Health"])
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
        }
    }


# API information endpoint
@app.get("/api", tags=["Root"])
async def api_info():
    """Return API information."""
    return {
        "name": "Enterprise RAG Platform",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }


# Serve the production frontend when `npm run build` has created web/dist.
WEB_DIST_DIR = Path(
    os.getenv("WEB_DIST_DIR", Path(__file__).resolve().parents[1] / "web" / "dist")
).resolve()
WEB_INDEX = WEB_DIST_DIR / "index.html"

if WEB_INDEX.is_file():
    assets_dir = WEB_DIST_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def frontend(full_path: str):
        """Serve static files and fall back to the Vue SPA entry point."""
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")
        requested = (WEB_DIST_DIR / full_path).resolve()
        if requested.is_relative_to(WEB_DIST_DIR) and requested.is_file():
            return FileResponse(requested)
        return FileResponse(WEB_INDEX)
else:
    @app.get("/", tags=["Root"])
    async def root():
        """Return API information when the frontend has not been built."""
        return await api_info()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
