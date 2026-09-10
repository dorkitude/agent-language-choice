# Kimi local probe recovery

Source decision: finish all five models × 17 targets × 100 stages in the existing records, then build the standalone dashboard. Tracking: https://github.com/dorkitude/agent-language-choice/issues/6.

At 2026-09-10T09:55:12.826403+00:00, verified and terminated two stalled local probes. Kimi Java run `20260731T000102Z_pi_kimi-k2p7-code_java-stdlib` launched another foreground server through `bash run.sh compile-test` after the earlier intervention documented in [031](031-kimi-java-foreground-probe.md). Its server and shell (32009, 32008) had remained live for more than 11 minutes. Kimi Sinatra run `20260730T075550Z_pi_kimi-k2p7-code_ruby-sinatra` had a storage probe waiting during cleanup with Puma still live after more than one hour; terminated server 4869 and probe shells 4866 and 4865.

Both interventions were recorded before sending SIGTERM in the shared operator event ledger. Pi agents 37004 and 70667 and harness 20725 were preserved. No generated implementation was edited and no hints were supplied. Neither intervention establishes a stage pass; both runs must be disclosed as manually assisted runtime recovery.
