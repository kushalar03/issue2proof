"""Checkpointed reproduce-first investigations with bounded candidate revisions."""

import ast
import hashlib
import json
from dataclasses import replace

from .draft import RepositoryProvider, python_source, unified_patch
from .environments import build_environment
from .execution import SandboxExecutor
from .sandbox import SandboxConfig


def investigate(report, options, context, provider=None, executor=None, config=None):
    context.check()
    if report.get("error_type"):
        report.setdefault("prior_errors", []).append(
            {
                "type": report.pop("error_type"),
                "explanation": report.get("explanation"),
                "recovered_by": "explicit resume",
            }
        )
    for name, source in {
        **report["sources"],
        **report["existing_tests"],
        **report.get("resources", {}),
        **report.get("dependency_manifests", {}),
    }.items():
        if hashlib.sha256(source.encode()).hexdigest() != report["file_hashes"].get(
            name
        ):
            raise ValueError("Original project files changed after inspection.")
    config = config or SandboxConfig.from_env()
    report.setdefault("pipeline", {})
    report.setdefault("model_requests", [])
    report.setdefault("attempts", [])
    report["independent_test_paths"] = options["independent_test_paths"]
    independent = {
        name: source
        for name, source in report["existing_tests"].items()
        if name in options["independent_test_paths"]
    }
    ordinary = {
        name: source
        for name, source in report["existing_tests"].items()
        if name not in independent
    }
    if not ordinary or not independent:
        raise ValueError(
            "Keep ordinary tests and reserve at least one independent test."
        )
    report["test_hashes"] = {
        name: hashlib.sha256(source.encode()).hexdigest()
        for name, source in report["existing_tests"].items()
    }

    def checkpoint(stage):
        report.update(
            verdict="running", explanation=stage.replace("_", " ").capitalize() + "."
        )
        context.save(report, stage)

    def passed(check):
        return (
            check.get("evidence_valid") is True
            and check["exit_code"] == 0
            and check["summary"]["tests"] > check["summary"].get("skipped", 0)
        )

    def model(instruction, payload, *, role="engineering"):
        payload = json.loads(json.dumps(payload))
        if len(json.dumps(payload)) > 33000:
            payload["existing_tests"] = {}
            for previous in payload.get("previous_attempts", []):
                for key in ("diff", "regression", "existing"):
                    if isinstance(previous.get(key), str):
                        previous[key] = previous[key][-1000:]
        while len(json.dumps(payload)) > 33000:
            name = max(payload["sources"], key=lambda key: len(payload["sources"][key]))
            source = payload["sources"][name]
            if len(source) < 1000:
                raise ValueError(
                    "Issue and dependency context exceeds the bounded model window."
                )
            payload["sources"][name] = (
                source[: int(len(source) * 0.8)] + "\n# ... context excerpt ...\n"
            )
            if name not in payload.setdefault("excerpted_paths", []):
                payload["excerpted_paths"].append(name)
        fingerprint = hashlib.sha256(
            json.dumps(
                {"instruction": instruction, "payload": payload, "role": role},
                sort_keys=True,
            ).encode()
        ).hexdigest()
        cached = report.get("pending_model_response", {})
        if cached.get("fingerprint") == fingerprint:
            return cached["result"]
        reservation = context.reserve("model", role=role)
        response = provider.request(instruction, payload, role=role)
        context.reconcile(reservation, response.get("estimated_cost_usd"))
        report["model_requests"].append(
            {key: value for key, value in response.items() if key != "result"}
        )
        report.setdefault("model_outputs", []).append(response["result"])
        report["pending_model_response"] = {
            "fingerprint": fingerprint,
            "result": response["result"],
        }
        context.save(report, "model_response_received")
        return response["result"]

    if "environment" not in report:
        checkpoint("preparing_dependencies")
        if options["prepare_dependencies"]:
            config, report["environment"] = build_environment(report, config, context)
        else:
            report["environment"] = {
                "image": config.image,
                "prepared": False,
                "requirements": [],
                "policy": "Use selected immutable image.",
            }
        checkpoint("environment_ready")
    else:
        config = replace(config, image=report["environment"]["image"])
    own_executor = executor is None
    executor = executor or SandboxExecutor(config, context=context)
    provider = provider or RepositoryProvider()
    checks = report["pipeline"]

    def execute(sources, tests):
        context.check()
        files = {**report.get("resources", {}), **sources, **tests}
        if any(
            name.rsplit("/", 1)[-1] in {"pyproject.toml", "setup.py", "setup.cfg"}
            for name in report["dependency_manifests"]
        ):
            files.update(report["dependency_manifests"])
            return executor.execute(files, list(tests), install_project=True)
        return executor.execute(files, list(tests))

    try:
        for name, tests in [
            ("baseline", ordinary),
            ("independent_baseline", independent),
        ]:
            if name not in checks:
                checkpoint(name)
                checks[name] = execute(report["sources"], tests)
                if (
                    not checks[name].get("evidence_valid")
                    and checks[name].get("evidence_error")
                    in {
                        "sandbox_controller_failed",
                        "controller_evidence_invalid_json",
                        "project_install_failed",
                    }
                ):
                    checkpoint(name + "_retry")
                    checks[name] = execute(report["sources"], tests)
                checkpoint(name + "_complete")
            if (
                not checks[name].get("evidence_valid")
                or name == "baseline"
                and not passed(checks[name])
            ):
                report.update(
                    verdict="setup_failed",
                    explanation="Original test setup or existing suite failed. No repair request was made.",
                )
                return report
        payload = build_model_context(report, options)
        if "generated_regression" not in report:
            checkpoint("generating_reproduction")
            result = model(
                'Return exactly {"test_source": "pytest source or null", "clarification": "question or null"}. If behavior is ambiguous ask a concrete question with test_source=null. Otherwise provide a minimal focused pytest regression for the reported failure only. Do not duplicate unrelated existing-suite checks or invent extra behavior. Use Unicode literals directly when testing Unicode text. The sandbox is Linux/Python 3.12. Do not skip tests based on the host platform. For platform-specific logic, replace the target module-local OS reference with an appropriate test double; do not mutate global os.name. Use the project source layout and existing import style. Do not change implementation or existing tests.',
                {
                    **payload,
                    "reproduction_feedback": report.get("reproduction_feedback"),
                },
            )
            if (
                not isinstance(result, dict)
                or not result
                or not set(result).issubset({"test_source", "clarification"})
            ):
                raise ValueError("Invalid reproduction response.")
            result = {
                "test_source": result.get("test_source"),
                "clarification": result.get("clarification") or None,
            }
            if (
                result["test_source"] is None
                and isinstance(result["clarification"], str)
                and 0 < len(result["clarification"]) <= 1000
            ):
                report.update(
                    verdict="needs_clarification", explanation=result["clarification"]
                )
                return report
            tree = python_source(result["test_source"])
            if result["clarification"] is not None or not any(
                isinstance(node, ast.FunctionDef)
                and node.name.startswith("test_")
                and any(isinstance(child, ast.Assert) for child in ast.walk(node))
                for node in tree.body
            ):
                raise ValueError(
                    "Reproduction must contain an assertion inside a test."
                )
            report["generated_regression"] = {
                "path": "issue2proof_generated/test_regression.py",
                "source": result["test_source"],
                "sha256": hashlib.sha256(result["test_source"].encode()).hexdigest(),
            }
            checkpoint("reproduction_frozen")
        regression = report["generated_regression"]
        if (
            hashlib.sha256(regression["source"].encode()).hexdigest()
            != regression["sha256"]
        ):
            raise ValueError("Frozen regression was modified.")
        report["test_hashes"][regression["path"]] = regression["sha256"]
        if "reproduction" not in checks:
            checkpoint("reproducing_original_failure")
            checks["reproduction"] = execute(
                report["sources"], {regression["path"]: regression["source"]}
            )
            checkpoint("reproduction_complete")
        reproduction = checks["reproduction"]
        if not (
            reproduction.get("evidence_valid")
            and reproduction["exit_code"] == 1
            and reproduction.get("assertion_failures", 0) > 0
            and reproduction["assertion_failures"]
            == reproduction["summary"]["failures"]
        ):
            if not report.get("reproduction_attempts"):
                report.setdefault("reproduction_attempts", []).append(
                    {"test": regression, "check": reproduction}
                )
                report["reproduction_feedback"] = {
                    "prior_test": regression["source"],
                    "output": reproduction.get("output", "")[-2000:],
                    "reason": "Reproduction must run on Linux without skips/setup errors and fail on an assertion for the reported bug.",
                }
                report.pop("generated_regression", None)
                checks.pop("reproduction", None)
                checkpoint("refining_unaccepted_reproduction")
                return investigate(
                    report,
                    options,
                    context,
                    provider=provider,
                    executor=executor,
                    config=config,
                )
            report.update(
                verdict="not_reproduced",
                explanation="Two reproduction attempts did not establish a clean original assertion failure. No repair request was made.",
            )
            return report
        report["events"].append(
            "Original assertion failure reproduced before requesting any repair."
        )
        for number in range(1, options["max_repairs"] + 1):
            if len(report["attempts"]) < number:
                checkpoint(f"generating_repair_{number}")
                feedback = []
                for previous in report["attempts"][-1:]:
                    # No independent test content, output or node names are sent back.
                    feedback.append(
                        {
                            "diff": previous.get("diff", "")[-4000:],
                            "regression": previous.get("checks", {})
                            .get("regression", {})
                            .get("output", "")[-2000:],
                            "existing": previous.get("checks", {})
                            .get("existing", {})
                            .get("output", "")[-2000:],
                            "independent_checks_passed": previous.get("checks", {})
                            .get("independent", {})
                            .get("exit_code")
                            == 0,
                            "rejection": previous.get("rejection"),
                        }
                    )
                result = model(
                    'Return exactly {"edits": [{"path": "existing implementation path", "old": "exact unique old source span", "new": "replacement span"}]}. Use at most ten edits across five implementation files, never tests/manifests/new paths. Old spans must match exactly once in the original sources provided in this request, never in a prior candidate. Repair the issue while preserving existing behavior. Revise prior failures using feedback. The regression is frozen.',
                    {
                        **payload,
                        "regression": regression["source"],
                        "previous_attempts": feedback,
                    },
                )
                attempt = {"number": number, "checks": {}, "accepted": False}
                report["attempts"].append(attempt)
                try:
                    if isinstance(result, dict) and set(result) == {"edits"}:
                        if (
                            not isinstance(result["edits"], list)
                            or not 1 <= len(result["edits"]) <= 10
                        ):
                            raise ValueError("Invalid edit list.")
                        changes = {}
                        for edit in result["edits"]:
                            if not isinstance(edit, dict) or set(edit) != {
                                "path",
                                "old",
                                "new",
                            }:
                                raise ValueError("Invalid edit schema.")
                            name = edit["path"]
                            if (
                                name not in payload["sources"]
                                or not isinstance(edit["old"], str)
                                or not edit["old"]
                                or not isinstance(edit["new"], str)
                            ):
                                raise ValueError("Invalid or protected edit path.")
                            original = changes.get(name, report["sources"][name])
                            if original.count(edit["old"]) != 1:
                                raise ValueError(
                                    "Edit must match one unique source span."
                                )
                            changes[name] = original.replace(
                                edit["old"], edit["new"], 1
                            )
                    elif (
                        isinstance(result, dict)
                        and set(result) == {"changes"}
                        and isinstance(result["changes"], dict)
                    ):
                        changes = result["changes"]
                        if any(
                            name in payload.get("excerpted_paths", [])
                            for name in changes
                        ):
                            raise ValueError(
                                "Use span edits for excerpted implementation files."
                            )
                    else:
                        raise ValueError("Invalid candidate schema.")
                    if not 1 <= len(changes) <= 5:
                        raise ValueError(
                            "Candidate must change one to five implementation files."
                        )
                    for name, source in changes.items():
                        if name not in payload["sources"]:
                            raise ValueError(
                                "Candidate modified a protected or unknown path."
                            )
                        python_source(source, limit=200000)
                    diff = "".join(
                        unified_patch(name, report["sources"][name], source)
                        for name, source in changes.items()
                    )
                    if not diff:
                        raise ValueError("Candidate made no implementation changes.")
                    attempt.update(
                        changes=changes,
                        diff=diff,
                        hashes={
                            name: hashlib.sha256(source.encode()).hexdigest()
                            for name, source in changes.items()
                        },
                    )
                except ValueError as error:
                    attempt["rejection"] = str(error)
                checkpoint(f"repair_{number}_generated")
            attempt = report["attempts"][number - 1]
            if attempt.get("rejection"):
                continue
            if any(
                hashlib.sha256(source.encode()).hexdigest()
                != attempt["hashes"].get(name)
                for name, source in attempt["changes"].items()
            ):
                raise ValueError("Candidate changed after generation.")
            sources = {**report["sources"], **attempt["changes"]}
            for name, tests in [
                ("regression", {regression["path"]: regression["source"]}),
                ("existing", ordinary),
                ("independent", independent),
            ]:
                if name not in attempt["checks"]:
                    checkpoint(f"repair_{number}_{name}")
                    attempt["checks"][name] = execute(sources, tests)
                    checkpoint(f"repair_{number}_{name}_complete")
            attempt["accepted"] = all(
                passed(check) for check in attempt["checks"].values()
            )
            for label, baseline in [
                ("regression", reproduction),
                ("existing", checks["baseline"]),
                ("independent", checks["independent_baseline"]),
            ]:
                actual = attempt["checks"][label].get("summary", {})
                expected = baseline.get("summary", {})
                if actual.get("tests") != expected.get("tests") or actual.get(
                    "skipped", 0
                ) > expected.get("skipped", 0):
                    attempt["accepted"] = False
                    attempt["count_integrity_failed"] = True
            if attempt["accepted"]:
                report.update(
                    verdict="checks_passed",
                    explanation=f"Original failure reproduced before repair. Candidate {number} passed frozen regression, existing and independent tests.",
                    draft_changes=attempt["changes"],
                    draft_diff=attempt["diff"],
                    candidate_hashes=attempt["hashes"],
                    verification={**checks, **attempt["checks"]},
                )
                return report
        report.update(
            verdict="unresolved",
            explanation="Repair budget exhausted without a candidate passing every check.",
        )
        return report
    finally:
        if own_executor:
            executor.close()
        report["limitations"] = [
            "Checks cover the collected tests, not universal correctness.",
            "Untrusted Python can manipulate its own test framework; evidence is not adversarial proof.",
            "Dependencies use published binary wheels only. Native source builds and system-package recipes require a separately prepared image.",
        ]


