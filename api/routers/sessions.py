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
    title: str = ""
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
    session_memory = Depends(get_session_memory),
):
    """List all active sessions."""
    try:
        sessions, total = await session_memory.list_sessions(skip, limit)
        return SessionListResponse(
            sessions=[
                SessionInfo(
                    session_id=s["session_id"],
                    message_count=s.get("message_count", 0),
                    title=s.get("title", ""),
                    created_at=s.get("created_at"),
                    last_active=s.get("last_active"),
                )
                for s in sessions
            ],
            total=total,
        )
    except Exception as e:
        log.error(f"Failed to list sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
