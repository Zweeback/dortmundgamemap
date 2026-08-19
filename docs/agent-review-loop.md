# Agent review loop

Issue: #10

## Overview

Two read-only AI review gates, orchestrated by a state-machine workflow.

```
DATA_READY → RUNTIME_UPDATED → CI_GREEN
  → GEMINI_REVIEWED → GROK_REVIEWED
  → SUPERVISOR_GATE → MERGE_READY | REWORK
```

## Workflow files

| File | Purpose |
|---|---|
| `.github/workflows/review-loop.yml` | Orchestrator — entry point, state machine |
| `.github/workflows/gemini-review.yml` | Gate 2: Gemini architecture/correctness review |
| `.github/workflows/grok-review.yml` | Gate 3: Grok adversarial/runtime-risk review |

## How to trigger

### Manual (safe test trigger)

```
Actions → "Review loop orchestrator" → Run workflow → pr_number: <11 or this PR>
```

Or via the label trigger: add the label **`review-loop`** to any open PR.

### Programmatic

The orchestrator can be called from other workflows via `workflow_call` on any of the three files.

## Models used

| Gate | Model ID | Endpoint |
|---|---|---|
| Gemini architecture review | `google/gemini-2.5-pro` | `https://models.inference.ai.azure.com/chat/completions` |
| Grok adversarial review | `xai/grok-3` | `https://models.inference.ai.azure.com/chat/completions` |

Authentication: built-in `GITHUB_TOKEN` with `models: read` permission — no external secrets needed.

## Prerequisites and blockers

### GitHub Models (required)

GitHub Models must be enabled for this repository before the Gemini/Grok gates can call the model API.

**Setup path:**
`Repository Settings → Copilot → GitHub Models → Enable`

Without this, the model call steps will fail with HTTP 403 or 404 and print an explicit error message:

```
::error::GitHub Models returned HTTP 403. Ensure GitHub Models is enabled for this
repository (Settings > Copilot > GitHub Models).
```

### GitHub Agentic Workflows (`gh aw`)

`gh aw` is not yet GA on GitHub-hosted runners (status as of 2026-08). This infrastructure uses standard `workflow_call` composition, which provides equivalent orchestration capability. The implementation will be migrated to `gh aw` once it reaches GA.

### Permissions required

| Permission | Scope | Why |
|---|---|---|
| `contents: read` | Repository | Checkout |
| `pull-requests: write` | Repository | Post review comments and labels |
| `models: read` | Repository | Call GitHub Models API |
| `issues: write` | Repository | Create labels (first run only) |

All permissions are scoped to the minimum required. No secrets beyond `GITHUB_TOKEN` are used. No auto-merge, no code mutation.

## Constraints

- No runtime or geodata implementation changes.
- Gemini gate: architecture/correctness review only.
- Grok gate: adversarial/runtime-risk review only.
- Reviewers post comments/status only; no merge, no code mutation.
- Human must merge after `MERGE_READY` label is set.
