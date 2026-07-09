const DATA_PATHS = [
  "../../../results/dnd-rest-benchmark/dashboard-data.json",
  "./dashboard-data.json",
  "/results/dnd-rest-benchmark/dashboard-data.json",
];

const state = {
  data: null,
  mode: "lifecycle",
  model: "all",
  target: "all",
  status: "all",
  search: "",
  selectedId: null,
  selectedShot: 0,
  selectedArtifact: "",
};

const el = {
  generatedAt: document.querySelector("#generatedAt"),
  summaryGrid: document.querySelector("#summaryGrid"),
  refreshButton: document.querySelector("#refreshButton"),
  modeFilter: document.querySelector("#modeFilter"),
  modelFilter: document.querySelector("#modelFilter"),
  targetFilter: document.querySelector("#targetFilter"),
  statusFilter: document.querySelector("#statusFilter"),
  searchInput: document.querySelector("#searchInput"),
  matrix: document.querySelector("#matrix"),
  matrixCaption: document.querySelector("#matrixCaption"),
  analytics: document.querySelector("#analytics"),
  detailTitle: document.querySelector("#detailTitle"),
  detailSubtitle: document.querySelector("#detailSubtitle"),
  detailBadges: document.querySelector("#detailBadges"),
  detailEmpty: document.querySelector("#detailEmpty"),
  detailContent: document.querySelector("#detailContent"),
  shotRail: document.querySelector("#shotRail"),
  artifactTabs: document.querySelector("#artifactTabs"),
  artifactViewer: document.querySelector("#artifactViewer"),
};

