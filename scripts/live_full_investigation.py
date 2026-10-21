"""Run a durable reproduce-first historical real-bug investigation."""

import json
from pathlib import Path

from issue2proof.app import save_report
from issue2proof.jobs import Worker, database, enqueue, get_job
from issue2proof.repository import inspect_archive

root = Path("examples/real-bugs/werkzeug-safe-join")
provenance = json.loads((root / "provenance.json").read_text())
report = inspect_archive(
    (root.parent / "werkzeug-safe-join.zip").read_bytes(), provenance["issue"]
)
report["provenance"] = provenance
report = save_report(report)
job = enqueue(
    report["id"],
    {
        "independent_test_paths": ["tests/test_independent.py"],
        "prepare_dependencies": True,
        "max_repairs": 3,
        "max_model_calls": 5,
        "max_sandbox_calls": 16,
        "budget_usd": 2.0,
    },
)
Worker().run_once()

with database() as db:
    report = json.loads(
        db.execute("SELECT report FROM runs WHERE id=?", (report["id"],)).fetchone()[0]
    )
Path("artifacts/real-bug-werkzeug.json").write_text(json.dumps(report, indent=2) + "\n")
Path("artifacts/real-bug-job.json").write_text(
    json.dumps(get_job(job["id"]), indent=2) + "\n"
)
print(
    json.dumps(
        {
            "job": get_job(job["id"])["state"],
            "verdict": report["verdict"],
            "explanation": report["explanation"],
            "stage": get_job(job["id"])["stage"],
        },
        indent=2,
    )
)
raise SystemExit(0 if report["verdict"] == "checks_passed" else 1)
