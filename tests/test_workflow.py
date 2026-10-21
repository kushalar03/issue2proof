import pytest
from fastapi.testclient import TestClient

from issue2proof.app import app
from issue2proof.engine import run_demo


@pytest.mark.parametrize(
    "case,verdict,count",
    [
        ("repair", "verified", 1),
        ("reject", "verified", 2),
        ("unresolved", "unresolved", 2),
        ("ambiguous", "needs_clarification", 0),
    ],
)
def test_verdicts(case, verdict, count):
    report = run_demo(case)
    assert report["verdict"] == verdict
    assert len(report["attempts"]) == count
    if count:
        assert report["reproduction"]["exit_code"] == 1
        assert "assert -50 == 0" in report["reproduction"]["output"]
        assert all(attempt["protected_tests_intact"] for attempt in report["attempts"])


def test_plausible_patch_is_rejected():
    report = run_demo("reject")
    bad, good = report["attempts"]
    assert bad["regression"]["exit_code"] == 0
    assert bad["existing"]["exit_code"] == 1
    assert bad["independent"]["exit_code"] == 1
    assert not bad["accepted"]
    assert good["accepted"]


def test_api_persists_and_exports(tmp_path, monkeypatch):
    monkeypatch.setenv("ISSUE2PROOF_DB", str(tmp_path / "runs.sqlite3"))
    client = TestClient(app)
    response = client.post("/api/runs", json={"case": "ambiguous"})
    assert response.status_code == 201
    report = response.json()
    assert client.get("/api/runs/" + report["id"]).json() == report
    assert client.get("/api/runs").json() == [report]
    export = client.get("/api/runs/" + report["id"] + "/report")
    assert export.json() == report
    assert "attachment" in export.headers["content-disposition"]
    assert client.get("/api/runs/missing").status_code == 404
    assert client.post("/api/runs", json={"case": "../../evil"}).status_code == 422
    assert client.get("/").status_code == 200