async function loadData() {
  let lastError;
  for (const path of DATA_PATHS) {
    try {
      const response = await fetch(`${path}?t=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      state.data = await response.json();
      state.selectedId = state.selectedId || firstRun()?.id || null;
      render();
      return;
    } catch (error) {
      lastError = error;
    }
  }
  el.generatedAt.textContent = `Could not load dashboard JSON: ${lastError?.message || "unknown error"}`;
}

function runs() {
  if (!state.data) return [];
  return state.mode === "flat" ? state.data.flat_runs : state.data.lifecycle_runs;
}

function firstRun() {
  return runs()[0];
}

function modelKey(run) {
  const meta = run.metadata || {};
  return `${meta.provider}/${meta.model}`;
}

function runStatus(run) {
  if (state.mode === "lifecycle") return run.status || (run.passed ? "pass" : "fail");
  return run.passed ? "pass" : "fail";
}

function testText(run) {
  if (state.mode === "lifecycle") {
    return `${run.completed_stages || 0}/${run.stage_count || 0} stages, ${run.total_shots || 0} shots`;
  }
  const summary = run.test_summary || {};
  return `${summary.passed_count || 0}/${summary.total_count || 0} tests`;
}

function filteredRuns() {
  const q = state.search.trim().toLowerCase();
  return runs().filter((run) => {
    const meta = run.metadata || {};
    if (state.model !== "all" && modelKey(run) !== state.model) return false;
    if (state.target !== "all" && meta.target !== state.target) return false;
    if (state.status !== "all" && runStatus(run) !== state.status) return false;
    if (!q) return true;
    return JSON.stringify({
      id: run.id,
      meta,
      status: runStatus(run),
      stage_results: run.stage_results,
      failed_stage: run.failed_stage,
      shots: (run.shots || []).map((shot) => ({
        stage: shot.stage,
        kind: shot.kind,
        evaluation: shot.evaluation,
        summary: shot.test_summary,
      })),
      evaluation: run.evaluation,
    }).toLowerCase().includes(q);
  });
}

function render() {
  populateFilters();
  renderSummary();
  renderMatrix();
  renderAnalytics();
  renderDetail();
}

function populateFilters() {
  const allRuns = runs();
  fillSelect(el.modelFilter, "All models", unique(allRuns.map(modelKey)), state.model);
  fillSelect(el.targetFilter, "All targets", unique(allRuns.map((run) => run.metadata?.target)), state.target);
}

function fillSelect(select, allLabel, values, current) {
  const html = [`<option value="all">${escapeHtml(allLabel)}</option>`]
    .concat(values.filter(Boolean).map((value) => `<option value="${escapeAttr(value)}">${escapeHtml(value)}</option>`))
    .join("");
  if (select.innerHTML !== html) select.innerHTML = html;
  select.value = values.includes(current) ? current : "all";
  if (select.value !== current) {
    if (select === el.modelFilter) state.model = select.value;
    if (select === el.targetFilter) state.target = select.value;
  }
}

function renderSummary() {
  const all = runs();
  const complete = all.filter((run) => runStatus(run) !== "partial");
  const passed = all.filter((run) => runStatus(run) === "pass");
  const partial = all.filter((run) => runStatus(run) === "partial");
  const shots = all.reduce((sum, run) => sum + (run.total_shots || (run.agent ? 1 : 0)), 0);
  const failures = collectFailures(all).length;
  el.generatedAt.textContent = `JSON generated ${formatDate(state.data.generated_at_utc)}`;
  el.summaryGrid.innerHTML = [
    metric("Mode", state.mode === "lifecycle" ? "Lifecycle" : "Flat"),
    metric("Cells", String(all.length)),
    metric("Passed", `${passed.length}/${complete.length || all.length}`),
    metric("Partial", String(partial.length)),
    metric("Shots", String(shots)),
    metric("Failures", String(failures)),
  ].join("");
}

function metric(label, value) {
  return `<div class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function renderMatrix() {
  const all = filteredRuns();
  const targets = unique(all.map((run) => run.metadata?.target));
  const models = unique(all.map(modelKey));
  const byCell = new Map(all.map((run) => [`${run.metadata?.target}|${modelKey(run)}`, run]));
  el.matrixCaption.textContent = `${all.length} visible ${state.mode} runs`;
  if (!targets.length || !models.length) {
    el.matrix.innerHTML = `<div class="empty-state"><strong>No runs match the filters.</strong></div>`;
    return;
  }
  const head = `<thead><tr><th>Target</th>${models.map((model) => `<th>${escapeHtml(model)}</th>`).join("")}</tr></thead>`;
  const body = targets.map((target) => {
    const cells = models.map((model) => {
      const run = byCell.get(`${target}|${model}`);
      if (!run) return `<td><button class="cell-button empty" type="button">No run</button></td>`;
      const status = runStatus(run);
      const selected = run.id === state.selectedId ? " selected" : "";
      return `<td><button class="cell-button ${status}${selected}" type="button" data-run-id="${escapeAttr(run.id)}">
        <span class="cell-main">${status.toUpperCase()}</span>
        <span class="cell-sub">${escapeHtml(testText(run))}</span>
      </button></td>`;
    }).join("");
    return `<tr><td><strong>${escapeHtml(target)}</strong></td>${cells}</tr>`;
  }).join("");
  el.matrix.innerHTML = `<table>${head}<tbody>${body}</tbody></table>`;
  el.matrix.querySelectorAll("[data-run-id]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedId = button.dataset.runId;
      state.selectedShot = 0;
      state.selectedArtifact = "";
      render();
    });
  });
}

function renderAnalytics() {
  const all = filteredRuns();
  const byModel = groupStats(all, modelKey);
  const byTarget = groupStats(all, (run) => run.metadata?.target || "unknown");
  const failures = collectFailures(all).slice(0, 8);
  el.analytics.innerHTML = [
    rankBlock("By Model", byModel),
    rankBlock("By Target", byTarget),
    failureBlock(failures),
  ].join("");
}

function groupStats(all, keyFn) {
  const groups = new Map();
  for (const run of all) {
    const key = keyFn(run);
    const item = groups.get(key) || { key, total: 0, pass: 0, shots: 0 };
    item.total += 1;
    item.pass += runStatus(run) === "pass" ? 1 : 0;
    item.shots += run.total_shots || 0;
    groups.set(key, item);
  }
  return [...groups.values()].sort((a, b) => b.pass / b.total - a.pass / a.total || a.key.localeCompare(b.key));
}

function rankBlock(title, rows) {
  const content = rows.map((row) => {
    const pct = row.total ? Math.round((row.pass / row.total) * 100) : 0;
    const shots = row.shots ? `, ${row.shots} shots` : "";
    return `<div class="rank-row">
      <strong>${escapeHtml(row.key)}</strong><span>${row.pass}/${row.total}${shots}</span>
      <div class="bar"><span style="width:${pct}%"></span></div>
    </div>`;
  }).join("") || `<p class="shot-meta">No data.</p>`;
  return `<section><h2>${escapeHtml(title)}</h2><div class="rank-list">${content}</div></section>`;
}

function failureBlock(failures) {
  const rows = failures.map((failure) => `<button class="shot-button" type="button" data-run-id="${escapeAttr(failure.runId)}">
    <span class="shot-title"><span>${escapeHtml(failure.label)}</span><span>${escapeHtml(failure.stage || "")}</span></span>
    <span class="shot-meta">${escapeHtml(failure.error || failure.test || "failure")}</span>
  </button>`).join("") || `<p class="shot-meta">No visible failures.</p>`;
  setTimeout(() => {
    el.analytics.querySelectorAll("[data-run-id]").forEach((button) => {
      button.addEventListener("click", () => {
        state.selectedId = button.dataset.runId;
        state.selectedShot = 0;
        state.selectedArtifact = "";
        render();
      });
    });
  }, 0);
  return `<section><h2>Recent Failures</h2><div class="rank-list">${rows}</div></section>`;
}

function collectFailures(all) {
  const failures = [];
  for (const run of all) {
    const meta = run.metadata || {};
    const label = `${modelKey(run)} ${meta.target}`;
    if (state.mode === "lifecycle") {
      for (const shot of run.shots || []) {
        if (shot.passed) continue;
        const failed = shot.test_summary?.failed_tests || [];
        if (!failed.length && shot.evaluation?.error) {
          failures.push({ runId: run.id, label, stage: shot.stage, error: shot.evaluation.error });
        }
        for (const test of failed) {
          failures.push({ runId: run.id, label, stage: shot.stage, test: test.id, error: test.error });
        }
      }
    } else if (!run.passed) {
      const failed = run.test_summary?.failed_tests || [];
      if (!failed.length) failures.push({ runId: run.id, label, error: run.evaluation?.error });
      for (const test of failed) failures.push({ runId: run.id, label, test: test.id, error: test.error });
    }
  }
  return failures.reverse();
}

function renderDetail() {
  const run = runs().find((item) => item.id === state.selectedId);
  if (!run) {
    el.detailEmpty.classList.remove("hidden");
    el.detailContent.classList.add("hidden");
    el.detailTitle.textContent = "Select a matrix cell";
    el.detailSubtitle.textContent = "Choose a run to inspect prompts, model output, evaluator failures, and logs.";
    el.detailBadges.innerHTML = "";
    return;
  }

  const meta = run.metadata || {};
  const status = runStatus(run);
  el.detailEmpty.classList.add("hidden");
  el.detailContent.classList.remove("hidden");
  el.detailTitle.textContent = `${modelKey(run)} · ${meta.target}`;
  el.detailSubtitle.textContent = `${meta.language}/${meta.framework} · ${run.run_dir}`;
  el.detailBadges.innerHTML = [
    badge(status, status.toUpperCase()),
    badge("", state.mode === "lifecycle" ? `${run.completed_stages}/${run.stage_count} stages` : testText(run)),
    badge("", state.mode === "lifecycle" ? `${run.total_shots} shots` : `${Math.round(run.agent?.elapsed_seconds || 0)}s`),
  ].join("");

  const shots = state.mode === "lifecycle" ? run.shots || [] : [flatAsShot(run)];
  if (state.selectedShot >= shots.length) state.selectedShot = 0;
  const shot = shots[state.selectedShot] || shots[0];
  renderShotRail(shots);
  renderArtifacts(shot);
}

function flatAsShot(run) {
  return {
    shot: 1,
    stage: "core",
    kind: "creative",
    passed: run.passed,
    agent: run.agent,
    test_summary: run.test_summary,
    evaluation: run.evaluation,
    artifacts: run.artifacts,
  };
}

function renderShotRail(shots) {
  el.shotRail.innerHTML = shots.map((shot, index) => {
    const selected = index === state.selectedShot ? " selected" : "";
    const status = shot.passed ? "pass" : "fail";
    const summary = shot.test_summary || {};
    return `<button class="shot-button${selected}" type="button" data-shot="${index}">
      <span class="shot-title"><span>Shot ${shot.shot}: ${escapeHtml(shot.stage)}</span>${badge(status, shot.passed ? "PASS" : "FAIL")}</span>
      <span class="shot-meta">${escapeHtml(shot.kind)} · ${summary.passed_count || 0}/${summary.total_count || 0} tests · ${Math.round(shot.agent?.elapsed_seconds || 0)}s</span>
    </button>`;
  }).join("");
  el.shotRail.querySelectorAll("[data-shot]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedShot = Number(button.dataset.shot);
      state.selectedArtifact = "";
      renderDetail();
    });
  });
}

