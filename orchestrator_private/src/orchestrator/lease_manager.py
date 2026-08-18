from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from orchestrator.state_machine import JobStateMachine, OWNED_STATES


class LeaseError(RuntimeError):
    pass


def utcnow_dt() -> datetime:
    return datetime.now(timezone.utc)


def utcnow() -> str:
    return utcnow_dt().isoformat().replace("+00:00", "Z")


def parse_utc(value: str | None) -> datetime | None:
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


@dataclass(frozen=True)
class LeaseConfig:
    default_lease_seconds: int = 600
    heartbeat_timeout_seconds: int = 120
    max_active_state_seconds: int = 1800


class LeaseManager:
    """Persistent ownership and expiry enforcement for bridge jobs.

    The manager is transport-agnostic. It can sit under today's FastAPI bridge
    and later under JetStream without changing lease semantics.
    """

    def __init__(
        self,
        jobs_dir: str | os.PathLike[str],
        *,
        token_secret: str,
        supervisor_instance_id: str,
        config: LeaseConfig | None = None,
    ) -> None:
        if not token_secret:
            raise ValueError("token_secret must be non-empty")
        self.jobs_dir = Path(jobs_dir)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.token_secret = token_secret.encode("utf-8")
        self.supervisor_instance_id = supervisor_instance_id
        self.local_owner = f"gateway.local:{supervisor_instance_id}"
        self.config = config or LeaseConfig()
        self._lock = threading.RLock()

    def state_path(self, job_id: str) -> Path:
        return self.jobs_dir / job_id / "job_state.json"

    def load(self, job_id: str) -> dict[str, Any]:
        path = self.state_path(job_id)
        if not path.exists():
            raise LeaseError(f"job not found: {job_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def create_claimed(
        self,
        job_record: dict[str, Any],
        *,
        owner: str,
        worker_type: str,
        lease_seconds: int | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        job_id = str(job_record["job_id"])
        path = self.state_path(job_id)
        with self._lock:
            if path.exists():
                raise LeaseError(f"job already exists: {job_id}")
            record = dict(job_record)
            record.setdefault("current_state", record.get("state", "accepted"))
            record.setdefault("state_entered_at", utcnow())
            before: dict[str, Any] = {}
            after = self._apply_fresh_claim(
                record,
                owner=owner,
                worker_type=worker_type,
                lease_seconds=lease_seconds,
            )
            _atomic_json_write(path, after)
        return after, self._event("lease.claimed", job_id, before, after)

    def claim(
        self,
        job_id: str,
        *,
        owner: str,
        worker_type: str,
        lease_seconds: int | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        with self._lock:
            before = self.load(job_id)
            state = before.get("current_state", before.get("state"))
            if state in {"succeeded", "completed", "cancelled"}:
                raise LeaseError(f"terminal job cannot be claimed: {state}")

            existing_expiry = parse_utc(before.get("lease_expires_at"))
            existing_owner = before.get("owner")
            now = utcnow_dt()
            if state in OWNED_STATES and existing_owner and existing_expiry and existing_expiry > now:
                raise LeaseError(f"job already has an active lease owned by {existing_owner}")

            after = self._apply_fresh_claim(
                dict(before),
                owner=owner,
                worker_type=worker_type,
                lease_seconds=lease_seconds,
            )
            _atomic_json_write(self.state_path(job_id), after)

            # Reclaiming an inactive recoverable job is atomic from the caller's
            # perspective: once a fresh lease is issued, the state becomes
            # retrying so heartbeat/extend are immediately valid.
            if state in {"orphaned", "deferred", "failed", "verification_rejected"}:
                sm = JobStateMachine(job_id, jobs_root=self.jobs_dir)
                sm.transition_to(
                    "retrying",
                    reason=f"lease_reclaimed_from_{state}",
                    owner=owner,
                    lease_id=after["lease_id"],
                )
                after = self.load(job_id)
        return after, self._event("lease.claimed", job_id, before, after)

    def heartbeat(self, job_id: str, *, owner: str, lease_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        with self._lock:
            before = self.validate(job_id, owner=owner, lease_id=lease_id)
            after = dict(before)
            after["last_heartbeat_at"] = utcnow()
            after["updated_at"] = after["last_heartbeat_at"]
            _atomic_json_write(self.state_path(job_id), after)
        return after, self._event("agent.heartbeat", job_id, before, after)

    def extend(self, job_id: str, *, owner: str, lease_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        with self._lock:
            before = self.validate(job_id, owner=owner, lease_id=lease_id)
            after = dict(before)
            lease_seconds = int(after.get("lease_seconds") or self.config.default_lease_seconds)
            now = utcnow_dt()
            after["lease_generation"] = int(after.get("lease_generation", 0)) + 1
            after["lease_id"] = f"lease_{uuid.uuid4().hex}"
            after["lease_expires_at"] = (now + timedelta(seconds=lease_seconds)).isoformat().replace("+00:00", "Z")
            after["last_heartbeat_at"] = now.isoformat().replace("+00:00", "Z")
            after["updated_at"] = after["last_heartbeat_at"]
            _atomic_json_write(self.state_path(job_id), after)
        return after, self._event("lease.extended", job_id, before, after)

    def validate(self, job_id: str, *, owner: str, lease_id: str) -> dict[str, Any]:
        record = self.load(job_id)
        state = record.get("current_state", record.get("state"))
        if state not in OWNED_STATES:
            raise LeaseError(f"job is not in a mutable owned state: {state}")
        if record.get("owner") != owner or record.get("lease_id") != lease_id:
            raise LeaseError("stale or foreign lease")
        expires_at = parse_utc(record.get("lease_expires_at"))
        if expires_at is None or expires_at <= utcnow_dt():
            raise LeaseError("lease expired")
        return record

    def issue_lease_token(self, job_id: str, *, owner: str, lease_id: str, generation: int) -> str:
        message = f"{job_id}|{owner}|{lease_id}|{generation}".encode("utf-8")
        return hmac.new(self.token_secret, message, hashlib.sha256).hexdigest()

    def verify_lease_token(
        self,
        token: str,
        *,
        job_id: str,
        owner: str,
        lease_id: str,
        generation: int,
    ) -> bool:
        expected = self.issue_lease_token(
            job_id,
            owner=owner,
            lease_id=lease_id,
            generation=generation,
        )
        return hmac.compare_digest(token, expected)

    def sweep_once(self) -> list[dict[str, Any]]:
        """Classify every stale active job. This is the sole orphan writer."""
        events: list[dict[str, Any]] = []
        with self._lock:
            for path in self.jobs_dir.glob("*/job_state.json"):
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                state = record.get("current_state", record.get("state"))
                if state not in OWNED_STATES:
                    continue
                reason = self._orphan_reason(record)
                if not reason:
                    continue
                events.extend(self._orphan(path.parent.name, reason=reason))
        return events

    def _orphan_reason(self, record: dict[str, Any]) -> str | None:
        """Return the first violated invariant deterministically.

        Structural ownership faults take precedence over clocks. For time-based
        guards, the earliest violated deadline wins. This makes lease expiry,
        heartbeat timeout, and active-state TTL independent hard ceilings rather
        than an ambiguous check order. A valid lease never overrides the state TTL.
        """
        owner = record.get("owner")
        lease_id = record.get("lease_id")
        expires_at = parse_utc(record.get("lease_expires_at"))
        heartbeat_at = parse_utc(record.get("last_heartbeat_at"))
        state_entered_at = parse_utc(record.get("state_entered_at")) or parse_utc(record.get("updated_at"))
        now = utcnow_dt()

        if not owner or not lease_id or expires_at is None:
            return "missing_lease_metadata"
        if owner.startswith("gateway.local:") and owner != self.local_owner:
            return "stale_process_owner"
        if heartbeat_at is None:
            return "heartbeat_missing"

        max_active = int(record.get("max_active_state_seconds") or self.config.max_active_state_seconds)
        deadlines: list[tuple[datetime, int, str]] = [
            (expires_at, 0, "lease_expired"),
            (heartbeat_at + timedelta(seconds=self.config.heartbeat_timeout_seconds), 1, "heartbeat_timeout"),
        ]
        if state_entered_at is not None:
            deadlines.append(
                (state_entered_at + timedelta(seconds=max_active), 2, "state_ttl_exceeded")
            )

        violated = [item for item in deadlines if item[0] <= now]
        if not violated:
            return None
        violated.sort(key=lambda item: (item[0], item[1]))
        return violated[0][2]

    def _orphan(self, job_id: str, *, reason: str) -> list[dict[str, Any]]:
        before = self.load(job_id)
        state_before = before.get("current_state", before.get("state"))
        lease_before = before.get("lease_id")
        owner_before = before.get("owner")

        events: list[dict[str, Any]] = []
        if reason == "lease_expired":
            events.append(self._event("lease.expired", job_id, before, before, reason=reason))

        sm = JobStateMachine(job_id, jobs_root=self.jobs_dir)
        sm.transition_to("orphaned", reason=reason, authority="sweeper")
        after = self.load(job_id)
        orphaned_at = utcnow()
        after["orphaned_at"] = orphaned_at
        after["orphaned_reason"] = reason
        after["orphaned_from_state"] = state_before
        after["previous_owner"] = owner_before
        after["previous_lease_id"] = lease_before
        after["owner"] = None
        after["lease_id"] = None
        after["lease_expires_at"] = None
        after["last_heartbeat_at"] = None
        after["updated_at"] = orphaned_at
        _atomic_json_write(self.state_path(job_id), after)
        events.append(self._event("agent.orphaned", job_id, before, after, reason=reason))
        return events

    def _apply_fresh_claim(
        self,
        record: dict[str, Any],
        *,
        owner: str,
        worker_type: str,
        lease_seconds: int | None,
    ) -> dict[str, Any]:
        seconds = int(lease_seconds or self.config.default_lease_seconds)
        if seconds <= 0:
            raise LeaseError("lease_seconds must be positive")
        now = utcnow_dt()
        record["owner"] = owner
        record["worker_type"] = worker_type
        record["lease_seconds"] = seconds
        record["lease_generation"] = int(record.get("lease_generation", 0)) + 1
        record["lease_id"] = f"lease_{uuid.uuid4().hex}"
        record["lease_expires_at"] = (now + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")
        record["last_heartbeat_at"] = now.isoformat().replace("+00:00", "Z")
        record["max_active_state_seconds"] = int(
            record.get("max_active_state_seconds") or self.config.max_active_state_seconds
        )
        record["updated_at"] = record["last_heartbeat_at"]
        record.setdefault("state_entered_at", record["last_heartbeat_at"])
        return record

    @staticmethod
    def _event(
        event_type: str,
        job_id: str,
        before: dict[str, Any],
        after: dict[str, Any],
        *,
        reason: str | None = None,
    ) -> dict[str, Any]:
        event: dict[str, Any] = {
            "type": event_type,
            "job_id": job_id,
            "before": before,
            "after": after,
            "time_utc": utcnow(),
        }
        if reason:
            event["reason"] = reason
        return event