def build_model_context(report, options):
    """Bound model context independently of the larger executable repository."""
    selected = options.get("source_paths") or list(report["sources"])
    sources = {}
    remaining = 22000
    keywords = set(
        report["issue"].replace("(", " ").replace(")", " ").replace(".", " ").split()
    )
    excerpts = []
    for name in selected:
        original = report["sources"][name]
        allowance = min(remaining, 18000)
        if allowance < 1000:
            break
        if len(original) <= allowance:
            content = original
        else:
            tree = ast.parse(original)
            fragments = [original[: min(4000, allowance // 3)]]
            for node in tree.body:
                if getattr(node, "name", None) in keywords:
                    fragment = ast.get_source_segment(original, node)
                    if fragment and len(fragment) < allowance - sum(
                        map(len, fragments)
                    ):
                        fragments.append(fragment)
            content = "\n# ... context excerpt ...\n".join(fragments)
            excerpts.append(name)
        sources[name] = content
        remaining -= len(content)
    tests = {}
    remaining = 4000
    for name, source in report["existing_tests"].items():
        if name not in options["independent_test_paths"] and len(source) <= remaining:
            tests[name] = source
            remaining -= len(source)
    from .environments import dependency_plan

    return {
        "issue": report["issue"],
        "sources": sources,
        "excerpted_paths": excerpts,
        "existing_tests": tests,
        "ordinary_test_paths": [
            name
            for name in report["existing_tests"]
            if name not in options["independent_test_paths"]
        ],
        "dependencies": dependency_plan(report["dependency_manifests"])["requirements"],
    }
