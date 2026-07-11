#!/usr/bin/env python3
"""Language-choice code generation benchmark harness.

Agents implement a black-box CLI contract in an isolated run directory. The
harness scores the produced ./run.sh with stdin/stdout tests that are identical
across implementation languages.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TASKS_DIR = Path(__file__).resolve().parent / "tasks"
RESULTS_DIR = ROOT / "results" / "codegen-benchmark" / "runs"
OPENJDK_BIN = Path("/opt/homebrew/opt/openjdk/bin")

PI_MODEL_ALIASES = {
    "glm-5p2": "accounts/fireworks/models/glm-5p2",
    "kimi-k2p7-code": "accounts/fireworks/models/kimi-k2p7-code",
    "kimi-k2p5": "accounts/fireworks/models/kimi-k2p5",
}

DEFAULT_MATRIX_MODELS = [
    {"label": "claude-opus-latest", "provider": "claude", "model": "opus"},
    {"label": "claude-sonnet-latest", "provider": "claude", "model": "sonnet"},
    {"label": "gpt-5.5-medium", "provider": "codex", "model": "gpt-5.5"},
    {"label": "kimi-k2p7-code", "provider": "pi", "model": "kimi-k2p7-code"},
    {"label": "glm-5p2", "provider": "pi", "model": "glm-5p2"},
]

LANGUAGE_GUIDANCE = {
    "go": "Use Go. A typical run.sh can execute `go run .`.",
    "typescript": (
        "Use TypeScript. Prefer `tsc` plus `node`; do not rely on npm packages "
        "or tsx being installed."
    ),
    "python": "Use Python 3. A typical run.sh can execute `python3 main.py`.",
    "java": "Use Java. A typical run.sh can compile with `javac` then run `java Main`.",
    "ruby": "Use Ruby. A typical run.sh can execute `ruby main.rb`.",
    "php": "Use PHP. A typical run.sh can execute `php main.php`.",
}

LANGUAGE_MARKERS = {
    "go": ["*.go"],
    "typescript": ["*.ts", "tsconfig.json"],
    "python": ["*.py"],
    "java": ["*.java"],
    "ruby": ["*.rb"],
    "php": ["*.php"],
}


@dataclass(frozen=True)
class TestCase:
    name: str
    stdin: str
    expected_stdout: str


@dataclass(frozen=True)
class Task:
    task_id: str
    title: str
    category: str
    spec: str
    tests: list[TestCase]
    starter_files: dict[str, dict[str, str]]


def load_task(task_id: str) -> Task:
    path = TASKS_DIR / f"{task_id}.json"
    if not path.exists():
        known = ", ".join(sorted(p.stem for p in TASKS_DIR.glob("*.json")))
        raise SystemExit(f"Unknown task {task_id!r}. Known tasks: {known}")
    data = json.loads(path.read_text())
    return Task(
        task_id=data["id"],
        title=data["title"],
        category=data["category"],
        spec=data["spec"].strip(),
        tests=[
            TestCase(
                name=t["name"],
                stdin=normalize_stdin(t["stdin"]),
                expected_stdout=normalize_stdout(t["expected_stdout"]),
            )
            for t in data["tests"]
        ],
        starter_files=data.get("starter_files", {}),
    )


def normalize_stdin(value: str) -> str:
    value = textwrap.dedent(value)
    if value.startswith("\n"):
        value = value[1:]
    if value and not value.endswith("\n"):
        value += "\n"
    return value


def normalize_stdout(value: str) -> str:
    stripped = textwrap.dedent(value).strip()
    return stripped + ("\n" if stripped else "")


def slug(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    return value.strip("-") or "run"


def resolve_fireworks_api_key() -> str | None:
    return os.environ.get("FIREWORKS_API_KEY", "").strip() or None


def benchmark_env() -> dict[str, str]:
    env = os.environ.copy()
    if OPENJDK_BIN.exists():
        env["PATH"] = f"{OPENJDK_BIN}:{env.get('PATH', '')}"
        env.setdefault("JAVA_HOME", str(OPENJDK_BIN.parent))
    return env


def build_prompt(task: Task, language: str) -> str:
    language_hint = LANGUAGE_GUIDANCE[language]
    starter_note = ""
    if task.starter_files:
        starter_note = (
            "\nA starter repository has already been placed in the current "
            "directory. Modify or replace it as needed, but keep the final "
            "`./run.sh` contract.\n"
        )
    return textwrap.dedent(
        f"""
        You are participating in a programming-language benchmark.

        Target language: {language}
        Language guidance: {language_hint}
        {starter_note}

        Implement the task below in the current working directory.

        Required contract:
        - Create a POSIX shell script named run.sh in the current directory.
        - `./run.sh` must read from stdin and write the answer to stdout.
        - Use the requested target language for the implementation.
        - Use only the language standard library for this pilot task.
        - Do not use network access.
        - Do not edit files outside the current working directory.
        - Make the solution deterministic.

        Task: {task.title}

        {task.spec}

        Finish when `./run.sh` is ready.
        """
    ).strip()


def materialize_starter_files(run_dir: Path, task: Task, language: str) -> None:
    files = task.starter_files.get(language, {})
    for relative_path, content in files.items():
        path = run_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, list):
            content = "\n".join(content) + "\n"
        path.write_text(textwrap.dedent(content).lstrip("\n"))
        if path.name == "run.sh":
            path.chmod(path.stat().st_mode | 0o111)


def write_task_markdown(run_dir: Path, task: Task, language: str, prompt: str) -> None:
    tests_preview = "\n\n".join(
        f"### {test.name}\n\nstdin:\n```text\n{test.stdin}```\n\nexpected stdout:\n```text\n{test.expected_stdout}```"
        for test in task.tests
    )
    (run_dir / "TASK.md").write_text(
        f"# {task.title}\n\n"
        f"- Task ID: `{task.task_id}`\n"
        f"- Category: `{task.category}`\n"
        f"- Language: `{language}`\n\n"
        "## Agent Prompt\n\n"
        f"```text\n{prompt}\n```\n\n"
        "## Tests\n\n"
        f"{tests_preview}\n"
    )


def make_run_dir(provider: str, model: str, language: str, task_id: str) -> Path:
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = "_".join([timestamp, slug(provider), slug(model), slug(language), slug(task_id)])
    run_dir = RESULTS_DIR / name
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def run_agent(
    provider: str,
    model: str,
    prompt: str,
    run_dir: Path,
    timeout_seconds: int,
    codex_danger_full_access: bool,
    codex_reasoning_effort: str,
    claude_effort: str,
) -> dict[str, Any]:
    env = benchmark_env()
    command: list[str]

    if provider == "pi":
        key = resolve_fireworks_api_key()
        if key:
            env["FIREWORKS_API_KEY"] = key
        model_id = PI_MODEL_ALIASES.get(model, model)
        command = [
            "pi",
            "--no-session",
            "--provider",
            "fireworks",
            "--model",
            model_id,
            "--thinking",
            "medium",
            "-p",
            prompt,
        ]
    elif provider == "claude":
        command = [
            "claude",
            "-p",
            "--model",
            model,
            "--effort",
            claude_effort,
            "--permission-mode",
            "bypassPermissions",
            "--no-session-persistence",
            prompt,
        ]
    elif provider == "codex":
        command = [
            "codex",
            "exec",
            "-C",
            str(run_dir),
            "--skip-git-repo-check",
            "--ephemeral",
            "--model",
            model,
            "-c",
            f'model_reasoning_effort="{codex_reasoning_effort}"',
            "-o",
            str(run_dir / "agent_last_message.txt"),
        ]
        if codex_danger_full_access:
            command.append("--dangerously-bypass-approvals-and-sandbox")
        else:
            command.extend(["--sandbox", "workspace-write"])
        command.append(prompt)
    else:
        raise SystemExit(f"Unknown provider {provider!r}")

    started = time.time()
    try:
        completed = subprocess.run(
            command,
            cwd=run_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        completed = exc
        timed_out = True

    elapsed = time.time() - started
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    (run_dir / "agent_stdout.txt").write_text(stdout)
    (run_dir / "agent_stderr.txt").write_text(stderr)

    return {
        "provider": provider,
        "model": model,
        "codex_reasoning_effort": codex_reasoning_effort if provider == "codex" else None,
        "claude_effort": claude_effort if provider == "claude" else None,
        "timed_out": timed_out,
        "returncode": None if timed_out else completed.returncode,
        "elapsed_seconds": round(elapsed, 3),
        "command": redact_command(command),
    }


def redact_command(command: list[str]) -> list[str]:
    redacted: list[str] = []
    for part in command:
        if part.startswith("fw_"):
            redacted.append("<redacted>")
        else:
            redacted.append(part)
    return redacted


def validate_language_marker(run_dir: Path, language: str) -> dict[str, Any]:
    markers = LANGUAGE_MARKERS[language]
    found: list[str] = []
    for pattern in markers:
        found.extend(str(path.relative_to(run_dir)) for path in run_dir.glob(pattern))
    return {
        "language": language,
        "expected_markers": markers,
        "found_markers": sorted(found),
        "passed": bool(found),
    }


def run_tests(run_dir: Path, task: Task, per_test_timeout: int) -> dict[str, Any]:
    run_sh = run_dir / "run.sh"
    if not run_sh.exists():
        return {
            "passed": False,
            "error": "run.sh was not created",
            "tests": [],
        }
    run_sh.chmod(run_sh.stat().st_mode | 0o111)

    results: list[dict[str, Any]] = []
    for test in task.tests:
        started = time.time()
        try:
            completed = subprocess.run(
                ["./run.sh"],
                cwd=run_dir,
                env=benchmark_env(),
                input=test.stdin,
                capture_output=True,
                text=True,
                timeout=per_test_timeout,
            )
            timed_out = False
            stdout = completed.stdout
            stderr = completed.stderr
            returncode = completed.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            returncode = None

        normalized_stdout = stdout.strip() + ("\n" if stdout.strip() else "")
        passed = (
            not timed_out
            and returncode == 0
            and normalized_stdout == test.expected_stdout
        )
        results.append(
            {
                "name": test.name,
                "passed": passed,
                "timed_out": timed_out,
                "returncode": returncode,
                "elapsed_seconds": round(time.time() - started, 3),
                "expected_stdout": test.expected_stdout,
                "actual_stdout": stdout,
                "stderr": stderr,
            }
        )

    return {
        "passed": all(result["passed"] for result in results),
        "tests": results,
    }


def run_one(args: argparse.Namespace) -> int:
    if args.language not in LANGUAGE_GUIDANCE:
        known = ", ".join(sorted(LANGUAGE_GUIDANCE))
        raise SystemExit(f"Unknown language {args.language!r}. Known languages: {known}")

    task = load_task(args.task)
    run_dir = make_run_dir(args.provider, args.model, args.language, task.task_id)
    materialize_starter_files(run_dir, task, args.language)
    prompt = build_prompt(task, args.language)
    write_task_markdown(run_dir, task, args.language, prompt)

    metadata = {
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "provider": args.provider,
        "model": args.model,
        "language": args.language,
        "task_id": task.task_id,
        "task_title": task.title,
        "task_category": task.category,
        "run_dir": str(run_dir),
    }
    (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")

    agent = run_agent(
        provider=args.provider,
        model=args.model,
        prompt=prompt,
        run_dir=run_dir,
        timeout_seconds=args.agent_timeout,
        codex_danger_full_access=args.codex_danger_full_access,
        codex_reasoning_effort=args.codex_reasoning_effort,
        claude_effort=args.claude_effort,
    )
    language_marker = validate_language_marker(run_dir, args.language)
    tests = run_tests(run_dir, task, args.test_timeout)

    result = {
        "metadata": metadata,
        "agent": agent,
        "language_marker": language_marker,
        "tests": tests,
        "passed": (
            not agent["timed_out"]
            and agent["returncode"] == 0
            and language_marker["passed"]
            and tests["passed"]
        ),
    }
    (run_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n")

    print(json.dumps({"run_dir": str(run_dir), "passed": result["passed"]}, indent=2))
    return 0 if result["passed"] else 1


def list_tasks(_: argparse.Namespace) -> int:
    for path in sorted(TASKS_DIR.glob("*.json")):
        data = json.loads(path.read_text())
        print(f"{data['id']}\t{data['category']}\t{data['title']}")
    return 0


def list_runs(_: argparse.Namespace) -> int:
    if not RESULTS_DIR.exists():
        return 0
    print("status\tprovider\tmodel\tlanguage\ttask\tagent_seconds\ttests\trun_dir")
    for result_path in sorted(RESULTS_DIR.glob("*/result.json")):
        data = json.loads(result_path.read_text())
        status = "PASS" if data.get("passed") else "FAIL"
        meta = data["metadata"]
        agent_seconds = data.get("agent", {}).get("elapsed_seconds", "")
        tests = data.get("tests", {}).get("tests", [])
        test_count = f"{sum(1 for test in tests if test.get('passed'))}/{len(tests)}"
        print(
            f"{status}\t{meta['provider']}\t{meta['model']}\t"
            f"{meta['language']}\t{meta['task_id']}\t{agent_seconds}\t"
            f"{test_count}\t{result_path.parent}"
        )
    return 0


def split_csv(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def selected_models(selector: str | None) -> list[dict[str, str]]:
    labels = split_csv(selector, [model["label"] for model in DEFAULT_MATRIX_MODELS])
    models_by_label = {model["label"]: model for model in DEFAULT_MATRIX_MODELS}
    unknown = [label for label in labels if label not in models_by_label]
    if unknown:
        known = ", ".join(model["label"] for model in DEFAULT_MATRIX_MODELS)
        raise SystemExit(f"Unknown model label(s): {', '.join(unknown)}. Known: {known}")
    return [models_by_label[label] for label in labels]


def matrix_combinations(args: argparse.Namespace) -> list[dict[str, str]]:
    tasks = split_csv(args.tasks, sorted(p.stem for p in TASKS_DIR.glob("*.json")))
    languages = split_csv(args.languages, sorted(LANGUAGE_GUIDANCE))
    models = selected_models(args.models)

    for task_id in tasks:
        load_task(task_id)
    unknown_languages = [language for language in languages if language not in LANGUAGE_GUIDANCE]
    if unknown_languages:
        known = ", ".join(sorted(LANGUAGE_GUIDANCE))
        raise SystemExit(f"Unknown language(s): {', '.join(unknown_languages)}. Known: {known}")

    combos: list[dict[str, str]] = []
    for task_id in tasks:
        for language in languages:
            for model in models:
                combos.append(
                    {
                        "task": task_id,
                        "language": language,
                        "label": model["label"],
                        "provider": model["provider"],
                        "model": model["model"],
                    }
                )
    return combos


def matrix_plan(args: argparse.Namespace) -> int:
    combos = matrix_combinations(args)
    print("provider\tmodel_label\tmodel_arg\tlanguage\ttask")
    for combo in combos:
        print(
            f"{combo['provider']}\t{combo['label']}\t{combo['model']}\t"
            f"{combo['language']}\t{combo['task']}"
        )
    print(f"\n{len(combos)} planned runs")
    return 0


def run_matrix(args: argparse.Namespace) -> int:
    combos = matrix_combinations(args)
    failures = 0
    for index, combo in enumerate(combos, start=1):
        if args.skip_existing and completed_run_exists(combo):
            print(
                f"[{index}/{len(combos)}] skip existing {combo['label']} "
                f"{combo['language']} {combo['task']}",
                flush=True,
            )
            continue
        print(
            f"[{index}/{len(combos)}] {combo['label']} "
            f"{combo['language']} {combo['task']}",
            flush=True,
        )
        run_args = argparse.Namespace(
            provider=combo["provider"],
            model=combo["model"],
            language=combo["language"],
            task=combo["task"],
            agent_timeout=args.agent_timeout,
            test_timeout=args.test_timeout,
            codex_danger_full_access=args.codex_danger_full_access,
            codex_reasoning_effort=args.codex_reasoning_effort,
            claude_effort=args.claude_effort,
        )
        code = run_one(run_args)
        if code != 0:
            failures += 1
            if not args.continue_on_fail:
                return code
    return 1 if failures else 0


def completed_run_exists(combo: dict[str, str]) -> bool:
    if not RESULTS_DIR.exists():
        return False
    for result_path in RESULTS_DIR.glob("*/result.json"):
        try:
            data = json.loads(result_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        meta = data.get("metadata", {})
        if (
            data.get("passed")
            and meta.get("provider") == combo["provider"]
            and meta.get("model") == combo["model"]
            and meta.get("language") == combo["language"]
            and meta.get("task_id") == combo["task"]
        ):
            return True
    return False


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(required=True)

    list_parser = subparsers.add_parser("list-tasks")
    list_parser.set_defaults(func=list_tasks)

    runs_parser = subparsers.add_parser("list-runs")
    runs_parser.set_defaults(func=list_runs)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--provider", choices=["pi", "claude", "codex"], required=True)
    run_parser.add_argument("--model", required=True)
    run_parser.add_argument("--language", required=True, choices=sorted(LANGUAGE_GUIDANCE))
    run_parser.add_argument("--task", required=True)
    run_parser.add_argument("--agent-timeout", type=int, default=600)
    run_parser.add_argument("--test-timeout", type=int, default=20)
    run_parser.add_argument("--codex-reasoning-effort", default="medium")
    run_parser.add_argument("--claude-effort", default="medium")
    run_parser.add_argument(
        "--codex-danger-full-access",
        action="store_true",
        help="Use Codex's approval/sandbox bypass. Intended only for isolated run dirs.",
    )
    run_parser.set_defaults(func=run_one)

    plan_parser = subparsers.add_parser("matrix-plan")
    plan_parser.add_argument("--models", help="Comma-separated model labels")
    plan_parser.add_argument("--languages", help="Comma-separated languages")
    plan_parser.add_argument("--tasks", help="Comma-separated task IDs")
    plan_parser.set_defaults(func=matrix_plan)

    matrix_parser = subparsers.add_parser("run-matrix")
    matrix_parser.add_argument("--models", help="Comma-separated model labels")
    matrix_parser.add_argument("--languages", help="Comma-separated languages")
    matrix_parser.add_argument("--tasks", help="Comma-separated task IDs")
    matrix_parser.add_argument("--agent-timeout", type=int, default=600)
    matrix_parser.add_argument("--test-timeout", type=int, default=20)
    matrix_parser.add_argument("--codex-reasoning-effort", default="medium")
    matrix_parser.add_argument("--claude-effort", default="medium")
    matrix_parser.add_argument("--codex-danger-full-access", action="store_true")
    matrix_parser.add_argument("--continue-on-fail", action="store_true")
    matrix_parser.add_argument("--skip-existing", action="store_true")
    matrix_parser.set_defaults(func=run_matrix)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
