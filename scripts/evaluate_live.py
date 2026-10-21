"""Evaluate frozen live-generated regression against reviewed good and bad repairs."""

import copy
import hashlib
import json
from pathlib import Path

from issue2proof.draft import unified_patch
from issue2proof.execution import SandboxExecutor, verify_repository
from issue2proof.fixtures import REGRESSION, WRONG_FIX

original = json.loads(Path("artifacts/live-repository-draft.json").read_text())
bad = copy.deepcopy(original)
bad["mode"] = "reviewed negative-control repository fixture"
bad["model_requests"] = []
bad["generated_regression"]["source"] = REGRESSION
bad["generated_regression"]["sha256"] = hashlib.sha256(REGRESSION.encode()).hexdigest()
bad["test_hashes"][bad["generated_regression"]["path"]] = bad["generated_regression"][
    "sha256"
]
bad["draft_diff"] = unified_patch("pricing.py", bad["sources"]["pricing.py"], WRONG_FIX)
bad["draft_changes"] = {"pricing.py": WRONG_FIX}
bad["candidate_hashes"] = {"pricing.py": hashlib.sha256(WRONG_FIX.encode()).hexdigest()}
rejected = verify_repository(bad)
Path("artifacts/live-rejection-evaluation.json").write_text(
    json.dumps(rejected, indent=2) + "\n"
)
controls_test = """import os, resource
import pytest

def test_controller_limits_and_integrity():
    assert os.getuid() == 65534
    assert resource.getrlimit(resource.RLIMIT_AS)[0] == 512*1024*1024
    assert resource.getrlimit(resource.RLIMIT_CPU)[0] == 15
    with pytest.raises(PermissionError):
        open('/work/pricing.py','w')
    with pytest.raises(MemoryError):
        bytearray(700*1024*1024)
"""
executor = SandboxExecutor()
try:
    controls = executor.execute(
        {"pricing.py": "x = 1\n", "test_controls.py": controls_test},
        ["test_controls.py"],
    )
finally:
    executor.close()
Path("artifacts/resource-integrity-validation.json").write_text(
    json.dumps(controls, indent=2) + "\n"
)
summary = {
    "mode": "live remote reviewed fixture evaluation, not held-out real-bug benchmark",
    "model_generated_repair": json.loads(
        Path("artifacts/live-repository-repair.json").read_text()
    )["verdict"],
    "wrong_candidate_verdict": rejected["verdict"],
    "wrong_candidate_regression_passed": rejected.get("verification", {})
    .get("regression", {})
    .get("exit_code")
    == 0,
    "wrong_candidate_existing_failed": rejected.get("verification", {})
    .get("existing", {})
    .get("exit_code")
    == 1,
    "resource_and_file_integrity_probe": controls.get("evidence_valid")
    and controls["exit_code"] == 0,
}
summary["passed"] = (
    summary["model_generated_repair"] == "checks_passed"
    and summary["wrong_candidate_verdict"] == "unresolved"
    and summary["wrong_candidate_regression_passed"]
    and summary["wrong_candidate_existing_failed"]
    and summary["resource_and_file_integrity_probe"]
)
Path("artifacts/live-evaluation.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
raise SystemExit(0 if summary["passed"] else 1)
