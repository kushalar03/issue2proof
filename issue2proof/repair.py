"""Bounded model repairs of the reviewed pricing fixture; remote execution only."""

import difflib
import hashlib
from dataclasses import asdict

from .fixtures import CASES, EXISTING, INDEPENDENT, ORIGINAL, REGRESSION
from .provider import NebiusProvider
from .remote import RemoteRunner, validate_source
from .sandbox import SandboxConfig, smoke_check


def run_repair(case: str, provider=None, runner=None) -> dict:
    fixture = CASES[case]
    report = {
        "case": case,
        "mode": "model repair / restricted pricing fixture",
        "issue": fixture["issue"],
        "verdict": "blocked",
        "attempts": [],
        "events": [],
        "limitations": [
            "Only the reviewed pricing fixture and pure arithmetic repairs are supported.",
            "Tests are reviewed fixtures, not model-generated reproductions or a real-bug benchmark.",
            "Verification covers the listed checks only.",
            "Remote network isolation and resource quotas have not been validated; arbitrary code is disabled.",
        ],
    }
    if case == "ambiguous":
        report.update(
            verdict="needs_clarification",
            explanation="Confirm clamp-to-zero behavior before repair.",
        )
        return report
    stage = "configuration"
    try:
        if runner is None:
            config = SandboxConfig.from_env()
            stage = "sandbox_smoke"
            smoke = smoke_check(config)
            report["sandbox_smoke"] = smoke
            if not smoke["ok"]:
                report["explanation"] = (
                    "Sandbox transfer/execution validation failed; no model request made."
                )
                return report
            runner = RemoteRunner(config)
        provider = provider or NebiusProvider()
        tests = {
            "test_existing.py": EXISTING,
            "test_regression.py": REGRESSION,
            "test_independent.py": INDEPENDENT,
        }
        report["test_hashes"] = {
            name: hashlib.sha256(source.encode()).hexdigest()
            for name, source in tests.items()
        }
        report["regression_test"] = REGRESSION
        stage = "reproduction"
        baseline = runner.execute(ORIGINAL, "test_existing.py", EXISTING)
        reproduction = runner.execute(ORIGINAL, "test_regression.py", REGRESSION)
        report.update(baseline=baseline, reproduction=reproduction)
        if not (
            baseline.get("evidence_valid")
            and baseline["exit_code"] == 0
            and reproduction.get("evidence_valid")
            and reproduction["exit_code"] == 1
            and "FAILED test_regression.py::test_excess_discount"
            in reproduction["output"]
            and "E   assert -50 == 0" in reproduction["output"]
        ):
            report.update(
                verdict="not_reproduced",
                explanation="Baseline or behavioral failure evidence is incomplete.",
            )
            return report
        report["events"].append(
            "Original failure reproduced remotely; reviewed tests frozen outside candidate execution."
        )
        feedback = ""
        for number in range(1, 3):
            stage = "model"
            candidate = provider.generate(
                fixture["issue"],
                ORIGINAL,
                "Return only def total(subtotal, discount) with one arithmetic return using addition, subtraction, min or max. "
                + feedback,
            )
            attempt = {
                "number": number,
                "accepted": False,
                "model": asdict(candidate),
                "diff": "".join(
                    difflib.unified_diff(
                        ORIGINAL.splitlines(True),
                        candidate.source.splitlines(True),
                        fromfile="a/pricing.py",
                        tofile="b/pricing.py",
                    )
                ),
            }
            report["attempts"].append(attempt)
            try:
                validate_source(candidate.source)
            except ValueError as error:
                attempt["rejection"] = str(error)
                feedback = "Previous candidate rejected: " + str(error)
                continue
            stage = "verification"
            for label, name in (
                ("regression", "test_regression.py"),
                ("existing", "test_existing.py"),
                ("independent", "test_independent.py"),
            ):
                attempt[label] = runner.execute(candidate.source, name, tests[name])
            checks = [
                attempt[label] for label in ("regression", "existing", "independent")
            ]
            attempt["protected_tests_intact"] = all(
                check.get("protected_tests_intact") is True for check in checks
            )
            attempt["accepted"] = attempt["protected_tests_intact"] and all(
                check.get("evidence_valid") is True and check["exit_code"] == 0
                for check in checks
            )
            if attempt["accepted"]:
                report.update(
                    verdict="verified",
                    explanation="Model repair passed frozen regression, existing and independent checks in fresh remote executions.",
                )
                return report
            # Independent test contents and output never enter model context.
            feedback = "The prior repair failed reviewed checks. Preserve ordinary totals and clamp excess discounts to zero."
        report.update(
            verdict="unresolved",
            explanation="No candidate passed every check within the two-attempt budget.",
        )
    except Exception as error:  # noqa: BLE001 - sanitize SDK errors at the report boundary
        # SDK and transport errors can contain credentials: do not serialize them.
        report.update(
            stage=stage,
            error_type=type(error).__name__,
            explanation=f"{stage.replace('_', ' ').capitalize()} failed; no verified verdict was issued.",
        )
        if stage == "configuration" and isinstance(error, ValueError):
            report["explanation"] = str(error)
    return report
