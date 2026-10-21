"""Run the reviewed upload example through actual Nebius inference and verification."""

import json
from pathlib import Path

from issue2proof.draft import generate_draft
from issue2proof.execution import verify_repository
from issue2proof.repository import inspect_archive

report = inspect_archive(
    Path("examples/pricing-project.zip").read_bytes(),
    "An excess discount makes the total negative. Clamp the total to zero while preserving normal order totals.",
)
report["independent_test_paths"] = ["tests/test_boundaries.py"]
report = generate_draft(report)
Path("artifacts/live-repository-draft.json").write_text(
    json.dumps(report, indent=2) + "\n"
)
if report["verdict"] == "awaiting_sandbox":
    report = verify_repository(report)
Path("artifacts/live-repository-repair.json").write_text(
    json.dumps(report, indent=2) + "\n"
)
print(
    json.dumps(
        {"verdict": report["verdict"], "explanation": report["explanation"]}, indent=2
    )
)
raise SystemExit(0 if report["verdict"] == "checks_passed" else 1)
