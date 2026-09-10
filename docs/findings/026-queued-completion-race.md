# Recheck completion when a queued worker starts

September 9, 2026 (Pacific time). Operational tracking: [issue #6](https://github.com/dorkitude/agent-language-choice/issues/6).

Source context: finish all five models × 17 targets × 100 stages in the existing records, then build the standalone dashboard.

The shared runner (PID 20725) created `20260910T041628Z_codex_gpt-5.6-terra_typescript-nextjs` after the existing Next.js run had already passed all 100 stages. The matrix filters completed cells when it constructs its queue; a second runner can complete a queued cell before its worker starts. The worker previously treated the absence of a resumable run as permission to start another run.

`run_lifecycle_one` now checks `skip_existing` after acquiring the cell lock, before creating or resuming artifacts. This prevents a completed queued cell from being restarted by freshly loaded runners. All eight harness regression tests pass, including a completed-at-worker-start case.

PID 20725 still has the previous code loaded. Its existing duplicate run and original successful evidence remain preserved; handling that duplicate and reconciling its old authentication classifications remain outstanding. This change does not repair generated implementations or alter benchmark results.
