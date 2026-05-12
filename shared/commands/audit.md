---
description: Audit this repo's structural integrity via the agents-harness-auditor sub-agent
---

Delegate to the `agents-harness-auditor` sub-agent.

If `$ARGUMENTS` is provided, pass it as a scope hint (e.g. `render scripts only`, `skills only`, `skip git status`). If empty, let the auditor run all standard checks.

Surface the auditor's output verbatim — including its top-line `PASS` / `WARN` / `FAIL` verdict and any fix commands it recommends. The user reads the report and decides what to act on.

If the sub-agent isn't available in the current tool, fall back to performing the audit yourself, following `shared/subagents/agents-harness-auditor.md`.

$ARGUMENTS
