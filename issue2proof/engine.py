import difflib
import hashlib
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .fixtures import CASES, EXISTING, INDEPENDENT, ORIGINAL, REGRESSION


def execute(root: Path, files: list[str]) -> dict:
    """Trusted demo fixtures only. Never call this on uploaded or model-written code."""
    started = time.monotonic()
    command = [sys.executable, "-m", "pytest", "-q", "--tb=short", *files]
    try:
        completed = subprocess.run(
            command,
            check=False,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
            env={
                "PATH": os.defpath,
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        return {
            "command": "python -m pytest -q --tb=short " + " ".join(files),
            "exit_code": completed.returncode,
            "output": (completed.stdout + completed.stderr)[-20000:],
            "seconds": round(time.monotonic() - started, 3),
        }
    except subprocess.TimeoutExpired:
        return {
            "command": "pytest",
            "exit_code": 124,
            "output": "Execution timed out after 15 seconds.",
            "seconds": 15,
        }


def run_demo(case: str) -> dict:
    fixture = CASES[case]
    report = {
        "case": case,
        "mode": "reviewed demo fixtures",
        "issue": fixture["issue"],
        "verdict": "needs_clarification",
        "events": [],
        "attempts": [],
        "limitations": [
            "Evidence covers the listed tests only; it is not a mathematical proof.",
            "Demo patches and tests are prewritten. No model inference or remote sandbox was used.",
        ],
    }
    if case == "ambiguous":
        report["explanation"] = (
            "Confirm whether excess discounts should clamp to zero or raise an error before generating a test."
        )
        return report
    with tempfile.TemporaryDirectory(prefix="issue2proof-") as directory:
        root = Path(directory)
        protected = {
            "test_regression.py": REGRESSION,
            "test_existing.py": EXISTING,
            "test_independent.py": INDEPENDENT,
        }
        (root / "pricing.py").write_text(ORIGINAL)
        for name, source in protected.items():
            (root / name).write_text(source)
        hashes = {
            name: hashlib.sha256(source.encode()).hexdigest()
            for name, source in protected.items()
        }
        report["test_hashes"] = hashes
        report["regression_test"] = REGRESSION
        baseline = execute(root, ["test_existing.py"])
        reproduction = execute(root, ["test_regression.py"])
        report["baseline"] = baseline
        report["reproduction"] = reproduction
        reproduced = (
            reproduction["exit_code"] == 1
            and "FAILED test_regression.py::test_excess_discount"
            in reproduction["output"]
            and "E   assert -50 == 0" in reproduction["output"]
        )
        if baseline["exit_code"] != 0 or not reproduced:
            report.update(
                verdict="not_reproduced",
                explanation="Baseline or behavioral reproduction gate failed.",
            )
            return report
        report["events"] = [
            "Existing suite passed on original code.",
            "Regression failed on the expected assertion.",
            "Regression and independent tests frozen before repair.",
        ]
        for index, patch in enumerate(fixture["patches"][:2], 1):
            (root / "pricing.py").write_text(patch)
            regression = execute(root, ["test_regression.py"])
            existing = execute(root, ["test_existing.py"])
            independent = execute(root, ["test_independent.py"])
            intact = all(
                hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
                for name, digest in hashes.items()
            )
            accepted = intact and all(
                check["exit_code"] == 0 for check in [regression, existing, independent]
            )
            report["attempts"].append(
                {
                    "number": index,
                    "diff": "".join(
                        difflib.unified_diff(
                            ORIGINAL.splitlines(True),
                            patch.splitlines(True),
                            fromfile="a/pricing.py",
                            tofile="b/pricing.py",
                        )
                    ),
                    "regression": regression,
                    "existing": existing,
                    "independent": independent,
                    "protected_tests_intact": intact,
                    "accepted": accepted,
                }
            )
            if accepted:
                report.update(
                    verdict="verified",
                    explanation="Original failure reproduced; the patch passed the frozen regression, existing suite, and independent boundary checks.",
                )
                break
            report["events"].append(
                f"Attempt {index} rejected: passing the regression alone is insufficient."
            )
        else:
            report.update(
                verdict="unresolved",
                explanation="Neither candidate passed all checks. Stopped at the two-attempt budget.",
            )
    return report
