# Agent review loop scaffold

Issue: #10

This branch exists only to give GitHub Copilot Cloud Agent a dedicated PR workspace for the review-gate infrastructure.

Target state machine:

`DATA_READY -> RUNTIME_UPDATED -> CI_GREEN -> GEMINI_REVIEWED -> GROK_REVIEWED -> SUPERVISOR_GATE -> MERGE_READY | REWORK`

Constraints:
- No runtime or geodata implementation changes.
- Gemini gate: architecture/correctness review only.
- Grok gate: adversarial/runtime-risk review only.
- Reviewers may post comments/status only; no auto-merge and no code mutation.
- Prefer GitHub Agentic Workflows / `gh aw` when repository prerequisites support them.
- Document exact engines/models actually available; do not assume model access.
- If blocked, report the exact prerequisite and smallest setup step.

Copilot should replace/extend this scaffold with the minimal tested infrastructure and compiled workflow artifacts where required.
