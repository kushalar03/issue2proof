import hashlib
import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from test_repository import project

from issue2proof.access import validate_configuration
from issue2proof.app import app, save_report
from issue2proof.environments import dependency_plan
from issue2proof.jobs import (
    BudgetExceeded,
    Cancelled,
    Context,
    budget_status,
    cancel,
    claim,
    database,
    enqueue,
    get_job,
    prune,
    resume,
)


def options():
    return {
        "independent_test_paths": ["tests/test_private.py"],
        "prepare_dependencies": False,
        "max_model_calls": 2,
        "max_sandbox_calls": 6,
        "max_repairs": 1,
        "budget_usd": 2.0,
    }


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("ISSUE2PROOF_DB", str(tmp_path / "runs.sqlite3"))
    monkeypatch.setenv("ISSUE2PROOF_WORKER", "0")
    monkeypatch.delenv("ISSUE2PROOF_PUBLIC", raising=False)
    monkeypatch.delenv("ISSUE2PROOF_ACCESS_TOKEN", raising=False)
    return save_report(project())


def test_exclusive_claim_and_duplicate_enqueue(isolated):
    job = enqueue(isolated["id"], options())
    with pytest.raises(ValueError, match="already"):
        enqueue(isolated["id"], options())
    assert claim("worker-a")["id"] == job["id"]
    assert claim("worker-b") is None


def test_reservations_and_cancel_are_persistent(isolated):
    job = enqueue(isolated["id"], options())
    claim("worker")
    context = Context(job["id"], "worker")
    try:
        context.reserve("model")
        context.reserve("model")
        with pytest.raises(BudgetExceeded):
            context.reserve("model")
        assert get_job(job["id"])["model_calls"] == 2
        cancel(job["id"])
        with pytest.raises(Cancelled):
            context.check()
    finally:
        context.finish("cancelled")


def test_expired_lease_requires_explicit_resume_and_preserves_budget(isolated):
    job = enqueue(isolated["id"], options())
    claim("old-worker")
    with database() as db:
        db.execute(
            "UPDATE jobs SET lease=?,model_calls=1 WHERE id=?",
            (time.time() - 1, job["id"]),
        )
    assert claim("new-worker") is None
    assert get_job(job["id"])["state"] == "interrupted"
    resume(job["id"])
    assert claim("new-worker")["id"] == job["id"]
    assert get_job(job["id"])["model_calls"] == 1
    old = Context(job["id"], "old-worker")
    try:
        with pytest.raises(Cancelled):
            old.check()
    finally:
        old.finish("cancelled")
    assert get_job(job["id"])["state"] == "running"


def test_daily_budget_and_retention(isolated, monkeypatch):
    monkeypatch.setenv("ISSUE2PROOF_DAILY_BUDGET_USD", "0.01")
    job = enqueue(isolated["id"], options())
    claim("worker")
    context = Context(job["id"], "worker")
    try:
        with pytest.raises(BudgetExceeded, match="daily"):
            context.reserve("model")
    finally:
        context.finish("failed")
    with database() as db:
        db.execute(
            "UPDATE runs SET created_at=? WHERE id=?",
            ((datetime.now(UTC) - timedelta(days=10)).isoformat(), isolated["id"]),
        )
    assert prune() == 1


def test_lifetime_budget_protects_reserved_credit(isolated, monkeypatch):
    monkeypatch.setenv("ISSUE2PROOF_TOTAL_BUDGET_USD", "0.05")
    monkeypatch.setenv("ISSUE2PROOF_PROTECTED_RESERVE_USD", "0.02")
    job = enqueue(isolated["id"], options())
    claim("worker")
    context = Context(job["id"], "worker")
    try:
        reservation = context.reserve("model", role="engineering")
        assert budget_status()["remaining_spendable_usd"] == 0
        with pytest.raises(BudgetExceeded, match="lifetime"):
            context.reserve("model", role="fast")
        context.reconcile(reservation, 0.005)
        assert budget_status()["remaining_spendable_usd"] == 0.025
        context.reserve("model", role="fast")
        assert get_job(job["id"])["model_roles"] == {
            "engineering": 1,
            "fast": 1,
        }
    finally:
        context.finish("completed")


def test_private_authentication_and_cross_origin_guard(isolated, monkeypatch):
    token = "a-long-private-application-token-123456"
    monkeypatch.setenv("ISSUE2PROOF_ACCESS_TOKEN", f"  {token}  ")
    client = TestClient(app)
    health = client.get("/api/health").json()
    assert health["authenticated"] is False
    assert health["authentication_token_fingerprint"] == hashlib.sha256(
        token.encode()
    ).hexdigest()[:12]
    assert client.get("/api/runs").status_code == 401
    assert client.post("/api/login", json={"token": "wrong"}).status_code == 401
    assert client.post("/api/login", json={"token": f" {token} "}).status_code == 200
    assert client.get("/api/health").json()["authenticated"] is True
    assert client.get("/api/runs").status_code == 200
    assert "default-src 'self'" in client.get("/").headers["content-security-policy"]
    assert (
        client.post(
            "/api/logout", headers={"Origin": "https://untrusted.example"}
        ).status_code
        == 403
    )
    assert client.post("/api/logout").status_code == 204
    assert (
        client.get(
            "/api/runs", headers={"Authorization": "Bearer " + token}
        ).status_code
        == 200
    )
    monkeypatch.setenv("ISSUE2PROOF_PUBLIC", "1")
    monkeypatch.delenv("ISSUE2PROOF_ACCESS_TOKEN")
    with pytest.raises(RuntimeError):
        validate_configuration()


