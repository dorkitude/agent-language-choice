#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DATA_JSON="${1:-$ROOT/results/dnd-rest-benchmark/dashboard-data.json}"
OUT_JSON="${2:-$ROOT/results/dnd-rest-benchmark/findings-data.json}"
OUT_HTML="${3:-$ROOT/results/dnd-rest-benchmark/dnd-rest-findings.html}"

mkdir -p "$(dirname "$OUT_JSON")" "$(dirname "$OUT_HTML")"

python3 - "$DATA_JSON" "$OUT_JSON" <<'PY'
import collections
import datetime as dt
import json
import pathlib
import sys

data_path = pathlib.Path(sys.argv[1])
out_path = pathlib.Path(sys.argv[2])
data = json.loads(data_path.read_text())

full_stages = [
    "core",
    "characters",
    "combat-state",
    "auth-users",
    "sqlite-storage",
    "compendium",
    "campaign-state",
    "phb-rules",
    "dm-tools",
]


def model_key(run):
    meta = run.get("metadata") or {}
    return f"{meta.get('provider')}/{meta.get('model')}"


def target_key(run):
    return (run.get("metadata") or {}).get("target") or "unknown"


def status(run):
    return run.get("status") or ("pass" if run.get("passed") else "fail")


def is_full_lifecycle(run):
    meta = run.get("metadata") or {}
    return meta.get("stages") == full_stages and bool(run.get("completed_at_utc"))


def group_stats(runs, key_fn):
    groups = collections.defaultdict(lambda: {"total": 0, "pass": 0, "fail": 0, "partial": 0, "shots": 0, "pass_shots": []})
    for run in runs:
        key = key_fn(run)
        item = groups[key]
        item["total"] += 1
        item["shots"] += int(run.get("total_shots") or 0)
        st = status(run)
        if st == "pass":
            item["pass"] += 1
            item["pass_shots"].append(int(run.get("total_shots") or 0))
        elif st == "partial":
            item["partial"] += 1
        else:
            item["fail"] += 1
    rows = []
    for key, item in groups.items():
        total = item["total"]
        pass_shots = item.pop("pass_shots")
        item["key"] = key
        item["pass_rate"] = item["pass"] / total if total else 0
        item["avg_shots"] = item["shots"] / total if total else 0
        item["avg_pass_shots"] = sum(pass_shots) / len(pass_shots) if pass_shots else None
        rows.append(item)
    return sorted(rows, key=lambda r: (-r["pass_rate"], r["avg_shots"], r["key"]))


def failure_summary(runs):
    rows = []
    for run in runs:
        if status(run) == "pass":
            continue
        rows.append({
            "id": run.get("id"),
            "model": model_key(run),
            "target": target_key(run),
            "failed_stage": run.get("failed_stage"),
            "completed_stages": run.get("completed_stages"),
            "stage_count": run.get("stage_count"),
            "total_shots": run.get("total_shots") or 0,
        })
    return sorted(rows, key=lambda r: (r["target"], r["model"]))


lifecycle = data.get("lifecycle_runs") or []
flat = data.get("flat_runs") or []
full = [run for run in lifecycle if is_full_lifecycle(run)]
full_passes = [run for run in full if status(run) == "pass"]
rust = [run for run in full if target_key(run) == "rust-stdlib"]
default_stages = [stage.get("id") for stage in data.get("stages", []) if stage.get("id")]

summary = {
    "generated_at_utc": dt.datetime.now(dt.UTC).isoformat(),
    "source_generated_at_utc": data.get("generated_at_utc"),
    "full_lifecycle": {
        "cells": len(full),
        "passes": len(full_passes),
        "fails": sum(1 for run in full if status(run) == "fail"),
        "partials": sum(1 for run in full if status(run) == "partial"),
        "total_shots": sum(int(run.get("total_shots") or 0) for run in full),
        "avg_pass_shots": (
            sum(int(run.get("total_shots") or 0) for run in full_passes) / len(full_passes)
            if full_passes else None
        ),
    },
    "latest_target_append": {
        "target": "rust-stdlib",
        "cells": len(rust),
        "passes": sum(1 for run in rust if status(run) == "pass"),
        "fails": sum(1 for run in rust if status(run) == "fail"),
        "partials": sum(1 for run in rust if status(run) == "partial"),
        "rows": [
            {
                "id": run.get("id"),
                "model": model_key(run),
                "status": status(run),
                "passed": bool(run.get("passed")),
                "completed_stages": run.get("completed_stages"),
                "stage_count": run.get("stage_count"),
                "failed_stage": run.get("failed_stage"),
                "total_shots": run.get("total_shots") or 0,
            }
            for run in sorted(rust, key=model_key)
        ],
    },
    "default_roadmap": {
        "stages": default_stages,
        "stage_count": len(default_stages),
        "maintenance_inheritances": max(len(default_stages) - 1, 0),
        "max_shots_with_one_fix": len(default_stages) * 2,
        "final_suite": default_stages[-1] if default_stages else None,
    },
    "by_model": group_stats(full, model_key),
    "by_target": group_stats(full, target_key),
    "failures": failure_summary(full),
    "findings": [
        "The lifecycle benchmark is more informative than a first-pass task because shots accumulate as fresh maintenance and bug-fix agents inherit a growing codebase.",
        "The completed result set contains nine-stage cells; the default roadmap now has sixteen stages, which means fifteen fresh maintenance inheritances after the initial build.",
        "Pass rate alone hides important differences. Shot count, failed stage, and bug-fix recovery are first-class measurements in this experiment.",
        "Future matrix runs should use the sixteen-stage default roadmap so the benchmark measures behavior deeper into long-lived codebase maintenance.",
    ],
}

