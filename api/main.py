"""
FastAPI Application for Enterprise RAG Platform

Provides REST API and WebSocket endpoints for:
- Chat/conversation
- Document management
- Session management
- System monitoring
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import hashlib
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

    log.info("Startup complete!")

    yield

    # Shutdown
    log.info("Shutting down...")

    # Close connections
    from core.memory.redis_memory import get_session_memory
    memory = get_session_memory()
    await memory.close()

    from agent.harness import get_agent_harness
    get_agent_harness().close()

    log.info("Shutdown complete")


# Create FastAPI application
app = FastAPI(
    title="Enterprise RAG Platform",
    description="企业级RAG智能平台API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
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


# Root endpoint
@app.get("/", tags=["Root"])
async def root():
    """Root endpoint with API information."""
    return {
        "name": "Enterprise RAG Platform",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
