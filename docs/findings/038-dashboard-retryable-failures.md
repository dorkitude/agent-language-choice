# Dashboard retryable failure accounting

Source decision: run all 85 model/target cells and then deliver a standalone Tokyo Night Chart.js dashboard with embedded JSON. Tracking: https://github.com/dorkitude/agent-language-choice/issues/6.

The dashboard previously counted every SQLite `fail` row as terminal, including interrupted attempts whose corrected infrastructure classification leaves retries available. Before treating a stored failure as terminal, the builder now verifies its result artifact matches the SQLite SHA-256 and applies the current harness retry and status logic. Retryable failures display as blocked; missing or changed failure artifacts display as partial pending reconciliation. The original stored status and historical attempts remain available in embedded JSON. No database rows or run artifacts are modified.

Validation: two dashboard unit tests pass, covering pending retries, terminal failures, changed/missing artifacts, latest-attempt selection, 85 planned cells, operator notes, and unknown costs. The refreshed preview contains 85 cells with 56 unresolved. This count uses latest attempts, including duplicates awaiting reconciliation; it does not replace the experiment's original completed-run evidence.
