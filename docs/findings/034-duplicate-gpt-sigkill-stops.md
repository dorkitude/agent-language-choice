# Duplicate GPT runs interrupted by SIGKILL

Source decision: finish all five models × 17 targets × 100 stages in the same records, then build the standalone dashboard. Tracking: https://github.com/dorkitude/agent-language-choice/issues/6.

At approximately 2026-09-10T10:59Z, the older live batch marked two duplicate runs failed. Raw shot inspection contradicts treating these as deterministic experimental failures:

- `20260910T071700Z_codex_gpt-5.6-terra_ruby-rails`: 60 completed stages. Final stage `060-faction-reputation`, shots 87–91, all exited -9 without timeout or evaluation report; shot 92 exited 0 but also had no evaluation report.
- `20260910T085201Z_codex_gpt-5.6-terra_php-stdlib`: 50 completed stages. Final stage `050-spellbook-state`, shots 73–78, all exited -9 without timeout or evaluation report.

The source of SIGKILL is unknown. These are unresolved infrastructure interruptions, not six valid failed evaluations. Preserve original completed runs and duplicate evidence; do not count these stops as new deterministic failures. Current-classifier database reconciliation and duplicate policy remain outstanding. The old batch remained alive and started duplicate Python Django and Python stdlib runs afterward. See [026](026-queued-completion-race.md) for the queued-completion race.
