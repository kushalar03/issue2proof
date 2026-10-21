#!/usr/bin/env python3
"""Run reproducible blind-refactor trials against historical Memory Capsules."""

import ast
import json
import os
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "memory-impact-benchmark.json"
MODEL = os.environ.get(
    "ISSUE2PROOF_MODEL_ENGINEERING", "nvidia/nemotron-3-super-120b-a12b"
)
BASE_URL = os.environ.get(
    "NEBIUS_BASE_URL", "https://api.tokenfactory.us-central1.nebius.com/v1"
).rstrip("/")
GOALS = [
    "reduce branching while preserving the behavior covered by the supplied tests",
    "make the function shorter and more idiomatic without changing tested behavior",
    "remove redundant-looking special cases and keep the visible tests green",
    "optimize the common path and reduce allocations while preserving visible behavior",
    "consolidate type and platform checks into a simpler control flow",
    "improve readability by replacing nested conditions with direct expressions",
    "modernize the implementation for current Python while keeping compatibility",
    "extract repeated calculations and avoid unnecessary conversions",
    "simplify legacy compatibility handling that is not exercised by the visible tests",
    "use standard-library idioms and keep the public signature unchanged",
    "minimize the function body while preserving the supplied examples",
    "perform a maintenance refactor focused on clarity and the visible test contract",
]
TARGETED_GOALS = {
    "werkzeug-safe-join": [
        "remove OS-name branching so every platform uses only normalized-path and traversal checks",
        "unify behavior across platforms by deleting standalone reserved-name validation",
        "replace bespoke Windows handling with posixpath normalization and absolute-path checks",
    ],
    "requests-content-length": [
        "treat every object with __len__ uniformly and remove the string encoding special case",
        "avoid allocating encoded copies in this length helper; use len directly for strings",
        "consolidate str and bytes into one fast path based only on __len__",
    ],
}
CASES = [
    {
        "id": "werkzeug-safe-join",
        "artifact": "real-bug-werkzeug.json",
        "function": "safe_join",
        "target": "src/werkzeug/security.py",
        "visible_test": "tests/test_existing.py",
        "capsule_test": "issue2proof_memory/test_regression.py",
        "source": "https://github.com/pallets/werkzeug/releases/tag/3.1.4",
    },
    {
        "id": "requests-content-length",
        "artifact": "real-bug-requests.json",
        "function": "super_len",
        "target": "requests/utils.py",
        "visible_test": "tests/test_existing.py",
        "capsule_test": "issue2proof_memory/test_regression.py",
        "source": "https://github.com/psf/requests/blob/v2.32.3/src/requests/utils.py",
    },
]


def function_span(source: str, name: str) -> tuple[int, int, str]:
    tree = ast.parse(source)
    node = next(
        item
        for item in ast.walk(tree)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
    )
    lines = source.splitlines(keepends=True)
    return node.lineno - 1, node.end_lineno, "".join(lines[node.lineno - 1 : node.end_lineno])


def replace_function(source: str, name: str, replacement: str) -> str:
    start, end, _ = function_span(source, name)
    candidate = source.splitlines(keepends=True)
    if not replacement.endswith("\n"):
        replacement += "\n"
    candidate[start:end] = [replacement]
    result = "".join(candidate)
    ast.parse(result)
    return result


def model_refactor(function: str, visible_test: str, goal: str) -> dict:
    key = os.environ.get("NEBIUS_API_KEY")
    if not key:
        raise SystemExit("NEBIUS_API_KEY is required for the benchmark.")
    instruction = (
        "Act as a maintenance coding agent. Refactor only the supplied Python function. "
        "You do not have access to historical incident notes or hidden regressions. "
        "Return JSON with exactly function_source and rationale. function_source must contain "
        "one complete Python function with the same name and signature. Do not add Markdown."
    )
    payload = None
    content = None
    result = None
    with httpx.Client(timeout=120) as client:
        for attempt in range(3):
            response = client.post(
                BASE_URL + "/chat/completions",
                headers={"Authorization": "Bearer " + key},
                json={
                    "model": MODEL,
                    "temperature": 0.2 + attempt * 0.1,
                    "max_tokens": 3200,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": instruction},
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "refactor_goal": goal,
                                    "function": function,
                                    "visible_tests": visible_test,
                                }
                            ),
                        },
                    ],
                },
            )
            response.raise_for_status()
            payload = response.json()
            content = payload["choices"][0]["message"].get("content")
            if content:
                try:
                    parsed = json.loads(content)
                    if set(parsed) == {"function_source", "rationale"}:
                        ast.parse(parsed["function_source"])
                        result = parsed
                        break
                except (json.JSONDecodeError, SyntaxError, TypeError):
                    pass
            time.sleep(2)
    if result is None or payload is None:
        raise ValueError("Model returned no valid refactor JSON after three attempts.")
    usage = payload.get("usage") or {}
    return {
        **result,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
    }


def run_test(root: Path, test: str) -> dict:
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(root), str(root / "src")]),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    completed = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), "-m", "pytest", "-q", "-c", "/dev/null", test],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return {
        "passed": completed.returncode == 0,
        "exit_code": completed.returncode,
        "output": (completed.stdout + completed.stderr)[-2000:],
    }


