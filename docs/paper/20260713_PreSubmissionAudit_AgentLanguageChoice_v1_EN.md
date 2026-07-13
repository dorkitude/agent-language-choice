# Pre-Submission Audit: Agent Language Choice

Version: v1. Date: 2026-07-13. Paper-compiler mode: audit scaffold.

This is not a final audit of a complete manuscript. It is the current gap list
before drafting.

## High-Priority Gaps

| Gap | Status | Fulfillment question / action |
| --- | --- | --- |
| Exact author metadata | ❌ | What ORCID, affiliation string, and author order should appear in the manuscript? |
| Final run scope | ⚠️ | Will the first submission use the nine-stage matrix, or should it wait for the 16-stage inherited-codebase run? |
| Unit of analysis | ❌ | Freeze whether the paper analyzes latest terminal cells, all attempts, or a two-level cell/shot model; write the exclusion/rerun policy before final analysis. |
| Quantitative target covariates | ❌ | Code each target for dependency count, compile/typecheck signal, framework churn, formatter uniformity, explicitness, and corpus prevalence. |
| Statistical analysis | ❌ | Define and run the mixed-effects model for pass/fail, shot burden, and failed stage. |
| Related work completeness | ⚠️ | Expand and verify 2024-2026 coding-agent benchmark literature and package-hallucination/churn literature. |
| Artifact release policy | ⚠️ | Decide which raw transcripts can be public and which must be summarized or hashed. |

## Medium-Priority Gaps

| Gap | Status | Fulfillment question / action |
| --- | --- | --- |
| Wall-clock and cost metrics | ⚠️ | Extract provider/runtime timing and token/cost estimates where available. |
| Figures | ❌ | Generate plots from SQLite/dashboard JSON. |
| Venue formatting | ❌ | Pick ASE/ICSE/FSE/EMSE target before final structure and page-budget decisions. |
| External review | ❌ | Have Yusuke review design, claims, and related-work positioning. |
| Reproducibility package | ⚠️ | Add exact commands for rerunning matrix subsets and rebuilding the dashboard from JSON. |
| Reviewer FAQ | ❌ | Add anticipated answers for task authorship bias, benchmark representativeness, corpus prevalence, model cutoff, and provider comparability. |

## Low-Priority Gaps

| Gap | Status | Fulfillment question / action |
| --- | --- | --- |
| DOCX lifecycle outputs | N/A | Markdown is sufficient for repo-native collaboration; convert to DOCX only if collaborator workflow requires it. |
| Landing page polish | ⚠️ | The self-contained HTML works as an artifact viewer; public microsite polish can wait until submission package. |

## Current Go/No-Go

Go for internal collaborator review: yes.

Go for external submission: no. The project needs quantitative covariate
coding, statistical analysis, related-work expansion, and a decision on whether
to include the 16-stage run.

## Subagent Review Notes

An independent proposal/paper-gap pass on 2026-07-13 identified the same
blocking path: freeze the empirical dataset boundary, turn qualitative target
dimensions into coded variables, run inferential analysis, and state the
contribution without broad language-ranking claims. The recommended paper
shape is a Type D empirical study with an ASE/ICSE/FSE-style IMRAD structure.
