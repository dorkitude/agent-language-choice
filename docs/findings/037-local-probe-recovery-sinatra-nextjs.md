# Sinatra and Next.js local probe recovery

Source decision: “run all of them, then when done build a single-page HTML/Chart.js dashboard” with the experiment records kept in the same place. Tracking: https://github.com/dorkitude/agent-language-choice/issues/6.

At 2026-09-10T14:39:05Z, verified and terminated two stalled local commands, recording each intervention first in `results/dnd-rest-benchmark/operator-events.jsonl`.

- Kimi Sinatra run `20260730T075550Z_pi_kimi-k2p7-code_ruby-sinatra`, at 97 completed stages: its `dndeval-reference -h 2>&1 | head -40` probe launched a foreground server and waited over 13 minutes. Sent SIGTERM only to probe processes 16671, 16672, and 16670; preserved Pi agent 7610.
- GLM Next.js run `20260910T120423Z_pi_glm-5p2_typescript-nextjs`, at 2 completed stages: `grep -rl "missing JSON key" / 2>/dev/null | head -20` remained live for over two hours. Sent SIGTERM only to search processes 86618, 86619, and 86616; preserved Pi agent 51211.

Harness 20725 remained live. No generated source was changed or hints supplied. These actions do not establish stage success. Both runs must disclose manual runtime intervention in the final dashboard; Sinatra also retains its earlier recovery record in [032](032-kimi-local-probe-recovery.md).

At 2026-09-10T14:44:12.299872+00:00, Sinatra repeated the foreground reference-server probe without the `-h` flag, again piping its output to `head -40`. After confirming it remained live for over four minutes with no exit condition, recorded another operator event and sent SIGTERM only to processes 43592, 43593, and 43591. Pi 7610 and harness 20725 were preserved. The same manual-intervention disclosure applies.
