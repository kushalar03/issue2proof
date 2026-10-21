"""Exercise src-layout imports and automatic wheel-only dependency preparation."""

import json
from pathlib import Path

from issue2proof.app import save_report
from issue2proof.jobs import Worker, database, enqueue, get_job
from issue2proof.repository import inspect_archive

report = save_report(
    inspect_archive(
        Path("examples/calendar-project.zip").read_bytes(),
        "add_months must add calendar months, preserving the day when valid and clamping to the last valid day otherwise. It must handle zero and negative month offsets. Currently it adds fixed 30-day intervals. The installed python-dateutil dependency is available and may be used.",
    )
)
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
worker = Worker()
while worker.run_once():
    if get_job(job["id"])["state"] not in {"queued", "running"}:
        break
with database() as db:
    report = json.loads(
        db.execute("SELECT report FROM runs WHERE id=?", (report["id"],)).fetchone()[0]
    )
Path("artifacts/live-dependency-investigation.json").write_text(
    json.dumps(report, indent=2) + "\n"
)
Path("artifacts/live-dependency-job.json").write_text(
    json.dumps(get_job(job["id"]), indent=2) + "\n"
)
print(
    json.dumps(
        {
            "verdict": report["verdict"],
            "stage": get_job(job["id"])["stage"],
            "installed": report.get("environment", {}).get("installed"),
        },
        indent=2,
    )
)
raise SystemExit(0 if report["verdict"] == "checks_passed" else 1)
