from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from orchestrator.state_machine import JobStateMachine


class VerificationError(RuntimeError):
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


def canonical_json_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


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
class VerificationConfig:
    verification_ttl_seconds: int = 120


class ArtifactVerifier:
    """Independent completion verifier for persisted bridge jobs.

    Workers may only claim completion. This verifier is the sole authority that
    can promote ``verifying`` to ``succeeded`` or reject it. All artifact bytes
    are re-read from disk; worker-supplied size/hash values are never trusted.
    """

    def __init__(
        self,
        base_dir: str | os.PathLike[str],
        jobs_dir: str | os.PathLike[str],
        *,
        config: VerificationConfig | None = None,
    ) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.jobs_dir = Path(jobs_dir).resolve()
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.config = config or VerificationConfig()
        if self.config.verification_ttl_seconds <= 0:
            raise ValueError("verification_ttl_seconds must be positive")
        self._lock = threading.RLock()

    def state_path(self, job_id: str) -> Path:
        return self.jobs_dir / job_id / "job_state.json"

    def load(self, job_id: str) -> dict[str, Any]:
        path = self.state_path(job_id)
        if not path.exists():
            raise VerificationError(f"job not found: {job_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def build_contract(
        self,
        *,
        job_id: str,
        target: str,
        command_type: str,
        constraints: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        constraints = constraints or {}
        supplied = constraints.get("artifact_contract")
        supplied = dict(supplied) if isinstance(supplied, dict) else {}

        allowed_root = supplied.pop("allowed_root", f"artifacts/jobs/{job_id}")
        root_path = self._resolve_under_base(str(allowed_root))
        try:
            relative_root = root_path.relative_to(self.base_dir).as_posix()
        except ValueError as exc:
            raise VerificationError("artifact contract root must remain inside BASE_DIR") from exc

        min_artifacts = int(supplied.pop("min_artifacts", 1))
        if min_artifacts < 0:
            raise VerificationError("min_artifacts cannot be negative")

        suffixes = supplied.pop("required_suffixes", [])
        if suffixes is None:
            suffixes = []
        if not isinstance(suffixes, list) or not all(isinstance(item, str) for item in suffixes):
            raise VerificationError("required_suffixes must be a list of strings")

        return {
            "schema": "artifact.contract.v1",
            "job_id": job_id,
            "target": target,
            "command_type": command_type,
            "allowed_root": relative_root,
            "min_artifacts": min_artifacts,
            "required_suffixes": sorted(set(suffixes)),
            "requirements": supplied,
        }

    def contract_hash(self, contract: dict[str, Any]) -> str:
        return canonical_json_hash(contract)

    def make_claims(self, job_id: str, artifact_refs: Iterable[str]) -> list[dict[str, Any]]:
        claims: list[dict[str, Any]] = []
        for ref in artifact_refs:
            ref = str(ref).replace("\\", "/")
            try:
                path = self._resolve_artifact(job_id, ref, contract=None)
                if not path.exists() or not path.is_file():
                    raise FileNotFoundError(str(path))
                claims.append({
                    "path": ref,
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                })
            except Exception:
                # A worker is still allowed to claim a broken/missing artifact;
                # the verifier, not the claim builder, decides whether completion
                # is accepted. Sentinel values guarantee rejection.
                claims.append({"path": ref, "size_bytes": -1, "sha256": ""})
        return claims

    def begin_completion_claim(
        self,
        job_id: str,
        *,
        owner: str,
        lease_id: str,
        contract_hash: str,
        artifacts: list[dict[str, Any]],
        lease_manager: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        with self._lock:
            lease_manager.validate(job_id, owner=owner, lease_id=lease_id)
            before = self.load(job_id)
            state = before.get("current_state", before.get("state"))
            if state != "running":
                raise VerificationError(f"completion may only be claimed from running, got: {state}")

            self._validate_claim_shape(artifacts)
            sm = JobStateMachine(job_id, jobs_root=self.jobs_dir)
            sm.transition_to(
                "verifying",
                reason="completion_claimed",
                authority="worker",
                owner=owner,
                lease_id=lease_id,
            )

            now = utcnow_dt()
            after = self.load(job_id)
            after["completion_claimed_by"] = owner
            after["completion_claimed_lease_id"] = lease_id
            after["claimed_contract_hash"] = contract_hash
            after["claimed_artifacts"] = artifacts
            after["verification_started_at"] = now.isoformat().replace("+00:00", "Z")
            after["verification_ttl_seconds"] = self.config.verification_ttl_seconds
            after["verification_deadline_at"] = (
                now + timedelta(seconds=self.config.verification_ttl_seconds)
            ).isoformat().replace("+00:00", "Z")
            after["verification_errors"] = []
            after["verification_completed_at"] = None
            after["updated_at"] = after["verification_started_at"]
            _atomic_json_write(self.state_path(job_id), after)

        return after, self._event("completion.claimed", job_id, before, after)

    def verify_once(self, job_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        with self._lock:
            before = self.load(job_id)
            state = before.get("current_state", before.get("state"))
            if state != "verifying":
                raise VerificationError(f"job is not verifying: {state}")

            errors = self._verification_errors(before)
            if errors:
                after = self._reject(job_id, before, errors)
                return after, [self._event("verification.rejected", job_id, before, after)]

            sm = JobStateMachine(job_id, jobs_root=self.jobs_dir)
            sm.transition_to(
                "succeeded",
                reason="artifact_verification_passed",
                authority="verifier",
            )
            after = self.load(job_id)
            after["state"] = "succeeded"
            after["current_state"] = "succeeded"
            after["verification_completed_at"] = utcnow()
            after["verification_errors"] = []
            after["verified_artifacts"] = list(before.get("claimed_artifacts") or [])
            after["updated_at"] = after["verification_completed_at"]
            _atomic_json_write(self.state_path(job_id), after)
            return after, [
                self._event("verification.succeeded", job_id, before, after),
                self._event("job.succeeded", job_id, before, after),
            ]

    def process_pending_once(self) -> list[dict[str, Any]]:
        """Resume/reject every persisted verifying job under the process lock."""
        events: list[dict[str, Any]] = []
        for path in self.jobs_dir.glob("*/job_state.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if record.get("current_state", record.get("state")) != "verifying":
                continue
            try:
                _, emitted = self.verify_once(path.parent.name)
                events.extend(emitted)
            except VerificationError as exc:
                current = self.load(path.parent.name)
                rejected = self._reject(path.parent.name, current, [f"verifier_internal_error:{exc}"])
                events.append(self._event("verification.rejected", path.parent.name, current, rejected))
        return events

    def _verification_errors(self, record: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        now = utcnow_dt()
        deadline = parse_utc(record.get("verification_deadline_at"))
        if deadline is None:
            return ["missing_verification_deadline"]
        if now >= deadline:
            return ["verification_ttl_exceeded"]

        contract = record.get("artifact_contract")
        expected_hash = record.get("expected_artifact_contract_hash")
        claimed_hash = record.get("claimed_contract_hash")
        if not isinstance(contract, dict) or not expected_hash:
            errors.append("missing_expected_artifact_contract")
            return errors
        if self.contract_hash(contract) != expected_hash:
            errors.append("stored_contract_hash_mismatch")
        if claimed_hash != expected_hash:
            errors.append("claimed_contract_hash_mismatch")

        claims = record.get("claimed_artifacts")
        if not isinstance(claims, list):
            errors.append("missing_artifact_claims")
            return errors

        min_artifacts = int(contract.get("min_artifacts", 1))
        if len(claims) < min_artifacts:
            errors.append(f"artifact_count_below_minimum:{len(claims)}<{min_artifacts}")

        seen: set[str] = set()
        suffixes = contract.get("required_suffixes") or []
        for index, claim in enumerate(claims):
            if utcnow_dt() >= deadline:
                errors.append("verification_ttl_exceeded")
                break
            if not isinstance(claim, dict):
                errors.append(f"artifact_claim_invalid:{index}")
                continue
            ref = str(claim.get("path", ""))
            if not ref:
                errors.append(f"artifact_path_missing:{index}")
                continue
            if ref in seen:
                errors.append(f"artifact_duplicate:{ref}")
                continue
            seen.add(ref)
            try:
                path = self._resolve_artifact(str(record["job_id"]), ref, contract=contract)
            except VerificationError as exc:
                errors.append(f"artifact_path_rejected:{ref}:{exc}")
                continue
            if suffixes and path.suffix not in suffixes:
                errors.append(f"artifact_suffix_rejected:{ref}:{path.suffix}")
                continue
            if not path.exists():
                errors.append(f"artifact_missing:{ref}")
                continue
            if not path.is_file():
                errors.append(f"artifact_not_file:{ref}")
                continue
            actual_size = path.stat().st_size
            claimed_size = claim.get("size_bytes")
            if not isinstance(claimed_size, int) or claimed_size != actual_size:
                errors.append(f"artifact_size_mismatch:{ref}:claimed={claimed_size}:actual={actual_size}")
                continue
            claimed_sha = str(claim.get("sha256", ""))
            actual_sha = sha256_file(path)
            if claimed_sha != actual_sha:
                errors.append(f"artifact_sha256_mismatch:{ref}")

        if utcnow_dt() >= deadline and "verification_ttl_exceeded" not in errors:
            errors.append("verification_ttl_exceeded")
        return errors

    def _reject(
        self,
        job_id: str,
        before: dict[str, Any],
        errors: list[str],
    ) -> dict[str, Any]:
        sm = JobStateMachine(job_id, jobs_root=self.jobs_dir)
        if sm.state == "verifying":
            sm.transition_to(
                "verification_rejected",
                reason=";".join(errors),
                authority="verifier",
            )
        after = self.load(job_id)
        after["state"] = "verification_rejected"
        after["current_state"] = "verification_rejected"
        after["verification_errors"] = errors
        after["verification_completed_at"] = utcnow()
        after["error"] = "verification_rejected:" + ";".join(errors)
        after["updated_at"] = after["verification_completed_at"]
        _atomic_json_write(self.state_path(job_id), after)
        return after

    def _validate_claim_shape(self, artifacts: list[dict[str, Any]]) -> None:
        if not isinstance(artifacts, list):
            raise VerificationError("artifacts must be a list")
        for index, claim in enumerate(artifacts):
            if not isinstance(claim, dict):
                raise VerificationError(f"artifact claim {index} must be an object")
            if not isinstance(claim.get("path"), str) or not claim["path"]:
                raise VerificationError(f"artifact claim {index} missing path")
            if not isinstance(claim.get("size_bytes"), int):
                raise VerificationError(f"artifact claim {index} missing integer size_bytes")
            if not isinstance(claim.get("sha256"), str):
                raise VerificationError(f"artifact claim {index} missing sha256")

    def _resolve_under_base(self, value: str) -> Path:
        raw = Path(value)
        candidate = raw if raw.is_absolute() else self.base_dir / raw
        candidate = candidate.resolve()
        try:
            candidate.relative_to(self.base_dir)
        except ValueError as exc:
            raise VerificationError("path escapes BASE_DIR") from exc
        return candidate

    def _resolve_artifact(
        self,
        job_id: str,
        artifact_ref: str,
        *,
        contract: dict[str, Any] | None,
    ) -> Path:
        path = self._resolve_under_base(artifact_ref)
        if contract is None:
            allowed_root = (self.jobs_dir / job_id).resolve()
        else:
            allowed_root = self._resolve_under_base(str(contract.get("allowed_root", f"artifacts/jobs/{job_id}")))
        try:
            path.relative_to(allowed_root)
        except ValueError as exc:
            raise VerificationError("artifact escapes contract allowed_root") from exc
        return path

    @staticmethod
    def _event(
        event_type: str,
        job_id: str,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "type": event_type,
            "job_id": job_id,
            "time_utc": utcnow(),
            "before": before,
            "after": after,
        }
