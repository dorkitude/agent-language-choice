# Research Project Proposal: Agent Language Choice

Version: v1. Date: 2026-07-13. Format: Markdown equivalent of the
`research-proposer` template.

## Researcher List And Affiliations

| Name | Affiliation | Role | ID |
| --- | --- | --- | --- |
| Kyle | Endgame, CTO | PI / first author / benchmark design and implementation | ORCID: TBD |
| Yusuke Takahashi | AIx / research-lifecycle collaborator | collaborator / paper-shaping and research-process review | ORCID: TBD |

Author-order rationale: provisional. Kyle currently owns the research question,
harness, experiments, artifacts, and first interpretation. Yusuke is listed as a
collaborator because the next phase uses the Research Lifecycle Guide and
requires research-process and publication-strategy review.

## Overview

This project studies how programming-language and framework design dimensions
predict LLM coding-agent success as a codebase grows through repeated
maintenance. The current artifact is a deterministic D&D REST API lifecycle
benchmark: five model families are evaluated across fifteen language/framework
targets, with cumulative black-box HTTP checks and every creative,
maintenance, and bug-fix invocation counted as a shot. The latest nine-stage
baseline contains 75 model/target cells, 59 full lifecycle passes, 16
deterministic failures, and 784 total shots. The study's core contribution is
not a ranking of languages, but an empirical instrument for measuring how
verification feedback, ecosystem volatility, dependency surface, explicitness,
idiom uniformity, and corpus prevalence interact with agentic repair loops.

Core claim: language/framework choice affects not only whether coding agents
eventually pass a benchmark, but how many repair shots they need and where
they fail as inherited codebases grow.

Keywords: LLM coding agents; empirical software engineering; programming
languages; benchmark design; software maintenance.

Target field: empirical software engineering / AI for software engineering.

## Schedule And Roles

| Item | Timing | Owner | Output |
| --- | --- | --- | --- |
| Freeze nine-stage baseline | Complete, 2026-07-13 | Kyle | Results JSON, SQLite DB, self-contained HTML, findings docs |
| Paper-prep scaffolding | Complete, 2026-07-13 | Kyle + subagents | This `docs/paper/` folder |
| 16-stage lifecycle run | Next | Kyle | Extended results for long-lived inherited codebases |
| Covariate coding | Next | Kyle + reviewer | Quantitative target rubric for design dimensions |
| Related-work expansion | Next | Kyle + Yusuke | Verified references and positioning |
| First paper draft | After 16-stage run | Kyle | IMRAD draft |
| Collaborator review | After draft v1 | Yusuke | Gap review and venue strategy |

Nearest go/no-go: decide whether the nine-stage matrix is sufficient for a
short empirical paper or whether submission waits for the 16-stage lifecycle.

Dependencies: 16-stage run depends on deterministic evaluator readiness for
stages 10-16 and available model/provider budget.

## Background

LLM coding-agent benchmarks often evaluate short greenfield tasks or
repository-level bug fixes in a single dominant language. This project fills a
gap between those settings: like-for-like API specs across many
language/framework targets, evaluated over cumulative maintenance stages where
fresh agents inherit prior code. The setup tests whether language and ecosystem
properties change agent reliability and repair burden under realistic
codebase-growth pressure.

## 1. Objectives, Research Questions, Core Contributions

Objective: identify which language/framework design dimensions predict coding
agent success, failure stage, and shot burden.

RQ1: How much do pass rate and shot burden vary across models, languages, and
frameworks under identical black-box API tasks?

RQ2: Which stages create the most deterministic failures as a codebase grows?

RQ3: Do target-level design dimensions explain variance after controlling for
model and task stage?

Contributions:

1. A central Go/Cobra/Viper evaluator for deterministic cross-language REST API checks.
2. A 15-target, 5-model lifecycle benchmark with shot-level transcript and artifact capture.
3. A SQLite-backed experiment-state index and self-contained JSON-powered findings dashboard.
4. A design-dimension framing for studying language choice in agentic code generation.

