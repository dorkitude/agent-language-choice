# Recheck of a terminal result affected by evaluator backpressure

September 9, 2026. Operational tracking: [issue #6](https://github.com/dorkitude/agent-language-choice/issues/6).

Source context: the user requested all five models across all 17 targets and 100 stages, continuing in the existing experiment records, followed by an offline Chart.js dashboard. Completion requires distinguishing model failures from harness failures.

An audit of the three latest terminal failures found ordinary assertion failures in GPT/Ruby stdlib (stage 18) and GPT/TypeScript Node (stage 90). Sonnet/Sinatra stage 77 instead mixed seven request deadlines with two dependent assertion failures. Its final original evaluation passed 548/557 checks. A timeout-only classifier did not recognize this mixed failure as infrastructure affected.

The unchanged Sonnet/Sinatra implementation was copied for an isolated reevaluation with the corrected server-log handling and shared evaluation lock. It passed all 557 checks. No model invocation, solution hint, or implementation edit was made. Source and original result hashes were checked before accepting the correction.

The original run `20260804T072004Z_claude_claude-sonnet-5_ruby-sinatra` now has 77 completed stages and remains partial, ready to resume at stage 78 when Claude authentication is restored. Its 103 recorded model shots are retained. The effective evaluation of shot 103 was corrected; its original evaluation remains embedded as `evaluation_before_harness_recheck`, its archived evaluation file remains unchanged, and the complete before-state plus recheck receipt are stored in the run's `evaluation-rechecks/` directory. An operator event makes this correction visible in the dashboard.

This is not a full 100-stage pass. Already-running queues may have skipped this formerly terminal cell during startup; a fresh sweep is required after those queues finish. The two remaining terminal failures were not reopened.
