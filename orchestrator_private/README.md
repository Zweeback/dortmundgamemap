# Private Orchestrator Integration Staging

This directory stages the accepted Patch 1A + Patch 2 hardening in a private GitHub-controlled branch for independent CI verification.

Status:
- Patch 1A accepted: ownership, lease, heartbeat, hard TTL, sole sweeper authority, process-exclusive lock.
- Patch 2 accepted: `completion.claimed -> verifying -> succeeded | verification_rejected` with existence, size, SHA-256, contract hash, and verification TTL.
- Local verification before staging: 27 tests passed.
- GitHub Actions verification on the private staging branch: 27 tests passed.
- Not deployed.
- Single gateway process per `JOBS_DIR` is a hard operational constraint.
- `succeeded` is a point-in-time artifact verification, not an immutability guarantee.

The original binary ZIP staging attempt was removed after GitHub-side transfer produced a corrupt archive. The accepted source and chaos tests are now staged as UTF-8 source parts under `orchestrator_private/src/`; CI assembles the large `main.py` and the two test files before compilation and testing. This split is a connector-safe staging format only and should be normalized back to ordinary files when migrated to the dedicated canonical repository.

This is temporary private staging inside `Zweeback/dortmundgamemap`. Do not merge this draft PR into the game project. A dedicated private canonical orchestrator repository is still required before deployment.
