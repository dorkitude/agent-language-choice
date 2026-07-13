# Literature Review: Agent Language Choice

Version: v1. Date: 2026-07-13.

This file is the repo-native output of the Research Lifecycle Guide
`literature-researcher` / `literature-reviewer` pass. It separates verified
peer-reviewed/preprint sources from benchmark artifacts that are useful but
should not be treated as peer-reviewed evidence.

## Top Researchers And Groups To Watch

| Area | Researchers / groups |
| --- | --- |
| SWE agents / issue resolution | Carlos E. Jimenez, John Yang, Karthik Narasimhan, Ofir Press, Princeton SWE-bench group |
| Program repair and agentic SE | Abhik Roychoudhury / NUS APR, Lingming Zhang / UIUC |
| Multilingual code benchmarks | Federico Cassano, Arjun Guha, Baishakhi Ray |
| ML for code / naturalness | Miltos Allamanis, Earl Barr, Prem Devanbu |
| Ecosystem evolution | Alexandre Decan, Tom Mens |
| Security / dependency hallucination | Joseph Spracklen, Bimal Viswanath, Murtuza Jadliwala |

## Venues

Primary fit: ASE, ICSE, FSE.

Adjacent venues: ISSTA, MSR, ICSME, TSE, TOSEM, EMSE.

AI/model venues for benchmark framing: ICLR, NeurIPS, ICML, ACL/EMNLP.

Supply-chain/security angle: USENIX Security, IEEE S&P, CCS.

## Topic Map

| Axis | Existing literature covers | Project position |
| --- | --- | --- |
| Agentic coding benchmarks | SWE-bench, SWE-agent, OpenHands, AutoCodeRover, Agentless | Extends from mostly Python/repo issue repair toward controlled language/framework design variables. |
| Multilingual code generation | MultiPL-E, MBXP/HumanEval-X, McEval, Aider Polyglot | Moves from prompt/unit benchmarks to cumulative black-box maintenance tasks. |
| Feedback / repair loops | Self-repair, test feedback, agent-computer interfaces | Tests whether compile/typecheck/runtime feedback quality predicts convergence and shot burden. |
| Ecosystem volatility | Dependency-network evolution, outdated dependencies, package hallucination | Treats churn and dependency surface as measured independent variables. |
| Language design | Static typing, naturalness, verbosity, explicitness, idiom uniformity | Frames languages as design-space points, not better/worse labels. |

## Candidate References

