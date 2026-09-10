# Duplicate GPT runs interrupted by SIGKILL

Source decision: finish all five models × 17 targets × 100 stages in the same records, then build the standalone dashboard. Tracking: https://github.com/dorkitude/agent-language-choice/issues/6.

At approximately 2026-09-10T10:59Z, the older live batch marked two duplicate runs failed. Raw shot inspection contradicts treating these as deterministic experimental failures:

- `20260910T071700Z_codex_gpt-5.6-terra_ruby-rails`: 60 completed stages. Final stage `060-faction-reputation`, shots 87–91, all exited -9 without timeout or evaluation report; shot 92 exited 0 but also had no evaluation report.
- `20260910T085201Z_codex_gpt-5.6-terra_php-stdlib`: 50 completed stages. Final stage `050-spellbook-state`, shots 73–78, all exited -9 without timeout or evaluation report.

The source of SIGKILL is unknown. These are unresolved infrastructure interruptions, not six valid failed evaluations. Preserve original completed runs and duplicate evidence; do not count these stops as new deterministic failures. Current-classifier database reconciliation and duplicate policy remain outstanding. The old batch remained alive and started duplicate Python Django and Python stdlib runs afterward. See [026](026-queued-completion-race.md) for the queued-completion race.

## Classifier reconciliation

At 2026-09-10T11:03:03.667245+00:00, reindexed the stopped duplicates with the current harness under exclusive cell locks. Original result JSON hashes remained unchanged. The live SQLite database will be archived with final results.

- `20260910T071700Z_codex_gpt-5.6-terra_ruby-rails`: fail → fail; 6 infrastructure shots; raw SHA-256 `f1cd11dde5c410526b47d0784d6de6440e52bca0dbe618a7d2d09998e09559f1`.
- `20260910T085201Z_codex_gpt-5.6-terra_php-stdlib`: fail → fail; 5 infrastructure shots; raw SHA-256 `3b788c12ef77ed0fb2a4b20be22bbe2f9c2670feae2e90089e512a9ba2ec42cb`.
- `20260910T103710Z_codex_gpt-5.6-terra_python-flask`: fail → fail; 1 infrastructure shots; raw SHA-256 `aa0566f8a51a45f1bcad45e01ae802b330dabed7a5e8b0ebded7a31bd65d45e8`.

The duplicate Flask run stopped at 8 completed stages; its final `dm-tools` shots 15–20 all exited -9 without timeout or evaluation reports. These stops remain unresolved and require recovery or documented duplicate reconciliation.

Reindexing did not correct the top-level fail labels: the current classifier recognizes only some interrupted shots. Therefore these database labels must not be used as proof of terminal experimental failure; classifier investigation remains necessary.
