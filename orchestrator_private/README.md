# Private Orchestrator Integration Staging

This directory stores the accepted local hardening bundle for Patch 1A + Patch 2 in a private GitHub staging branch.

Status:
- Patch 1A accepted: ownership, lease, heartbeat, hard TTL, sole sweeper authority, process-exclusive lock.
- Patch 2 accepted: completion.claimed -> verifying -> succeeded / verification_rejected with existence, size, SHA-256, contract hash, and verification TTL.
- Local verification rerun before staging: 27 tests passed with `PYTHONPATH=. pytest -q tests/test_lease_chaos.py tests/test_completion_verification.py`.
- Not deployed.
- Single gateway process per JOBS_DIR is a hard operational constraint.
- `succeeded` is a point-in-time artifact verification, not an immutability guarantee.

The accepted integration bundle is stored as `orchestrator_patch2_complete.zip` with SHA-256 `6e104361feedefa98c5b75110f1204a7306575d232ae776b292306bb5ab12ede`.

This is temporary private staging inside `Zweeback/dortmundgamemap` because the connected GitHub toolset cannot create a new repository. Do not treat this as the final canonical repository and do not merge it into the game project without an explicit migration decision.
