"""Cancel an owned live background baseline before any inference request."""

import io
import json
import time
import zipfile
from pathlib import Path

import httpx

base = "http://127.0.0.1:8010"
headers = {"Authorization": "Bearer local-review-token-only-not-for-production"}
buffer = io.BytesIO()
with zipfile.ZipFile(buffer, "w") as archive:
    archive.writestr("code.py", "def value(): return 1\n")
    archive.writestr(
        "tests/test_slow.py",
        "import time\ndef test_slow():\n    time.sleep(60)\n    assert True\n",
    )
    archive.writestr("tests/test_independent.py", "def test_other(): assert True\n")
run = httpx.post(
    base + "/api/projects",
    params={"issue": "Check this reviewed cancellation probe."},
    content=buffer.getvalue(),
    headers=headers,
).json()
response = httpx.post(
    base + "/api/projects/" + run["id"] + "/investigate",
    headers=headers,
    json={
        "send_to_nebius": True,
        "execute_remote": True,
        "prepare_dependencies": False,
        "independent_test_paths": ["tests/test_independent.py"],
    },
)
response.raise_for_status()
job = response.json()
started = time.monotonic()
operation = None
while time.monotonic() - started < 20:
    job = httpx.get(base + "/api/jobs/" + job["id"], headers=headers).json()
    if job["operation_id"]:
        operation = job["operation_id"]
        break
    time.sleep(0.25)
assert operation, "No operation registered"
httpx.post(
    base + "/api/jobs/" + job["id"] + "/cancel", headers=headers
).raise_for_status()
while time.monotonic() - started < 40:
    job = httpx.get(base + "/api/jobs/" + job["id"], headers=headers).json()
    if job["state"] in {"cancelled", "failed"}:
        break
    time.sleep(0.3)
result = {
    "passed": job["state"] == "cancelled" and job["model_calls"] == 0,
    "job_id": job["id"],
    "operation_id": operation,
    "state": job["state"],
    "model_calls": job["model_calls"],
    "seconds": round(time.monotonic() - started, 2),
}
Path("artifacts/background-cancellation.json").write_text(
    json.dumps(result, indent=2) + "\n"
)
print(json.dumps(result, indent=2))
assert result["passed"]
