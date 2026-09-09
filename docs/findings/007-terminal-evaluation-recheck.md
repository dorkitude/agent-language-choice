# Recheck of a terminal result affected by evaluator backpressure

September 9, 2026. Operational tracking: [issue #6](https://github.com/dorkitude/agent-language-choice/issues/6).

Source context: the user requested all five models across all 17 targets and 100 stages, continuing in the existing experiment records, followed by an offline Chart.js dashboard. Completion requires distinguishing model failures from harness failures.

An audit of the three latest terminal failures found ordinary assertion failures in GPT/Ruby stdlib (stage 18) and GPT/TypeScript Node (stage 90). Sonnet/Sinatra stage 77 instead mixed seven request deadlines with two dependent assertion failures. Its final original evaluation passed 548/557 checks. A timeout-only classifier did not recognize this mixed failure as infrastructure affected.

The unchanged Sonnet/Sinatra implementation was copied for an isolated reevaluation with the corrected server-log handling and shared evaluation lock. It passed all 557 checks. No model invocation, solution hint, or implementation edit was made. Source and original result hashes were checked before accepting the correction.

The original run `20260804T072004Z_claude_claude-sonnet-5_ruby-sinatra` now has 77 completed stages and remains partial, ready to resume at stage 78 when Claude authentication is restored. Its 103 recorded model shots are retained. The effective evaluation of shot 103 was corrected; its original evaluation remains embedded as `evaluation_before_harness_recheck`, its archived evaluation file remains unchanged, and the complete before-state plus recheck receipt are stored in the run's `evaluation-rechecks/` directory. An operator event makes this correction visible in the dashboard.

This is not a full 100-stage pass. Already-running queues may have skipped this formerly terminal cell during startup; a fresh sweep is required after those queues finish. The two remaining terminal failures were not reopened.

## Further Sonnet timeout rechecks

Seven additional unchanged snapshots passed their formerly timed-out stage suites with the corrected harness:

| Target | Stage now completed | Checks passed |
| --- | ---: | ---: |
| PHP Slim | 83 | 642/642 |
| PHP stdlib | 83 | 642/642 |
| PHP Symfony | 83 | 642/642 |
| Python Django | 76 | 540/540 |
| Python Flask | 79 | 584/584 |
| Ruby Rails | 77 | 557/557 |
| TypeScript Next.js | 81 | 611/611 |

Each effective terminal-shot evaluation was corrected in its existing run and SQLite row. Original archived evaluations remain unchanged; each run retains a compressed before-state, the original evaluation embedded in the shot, and the full recheck receipt. No model shots were added, and generated implementations were not edited. Operator events expose all corrections in the dashboard. These runs remain partial and require further model work.

The Sonnet/Next.js recheck initially passed 568/611, with failures loading generated chunks from the copied build cache. Moving the snapshot’s .next cache aside and reevaluating the same application source passed 611/611. Application files were compared byte-for-byte before accepting the correction. Both recheck reports and the failed-cache stderr are preserved in the original run. The live GPT and Kimi queues continue.