## 2. Portfolio

| Deliverable | Venue | Contribution |
| --- | --- | --- |
| Baseline empirical paper | ASE / ICSE / FSE | Nine-stage or 16-stage cross-language lifecycle benchmark |
| Artifact paper / companion artifact | Same venue artifact track or Zenodo/GitHub release | Harness, evaluator, prompts, JSON/SQLite results, dashboard |
| Journal extension | EMSE-style journal | Longer roadmap, covariate modeling, seeded-debugging stratum |

Anti-salami rationale: the first paper should focus on the empirical benchmark
and primary lifecycle results. Seeded debugging, dependency-upgrade probes, and
longitudinal cost modeling should only split into later papers if they produce
independent research questions and data.

Preprint policy: post an arXiv preprint after collaborator review and before
conference submission if the venue permits it; preserve artifact snapshots with
commit SHAs and a DOI.

## 3. Experiment Plan

| ID | Title | Summary | Status |
| --- | --- | --- | --- |
| E1 | Nine-stage D&D REST lifecycle | 5 models x 15 targets x 9 cumulative stages | Complete |
| E2 | 16-stage long-lived codebase lifecycle | Same matrix extended to 15 maintenance inheritances | Planned |
| E3 | Target covariate coding | Dependency count, churn proxy, formatter uniformity, explicitness rubric, corpus prevalence | Planned |
| E4 | Seeded debugging stratum | Parallel starter repos with identical logical bugs | Designed, not run |
| E5 | Mixed-effects analysis | Success/shot burden/failure stage modeled by dimensions and controls | Planned |

Primary metrics: full lifecycle pass, completed stages, first failed stage,
total shots, bug-fix recovery, wall-clock time, dependency count, and
infrastructure-block status.

## 4. Publication Strategy

Primary: ASE research track, because the work is an empirical software
engineering study with a reproducible benchmark artifact.

Fallbacks: ICSE research track, FSE research track, or an empirical software
engineering journal extension if the 16-stage run and covariate analysis make
the paper too large for conference format.

Artifact strategy: release the agent-language-choice repository with cleaned
artifacts, result JSON, SQLite state DB, and a static dashboard. Keep raw
provider transcripts if license and privacy review allow; otherwise publish
hashes and summarized artifacts.

## 5. Materials And Links

- Research design: [`../../RESEARCH-DESIGN.md`](../../RESEARCH-DESIGN.md)
- Findings: [`../findings/002-full-lifecycle-matrix.md`](../findings/002-full-lifecycle-matrix.md)
- Infrastructure accounting: [`../findings/003-infra-block-classification.md`](../findings/003-infra-block-classification.md)
- Dashboard HTML: [`../../results/dnd-rest-benchmark/dnd-rest-findings.html`](../../results/dnd-rest-benchmark/dnd-rest-findings.html)
- Dashboard JSON: [`../../results/dnd-rest-benchmark/dashboard-data.json`](../../results/dnd-rest-benchmark/dashboard-data.json)
- State DB: [`../../results/dnd-rest-benchmark/experiment-state.sqlite3`](../../results/dnd-rest-benchmark/experiment-state.sqlite3)

## 6. FAQ

Why not just compare pass rates?

Pass rate hides repair burden. A cell that passes in 9 shots and a cell that
passes in 15 shots are operationally different.

Why use D&D REST APIs?

The domain gives deterministic, stateful, incrementally extensible API
contracts: dice math, character rules, combat state, persistence, campaign
state, PHB-like rules, and DM tools. It is complex enough to stress
maintenance without requiring proprietary data.

Why latest runtimes and frameworks?

The study intentionally measures coding agents against current environments.
That increases ecological validity and exposes post-training-cutoff churn.

What is the biggest current threat to validity?

The target design-dimension scores are still qualitative. They need a coded
rubric and sensitivity analysis before the claims become paper-ready.

