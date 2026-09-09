# Offline 100-stage report

Build after reconciling the experiment SQLite ledger:

```sh
python3 experiments/dnd-rest-benchmark/dashboard/build_report.py
```

Default output is the existing `results/dnd-rest-benchmark/dnd-rest-findings.html` location. The report embeds its dataset as plain JSON in `script#experiment-data` and embeds the pinned MIT-licensed Chart.js 4.5.1 runtime. No fetch, CDN, server, fonts, or external assets are required to view it. JSON is downloadable from the page. The old shell generator is retained as historical tooling for the nine-stage report; do not use it to summarize the 100-stage matrix.

The export reads one consistent read-only SQLite transaction and emits every declared model × target cell. Missing cells stay visible. It selects the latest created run per cell and shows all historical run summaries. Outcomes are never collapsed: pass, fail, partial, timeout, blocked, missing. Only pass/fail count as terminal. Shot detail retains unknown historical evaluator-timeout flags and missing metered costs.

Tests:

```sh
python3 -m unittest discover -s experiments/dnd-rest-benchmark/dashboard -p 'test_report.py'
# With Playwright installed and its Chromium test browser available:
node experiments/dnd-rest-benchmark/dashboard/verify_report.cjs results/dnd-rest-benchmark/dnd-rest-findings.html
```

The browser check runs offline, verifies 85 cells, three Chart.js charts, model/target filters, Rust's completed result, JSON export, mobile containment, and absence of JavaScript errors or HTTP requests. It saves desktop/mobile screenshots to a temporary directory.

During execution use `--output results/dnd-rest-benchmark/.cache/resume-20260909/dashboard-preview.html`. An incomplete preview is visibly labeled IN PROGRESS and does not satisfy the final all-runs-completed deliverable.
