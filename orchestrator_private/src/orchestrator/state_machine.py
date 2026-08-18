from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

logger = logging.getLogger("anti-gravity-bridge.state_machine")

OWNED_STATES: Set[str] = {"queued", "accepted", "validating", "ready", "running", "retrying"}
TERMINAL_STATES: Set[str] = {"succeeded", "failed", "cancelled", "orphaned", "verification_rejected"}
VERIFIER_FINAL_STATES: Set[str] = {"succeeded", "verification_rejected"}

ALLOWED_TRANSITIONS: Dict[str, Set[str]] = {
    "queued": {"validating", "cancelled", "orphaned"},
    "accepted": {"validating", "cancelled", "orphaned"},
    "validating": {"ready", "failed", "deferred", "cancelled", "orphaned"},
    "ready": {"running", "cancelled", "orphaned"},
    "running": {"verifying", "failed", "cancelled", "orphaned"},
    "deferred": {"retrying", "failed", "cancelled"},
    "failed": {"retrying", "cancelled"},
    "retrying": {"running", "deferred", "failed", "cancelled", "orphaned"},
    "orphaned": {"retrying", "failed", "cancelled"},
    "verifying": {"succeeded", "verification_rejected"},
    "verification_rejected": {"retrying", "failed", "cancelled"},
    "succeeded": set(),
    "cancelled": set(),
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


class JobStateMachine:
    """Strict lifecycle transitions for persisted bridge jobs.

    ``orphaned`` is deliberately special: the lease sweeper is the only
    authority permitted to write that state. Worker-driven transitions in
    owned states must present the current owner + lease_id from disk.
    """

    def __init__(
        self,
        job_id: str,
        initial_state: str = "queued",
        jobs_root: str | os.PathLike[str] | None = None,
    ) -> None:
        self.job_id = job_id
        self.state = initial_state
        self.history: List[Dict[str, Any]] = []

        if jobs_root is None:
            base_dir = Path(__file__).resolve().parent.parent
            jobs_root = base_dir / "artifacts" / "jobs"
        self.job_dir = Path(jobs_root) / job_id
        self.job_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.job_dir / "job_state.json"

        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                self.state = data.get("current_state", data.get("state", initial_state))
                self.history = data.get("history", [])
                if not self.history:
                    self._record_transition(self.state, reason="initial_state_recovered")
            except Exception:
                self._record_transition(initial_state, reason="state_recovery_failed")
        else:
            self._record_transition(initial_state, reason="initial_state")

    def transition_to(
        self,
        new_state: str,
        reason: str | None = None,
        *,
        authority: str = "worker",
        owner: str | None = None,
        lease_id: str | None = None,
    ) -> None:
        if new_state not in ALLOWED_TRANSITIONS:
            raise ValueError(f"Invalid state: {new_state}")

        allowed = ALLOWED_TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            raise ValueError(f"Illegal state transition from '{self.state}' to '{new_state}'")

        if new_state == "orphaned" and authority != "sweeper":
            raise PermissionError("Only the lease sweeper may transition a job to 'orphaned'")

        if new_state in VERIFIER_FINAL_STATES and authority != "verifier":
            raise PermissionError("Only the artifact verifier may finalize completion")

        if authority not in {"sweeper", "verifier"} and (self.state in OWNED_STATES or new_state in OWNED_STATES):
            self._assert_current_lease(owner=owner, lease_id=lease_id)

        old_state = self.state
        self.state = new_state
        self._record_transition(new_state, reason)
        logger.info(
            "Job %s transitioned: %s -> %s (authority=%s reason=%s)",
            self.job_id,
            old_state,
            new_state,
            authority,
            reason,
        )

    def _assert_current_lease(self, owner: str | None, lease_id: str | None) -> None:
        if not self.state_file.exists():
            raise PermissionError("Cannot mutate an owned state without persisted lease metadata")
        data = json.loads(self.state_file.read_text(encoding="utf-8"))
        current_owner = data.get("owner")
        current_lease = data.get("lease_id")
        expires_at = _parse_utc(data.get("lease_expires_at"))
        now = datetime.now(timezone.utc)

        if not owner or not lease_id:
            raise PermissionError("owner and lease_id are required for owned-state mutations")
        if current_owner != owner or current_lease != lease_id:
            raise PermissionError("stale or foreign lease presented for job mutation")
        if expires_at is None or expires_at <= now:
            raise PermissionError("lease expired before job mutation")

    def _record_transition(self, state: str, reason: str | None = None) -> None:
        timestamp = _utcnow()
        entry = {"state": state, "timestamp": timestamp, "reason": reason}
        self.history.append(entry)
        self._persist(state_entered_at=timestamp)

    def _persist(self, *, state_entered_at: str) -> None:
        existing: dict[str, Any] = {}
        if self.state_file.exists():
            try:
                existing = json.loads(self.state_file.read_text(encoding="utf-8"))
            except Exception:
                existing = {}

        existing["job_id"] = self.job_id
        existing["current_state"] = self.state
        existing["state"] = self.state
        existing["history"] = self.history
        existing["state_entered_at"] = state_entered_at
        existing["updated_at"] = _utcnow()
        _atomic_json_write(self.state_file, existing)