report = {
    "schema": "agent-language-choice.self-contained-report.v1",
    "summary": summary,
    "source_dashboard": data,
}

out_path.write_text(json.dumps(report, indent=2, sort_keys=True))
PY

python3 - "$OUT_JSON" "$OUT_HTML" <<'PY'
import json
import pathlib
import sys

json_path = pathlib.Path(sys.argv[1])
html_path = pathlib.Path(sys.argv[2])
json_text = json_path.read_text().replace("</script>", "<\\/script>")

html = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Agent Language Choice Findings</title>
  <style>
    :root {
      --bg: #1a1b26;
      --bg2: #16161e;
      --panel: #24283b;
      --panel2: #1f2335;
      --fg: #c0caf5;
      --muted: #9aa5ce;
      --line: #414868;
      --blue: #7aa2f7;
      --cyan: #7dcfff;
      --green: #9ece6a;
      --red: #f7768e;
      --orange: #ff9e64;
      --purple: #bb9af7;
      --yellow: #e0af68;
      color-scheme: dark;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--fg);
      line-height: 1.45;
    }
    header {
      position: sticky;
      top: 0;
      z-index: 2;
      border-bottom: 1px solid var(--line);
      background: rgba(26, 27, 38, 0.96);
      backdrop-filter: blur(12px);
    }
    .top {
      max-width: 1500px;
      margin: 0 auto;
      padding: 18px 22px;
      display: flex;
      gap: 18px;
      align-items: center;
      justify-content: space-between;
    }
    h1, h2, h3 { margin: 0; letter-spacing: 0; }
    h1 { font-size: 24px; }
    h2 { font-size: 17px; color: var(--cyan); }
    h3 { font-size: 14px; color: var(--purple); }
    p { margin: 0; color: var(--muted); }
    main {
      max-width: 1500px;
      margin: 0 auto;
      padding: 22px;
      display: grid;
      gap: 18px;
    }
    .grid { display: grid; gap: 14px; }
    .metrics { grid-template-columns: repeat(6, minmax(130px, 1fr)); }
    .two { grid-template-columns: minmax(0, 1.8fr) minmax(320px, 1fr); }
    .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    .panel-head {
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      display: flex;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
    }
    .panel-body { padding: 16px; }
    .metric {
      padding: 14px;
      background: var(--panel2);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .metric span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 4px;
    }
    .metric strong { display: block; font-size: 24px; color: var(--fg); }
    .toolbar {
      display: grid;
      grid-template-columns: repeat(4, minmax(150px, 1fr)) minmax(240px, 2fr);
      gap: 10px;
    }
    label span { display: block; color: var(--muted); font-size: 12px; margin-bottom: 5px; }
    select, input, button {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--bg2);
      color: var(--fg);
      padding: 9px 10px;
      font: inherit;
    }
    button { cursor: pointer; }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 9px;
      text-align: left;
      vertical-align: top;
    }
    th { color: var(--muted); font-weight: 600; background: var(--panel2); }
    .cell {
      display: grid;
      gap: 3px;
      min-width: 116px;
      text-align: left;
    }
    .cell.pass { border-color: rgba(158, 206, 106, .7); }
    .cell.fail { border-color: rgba(247, 118, 142, .7); }
    .cell.partial { border-color: rgba(224, 175, 104, .7); }
    .cell.selected { outline: 2px solid var(--blue); }
    .status-pass { color: var(--green); }
    .status-fail { color: var(--red); }
    .status-partial { color: var(--yellow); }
    .small { color: var(--muted); font-size: 12px; }
    .findings { display: grid; gap: 10px; }
    .finding {
      border-left: 3px solid var(--blue);
      padding: 10px 12px;
      background: var(--panel2);
      border-radius: 0 6px 6px 0;
    }
    .bars { display: grid; gap: 10px; }
    .barrow { display: grid; gap: 5px; }
    .barlabel { display: flex; justify-content: space-between; gap: 12px; font-size: 12px; color: var(--muted); }
    .bar { height: 8px; background: var(--bg2); border-radius: 999px; overflow: hidden; }
    .bar > span { display: block; height: 100%; background: linear-gradient(90deg, var(--blue), var(--cyan)); }
    .detail-grid { display: grid; grid-template-columns: 260px minmax(0, 1fr); gap: 14px; }
    .shot-list { display: grid; gap: 7px; align-content: start; }
    .shot-btn {
      text-align: left;
      border-radius: 6px;
      padding: 8px;
      background: var(--panel2);
    }
    .shot-btn.selected { outline: 2px solid var(--purple); }
    .tabs { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
    .tab { width: auto; padding: 7px 9px; font-size: 12px; }
    .tab.selected { border-color: var(--cyan); color: var(--cyan); }
    pre {
      margin: 0;
      min-height: 420px;
      max-height: 720px;
      overflow: auto;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #11111a;
      color: var(--fg);
      white-space: pre-wrap;
      word-break: break-word;
      font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    .hidden { display: none; }
    @media (max-width: 980px) {
      .metrics, .two, .toolbar, .detail-grid { grid-template-columns: 1fr; }
      .top { align-items: flex-start; flex-direction: column; }
    }
  </style>
</head>
<body>
  <script id="report-data" type="application/json">__REPORT_JSON__</script>
  <header>
    <div class="top">
      <div>
        <h1>Agent Language Choice Findings</h1>
        <p id="subtitle">Loading embedded benchmark JSON...</p>
      </div>
      <p>D&D REST lifecycle benchmark</p>
    </div>
  </header>
  <main>
    <section class="grid metrics" id="metrics"></section>

    <section class="panel">
      <div class="panel-head">
        <h2>Findings</h2>
        <p>Self-contained report with embedded JSON</p>
      </div>
      <div class="panel-body findings" id="findings"></div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <h2>Controls</h2>
        <p id="visibleCount"></p>
      </div>
      <div class="panel-body toolbar">
        <label><span>Run set</span><select id="runSet"><option value="full">Full lifecycle</option><option value="allLifecycle">All lifecycle</option><option value="flat">Flat first-pass</option></select></label>
        <label><span>Model</span><select id="modelFilter"></select></label>
        <label><span>Target</span><select id="targetFilter"></select></label>
        <label><span>Status</span><select id="statusFilter"><option value="all">All</option><option value="pass">Pass</option><option value="fail">Fail</option><option value="partial">Partial</option></select></label>
        <label><span>Search</span><input id="search" type="search" placeholder="target, model, stage, prompt, response, failure" /></label>
      </div>
    </section>

    <section class="grid two">
      <section class="panel">
        <div class="panel-head">
          <h2>Matrix</h2>
          <p>Click a cell for prompts, responses, and logs</p>
        </div>
        <div class="panel-body" style="overflow:auto">
          <div id="matrix"></div>
        </div>
      </section>
      <aside class="panel">
        <div class="panel-head">
          <h2>Analytics</h2>
          <p>Pass rate and shot burden</p>
        </div>
        <div class="panel-body bars" id="analytics"></div>
      </aside>
    </section>

    <section class="panel">
      <div class="panel-head">
        <div>
          <h2 id="detailTitle">Select a run</h2>
          <p id="detailMeta">No run selected.</p>
        </div>
      </div>
      <div class="panel-body">
        <div class="detail-grid hidden" id="detail">
          <div class="shot-list" id="shotList"></div>
          <div>
            <div class="tabs" id="tabs"></div>
            <pre id="artifact"></pre>
          </div>
        </div>
      </div>
    </section>
  </main>
  <script>
    const report = JSON.parse(document.getElementById("report-data").textContent);
    const dashboard = report.source_dashboard;
    const fullStages = ["core","characters","combat-state","auth-users","sqlite-storage","compendium","campaign-state","phb-rules","dm-tools"];
    const state = { runSet: "full", model: "all", target: "all", status: "all", search: "", selected: null, shot: 0, artifact: "" };
    const $ = (id) => document.getElementById(id);

    function modelKey(run) {
      const m = run.metadata || {};
      return `${m.provider}/${m.model}`;
    }
    function targetKey(run) { return (run.metadata || {}).target || "unknown"; }
    function status(run) { return run.status || (run.passed ? "pass" : "fail"); }
    function isFull(run) {
      const stages = (run.metadata || {}).stages || [];
      return JSON.stringify(stages) === JSON.stringify(fullStages) && !!run.completed_at_utc;
    }
    function allRuns() {
      if (state.runSet === "flat") return dashboard.flat_runs || [];
      const lifecycle = dashboard.lifecycle_runs || [];
      return state.runSet === "full" ? lifecycle.filter(isFull) : lifecycle;
    }
    function filteredRuns() {
      const q = state.search.trim().toLowerCase();
      return allRuns().filter((run) => {
        if (state.model !== "all" && modelKey(run) !== state.model) return false;
        if (state.target !== "all" && targetKey(run) !== state.target) return false;
        if (state.status !== "all" && status(run) !== state.status) return false;
        if (!q) return true;
        return JSON.stringify({
          id: run.id,
          meta: run.metadata,
          failed_stage: run.failed_stage,
          stage_results: run.stage_results,
          shots: (run.shots || []).map((shot) => ({stage: shot.stage, kind: shot.kind, artifacts: shot.artifacts, evaluation: shot.evaluation})),
        }).toLowerCase().includes(q);
      });
    }
    function unique(values) { return [...new Set(values.filter(Boolean))].sort(); }
    function esc(value) {
      return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;" }[ch]));
    }
    function metric(label, value) { return `<div class="metric"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`; }
    function renderMetrics() {
      const s = report.summary.full_lifecycle;
      const roadmap = report.summary.default_roadmap || {};
      $("subtitle").textContent = `Generated ${new Date(report.summary.generated_at_utc).toLocaleString()} from source JSON ${new Date(report.summary.source_generated_at_utc).toLocaleString()}`;
      $("metrics").innerHTML = [
        metric("Full cells", s.cells),
        metric("Passes", `${s.passes}/${s.cells}`),
        metric("Fails", s.fails),
        metric("Total shots", s.total_shots),
        metric("Default stages", roadmap.stage_count || "n/a"),
        metric("Inheritances", roadmap.maintenance_inheritances || "n/a"),
      ].join("");
      $("findings").innerHTML = report.summary.findings.map((text) => `<div class="finding">${esc(text)}</div>`).join("");
    }
    function fill(select, values, current, label) {
      select.innerHTML = `<option value="all">${label}</option>` + values.map((v) => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
      select.value = values.includes(current) ? current : "all";
    }
    function renderFilters() {
      const runs = allRuns();
      fill($("modelFilter"), unique(runs.map(modelKey)), state.model, "All models");
      fill($("targetFilter"), unique(runs.map(targetKey)), state.target, "All targets");
    }
    function renderMatrix() {
      const runs = filteredRuns();
      $("visibleCount").textContent = `${runs.length} visible runs`;
      const targets = unique(runs.map(targetKey));
      const models = unique(runs.map(modelKey));
      const byCell = new Map(runs.map((run) => [`${targetKey(run)}|${modelKey(run)}`, run]));
      if (!targets.length || !models.length) {
        $("matrix").innerHTML = `<p>No runs match the current filters.</p>`;
        return;
      }
      const head = `<thead><tr><th>Target</th>${models.map((m) => `<th>${esc(m)}</th>`).join("")}</tr></thead>`;
      const body = targets.map((target) => {
        const cells = models.map((model) => {
          const run = byCell.get(`${target}|${model}`);
          if (!run) return `<td><span class="small">No run</span></td>`;
          const st = status(run);
          const selected = state.selected && state.selected.id === run.id ? " selected" : "";
          const passed = run.completed_stages ?? (run.test_summary && run.test_summary.passed_count) ?? 0;
          const total = run.stage_count ?? (run.test_summary && run.test_summary.total_count) ?? "";
          return `<td><button class="cell ${st}${selected}" data-run="${esc(run.id)}"><strong class="status-${st}">${st.toUpperCase()}</strong><span class="small">${esc(passed)}/${esc(total)} stages, ${esc(run.total_shots || 0)} shots</span></button></td>`;
        }).join("");
        return `<tr><td><strong>${esc(target)}</strong></td>${cells}</tr>`;
      }).join("");
      $("matrix").innerHTML = `<table>${head}<tbody>${body}</tbody></table>`;
      document.querySelectorAll("[data-run]").forEach((button) => {
        button.addEventListener("click", () => {
          state.selected = runs.find((run) => run.id === button.dataset.run);
          state.shot = 0;
          state.artifact = "";
          renderDetail();
          renderMatrix();
        });
      });
    }
    function groupStats(runs, keyFn) {
      const groups = new Map();
      for (const run of runs) {
        const key = keyFn(run);
        const item = groups.get(key) || { key, total: 0, pass: 0, shots: 0 };
        item.total++;
        if (status(run) === "pass") item.pass++;
        item.shots += Number(run.total_shots || 0);
        groups.set(key, item);
      }
      return [...groups.values()].sort((a, b) => (b.pass / b.total) - (a.pass / a.total) || a.key.localeCompare(b.key));
    }
    function renderAnalytics() {
      const runs = filteredRuns();
      const blocks = [
        ["By Model", groupStats(runs, modelKey)],
        ["By Target", groupStats(runs, targetKey)],
      ].map(([title, rows]) => `<h3>${esc(title)}</h3>` + rows.map((row) => {
        const pct = row.total ? Math.round((row.pass / row.total) * 100) : 0;
        return `<div class="barrow"><div class="barlabel"><span>${esc(row.key)}</span><span>${row.pass}/${row.total}, ${row.shots} shots</span></div><div class="bar"><span style="width:${pct}%"></span></div></div>`;
      }).join(""));
      $("analytics").innerHTML = blocks.join("");
    }
    function renderDetail() {
      const run = state.selected;
      if (!run) {
        $("detail").classList.add("hidden");
        $("detailTitle").textContent = "Select a run";
        $("detailMeta").textContent = "No run selected.";
        return;
      }
      $("detail").classList.remove("hidden");
      $("detailTitle").textContent = `${targetKey(run)} | ${modelKey(run)} | ${status(run).toUpperCase()}`;
      $("detailMeta").textContent = `${run.id} | ${run.completed_stages || 0}/${run.stage_count || 0} stages | ${run.total_shots || 0} shots | failed stage: ${run.failed_stage || "none"}`;
      const shots = run.shots || [];
      $("shotList").innerHTML = shots.map((shot, i) => `<button class="shot-btn ${i === state.shot ? "selected" : ""}" data-shot="${i}"><strong>${esc(String(i + 1).padStart(2, "0"))}. ${esc(shot.stage)} ${esc(shot.kind)}</strong><span class="small">${shot.passed ? "pass" : "fail"} | ${esc((shot.test_summary && `${shot.test_summary.passed_count}/${shot.test_summary.total_count}`) || "")}</span></button>`).join("");
      document.querySelectorAll("[data-shot]").forEach((button) => button.addEventListener("click", () => {
        state.shot = Number(button.dataset.shot);
        state.artifact = "";
        renderDetail();
      }));
      const shot = shots[state.shot] || {};
      const artifactNames = Object.keys(shot.artifacts || {});
      if (!state.artifact || !artifactNames.includes(state.artifact)) state.artifact = artifactNames[0] || "";
      $("tabs").innerHTML = artifactNames.map((name) => `<button class="tab ${name === state.artifact ? "selected" : ""}" data-artifact="${esc(name)}">${esc(name)}</button>`).join("");
      document.querySelectorAll("[data-artifact]").forEach((button) => button.addEventListener("click", () => {
        state.artifact = button.dataset.artifact;
        renderDetail();
      }));
      const artifact = (shot.artifacts || {})[state.artifact];
      $("artifact").textContent = artifact ? artifact.text : "No artifact text for this shot.";
    }
    function render() {
      renderMetrics();
      renderFilters();
      renderMatrix();
      renderAnalytics();
      renderDetail();
    }
    ["runSet","modelFilter","targetFilter","statusFilter"].forEach((id) => {
      $(id).addEventListener("change", (event) => {
        if (id === "runSet") state.runSet = event.target.value;
        if (id === "modelFilter") state.model = event.target.value;
        if (id === "targetFilter") state.target = event.target.value;
        if (id === "statusFilter") state.status = event.target.value;
        state.selected = null;
        render();
      });
    });
    $("search").addEventListener("input", (event) => {
      state.search = event.target.value;
      renderMatrix();
      renderAnalytics();
    });
    render();
  </script>
</body>
</html>
'''

html_path.write_text(html.replace("__REPORT_JSON__", json_text))
PY

printf 'Wrote %s\nWrote %s\n' "$OUT_JSON" "$OUT_HTML"
