#!/usr/bin/env python3
"""Run D&D REST benchmark generation/evaluation matrix."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import signal
import re
import shutil
import socket
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BENCH_DIR = Path(__file__).resolve().parent
EVALUATOR_DIR = BENCH_DIR / "evaluator"
CHALLENGE_SPEC = BENCH_DIR / "challenges" / "core.md"
RUNS_DIR = ROOT / "results" / "dnd-rest-benchmark" / "runs"
LIFECYCLE_RUNS_DIR = ROOT / "results" / "dnd-rest-benchmark" / "lifecycle-runs"
CACHE_DIR = ROOT / "results" / "dnd-rest-benchmark" / ".cache"
DASHBOARD_DATA = ROOT / "results" / "dnd-rest-benchmark" / "dashboard-data.json"

LATEST = {
    "go": "1.26.5",
    "node": "26.4.0",
    "typescript": "7.0.2",
    "vite": "8.1.3",
    "next": "16.2.10",
    "react": "19.2.7",
    "react-dom": "19.2.7",
    "@vitejs/plugin-react": "6.0.3",
    "@types/node": "26.1.1",
    "@types/react": "19.2.17",
    "@types/react-dom": "19.2.3",
    "python": "3.14.6",
    "django": "6.0.7",
    "flask": "3.1.3",
    "ruby": "4.0.5",
    "sinatra": "4.2.1",
    "rails": "8.1.3",
    "rack": "3.2.6",
    "rackup": "2.3.1",
    "puma": "8.0.2",
    "php": "8.5.8",
    "composer": "2.10.2",
    "slim": "4.15.2",
    "slim-psr7": "1.8.0",
    "symfony-http-foundation": "8.1.1",
    "symfony-routing": "8.1.0",
    "openjdk": "26.0.1",
}

PI_MODEL_ALIASES = {
    "glm-5p2": "accounts/fireworks/models/glm-5p2",
    "kimi-k2p7-code": "accounts/fireworks/models/kimi-k2p7-code",
}

MODELS = [
    {"label": "claude-opus-latest", "provider": "claude", "model": "opus"},
    {"label": "claude-sonnet-latest", "provider": "claude", "model": "sonnet"},
    {"label": "gpt-5.5-medium", "provider": "codex", "model": "gpt-5.5"},
    {"label": "kimi-k2p7-code", "provider": "pi", "model": "kimi-k2p7-code"},
    {"label": "glm-5p2", "provider": "pi", "model": "glm-5p2"},
]


@dataclass(frozen=True)
class Target:
    id: str
    language: str
    framework: str
    guidance: str
    starter_files: dict[str, str]
    setup: list[list[str]]
    markers: list[str]


@dataclass(frozen=True)
class LifecycleStage:
    id: str
    suite: str
    spec_path: Path
    kind: str
    description: str


LIFECYCLE_STAGES = [
    LifecycleStage(
        id="core",
        suite="core",
        spec_path=BENCH_DIR / "challenges" / "core.md",
        kind="creative",
        description="Initial D&D REST API creation",
    ),
    LifecycleStage(
        id="characters",
        suite="characters",
        spec_path=BENCH_DIR / "challenges" / "characters.md",
        kind="maintenance",
        description="Inherit the passing service and add character-rule endpoints",
    ),
    LifecycleStage(
        id="combat-state",
        suite="combat-state",
        spec_path=BENCH_DIR / "challenges" / "combat-state.md",
        kind="maintenance",
        description="Inherit the expanded service and add stateful combat sessions",
    ),
    LifecycleStage(
        id="auth-users",
        suite="auth-users",
        spec_path=BENCH_DIR / "challenges" / "auth-users.md",
        kind="maintenance",
        description="Add deterministic username/password registration and login APIs",
    ),
    LifecycleStage(
        id="sqlite-storage",
        suite="sqlite-storage",
        spec_path=BENCH_DIR / "challenges" / "sqlite-storage.md",
        kind="maintenance",
        description="Move durable game-world/state storage behind SQLite-backed APIs",
    ),
    LifecycleStage(
        id="compendium",
        suite="compendium",
        spec_path=BENCH_DIR / "challenges" / "compendium.md",
        kind="maintenance",
        description="Add monster and item compendium CRUD backed by storage",
    ),
    LifecycleStage(
        id="campaign-state",
        suite="campaign-state",
        spec_path=BENCH_DIR / "challenges" / "campaign-state.md",
        kind="maintenance",
        description="Add persistent campaign, character, and session-log state APIs",
    ),
    LifecycleStage(
        id="phb-rules",
        suite="phb-rules",
        spec_path=BENCH_DIR / "challenges" / "phb-rules.md",
        kind="maintenance",
        description="Add selected PHB rules endpoints for spell slots, rests, and equipment load",
    ),
    LifecycleStage(
        id="dm-tools",
        suite="dm-tools",
        spec_path=BENCH_DIR / "challenges" / "dm-tools.md",
        kind="maintenance",
        description="Add DM-facing encounter, loot, and recap helpers over stored campaign data",
    ),
]


def targets() -> dict[str, Target]:
    return {
        "go-stdlib": Target(
            id="go-stdlib",
            language="go",
            framework="stdlib",
            guidance="Use Go 1.26.5, net/http, and encoding/json. Do not add third-party packages.",
            starter_files={
                "go.mod": "module dndrest\n\ngo 1.26\n",
                "run.sh": "#!/usr/bin/env bash\nset -euo pipefail\ngo run .\n",
            },
            setup=[],
            markers=["*.go"],
        ),
        "typescript-node": Target(
            id="typescript-node",
            language="typescript",
            framework="node-stdlib",
            guidance="Use TypeScript 7.0.2 and Node 26.4.0 built-in HTTP APIs. Do not add frameworks.",
            starter_files=node_package(
                {
                    "typescript": LATEST["typescript"],
                    "@types/node": LATEST["@types/node"],
                },
                "tsc && node dist/server.js",
            ),
            setup=[["npm", "install"]],
            markers=["src/server.ts"],
        ),
        "typescript-vite": Target(
            id="typescript-vite",
            language="typescript",
            framework="vite",
            guidance=(
                "Use Vite 8.1.3 with TypeScript. Implement the REST API through "
                "Vite dev-server middleware or a Vite plugin; do not replace it "
                "with a plain Node-only server."
            ),
            starter_files=node_package(
                {
                    "typescript": LATEST["typescript"],
                    "@types/node": LATEST["@types/node"],
                    "vite": LATEST["vite"],
                    "@vitejs/plugin-react": LATEST["@vitejs/plugin-react"],
                    "react": LATEST["react"],
                    "react-dom": LATEST["react-dom"],
                },
                "vite --host 127.0.0.1 --port \"$PORT\"",
            )
            | {
                "index.html": "<div id=\"root\"></div><script type=\"module\" src=\"/src/main.ts\"></script>\n",
                "src/main.ts": "console.log('dnd rest benchmark');\n",
            },
            setup=[["npm", "install"]],
            markers=["vite.config.ts", "src/main.ts"],
        ),
        "typescript-nextjs": Target(
            id="typescript-nextjs",
            language="typescript",
            framework="nextjs",
            guidance=(
                "Use Next.js 16.2.10, React 19.2.7, and TypeScript 7.0.2. "
                "Implement endpoints as Next route handlers under app/."
            ),
            starter_files=node_package(
                {
                    "typescript": LATEST["typescript"],
                    "@types/node": LATEST["@types/node"],
                    "@types/react": LATEST["@types/react"],
                    "@types/react-dom": LATEST["@types/react-dom"],
                    "next": LATEST["next"],
                    "react": LATEST["react"],
                    "react-dom": LATEST["react-dom"],
                },
                "next dev -H 127.0.0.1 -p \"$PORT\"",
            )
            | {
                "next.config.js": "/** @type {import('next').NextConfig} */\nmodule.exports = {};\n",
                "app/page.tsx": "export default function Page() { return <main>D&D REST benchmark</main>; }\n",
            },
            setup=[["npm", "install"]],
            markers=["app"],
        ),
        "python-stdlib": Target(
            id="python-stdlib",
            language="python",
            framework="stdlib",
            guidance="Use Python 3.14.6 standard library only, such as http.server and json.",
            starter_files={"run.sh": "#!/usr/bin/env bash\nset -euo pipefail\npython3 server.py\n"},
            setup=[],
            markers=["server.py"],
        ),
        "python-flask": Target(
            id="python-flask",
            language="python",
            framework="flask",
            guidance="Use Python 3.14.6 and Flask 3.1.3. Implement the REST API as Flask routes.",
            starter_files=python_requirements(
                {"Flask": LATEST["flask"]},
                "python3 app.py",
            )
            | {
                "app.py": textwrap.dedent(
                    """
                    from flask import Flask, jsonify
                    import os

                    app = Flask(__name__)

                    @app.get("/health")
                    def health():
                        return jsonify(ok=True)

                    if __name__ == "__main__":
                        app.run(host="127.0.0.1", port=int(os.environ["PORT"]))
                    """
                ).lstrip(),
            },
            setup=[
                ["python3", "-m", "pip", "install", "--target", ".deps", "-r", "requirements.txt"],
            ],
            markers=["app.py", "requirements.txt"],
        ),
        "python-django": Target(
            id="python-django",
            language="python",
            framework="django",
            guidance=(
                "Use Python 3.14.6 and Django 6.0.7. Implement the REST API as "
                "Django URL routes/views inside the seeded minimal project."
            ),
            starter_files=python_requirements(
                {"Django": LATEST["django"]},
                "python3 manage.py runserver 127.0.0.1:\"$PORT\" --noreload",
            )
            | {
                "manage.py": textwrap.dedent(
                    """
                    #!/usr/bin/env python3
                    import os
                    import sys

                    def main():
                        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dndsite.settings")
                        from django.core.management import execute_from_command_line
                        execute_from_command_line(sys.argv)

                    if __name__ == "__main__":
                        main()
                    """
                ).lstrip(),
                "dndsite/__init__.py": "",
                "dndsite/settings.py": textwrap.dedent(
                    """
                    SECRET_KEY = "benchmark"
                    DEBUG = True
                    ROOT_URLCONF = "dndsite.urls"
                    ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
                    INSTALLED_APPS = []
                    MIDDLEWARE = []
                    DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
                    """
                ).lstrip(),
                "dndsite/urls.py": textwrap.dedent(
                    """
                    from django.http import JsonResponse
                    from django.urls import path

                    def health(request):
                        return JsonResponse({"ok": True})

                    urlpatterns = [
                        path("health", health),
                    ]
                    """
                ).lstrip(),
            },
            setup=[
                ["python3", "-m", "pip", "install", "--target", ".deps", "-r", "requirements.txt"],
            ],
            markers=["manage.py", "dndsite/urls.py", "requirements.txt"],
        ),
        "java-stdlib": Target(
            id="java-stdlib",
            language="java",
            framework="stdlib",
            guidance="Use OpenJDK 26.0.1 and only the Java standard library, such as com.sun.net.httpserver.HttpServer.",
            starter_files={"run.sh": "#!/usr/bin/env bash\nset -euo pipefail\njavac Main.java\njava Main\n"},
            setup=[],
            markers=["Main.java"],
        ),
        "ruby-stdlib": Target(
            id="ruby-stdlib",
            language="ruby",
            framework="stdlib",
            guidance="Use Ruby 4.0.5 with the standard library only. Avoid Sinatra, Rails, Rack, and gems.",
            starter_files={"run.sh": "#!/usr/bin/env bash\nset -euo pipefail\nruby server.rb\n"},
            setup=[],
            markers=["server.rb"],
        ),
        "ruby-sinatra": Target(
            id="ruby-sinatra",
            language="ruby",
            framework="sinatra",
            guidance="Use Ruby 4.0.5, Sinatra 4.2.1, Rack 3.2.6, and Puma 8.0.2.",
            starter_files=ruby_gemfile(
                {
                    "sinatra": LATEST["sinatra"],
                    "rack": LATEST["rack"],
                    "puma": LATEST["puma"],
                },
                "bundle exec ruby app.rb -o 127.0.0.1 -p \"$PORT\"",
            ),
            setup=[["bundle", "install"]],
            markers=["app.rb", "Gemfile"],
        ),
        "ruby-rails": Target(
            id="ruby-rails",
            language="ruby",
            framework="rails",
            guidance=(
                "Use Ruby 4.0.5 and Rails 8.1.3. A minimal Rails API app is "
                "acceptable; implement the REST endpoints in Rails routes/controllers."
            ),
            starter_files=ruby_gemfile(
                {
                    "rails": LATEST["rails"],
                    "rack": LATEST["rack"],
                    "rackup": LATEST["rackup"],
                    "puma": LATEST["puma"],
                },
                "bundle exec rackup -o 127.0.0.1 -p \"$PORT\"",
            )
            | {
                "config.ru": "require_relative './app'\nrun Rails.application\n",
            },
            setup=[["bundle", "install"]],
            markers=["app.rb", "config.ru", "Gemfile"],
        ),
        "php-stdlib": Target(
            id="php-stdlib",
            language="php",
            framework="stdlib",
            guidance="Use PHP 8.5.8 and the built-in PHP server. Do not add Composer packages.",
            starter_files={
                "run.sh": "#!/usr/bin/env bash\nset -euo pipefail\nphp -S 127.0.0.1:\"$PORT\" index.php\n",
            },
            setup=[],
            markers=["index.php"],
        ),
        "php-slim": Target(
            id="php-slim",
            language="php",
            framework="slim",
            guidance="Use PHP 8.5.8, Composer 2.10.2, Slim 4.15.2, and slim/psr7 1.8.0.",
            starter_files=composer_package(
                {
                    "slim/slim": LATEST["slim"],
                    "slim/psr7": LATEST["slim-psr7"],
                },
                "php -S 127.0.0.1:\"$PORT\" index.php",
            )
            | {
                "index.php": textwrap.dedent(
                    """
                    <?php
                    require __DIR__ . '/vendor/autoload.php';

                    use Psr\\Http\\Message\\ResponseInterface as Response;
                    use Psr\\Http\\Message\\ServerRequestInterface as Request;
                    use Slim\\Factory\\AppFactory;

                    $app = AppFactory::create();

                    $app->get('/health', function (Request $request, Response $response) {
                        $response->getBody()->write(json_encode(['ok' => true]));
                        return $response->withHeader('Content-Type', 'application/json');
                    });

                    $app->run();
                    ?>
                    """
                ).lstrip(),
            },
            setup=[["composer", "install", "--no-interaction"]],
            markers=["index.php", "composer.json"],
        ),
        "php-symfony": Target(
            id="php-symfony",
            language="php",
            framework="symfony-components",
            guidance=(
                "Use PHP 8.5.8, Composer 2.10.2, Symfony HttpFoundation 8.1.1, "
                "and Symfony Routing 8.1.0. Implement routing with Symfony components."
            ),
            starter_files=composer_package(
                {
                    "symfony/http-foundation": LATEST["symfony-http-foundation"],
                    "symfony/routing": LATEST["symfony-routing"],
                },
                "php -S 127.0.0.1:\"$PORT\" index.php",
            )
            | {
                "index.php": textwrap.dedent(
                    """
                    <?php
                    require __DIR__ . '/vendor/autoload.php';

                    use Symfony\\Component\\HttpFoundation\\JsonResponse;
                    use Symfony\\Component\\HttpFoundation\\Request;

                    $request = Request::createFromGlobals();
                    if ($request->getPathInfo() === '/health') {
                        (new JsonResponse(['ok' => true]))->send();
                        return;
                    }
                    (new JsonResponse(['error' => 'not found'], 404))->send();
                    ?>
                    """
                ).lstrip(),
            },
            setup=[["composer", "install", "--no-interaction"]],
            markers=["index.php", "composer.json"],
        ),
    }


def node_package(deps: dict[str, str], start_command: str) -> dict[str, str]:
    return {
        "package.json": json.dumps(
            {
                "private": True,
                "type": "module",
                "scripts": {"start": start_command.split(" ", 1)[0] if False else "bash ./run.sh"},
                "dependencies": deps,
                "devDependencies": {},
            },
            indent=2,
        )
        + "\n",
        "tsconfig.json": json.dumps(
            {
                "compilerOptions": {
                    "target": "ES2024",
                    "module": "NodeNext",
                    "moduleResolution": "NodeNext",
                    "strict": True,
                    "skipLibCheck": True,
                    "outDir": "dist",
                },
                "include": ["src/**/*.ts", "app/**/*.ts", "app/**/*.tsx", "vite.config.ts"],
            },
            indent=2,
        )
        + "\n",
        "run.sh": f"#!/usr/bin/env bash\nset -euo pipefail\n{start_command}\n",
    }


def ruby_gemfile(gems: dict[str, str], start_command: str) -> dict[str, str]:
    lines = ["source 'https://rubygems.org'", ""]
    for name, version in gems.items():
        lines.append(f"gem '{name}', '{version}'")
    return {
        "Gemfile": "\n".join(lines) + "\n",
        "run.sh": f"#!/usr/bin/env bash\nset -euo pipefail\n{start_command}\n",
    }


def python_requirements(packages: dict[str, str], start_command: str) -> dict[str, str]:
    requirements = "".join(f"{name}=={version}\n" for name, version in packages.items())
    return {
        "requirements.txt": requirements,
        "run.sh": (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "export PYTHONPATH=\"$PWD/.deps:${PYTHONPATH:-}\"\n"
            f"{start_command}\n"
        ),
    }


def composer_package(packages: dict[str, str], start_command: str) -> dict[str, str]:
    return {
        "composer.json": json.dumps(
            {
                "require": packages,
                "config": {
                    "sort-packages": True,
                },
            },
            indent=2,
        )
        + "\n",
        "run.sh": f"#!/usr/bin/env bash\nset -euo pipefail\n{start_command}\n",
    }


def benchmark_env() -> dict[str, str]:
    env = os.environ.copy()
    prefixes = [
        "/opt/homebrew/bin",
        "/opt/homebrew/opt/ruby/bin",
        "/opt/homebrew/lib/ruby/gems/4.0.0/bin",
        "/opt/homebrew/opt/openjdk/bin",
    ]
    env["PATH"] = ":".join(prefixes + [env.get("PATH", "")])
    env["JAVA_HOME"] = "/opt/homebrew/opt/openjdk"
    env["DYLD_LIBRARY_PATH"] = ":".join(
        ["/opt/homebrew/opt/expat/lib", env.get("DYLD_LIBRARY_PATH", "")]
    ).rstrip(":")
    env["BUNDLE_PATH"] = "vendor/bundle"
    env["BUNDLE_JOBS"] = "4"
    env["COMPOSER_NO_INTERACTION"] = "1"
    return env


def resolve_fireworks_api_key(op_ref: str | None, op_account: str | None) -> str | None:
    for env_name in ("FIREWORKS_API_KEY", "LLM_GATEWAY_DEFAULT_FIREWORKS_API_KEY"):
        value = os.environ.get(env_name, "").strip()
        if value:
            return value
    if not op_ref:
        return None
    cmd = ["op", "read", op_ref]
    if op_account:
        cmd.extend(["--account", op_account])
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def slug(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    return value.strip("-") or "run"


def split_csv(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def build_prompt(target: Target) -> str:
    spec = CHALLENGE_SPEC.read_text()
    versions = "\n".join(f"- {key}: {value}" for key, value in sorted(LATEST.items()))
    return textwrap.dedent(
        f"""
        You are participating in a programming-language benchmark.

        Target: {target.id}
        Language: {target.language}
        Framework/runtime: {target.framework}

        Use the exact latest runtime/framework versions already pinned in this
        workspace. Do not downgrade packages or replace the requested framework.

        Relevant version pins:
        {versions}

        Target guidance:
        {target.guidance}

        Contract:
        - Implement the D&D REST API described below.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Do not edit files outside the current working directory.
        - Prefer deterministic, minimal code.

        Challenge spec:

        {spec}

        Finish when ./run.sh is ready.
        """
    ).strip()


def build_lifecycle_prompt(
    target: Target,
    stage: LifecycleStage,
    shot_kind: str,
    failure: dict[str, Any] | None = None,
) -> str:
    spec = stage.spec_path.read_text()
    versions = "\n".join(f"- {key}: {value}" for key, value in sorted(LATEST.items()))
    failure_text = ""
    if failure:
        failure_text = textwrap.dedent(
            f"""

            Previous deterministic failure report:

            ```text
            {failure_summary(failure)}
            ```

            Fix the implementation so the same evaluator suite passes. Do not
            remove previously implemented behavior while fixing this failure.
            """
        )

    if shot_kind == "creative":
        role = "Create the first implementation from the seeded starter files."
    elif shot_kind == "maintenance":
        role = (
            "You are a fresh maintenance agent inheriting this existing codebase. "
            "Add the requested feature stage while preserving all existing API behavior."
        )
    else:
        role = (
            "You are a fresh bug-fix agent inheriting this existing codebase after "
            "a deterministic evaluator failure."
        )

    return textwrap.dedent(
        f"""
        You are participating in a staged programming-language benchmark.

        Target: {target.id}
        Language: {target.language}
        Framework/runtime: {target.framework}
        Lifecycle stage: {stage.id}
        Shot kind: {shot_kind}

        {role}

        Use the exact latest runtime/framework versions already pinned in this
        workspace. Do not downgrade packages or replace the requested framework.

        Relevant version pins:
        {versions}

        Target guidance:
        {target.guidance}

        Contract:
        - Work only in the current directory.
        - Keep or create ./run.sh.
        - ./run.sh must start the HTTP server in the foreground.
        - The server must listen on 127.0.0.1 using the PORT environment variable.
        - Do not start the server before finishing your answer.
        - Preserve prior-stage behavior. The evaluator suite for this stage is cumulative.
        - Prefer deterministic, minimal code.

        Stage spec:

        {spec}
        {failure_text}

        Finish when ./run.sh is ready.
        """
    ).strip()


def failure_summary(failure: dict[str, Any]) -> str:
    parts: list[str] = []
    setup = failure.get("setup") or []
    if setup and not all(item.get("returncode") == 0 for item in setup):
        parts.append("setup failed")
        for item in setup:
            if item.get("returncode") != 0:
                parts.append(f"command: {' '.join(item.get('command', []))}")
                if item.get("stdout"):
                    parts.append("stdout:\n" + item["stdout"][-2000:])
                if item.get("stderr"):
                    parts.append("stderr:\n" + item["stderr"][-2000:])
                break
    agent = failure.get("agent") or {}
    if agent.get("timed_out"):
        parts.append("agent timed out")
    elif agent.get("returncode") not in (0, None):
        parts.append(f"agent exited with code {agent.get('returncode')}")
    evaluation = failure.get("evaluation") or {}
    if evaluation.get("error"):
        parts.append(str(evaluation["error"]))
    if evaluation.get("stdout"):
        parts.append(evaluation["stdout"][-4000:])
    if evaluation.get("stderr"):
        parts.append(evaluation["stderr"][-2000:])
    report = evaluation.get("report") or {}
    failed = [item for item in report.get("results", []) if not item.get("passed")]
    if failed:
        parts.append("failed test IDs: " + ", ".join(item.get("id", "") for item in failed))
    return "\n\n".join(part for part in parts if part).strip() or "unknown failure"


def materialize(run_dir: Path, target: Target) -> None:
    for rel, content in target.starter_files.items():
        path = run_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        if path.name == "run.sh":
            path.chmod(path.stat().st_mode | 0o111)
    (run_dir / "VERSION-PINS.json").write_text(json.dumps(LATEST, indent=2) + "\n")


def run_setup(run_dir: Path, target: Target, timeout: int) -> list[dict[str, Any]]:
    results = []
    for cmd in target.setup:
        started = time.time()
        completed = subprocess.run(
            cmd,
            cwd=run_dir,
            env=benchmark_env(),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        results.append(
            {
                "command": cmd,
                "returncode": completed.returncode,
                "elapsed_seconds": round(time.time() - started, 3),
                "stdout": completed.stdout[-4000:],
                "stderr": completed.stderr[-4000:],
            }
        )
        if completed.returncode != 0:
            break
    (run_dir / "setup.json").write_text(json.dumps(results, indent=2) + "\n")
    return results


def run_agent(args: argparse.Namespace, run_dir: Path, prompt: str) -> dict[str, Any]:
    env = benchmark_env()
    command: list[str]
    if args.provider == "pi":
        key = resolve_fireworks_api_key(args.op_ref, args.op_account)
        if key:
            env["FIREWORKS_API_KEY"] = key
        command = [
            "pi",
            "--no-session",
            "--provider",
            "fireworks",
            "--model",
            PI_MODEL_ALIASES.get(args.model, args.model),
            "--thinking",
            "medium",
            "-p",
            prompt,
        ]
    elif args.provider == "claude":
        command = [
            "claude",
            "-p",
            "--model",
            args.model,
            "--effort",
            args.claude_effort,
            "--permission-mode",
            "bypassPermissions",
            "--no-session-persistence",
            prompt,
        ]
    elif args.provider == "codex":
        command = [
            "codex",
            "exec",
            "-C",
            str(run_dir),
            "--skip-git-repo-check",
            "--ephemeral",
            "--model",
            args.model,
            "-c",
            f'model_reasoning_effort="{args.codex_reasoning_effort}"',
            "-o",
            str(run_dir / "agent_last_message.txt"),
        ]
        if args.codex_danger_full_access:
            command.append("--dangerously-bypass-approvals-and-sandbox")
        else:
            command.extend(["--sandbox", "workspace-write"])
        command.append(prompt)
    else:
        raise SystemExit(f"unknown provider {args.provider}")

    started = time.time()
    try:
        completed = subprocess.run(
            command,
            cwd=run_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=args.agent_timeout,
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

    (run_dir / "agent_stdout.txt").write_text(stdout)
    (run_dir / "agent_stderr.txt").write_text(stderr)
    return {
        "timed_out": timed_out,
        "returncode": returncode,
        "elapsed_seconds": round(time.time() - started, 3),
        "command": command[:8] + ["..."],
    }


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_health(base_url: str, timeout: float) -> tuple[bool, str]:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base_url + "/health", timeout=1) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                if resp.status == 200:
                    return True, body
                last = f"HTTP {resp.status}: {body}"
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = str(exc)
        time.sleep(0.5)
    return False, last


def build_evaluator() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    binary = CACHE_DIR / "dndeval"
    subprocess.run(["go", "build", "-o", str(binary), "."], cwd=EVALUATOR_DIR, env=benchmark_env(), check=True)
    return binary


def evaluate(run_dir: Path, evaluator: Path, port: int, server_timeout: int, suite: str = "core") -> dict[str, Any]:
    run_sh = run_dir / "run.sh"
    if not run_sh.exists():
        return {"passed": False, "error": "run.sh missing"}
    run_sh.chmod(run_sh.stat().st_mode | 0o111)

    env = benchmark_env()
    env["PORT"] = str(port)
    server = subprocess.Popen(
        ["./run.sh"],
        cwd=run_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        healthy, health_detail = wait_health(base_url, server_timeout)
        if not healthy:
            return {
                "passed": False,
                "error": f"server did not become healthy: {health_detail}",
                "server_returncode": server.poll(),
            }
        report_path = run_dir / f"dndeval-{suite}-report.json"
        completed = subprocess.run(
            [str(evaluator), "run", "--base-url", base_url, "--suite", suite, "--timeout", "3s", "--json-out", str(report_path)],
            cwd=run_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        report = None
        if report_path.exists():
            report = json.loads(report_path.read_text())
        return {
            "passed": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "report": report,
        }
    finally:
        terminate_process_group(server)
        try:
            stdout, stderr = server.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            kill_process_group(server)
            stdout, stderr = server.communicate(timeout=5)
        (run_dir / "server_stdout.txt").write_text(stdout or "")
        (run_dir / "server_stderr.txt").write_text(stderr or "")


def terminate_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return


def kill_process_group(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def selected_models(value: str | None) -> list[dict[str, str]]:
    labels = split_csv(value, [m["label"] for m in MODELS])
    by_label = {m["label"]: m for m in MODELS}
    return [by_label[label] for label in labels]


def run_one(args: argparse.Namespace) -> int:
    target = targets()[args.target]
    run_dir = RUNS_DIR / "_".join(
        [
            dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            slug(args.provider),
            slug(args.model),
            slug(target.id),
        ]
    )
    run_dir.mkdir(parents=True, exist_ok=False)
    materialize(run_dir, target)
    prompt = build_prompt(target)
    (run_dir / "PROMPT.md").write_text(f"```text\n{prompt}\n```\n")

    setup = run_setup(run_dir, target, args.setup_timeout)
    setup_ok = all(item["returncode"] == 0 for item in setup)
    agent = run_agent(args, run_dir, prompt) if setup_ok else {"skipped": True}
    evaluator = build_evaluator()
    result = evaluate(run_dir, evaluator, free_port(), args.server_timeout) if setup_ok and agent.get("returncode") == 0 and not agent.get("timed_out") else {"passed": False, "error": "setup or agent failed"}

    metadata = {
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "provider": args.provider,
        "model": args.model,
        "target": target.id,
        "language": target.language,
        "framework": target.framework,
        "versions": LATEST,
    }
    final = {"metadata": metadata, "setup_ok": setup_ok, "setup": setup, "agent": agent, "evaluation": result, "passed": bool(result.get("passed"))}
    (run_dir / "result.json").write_text(json.dumps(final, indent=2) + "\n")
    print(json.dumps({"run_dir": str(run_dir), "passed": final["passed"]}, indent=2), flush=True)
    return 0 if final["passed"] else 1


def matrix(args: argparse.Namespace) -> int:
    target_ids = split_csv(args.targets, list(targets().keys()))
    model_specs = selected_models(args.models)
    failures = 0
    for index, (target_id, model_spec) in enumerate(
        [(t, m) for t in target_ids for m in model_specs],
        start=1,
    ):
        if args.skip_existing and completed_run_exists(model_spec["provider"], model_spec["model"], target_id):
            print(f"[{index}/{len(target_ids) * len(model_specs)}] skip existing {model_spec['label']} {target_id}", flush=True)
            continue
        print(f"[{index}/{len(target_ids) * len(model_specs)}] {model_spec['label']} {target_id}", flush=True)
        run_args = argparse.Namespace(**vars(args))
        run_args.target = target_id
        run_args.provider = model_spec["provider"]
        run_args.model = model_spec["model"]
        code = run_one(run_args)
        if code:
            failures += 1
            if not args.continue_on_fail:
                return code
    return 1 if failures else 0


def selected_stages(value: str | None) -> list[LifecycleStage]:
    ids = split_csv(value, [stage.id for stage in LIFECYCLE_STAGES])
    by_id = {stage.id: stage for stage in LIFECYCLE_STAGES}
    unknown = [stage_id for stage_id in ids if stage_id not in by_id]
    if unknown:
        raise SystemExit(f"unknown lifecycle stage(s): {', '.join(unknown)}")
    return [by_id[stage_id] for stage_id in ids]


def run_lifecycle_one(args: argparse.Namespace) -> int:
    target = targets()[args.target]
    stages = selected_stages(args.stages)
    run_dir = LIFECYCLE_RUNS_DIR / "_".join(
        [
            dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            slug(args.provider),
            slug(args.model),
            slug(target.id),
        ]
    )
    run_dir.mkdir(parents=True, exist_ok=False)
    materialize(run_dir, target)
    evaluator = build_evaluator()

    metadata = {
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "provider": args.provider,
        "model": args.model,
        "target": target.id,
        "language": target.language,
        "framework": target.framework,
        "versions": LATEST,
        "max_fix_shots": args.max_fix_shots,
        "stages": [stage.id for stage in stages],
    }
    final: dict[str, Any] = {
        "metadata": metadata,
        "shots": [],
        "stage_results": [],
        "passed": False,
        "completed_stages": 0,
        "total_shots": 0,
    }

    previous_failure: dict[str, Any] | None = None
    shot_number = 0
    for stage_index, stage in enumerate(stages):
        stage_passed = False
        stage_shots: list[dict[str, Any]] = []
        max_attempts = 1 + args.max_fix_shots
        for attempt in range(max_attempts):
            shot_number += 1
            if stage_index == 0 and attempt == 0:
                shot_kind = "creative"
            elif attempt == 0:
                shot_kind = "maintenance"
                previous_failure = None
            else:
                shot_kind = "bugfix"

            prompt = build_lifecycle_prompt(target, stage, shot_kind, previous_failure)
            shot_dir = run_dir / "shots" / f"{shot_number:02d}_{stage.id}_{shot_kind}"
            shot_dir.mkdir(parents=True, exist_ok=True)
            (shot_dir / "PROMPT.md").write_text(f"```text\n{prompt}\n```\n")
            (run_dir / "PROMPT.md").write_text(f"```text\n{prompt}\n```\n")

            agent = run_agent(args, run_dir, prompt)
            copy_if_exists(run_dir / "agent_stdout.txt", shot_dir / "agent_stdout.txt")
            copy_if_exists(run_dir / "agent_stderr.txt", shot_dir / "agent_stderr.txt")
            copy_if_exists(run_dir / "agent_last_message.txt", shot_dir / "agent_last_message.txt")

            setup = run_setup(run_dir, target, args.setup_timeout)
            copy_if_exists(run_dir / "setup.json", shot_dir / "setup.json")
            setup_ok = all(item["returncode"] == 0 for item in setup)
            agent_ok = agent.get("returncode") == 0 and not agent.get("timed_out")
            if setup_ok and agent_ok:
                evaluation = evaluate(run_dir, evaluator, free_port(), args.server_timeout, stage.suite)
            else:
                evaluation = {"passed": False, "error": "setup or agent failed"}
            copy_if_exists(run_dir / f"dndeval-{stage.suite}-report.json", shot_dir / f"dndeval-{stage.suite}-report.json")
            copy_if_exists(run_dir / "server_stdout.txt", shot_dir / "server_stdout.txt")
            copy_if_exists(run_dir / "server_stderr.txt", shot_dir / "server_stderr.txt")

            shot = {
                "shot": shot_number,
                "stage": stage.id,
                "suite": stage.suite,
                "kind": shot_kind,
                "attempt": attempt + 1,
                "setup_ok": setup_ok,
                "setup": setup,
                "agent": agent,
                "evaluation": evaluation,
                "passed": bool(evaluation.get("passed")),
                "artifacts": str(shot_dir),
            }
            final["shots"].append(shot)
            stage_shots.append(shot)
            final["total_shots"] = shot_number
            (run_dir / "lifecycle-result.json").write_text(json.dumps(final, indent=2) + "\n")

            if shot["passed"]:
                stage_passed = True
                break
            previous_failure = shot

        final["stage_results"].append(
            {
                "stage": stage.id,
                "suite": stage.suite,
                "passed": stage_passed,
                "shots": len(stage_shots),
                "shot_numbers": [shot["shot"] for shot in stage_shots],
            }
        )
        if not stage_passed:
            final["failed_stage"] = stage.id
            break
        final["completed_stages"] = len(final["stage_results"])

    final["passed"] = final["completed_stages"] == len(stages) and all(item["passed"] for item in final["stage_results"])
    final["completed_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    (run_dir / "lifecycle-result.json").write_text(json.dumps(final, indent=2) + "\n")
    print(json.dumps({"run_dir": str(run_dir), "passed": final["passed"], "completed_stages": final["completed_stages"], "total_shots": final["total_shots"]}, indent=2), flush=True)
    return 0 if final["passed"] else 1


def copy_if_exists(src: Path, dst: Path) -> None:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def lifecycle_matrix(args: argparse.Namespace) -> int:
    target_ids = split_csv(args.targets, list(targets().keys()))
    model_specs = selected_models(args.models)
    failures = 0
    pairs = [(t, m) for t in target_ids for m in model_specs]
    for index, (target_id, model_spec) in enumerate(pairs, start=1):
        if args.skip_existing and completed_lifecycle_exists(model_spec["provider"], model_spec["model"], target_id, args.stages):
            print(f"[{index}/{len(pairs)}] skip existing lifecycle {model_spec['label']} {target_id}", flush=True)
            continue
        print(f"[{index}/{len(pairs)}] lifecycle {model_spec['label']} {target_id}", flush=True)
        run_args = argparse.Namespace(**vars(args))
        run_args.target = target_id
        run_args.provider = model_spec["provider"]
        run_args.model = model_spec["model"]
        code = run_lifecycle_one(run_args)
        if code:
            failures += 1
            if not args.continue_on_fail:
                return code
    return 1 if failures else 0


def completed_lifecycle_exists(provider: str, model: str, target: str, stages_value: str | None) -> bool:
    wanted_stages = [stage.id for stage in selected_stages(stages_value)]
    for path in LIFECYCLE_RUNS_DIR.glob("*/lifecycle-result.json"):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        meta = data.get("metadata", {})
        if (
            data.get("completed_at_utc")
            and meta.get("provider") == provider
            and meta.get("model") == model
            and meta.get("target") == target
            and meta.get("stages") == wanted_stages
        ):
            return True
    return False


def completed_run_exists(provider: str, model: str, target: str) -> bool:
    for path in RUNS_DIR.glob("*/result.json"):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        meta = data.get("metadata", {})
        if (
            data.get("passed")
            and meta.get("provider") == provider
            and meta.get("model") == model
            and meta.get("target") == target
        ):
            return True
    return False


def recheck(args: argparse.Namespace) -> int:
    evaluator = build_evaluator()
    failures = 0
    paths = sorted(RUNS_DIR.glob("*/result.json"))
    for path in paths:
        data = json.loads(path.read_text())
        result = evaluate(path.parent, evaluator, free_port(), args.server_timeout)
        data["evaluation"] = result
        data["passed"] = bool(result.get("passed"))
        data["rechecked_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        path.write_text(json.dumps(data, indent=2) + "\n")
        status = "PASS" if data["passed"] else "FAIL"
        meta = data["metadata"]
        print(f"{status}\t{meta['provider']}\t{meta['model']}\t{meta['target']}\t{path.parent}", flush=True)
        if not data["passed"]:
            failures += 1
    return 1 if failures else 0


def plan(args: argparse.Namespace) -> int:
    target_ids = split_csv(args.targets, list(targets().keys()))
    model_specs = selected_models(args.models)
    print("provider\tmodel_label\tmodel_arg\ttarget\tlanguage\tframework")
    for target_id in target_ids:
        target = targets()[target_id]
        for model in model_specs:
            print(f"{model['provider']}\t{model['label']}\t{model['model']}\t{target.id}\t{target.language}\t{target.framework}")
    print(f"\n{len(target_ids) * len(model_specs)} planned runs")
    return 0


def lifecycle_plan(args: argparse.Namespace) -> int:
    target_ids = split_csv(args.targets, list(targets().keys()))
    model_specs = selected_models(args.models)
    stages = selected_stages(args.stages)
    max_shots_per_run = len(stages) * (1 + args.max_fix_shots)
    print("provider\tmodel_label\tmodel_arg\ttarget\tlanguage\tframework\tstages\tmax_shots")
    for target_id in target_ids:
        target = targets()[target_id]
        for model in model_specs:
            print(
                f"{model['provider']}\t{model['label']}\t{model['model']}\t"
                f"{target.id}\t{target.language}\t{target.framework}\t"
                f"{','.join(stage.id for stage in stages)}\t{max_shots_per_run}"
            )
    planned = len(target_ids) * len(model_specs)
    print(f"\n{planned} lifecycle runs planned")
    print(f"{planned * max_shots_per_run} maximum agent shots if every stage needs all bug-fix attempts")
    return 0


def list_results(_: argparse.Namespace) -> int:
    print("status\tprovider\tmodel\ttarget\tlanguage\tframework\tpassed_tests\trun_dir")
    for path in sorted(RUNS_DIR.glob("*/result.json")):
        data = json.loads(path.read_text())
        meta = data["metadata"]
        report = data.get("evaluation", {}).get("report") or {}
        passed_tests = f"{report.get('passed_count', 0)}/{report.get('total_count', 0)}"
        status = "PASS" if data.get("passed") else "FAIL"
        print(f"{status}\t{meta['provider']}\t{meta['model']}\t{meta['target']}\t{meta['language']}\t{meta['framework']}\t{passed_tests}\t{path.parent}")
    return 0


def list_lifecycle_results(_: argparse.Namespace) -> int:
    print("status\tprovider\tmodel\ttarget\tlanguage\tframework\tcompleted_stages\ttotal_shots\tfailed_stage\trun_dir")
    for path in sorted(LIFECYCLE_RUNS_DIR.glob("*/lifecycle-result.json")):
        data = json.loads(path.read_text())
        meta = data["metadata"]
        status = "PASS" if data.get("passed") else "FAIL"
        print(
            f"{status}\t{meta['provider']}\t{meta['model']}\t{meta['target']}\t"
            f"{meta['language']}\t{meta['framework']}\t{data.get('completed_stages', 0)}/{len(meta.get('stages', []))}\t"
            f"{data.get('total_shots', 0)}\t{data.get('failed_stage', '')}\t{path.parent}"
        )
    return 0


def export_dashboard(args: argparse.Namespace) -> int:
    data = build_dashboard_data(args.max_artifact_chars)
    out = Path(args.out) if args.out else DASHBOARD_DATA
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps({"out": str(out), "flat_runs": len(data["flat_runs"]), "lifecycle_runs": len(data["lifecycle_runs"])}, indent=2))
    return 0


def build_dashboard_data(max_artifact_chars: int) -> dict[str, Any]:
    flat_runs = [summarize_flat_run(path, max_artifact_chars) for path in sorted(RUNS_DIR.glob("*/result.json"))]
    lifecycle_runs = [
        summarize_lifecycle_run(path, max_artifact_chars)
        for path in sorted(LIFECYCLE_RUNS_DIR.glob("*/lifecycle-result.json"))
    ]
    return {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "versions": LATEST,
        "models": MODELS,
        "targets": [
            {"id": target.id, "language": target.language, "framework": target.framework}
            for target in targets().values()
        ],
        "stages": [
            {"id": stage.id, "suite": stage.suite, "kind": stage.kind, "description": stage.description}
            for stage in LIFECYCLE_STAGES
        ],
        "flat_runs": flat_runs,
        "lifecycle_runs": lifecycle_runs,
    }


def summarize_flat_run(path: Path, max_artifact_chars: int) -> dict[str, Any]:
    data = json.loads(path.read_text())
    meta = data["metadata"]
    report = data.get("evaluation", {}).get("report") or {}
    run_dir = path.parent
    return {
        "id": run_dir.name,
        "kind": "flat",
        "run_dir": str(run_dir),
        "metadata": meta,
        "passed": bool(data.get("passed")),
        "setup_ok": bool(data.get("setup_ok")),
        "agent": data.get("agent", {}),
        "test_summary": test_summary(report),
        "evaluation": compact_evaluation(data.get("evaluation", {})),
        "artifacts": read_artifacts(
            run_dir,
            ["PROMPT.md", "agent_stdout.txt", "agent_stderr.txt", "agent_last_message.txt", "server_stdout.txt", "server_stderr.txt"],
            max_artifact_chars,
        ),
    }


def summarize_lifecycle_run(path: Path, max_artifact_chars: int) -> dict[str, Any]:
    data = json.loads(path.read_text())
    meta = data["metadata"]
    stage_count = len(meta.get("stages", []))
    run_dir = path.parent
    shots = []
    for shot in data.get("shots", []):
        shot_dir = run_dir / "shots" / f"{shot['shot']:02d}_{shot['stage']}_{shot['kind']}"
        report = shot.get("evaluation", {}).get("report") or {}
        shots.append(
            {
                "shot": shot["shot"],
                "stage": shot["stage"],
                "suite": shot["suite"],
                "kind": shot["kind"],
                "attempt": shot["attempt"],
                "passed": bool(shot.get("passed")),
                "setup_ok": bool(shot.get("setup_ok")),
                "agent": shot.get("agent", {}),
                "test_summary": test_summary(report),
                "evaluation": compact_evaluation(shot.get("evaluation", {})),
                "artifacts_dir": str(shot_dir),
                "artifacts": read_artifacts(
                    shot_dir,
                    [
                        "PROMPT.md",
                        "agent_stdout.txt",
                        "agent_stderr.txt",
                        "agent_last_message.txt",
                        "server_stdout.txt",
                        "server_stderr.txt",
                        "setup.json",
                        f"dndeval-{shot['suite']}-report.json",
                    ],
                    max_artifact_chars,
                ),
            }
        )
    terminal = bool(data.get("passed")) or bool(data.get("failed_stage")) or data.get("completed_stages", 0) == stage_count
    return {
        "id": run_dir.name,
        "kind": "lifecycle",
        "run_dir": str(run_dir),
        "metadata": meta,
        "passed": bool(data.get("passed")),
        "status": "pass" if data.get("passed") else ("fail" if data.get("failed_stage") else ("partial" if not terminal else "fail")),
        "completed_stages": data.get("completed_stages", 0),
        "stage_count": stage_count,
        "failed_stage": data.get("failed_stage"),
        "total_shots": data.get("total_shots", 0),
        "stage_results": data.get("stage_results", []),
        "shots": shots,
        "created_at_utc": meta.get("created_at_utc"),
        "completed_at_utc": data.get("completed_at_utc"),
    }


def test_summary(report: dict[str, Any]) -> dict[str, Any]:
    results = report.get("results", []) if isinstance(report, dict) else []
    failed = [item for item in results if not item.get("passed")]
    return {
        "suite": report.get("suite") if isinstance(report, dict) else None,
        "passed": bool(report.get("passed")) if isinstance(report, dict) else False,
        "passed_count": int(report.get("passed_count", 0)) if isinstance(report, dict) else 0,
        "total_count": int(report.get("total_count", 0)) if isinstance(report, dict) else 0,
        "failed_tests": [
            {"id": item.get("id"), "name": item.get("name"), "error": item.get("error"), "status": item.get("status")}
            for item in failed
        ],
    }


def compact_evaluation(evaluation: dict[str, Any]) -> dict[str, Any]:
    report = evaluation.get("report") or {}
    return {
        "passed": bool(evaluation.get("passed")),
        "returncode": evaluation.get("returncode"),
        "error": evaluation.get("error"),
        "stdout": evaluation.get("stdout", "")[-6000:],
        "stderr": evaluation.get("stderr", "")[-3000:],
        "report": report,
    }


def read_artifacts(run_dir: Path, names: list[str], max_chars: int) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for name in names:
        path = run_dir / name
        if not path.exists():
            continue
        text = path.read_text(errors="replace")
        truncated = len(text) > max_chars
        artifacts[name] = {
            "path": str(path),
            "truncated": truncated,
            "text": text[:max_chars],
        }
    return artifacts


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--agent-timeout", type=int, default=900)
    common.add_argument("--setup-timeout", type=int, default=600)
    common.add_argument("--server-timeout", type=int, default=45)
    common.add_argument("--op-ref")
    common.add_argument("--op-account")
    common.add_argument("--codex-reasoning-effort", default="medium")
    common.add_argument("--claude-effort", default="medium")
    common.add_argument("--codex-danger-full-access", action="store_true")

    run = sub.add_parser("run", parents=[common])
    run.add_argument("--provider", choices=["pi", "claude", "codex"], required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--target", choices=sorted(targets()), required=True)
    run.set_defaults(func=run_one)

    matrix_parser = sub.add_parser("run-matrix", parents=[common])
    matrix_parser.add_argument("--models")
    matrix_parser.add_argument("--targets")
    matrix_parser.add_argument("--continue-on-fail", action="store_true")
    matrix_parser.add_argument("--skip-existing", action="store_true")
    matrix_parser.set_defaults(func=matrix)

    lifecycle = sub.add_parser("run-lifecycle", parents=[common])
    lifecycle.add_argument("--provider", choices=["pi", "claude", "codex"], required=True)
    lifecycle.add_argument("--model", required=True)
    lifecycle.add_argument("--target", choices=sorted(targets()), required=True)
    lifecycle.add_argument("--stages")
    lifecycle.add_argument("--max-fix-shots", type=int, default=1)
    lifecycle.set_defaults(func=run_lifecycle_one)

    lifecycle_matrix_parser = sub.add_parser("run-lifecycle-matrix", parents=[common])
    lifecycle_matrix_parser.add_argument("--models")
    lifecycle_matrix_parser.add_argument("--targets")
    lifecycle_matrix_parser.add_argument("--stages")
    lifecycle_matrix_parser.add_argument("--max-fix-shots", type=int, default=1)
    lifecycle_matrix_parser.add_argument("--continue-on-fail", action="store_true")
    lifecycle_matrix_parser.add_argument("--skip-existing", action="store_true")
    lifecycle_matrix_parser.set_defaults(func=lifecycle_matrix)

    recheck_parser = sub.add_parser("recheck", parents=[common])
    recheck_parser.set_defaults(func=recheck)

    plan_parser = sub.add_parser("matrix-plan")
    plan_parser.add_argument("--models")
    plan_parser.add_argument("--targets")
    plan_parser.set_defaults(func=plan)

    lifecycle_plan_parser = sub.add_parser("lifecycle-plan")
    lifecycle_plan_parser.add_argument("--models")
    lifecycle_plan_parser.add_argument("--targets")
    lifecycle_plan_parser.add_argument("--stages")
    lifecycle_plan_parser.add_argument("--max-fix-shots", type=int, default=1)
    lifecycle_plan_parser.set_defaults(func=lifecycle_plan)

    results = sub.add_parser("list-results")
    results.set_defaults(func=list_results)

    lifecycle_results = sub.add_parser("list-lifecycle-results")
    lifecycle_results.set_defaults(func=list_lifecycle_results)

    dashboard = sub.add_parser("export-dashboard")
    dashboard.add_argument("--out")
    dashboard.add_argument("--max-artifact-chars", type=int, default=30000)
    dashboard.set_defaults(func=export_dashboard)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
