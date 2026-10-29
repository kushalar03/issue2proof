"""Create a reusable reviewed Python/pytest image; writes no credentials."""

import json
import os
from pathlib import Path

from contree_sdk import ContreeSync
from contree_sdk.auth import IAMAuth
from contree_sdk.config import ContreeConfig

from issue2proof.settings import load_environment

load_environment()

client = ContreeSync(
    config=ContreeConfig(
        auth=IAMAuth(
            token=os.environ["NEBIUS_API_KEY"],
            project_id=os.environ["NEBIUS_PROJECT_ID"],
        ),
        transport_timeout=30,
        operation_timeout=180,
    )
)
base = client.images.use("python:3.12-slim", strict=True)
execution = base.run(
    "python",
    args=["-m", "pip", "install", "--no-cache-dir", "pytest==9.0.3"],
    env={},
    preserve_env=False,
    timeout=120,
    disposable=False,
    truncate_output_at=10000,
).wait()
result = execution.result
report = {
    "ok": result.exit_code == 0 and not result.truncated,
    "base_image": str(base.uuid),
    "image": str(execution.uuid),
    "exit_code": result.exit_code,
    "seconds": result.elapsed_time.total_seconds(),
    "cost": result.cost,
    "stdout": result.stdout,
    "stderr": result.stderr,
}
Path("artifacts/prepared-image.json").write_text(json.dumps(report, indent=2) + "\n")
print(
    json.dumps(
        {k: v for k, v in report.items() if k not in {"stdout", "stderr"}}, indent=2
    )
)
raise SystemExit(0 if report["ok"] else 1)