function renderArtifacts(shot) {
  const artifacts = shot?.artifacts || {};
  const entries = Object.entries(artifacts);
  const synthetic = {
    "summary.json": {
      text: JSON.stringify({
        shot: shot?.shot,
        stage: shot?.stage,
        kind: shot?.kind,
        passed: shot?.passed,
        agent: shot?.agent,
        test_summary: shot?.test_summary,
        failed_tests: shot?.test_summary?.failed_tests,
      }, null, 2),
      truncated: false,
    },
  };
  const allEntries = Object.entries(synthetic).concat(entries);
  if (!state.selectedArtifact || !allEntries.find(([name]) => name === state.selectedArtifact)) {
    state.selectedArtifact = allEntries[0]?.[0] || "";
  }
  el.artifactTabs.innerHTML = allEntries.map(([name, value]) => {
    const selected = name === state.selectedArtifact ? " selected" : "";
    const suffix = value.truncated ? " *" : "";
    return `<button class="${selected}" type="button" data-artifact="${escapeAttr(name)}">${escapeHtml(name + suffix)}</button>`;
  }).join("");
  el.artifactTabs.querySelectorAll("[data-artifact]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedArtifact = button.dataset.artifact;
      renderArtifacts(shot);
    });
  });
  const selected = Object.fromEntries(allEntries)[state.selectedArtifact];
  el.artifactViewer.textContent = selected?.text || "No artifact text captured.";
}

function badge(status, text) {
  return `<span class="badge ${escapeAttr(status)}">${escapeHtml(text)}</span>`;
}

function unique(values) {
  return [...new Set(values.filter(Boolean))].sort((a, b) => String(a).localeCompare(String(b)));
}

function formatDate(value) {
  if (!value) return "unknown";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#96;");
}

el.refreshButton.addEventListener("click", loadData);
el.modeFilter.addEventListener("change", () => {
  state.mode = el.modeFilter.value;
  state.model = "all";
  state.target = "all";
  state.selectedId = null;
  state.selectedShot = 0;
  render();
});
el.modelFilter.addEventListener("change", () => {
  state.model = el.modelFilter.value;
  render();
});
el.targetFilter.addEventListener("change", () => {
  state.target = el.targetFilter.value;
  render();
});
el.statusFilter.addEventListener("change", () => {
  state.status = el.statusFilter.value;
  render();
});
el.searchInput.addEventListener("input", () => {
  state.search = el.searchInput.value;
  render();
});

loadData();