def test_login_rate_limit(isolated, monkeypatch):
    monkeypatch.setenv(
        "ISSUE2PROOF_ACCESS_TOKEN", "a-different-private-token-at-least-24-chars"
    )
    client = TestClient(app)
    for _ in range(5):
        assert client.post("/api/login", json={"token": "wrong"}).status_code == 401
    assert client.post("/api/login", json={"token": "wrong"}).status_code == 429


def test_async_start_returns_immediately_and_supports_cancel(isolated):
    client = TestClient(app)
    response = client.post(
        "/api/projects/" + isolated["id"] + "/investigate",
        json={**options(), "send_to_nebius": True, "execute_remote": True},
    )
    assert response.status_code == 202
    job = response.json()
    assert job["state"] == "queued"
    assert (
        client.post("/api/jobs/" + job["id"] + "/cancel").json()["state"] == "cancelled"
    )
    assert client.get("/api/jobs/" + job["id"]).json()["cancel_requested"] == 1
    assert client.delete("/api/runs/" + isolated["id"]).status_code == 204


@pytest.mark.parametrize(
    "value",
    [
        "-r secret.txt",
        "-e .",
        "https://example.com/x.whl",
        "pkg @ https://example.com/x.whl",
        "../project",
    ],
)
def test_dependency_options_and_urls_are_rejected(value):
    with pytest.raises(ValueError):
        dependency_plan({"requirements.txt": value})


def test_static_pyproject_dependencies_and_markers():
    plan = dependency_plan(
        {
            "pyproject.toml": '[project]\ndependencies=["python-dateutil==2.9.0.post0", "typing_extensions>=4; python_version < \'3.11\'"]'
        }
    )
    assert len(plan["requirements"]) == 5
    assert dependency_plan({"requirements.txt": "# comment\npytest==8.4.2\n"})[
        "requirements"
    ] == ["pytest==8.4.2"]


def test_static_pyproject_test_dependency_groups():
    plan = dependency_plan(
        {
            "pyproject.toml": """
[project]
name = "example"
version = "1.0"

[dependency-groups]
shared = ["coverage"]
tests = ["freezegun", "pytest", {include-group = "shared"}]

[project.optional-dependencies]
test = ["hypothesis"]

[build-system]
requires = ["flit_core<4"]
build-backend = "flit_core.buildapi"
"""
        }
    )
    assert plan["requirements"] == [
        "coverage",
        "flit_core<4",
        "freezegun",
        "hypothesis",
        "pytest",
    ]


def test_legacy_paid_endpoints_are_off_by_default(isolated, monkeypatch):
    monkeypatch.delenv("ISSUE2PROOF_LEGACY_API", raising=False)
    client = TestClient(app)
    assert (
        client.post(
            "/api/projects/" + isolated["id"] + "/draft", json={"send_to_nebius": True}
        ).status_code
        == 410
    )
    assert (
        client.post(
            "/api/projects/" + isolated["id"] + "/verify", json={"execute_remote": True}
        ).status_code
        == 410
    )


def test_public_mode_cookies_require_https(isolated, monkeypatch):
    monkeypatch.setenv("ISSUE2PROOF_PUBLIC", "1")
    monkeypatch.setenv(
        "ISSUE2PROOF_ACCESS_TOKEN", "a-private-application-token-at-least-24-chars"
    )
    client = TestClient(app, base_url="https://testserver")
    response = client.post(
        "/api/login", json={"token": "a-private-application-token-at-least-24-chars"}
    )
    assert (
        "Secure" in response.headers["set-cookie"]
        and "HttpOnly" in response.headers["set-cookie"]
    )
    assert client.get("/api/runs").status_code == 200


def test_clarification_preserves_reservations_and_completed_checkpoints(isolated):
    job = enqueue(isolated["id"], options())
    with database() as db:
        report = json.loads(
            db.execute(
                "SELECT report FROM runs WHERE id=?", (isolated["id"],)
            ).fetchone()[0]
        )
        report.update(
            verdict="needs_clarification",
            explanation="Clamp or raise?",
            pipeline={"baseline": {"exit_code": 0}},
        )
        db.execute(
            "UPDATE runs SET report=? WHERE id=?", (json.dumps(report), isolated["id"])
        )
        db.execute(
            "UPDATE jobs SET state='completed',model_calls=1,reserved_usd=0.02 WHERE id=?",
            (job["id"],),
        )
    response = TestClient(app).post(
        "/api/jobs/" + job["id"] + "/clarify",
        json={"answer": "Clamp the result to zero."},
    )
    assert response.status_code == 200 and response.json()["state"] == "queued"
    assert response.json()["model_calls"] == 1
    with database() as db:
        report = json.loads(
            db.execute(
                "SELECT report FROM runs WHERE id=?", (isolated["id"],)
            ).fetchone()[0]
        )
    assert report["pipeline"]["baseline"]["exit_code"] == 0
    assert "Clamp the result" in report["issue"]
