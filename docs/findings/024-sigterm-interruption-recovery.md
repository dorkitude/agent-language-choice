# Recover interrupted CLI attempts

Source context: finish all five models × 17 targets × 100 stages in the existing records, then produce the inline-JSON Tokyo Night dashboard. Tracking: [issue #6](https://github.com/dorkitude/agent-language-choice/issues/6).

On September 9 (Pacific), GPT PHP-Slim stopped at 45 stages and GPT Symfony at 14. All six attempts in each terminal stage exited on SIGTERM, with simultaneous exits across workers; their final attempts emitted only CLI startup events. The signal source is unknown. These are incomplete executions, not valid exhausted-fix outcomes.

The instrument now classifies non-timeout SIGTERM exits as recoverable `agent_killed`, even when partial output exists. Original logs and recorded attempts remain intact; corrected SQLite classification and queue selection derive from those logs. This rule also applies consistently to earlier SIGTERM attempts. Harness timeouts and ordinary nonzero exits retain their existing classification. Seven regression tests pass. No generated implementation was manually repaired.
