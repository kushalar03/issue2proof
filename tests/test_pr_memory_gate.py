import json
import os
import subprocess
import sys
from pathlib import Path

from issue2proof.memory import capsule_from_report
from issue2proof.portable import export_bundle


def test_pull_request_gate_recalls_scoped_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("ISSUE2PROOF_DB", str(tmp_path / "gate.sqlite3"))
    report = json.loads(
        (Path(__file__).resolve().parents[1] / "artifacts/real-bug-requests.json").read_text()
    )
    report["id"] = "gate-history"
    bundle = tmp_path / "memory.json"
    bundle.write_text(json.dumps(export_bundle([capsule_from_report(report)])))
    output = tmp_path / "output"
    summary = tmp_path / "summary"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/pr_memory_gate.py",
            "--bundle",
            str(bundle),
            "--change",
            "Refactor Unicode request serialization",
            "--report",
            str(tmp_path / "gate.json"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "GITHUB_OUTPUT": str(output), "GITHUB_STEP_SUMMARY": str(summary)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "verdict=recall_required" in output.read_text()
    assert "Unicode string body" in summary.read_text()
