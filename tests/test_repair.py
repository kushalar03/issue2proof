import hashlib
import json
import subprocess
import sys
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from issue2proof.app import app
from issue2proof.fixtures import EXISTING, FIX, ORIGINAL, REGRESSION, WRONG_FIX
from issue2proof.provider import Candidate
from issue2proof.remote import HARNESS, RemoteRunner, validate_source
from issue2proof.repair import run_repair
from issue2proof.sandbox import SandboxConfig


@pytest.mark.parametrize(
    "source", [ORIGINAL, FIX, WRONG_FIX, "def total(a,b):\n    return max(a-b, 0)\n"]
)
def test_pure_repairs_allowed(source):
    validate_source(source)


@pytest.mark.parametrize(
    "source",
    [
        "import os\ndef total(a,b): return 0",
        "def total(a,b): return __import__('os').system('id')",
        "def total(a,b): return a.__class__",
        "def total(a,b): return 2**1000000000",
        "def total(a,b): return [a]*1000000000",
        "def total(a,b):\n while True: pass",
        "@print\ndef total(a,b): return 0",
        "def total(a=print('x'),b=0): return 0",
        "def total(a:print('x'),b): return 0",
        "def total(a,b): return max(a,b, key=print)",
        "def total(max,b): return max(0,b)",
        "def total(a,b): return",
    ],
)
def test_unsafe_repairs_rejected(source):
    with pytest.raises(ValueError):
        validate_source(source)


class Provider:
    def __init__(self, sources):
        self.sources = iter(sources)
        self.requests = []

    def generate(self, issue, source, feedback):
        self.requests.append((issue, source, feedback))
        return Candidate(next(self.sources), "test-model", 10, 20, None)


class Runner:
    def __init__(self, broken=False):
        self.broken = broken
        self.calls = []

    def execute(self, source, name, tests):
        self.calls.append((source, name, tests))
        failed = (source == ORIGINAL and name == "test_regression.py") or (
            source == WRONG_FIX and name != "test_regression.py"
        )
        return {
            "evidence_valid": not self.broken,
            "exit_code": int(failed),
            "protected_tests_intact": True,
            "seconds": 0,
            "command": "pytest",
            "output": "FAILED test_regression.py::test_excess_discount\nE   assert -50 == 0"
            if failed
            else "passed",
        }


def test_repair_rejects_bad_candidate_and_keeps_independent_tests_private():
    provider = Provider([WRONG_FIX, FIX])
    report = run_repair("repair", provider, Runner())
    assert report["verdict"] == "verified"
    assert [attempt["accepted"] for attempt in report["attempts"]] == [False, True]
    assert "test_boundaries" not in json.dumps(provider.requests)
    assert "test_hashes" in report


def test_incomplete_baseline_prevents_model_request():
    provider = Provider([FIX])
    report = run_repair("repair", provider, Runner(broken=True))
    assert report["verdict"] == "not_reproduced"
    assert not provider.requests


def test_unsafe_model_output_never_executes():
    runner = Runner()
    report = run_repair("repair", Provider(["import os", FIX]), runner)
    assert report["verdict"] == "verified"
    assert "rejection" in report["attempts"][0]
    assert all(source != "import os" for source, _, _ in runner.calls)


def test_budget_exhaustion():
    provider = Provider([WRONG_FIX, WRONG_FIX])
    assert run_repair("repair", provider, Runner())["verdict"] == "unresolved"
    assert len(provider.requests) == 2


def test_remote_api_persists_blocked_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("ISSUE2PROOF_DB", str(tmp_path / "runs.db"))
    monkeypatch.delenv("NEBIUS_PROJECT_ID", raising=False)
    client = TestClient(app)
    response = client.post("/api/runs", json={"case": "repair", "mode": "remote"})
    assert response.status_code == 201
    assert response.json()["verdict"] == "blocked"
    assert "NEBIUS_PROJECT_ID" in response.json()["explanation"]
    assert (
        client.get("/api/runs/" + response.json()["id"] + "/report").json()
        == response.json()
    )


@pytest.mark.parametrize(
    "truncated,summary,intact,accepted",
    [
        (False, {"tests": 1, "failures": 0, "errors": 0, "skipped": 0}, True, True),
        (True, {"tests": 1, "failures": 0, "errors": 0, "skipped": 0}, True, False),
        (False, {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}, True, False),
        (False, {"tests": 1, "failures": 0, "errors": 1, "skipped": 0}, True, False),
        (False, {"tests": 1, "failures": 0, "errors": 0, "skipped": 1}, True, False),
        (False, {"tests": 1, "failures": 0, "errors": 0, "skipped": 0}, False, False),
    ],
)
def test_remote_evidence_gates(truncated, summary, intact, accepted):
    class Image:
        def run(self, **kwargs):
            assert kwargs["disposable"] and kwargs["timeout"] == 30
            assert kwargs["env"] == {} and not kwargs["preserve_env"]
            assert set(kwargs["files"]) == {
                "/tmp/issue2proof/pricing.py",
                "/tmp/issue2proof/test_existing.py",
                "/tmp/issue2proof/manifest.json",
                "/tmp/issue2proof-harness.py",
            }
            self.result = SimpleNamespace(
                exit_code=0,
                stdout=json.dumps(
                    {
                        "exit_code": 0,
                        "output": "passed",
                        "test_summary": summary,
                        "protected_tests_intact": intact,
                        "python": "3.12",
                        "pytest": "8.4",
                    }
                ),
                stderr="",
                elapsed_time=timedelta(seconds=1),
                cost=0.01,
                truncated=truncated,
            )
            return self

        def wait(self):
            return self

    client = SimpleNamespace(images=SimpleNamespace(use=lambda image: Image()))
    runner = RemoteRunner(SandboxConfig("secret", "project", "image", "url"), client)
    report = runner.execute(FIX, "test_existing.py", EXISTING)
    assert report["evidence_valid"] is accepted
    assert "secret" not in json.dumps(report)


@pytest.mark.parametrize(
    "source,test_name,test_source,exit_code",
    [
        (FIX, "test_existing.py", EXISTING, 0),
        (ORIGINAL, "test_regression.py", REGRESSION, 1),
    ],
)
def test_reviewed_harness_collects_real_junit_evidence(
    tmp_path, source, test_name, test_source, exit_code
):
    # Host execution is limited to reviewed fixture constants, never model output.
    (tmp_path / "pricing.py").write_text(source)
    (tmp_path / test_name).write_text(test_source)
    (tmp_path / "manifest.json").write_text(
        json.dumps({test_name: hashlib.sha256(test_source.encode()).hexdigest()})
    )
    harness = HARNESS.replace("'/tmp/issue2proof'", repr(str(tmp_path))).replace(
        "/tmp/results.xml", str(tmp_path / "results.xml")
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", harness, test_name],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    evidence = json.loads(completed.stdout)
    assert evidence["exit_code"] == exit_code
    assert evidence["test_summary"] == {
        "tests": 1,
        "failures": exit_code,
        "errors": 0,
        "skipped": 0,
    }
    assert evidence["protected_tests_intact"] is True
