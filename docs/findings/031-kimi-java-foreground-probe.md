# Kimi Java foreground probe intervention

Source context: finish all five models × 17 targets × 100 stages in the existing records, then build the standalone dashboard. Operational tracking: https://github.com/dorkitude/agent-language-choice/issues/6.

At 2026-09-10T09:42:57Z, run `20260731T000102Z_pi_kimi-k2p7-code_java-stdlib` was at 95 completed stages, with shot 134 working on `096-api-schema-endpoint`. Pi process 37004 had launched `/bin/bash -c bash run.sh compile-only-test 2>&1 || true` (37867), which was running the foreground `java dnd.Main` server (37868). The command had remained live for more than 40 minutes.

After verifying both process identities, recorded `operator_terminated_hung_local_probe` in the shared operator event ledger and sent SIGTERM only to that server and probe shell. Pi 37004 and harness 20725 were left alive; no generated source was edited and no hint was sent to the agent. This intervention does not establish stage success. The run must be reported as having manual runtime intervention, not as fully unattended.
