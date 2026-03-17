"""
Sessions Router for Enterprise RAG Platform

Handles session management endpoints.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from utils.log_utils import log

router = APIRouter()


# =============================================================================
# Models
# =============================================================================

class SessionInfo(BaseModel):
    """Session information model."""
    session_id: str
    message_count: int
    ttl_seconds: int
    created_at: Optional[float] = None
    last_active: Optional[float] = None


class SessionListResponse(BaseModel):
    """Session list response."""
    sessions: List[SessionInfo]
    total: int


class SessionCreateResponse(BaseModel):
    """Session creation response."""
    session_id: str
    message: str


# =============================================================================
# Dependencies
# =============================================================================

async def get_session_memory():
    """Get session memory instance."""
    from core.memory.redis_memory import get_session_memory
    return get_session_memory()


# =============================================================================
# Endpoints
# =============================================================================

@router.post("", response_model=SessionCreateResponse)
async def create_session():
    """Create a new session."""
    import uuid
    session_id = str(uuid.uuid4())

    return SessionCreateResponse(
        session_id=session_id,
        message="Session created successfully",
    )


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    skip: int = 0,
    limit: int = 20,
):
    """
    List all active sessions.

    Note: This is a placeholder. In production, use Redis SCAN
    or maintain a session registry.
    """
    # TODO: Implement actual session listing with Redis
    return SessionListResponse(
        sessions=[],
        total=0,
    )


@router.get("/{session_id}", response_model=SessionInfo)
async def get_session(
    session_id: str,
    session_memory = Depends(get_session_memory),
):
    """Get session details."""
    try:
        info = await session_memory.get_session_info(session_id)

        if not info.get("exists", False):
            raise HTTPException(status_code=404, detail="Session not found")

        return SessionInfo(
            session_id=session_id,
            message_count=info.get("message_count", 0),
            ttl_seconds=info.get("ttl_seconds", 0),
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to get session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    session_memory = Depends(get_session_memory),
):
    """Delete a session and its history."""
    try:
        await session_memory.clear_session(session_id)
        return {"status": "success", "message": f"Session {session_id} deleted"}

    except Exception as e:
        log.error(f"Failed to delete session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{session_id}/extend")
async def extend_session(
    session_id: str,
    session_memory = Depends(get_session_memory),
):
    """Extend session TTL."""
    try:
        await session_memory.extend_session(session_id)
        return {"status": "success", "message": f"Session {session_id} extended"}

    except Exception as e:
        log.error(f"Failed to extend session: {e}")
        raise HTTPException(status_code=500, detail=str(e))