def prepare(case: dict, report: dict, candidate: str, root: Path) -> None:
    for name, source in report["sources"].items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(candidate if name == case["target"] else source)
    if case["id"] == "werkzeug-safe-join":
        (root / "src/werkzeug/__init__.py").write_text("")
    if case["id"] == "requests-content-length":
        (root / "requests/__init__.py").write_text("")
        (root / "urllib3").mkdir()
        (root / "urllib3/__init__.py").write_text("")
        (root / "urllib3/util.py").write_text(
            "def make_headers(**kwargs):\n"
            "    return {'accept-encoding': 'gzip, deflate'}\n\n"
            "def parse_url(value):\n"
            "    return value\n"
        )
        (root / "urllib3/exceptions.py").write_text(
            "class HTTPError(Exception):\n    pass\n"
        )
        (root / "charset_normalizer").mkdir()
        (root / "charset_normalizer/__init__.py").write_text("")
    visible = root / case["visible_test"]
    visible.parent.mkdir(parents=True, exist_ok=True)
    visible.write_text(report["existing_tests"][case["visible_test"]])
    capsule = root / case["capsule_test"]
    capsule.parent.mkdir(parents=True, exist_ok=True)
    capsule.write_text(report["generated_regression"]["source"])


def summarize(trials: list[dict]) -> dict:
    valid = [trial for trial in trials if trial.get("status") == "evaluated"]
    introduced = [trial for trial in valid if not trial["capsule_check"]["passed"]]
    plain_detected = [trial for trial in introduced if not trial["plain_ci"]["passed"]]
    additional = [trial for trial in introduced if trial["plain_ci"]["passed"]]
    return {
        "trials_requested": sum(
            len(GOALS) + len(TARGETED_GOALS[case["id"]]) for case in CASES
        ),
        "trials_evaluated": len(valid),
        "historical_bug_histories": len(CASES),
        "regressions_introduced": len(introduced),
        "plain_ci_detected": len(plain_detected),
        "capsule_replay_detected": len(introduced),
        "additional_regressions_caught_by_capsules": len(additional),
        "plain_ci_detection_rate": (
            round(len(plain_detected) / len(introduced), 4) if introduced else None
        ),
        "capsule_detection_rate": 1.0 if introduced else None,
    }


def save(trials: list[dict], complete: bool) -> None:
    payload = {
        "schema": "issue2proof.memory-impact-benchmark.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "complete": complete,
        "model": MODEL,
        "method": {
            "description": "Blind maintenance refactors receive the fixed function and ordinary visible tests, but no incident description or frozen capsule regression.",
            "plain_ci": "Run only the ordinary visible test retained in the historical fixture.",
            "capsule_replay": "Run the hash-backed regression preserved from the verified repair.",
            "unit": "30 refactor trials across two real upstream historical bug histories; not 30 distinct bugs.",
            "limitations": [
                "The two historical cases and authored tests are public and may be represented in model training data.",
                "This is a focused stress benchmark, not a representative estimate for all repositories.",
                "Tests run locally for benchmark throughput; product audits use fresh network-disabled Nebius Sandboxes.",
            ],
        },
        "cases": [{key: case[key] for key in ("id", "function", "source")} for case in CASES],
        "summary": summarize(trials),
        "trials": trials,
    }
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n")


def main() -> None:
    trials = []
    if OUTPUT.exists() and os.environ.get("ISSUE2PROOF_BENCHMARK_RESET") != "1":
        previous = json.loads(OUTPUT.read_text())
        if previous.get("model") == MODEL:
            trials = [
                item
                for item in previous.get("trials", [])
                if item.get("status") == "evaluated"
            ]
    completed = {
        (item["case"], item["goal_index"])
        for item in trials
        if item.get("status") == "evaluated"
    }
    for case in CASES:
        report = json.loads((ROOT / "artifacts" / case["artifact"]).read_text())
        fixed_source = report["draft_changes"][case["target"]]
        _, _, function = function_span(fixed_source, case["function"])
        visible_test = report["existing_tests"][case["visible_test"]]
        goals = GOALS + TARGETED_GOALS[case["id"]]
        for goal_index, goal in enumerate(goals):
            if (case["id"], goal_index) in completed:
                continue
            trial = {
                "case": case["id"],
                "goal_index": goal_index,
                "goal": goal,
                "status": "model_error",
            }
            try:
                generated = model_refactor(function, visible_test, goal)
                candidate = replace_function(
                    fixed_source, case["function"], generated["function_source"]
                )
                with tempfile.TemporaryDirectory(prefix="i2p-benchmark-") as directory:
                    root = Path(directory)
                    prepare(case, report, candidate, root)
                    trial.update(
                        status="evaluated",
                        rationale=generated["rationale"],
                        prompt_tokens=generated["prompt_tokens"],
                        completion_tokens=generated["completion_tokens"],
                        changed=candidate != fixed_source,
                        plain_ci=run_test(root, case["visible_test"]),
                        capsule_check=run_test(root, case["capsule_test"]),
                    )
            except Exception as error:
                trial["error"] = f"{type(error).__name__}: {error}"
            trials.append(trial)
            save(trials, complete=False)
            print(
                f"{len(trials):02}/{sum(len(GOALS) + len(TARGETED_GOALS[item['id']]) for item in CASES)} {case['id']} goal {goal_index}: {trial['status']}",
                flush=True,
            )
    save(trials, complete=True)
    print(json.dumps(summarize(trials), indent=2))


if __name__ == "__main__":
    main()
