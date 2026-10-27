import copy
import json
from pathlib import Path

from issue2proof.history import import_verified_reports


def test_history_import_only_promotes_verified_reports(tmp_path, monkeypatch):
    monkeypatch.setenv("ISSUE2PROOF_DB", str(tmp_path / "history.sqlite3"))
    report = json.loads(
        (Path(__file__).resolve().parents[1] / "artifacts/real-bug-requests.json").read_text()
    )
    report["id"] = "verified-history"
    invalid = copy.deepcopy(report)
    invalid["id"] = "unresolved-history"
    invalid["verdict"] = "unresolved"
    result = import_verified_reports([report, invalid])
    assert len(result["imported"]) == 1
    assert result["imported"][0]["run_id"] == "verified-history"
    assert len(result["skipped"]) == 1
    assert "checks-passed" in result["skipped"][0]["reason"]