| # | Work | Relevance | URL | Status |
| ---: | --- | --- | --- | --- |
| 1 | Jimenez et al. 2024, "SWE-bench: Can Language Models Resolve Real-World GitHub Issues?" | Canonical real-world issue-resolution benchmark; important contrast because it is repository repair rather than controlled cross-language lifecycle design. | https://arxiv.org/abs/2310.06770 | ✅ |
| 2 | Yang et al. 2024, "SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering" | Shows that interface/tooling affects agent coding success. | https://arxiv.org/abs/2405.15793 | ✅ |
| 3 | Wang et al. 2025, "OpenHands: An Open Platform for AI Software Developers as Generalist Agents" | Open agent platform; useful for positioning the harness and agent tooling. | https://proceedings.iclr.cc/paper_files/paper/2025/file/a4b6ad6b48850c0c331d1259fc66a69c-Paper-Conference.pdf | ✅ |
| 4 | Xia et al. 2024/2025, "Agentless: Demystifying LLM-based Software Engineering Agents" | Important baseline: simpler localization/repair can rival more complex agent loops. | https://arxiv.org/abs/2407.01489 | ✅ |
| 5 | Zhang et al. 2024, "AutoCodeRover: Autonomous Program Improvement" | SE-oriented GitHub issue repair agent; connects to automated program repair. | https://dl.acm.org/doi/10.1145/3650212.3680384 | ✅ |
| 6 | Zan et al. 2025, "Multi-SWE-bench: A Multilingual Benchmark for Issue Resolving" | Closest competitor for multilingual issue resolution; novelty pressure for this project. | https://arxiv.org/abs/2504.02605 | ⚠️ preprint/version drift |
| 7 | SWE-bench Multilingual | Directly asks language-performance questions across multiple languages. | https://www.swebench.com/multilingual-leaderboard.html | ⚠️ benchmark artifact |
| 8 | Aider Polyglot Benchmark | Practical editing benchmark across C++, Go, Java, JavaScript, Python, and Rust. | https://aider.chat/docs/leaderboards/ | ⚠️ benchmark artifact |
| 9 | Cassano et al. 2023, "MultiPL-E: A Scalable and Polyglot Approach to Benchmarking Neural Code Generation" | Core multilingual code-generation benchmark; motivates language coverage and corpus-prevalence controls. | https://dl.acm.org/doi/10.1109/TSE.2023.3267446 | ✅ |
| 10 | Athiwaratkun et al. 2022/2023, "Multi-lingual Evaluation of Code Generation Models" | MBXP / HumanEval-X; multilingual execution-based evaluation. | https://arxiv.org/abs/2210.14868 | ✅ |
| 11 | Chai et al. 2024, "McEval: Massively Multilingual Code Evaluation" | Larger multilingual code benchmark; useful for coverage comparison. | https://arxiv.org/abs/2406.07436 | ✅ |
| 12 | Olausson et al. 2024, "Is Self-Repair a Silver Bullet for Code Generation?" | Supports repair-loop framing and limits of feedback-based self-repair. | https://arxiv.org/abs/2306.09896 | ✅ |
| 13 | Kocetkov et al. 2022, "The Stack: 3 TB of Permissively Licensed Source Code" | Corpus-prevalence covariate and training-data distribution concern. | https://arxiv.org/abs/2211.15533 | ✅ |
| 14 | Spracklen et al. 2024/2025, "We Have a Package for You!" | Package hallucination and dependency-surface risk. | https://arxiv.org/abs/2406.10279 | ✅ |
| 15 | Decan, Mens, and Grosjean 2019, "An Empirical Comparison of Dependency Network Evolution in Seven Software Packaging Ecosystems" | Anchor for ecosystem volatility and dependency-network evolution. | https://arxiv.org/abs/1710.04936 | ✅ |
| 16 | Gao, Bird, and Barr 2017, "To Type or Not to Type: Quantifying Detectable Bugs in JavaScript" | Static typing as detectable-error signal, not direct agent evidence. | https://dl.acm.org/doi/10.1109/ICSE.2017.75 | ✅ |
| 17 | Hindle et al. 2012, "On the Naturalness of Software" | Basis for predictability/redundancy framing. | https://dl.acm.org/doi/10.5555/2337223.2337322 | ✅ |
| 18 | Ray et al. 2014, "A Large Scale Study of Programming Languages and Code Quality in GitHub" | Classic language/quality empirical study; useful as cautionary related work. | https://dl.acm.org/doi/10.1145/2635868.2635922 | ✅ |

Quality report: 18 references; 14/18 post-2020; two artifact/non-peer-reviewed
items flagged; one version-drift caution flagged.

## Novelty Pressure

Multi-SWE-bench and SWE-bench Multilingual mean this paper cannot claim novelty
from "multilingual agent benchmark" alone. The defensible novelty is narrower:

1. controlled language/framework targets rather than naturally occurring issue
   distributions;
2. cumulative maintenance where fresh agents inherit growing codebases;
3. shot burden and failed stage as first-class outcomes;
4. explicit language/framework design covariates; and
5. deterministic black-box API evaluation across every target.

## Risks

- Static typing, stdlib size, corpus prevalence, and ecosystem churn are
  correlated; use mixed effects and sensitivity checks.
- Specs may encode stdlib-friendly assumptions; external review or task-source
  balancing is needed.
- Public benchmark examples may appear in training data; project-specific
  tasks reduce but do not eliminate contamination risk.
- Dependency-install behavior should be measured as an outcome because package
  hallucination is an operational risk, not just an implementation detail.
