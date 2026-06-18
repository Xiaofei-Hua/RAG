"""
Human-in-the-loop interrupt + declarative agent workflow DSL (P2.7).

Two lightweight capabilities:

  - **HITL gate**: a skill can flag that human approval is required before
    proceeding (e.g. for high-risk remediation actions). The gate writes a
    pending-approval record; an admin endpoint or CLI resolves it to
    approve/reject. This is a cooperative gate (the graph checks it) rather
    than a hard LangGraph ``interrupt_before``, to stay compatible with the
    existing fixed topology.

  - **Declarative workflow DSL**: a YAML/JSON spec that maps intents to
    execution plans (which skills run, in what order, with what config),
    loaded from ``data/workflows/*.yaml``. This lets operators define agent
    behaviour per use-case without editing the graph code.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.log_utils import log

__all__ = [
    "ApprovalRequest",
    "HITLGate",
    "get_hitl_gate",
    "WorkflowSpec",
    "load_workflow",
    "resolve_workflow_for_intent",
]


# ---------------------------------------------------------------------------
# HITL approval gate
# ---------------------------------------------------------------------------

@dataclass
class ApprovalRequest:
    """A pending human-approval request."""
    id: str
    session_id: str
    action: str          # e.g. "execute_remediation"
    detail: str = ""
    status: str = "pending"  # pending | approved | rejected
    created_at: float = field(default_factory=time.time)
    resolved_at: Optional[float] = None
    resolver: str = ""


class HITLGate:
    """SQLite-backed human-approval queue."""

    def __init__(self, db_path: str = "./data/hitl_approvals.db"):
        self._db_path = db_path
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                action TEXT,
                detail TEXT,
                status TEXT DEFAULT 'pending',
                created_at REAL,
                resolved_at REAL,
                resolver TEXT
            )
            """
        )
        self._conn.commit()

    def request_approval(
        self, session_id: str, action: str, detail: str = ""
    ) -> ApprovalRequest:
        """Create a pending approval request and return it."""
        req = ApprovalRequest(
            id=uuid.uuid4().hex[:12],
            session_id=session_id,
            action=action,
            detail=detail,
        )
        with self._lock:
            self._conn.execute(
                "INSERT INTO approvals (id, session_id, action, detail, status, created_at) "
                "VALUES (?, ?, ?, ?, 'pending', ?)",
                (req.id, req.session_id, req.action, req.detail, req.created_at),
            )
            self._conn.commit()
        log.info(f"HITL: approval requested {req.id} ({action})")
        return req

    def is_approved(self, request_id: str) -> bool:
        """True if the request was approved (False if pending or rejected)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT status FROM approvals WHERE id = ?", (request_id,)
            ).fetchone()
        return bool(row and row["status"] == "approved")

    def resolve(self, request_id: str, approved: bool, resolver: str = "admin") -> bool:
        """Resolve a pending request. Returns True if the row was updated."""
        status = "approved" if approved else "rejected"
        with self._lock:
            cur = self._conn.execute(
                "UPDATE approvals SET status = ?, resolved_at = ?, resolver = ? "
                "WHERE id = ? AND status = 'pending'",
                (status, time.time(), resolver, request_id),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def list_pending(self, limit: int = 50) -> List[ApprovalRequest]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM approvals WHERE status = 'pending' "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_req(r) for r in rows]

    @staticmethod
    def _row_to_req(row) -> ApprovalRequest:
        return ApprovalRequest(
            id=row["id"],
            session_id=row["session_id"],
            action=row["action"],
            detail=row["detail"] or "",
            status=row["status"],
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
            resolver=row["resolver"] or "",
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()


_gate: Optional[HITLGate] = None
_gate_lock = threading.Lock()


def get_hitl_gate() -> HITLGate:
    global _gate
    if _gate is None:
        with _gate_lock:
            if _gate is None:
                _gate = HITLGate()
    return _gate


# ---------------------------------------------------------------------------
# Declarative workflow DSL
# ---------------------------------------------------------------------------

@dataclass
class WorkflowSpec:
    """A declarative agent workflow: intent -> plan mapping."""
    name: str = ""
    description: str = ""
    # intent -> ordered list of skill names to execute
    plans: Dict[str, List[str]] = field(default_factory=dict)
    # per-skill config overrides
    skill_config: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    source: str = "file"


def load_workflow(path: str) -> Optional[WorkflowSpec]:
    """Load a workflow spec from YAML/JSON."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        import yaml

        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            log.warning(f"Failed to load workflow {path}: {e}")
            return None
    if not isinstance(data, dict):
        return None
    return WorkflowSpec(
        name=data.get("name", p.stem),
        description=data.get("description", ""),
        plans=data.get("plans", {}),
        skill_config=data.get("skill_config", {}),
        source=str(path),
    )


def _workflow_dir() -> Path:
    return Path(os.getenv("WORKFLOW_DIR", "data/workflows"))


def resolve_workflow_for_intent(
    intent: str, default_plan: Optional[List[str]] = None
) -> List[str]:
    """
    Resolve the ordered skill list for a given intent.

    Looks up ``data/workflows/*.yaml`` for a plan matching the intent; falls
    back to ``default_plan`` (the hardcoded graph order) when no spec exists.
    """
    wf_dir = _workflow_dir()
    if wf_dir.exists():
        for spec_file in sorted(wf_dir.glob("*.yaml")):
            spec = load_workflow(str(spec_file))
            if spec and intent in spec.plans:
                return spec.plans[intent]
    return default_plan or ["agent", "retrieve", "grade", "generate"]
