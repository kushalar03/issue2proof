from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from issue2proof.app import app, save_report
from issue2proof.execution import SandboxExecutor, verify_repository
from issue2proof.sandbox import SandboxConfig


def sample():
    from test_repository import Provider, project

    from issue2proof.draft import generate_draft

    report = project()
    report["independent_test_paths"] = ["tests/test_private.py"]
    return generate_draft(report, Provider())


class Executor:
    def __init__(self, bad=False, reproduction_error=False):
        self.calls = []
        self.bad = bad
        self.reproduction_error = reproduction_error

    def execute(self, files, tests):
        self.calls.append((files, tests))
        failed = len(self.calls) == 3 or (self.bad and len(self.calls) == 6)
        valid = not (self.reproduction_error and len(self.calls) == 3)
        return {
            "evidence_valid": valid,
            "exit_code": int(failed),
            "summary": {"tests": 1, "failures": int(failed), "errors": 0, "skipped": 0},
            "assertion_failures": int(failed),
            "files_intact": True,
            "seconds": 0,
            "output": "pytest output",
            "command": "pytest",
        }


def test_all_six_gates_and_independent_test_isolation():
    executor = Executor()
    report = verify_repository(sample(), executor)
    assert report["verdict"] == "checks_passed"
    assert len(executor.calls) == 6
    assert "tests/test_private.py" in executor.calls[2][0]
    assert "tests/test_private.py" not in executor.calls[2][1]
    assert "tests/test_existing.py" in executor.calls[5][0]
    assert "tests/test_existing.py" not in executor.calls[5][1]
    assert any("adversarial" in text for text in report["limitations"])


def test_bad_candidate_and_setup_failure_are_not_accepted():
    assert verify_repository(sample(), Executor(bad=True))["verdict"] == "unresolved"
    executor = Executor(reproduction_error=True)
    assert verify_repository(sample(), executor)["verdict"] == "not_reproduced"
    assert len(executor.calls) == 3


@pytest.mark.parametrize("field", ["sources", "existing_tests", "draft_changes"])
def test_hash_tampering_fails_before_execution(field):
    report = sample()
    key = next(iter(report[field]))
    report[field][key] += "\n# changed"
    executor = Executor()
    with pytest.raises(ValueError, match="changed"):
        verify_repository(report, executor)
    assert not executor.calls


def test_controller_failure_cannot_produce_valid_evidence():
    runner = SandboxExecutor(
        SandboxConfig("key", "project", "image", "url"), client=SimpleNamespace()
    )
    runner.run = lambda *args, **kwargs: {
        "exit_code": 0,
        "stdout": "not json",
        "stderr": "",
        "output_truncated": False,
        "network_disabled": True,
        "disposable": True,
    }
    report = runner.execute(
        {"test_x.py": "def test_x(): assert True"}, ["test_x.py"]
    )
    assert not report["evidence_valid"]
    assert report["evidence_error"] == "controller_evidence_invalid_json"
    assert report["output"] == "not json"
    with pytest.raises(ValueError, match="Unsafe"):
        runner.execute({"../test_x.py": "pass"}, ["../test_x.py"])


def test_server_network_and_truncation_metadata_are_required():
    runner = SandboxExecutor(
        SandboxConfig("key", "project", "image", "url"), client=SimpleNamespace()
    )
    for field in ["network_disabled", "disposable"]:
        response = {
            "exit_code": 0,
            "stdout": "{}",
            "stderr": "",
            "output_truncated": False,
            "network_disabled": True,
            "disposable": True,
        }
        response[field] = False
        runner.run = lambda *args, r=response, **kwargs: r
        assert not runner.execute({"test_x.py": "pass"}, ["test_x.py"])[
            "evidence_valid"
        ]


def test_pytest_collection_failure_keeps_bounded_diagnostics():
    runner = SandboxExecutor(
        SandboxConfig("key", "project", "image", "url"), client=SimpleNamespace()
    )
    evidence = {
        "exit_code": 2,
        "output": "ModuleNotFoundError: missing_test_dependency",
        "output_truncated": False,
        "timed_out": False,
        "summary": {"tests": 0, "failures": 0, "errors": 1, "skipped": 0},
        "files_intact": True,
        "input_hashes": {
            "test_x.py": "d74ff0ee8da3b9806b18c877dbf29bbde50b5bd8e4dad7a3a725000feb82e8f1"
        },
        "uid": 65534,
        "no_new_privileges": True,
    }
    runner.run = lambda *args, **kwargs: {
        "exit_code": 0,
        "stdout": __import__("json").dumps(evidence),
        "stderr": "",
        "output_truncated": False,
        "network_disabled": True,
        "disposable": True,
    }
    report = runner.execute({"test_x.py": "pass"}, ["test_x.py"])
    assert report["evidence_error"] == "pytest_setup_or_collection_failed"
    assert "missing_test_dependency" in report["output"]


def test_execution_endpoint_requires_consent_and_rejects_repeated_operations(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ISSUE2PROOF_LEGACY_API", "1")
    monkeypatch.setenv("ISSUE2PROOF_DB", str(tmp_path / "runs.db"))
    report = save_report(sample())
    client = TestClient(app)
    endpoint = "/api/projects/" + report["id"] + "/verify"
    assert client.post(endpoint, json={}).status_code == 422
    monkeypatch.setattr(
        "issue2proof.app.verify_repository",
        lambda report: verify_repository(report, Executor()),
    )
    response = client.post(endpoint, json={"execute_remote": True})
    assert response.json()["verdict"] == "checks_passed"
    assert client.post(endpoint, json={"execute_remote": True}).status_code == 409
    assert client.get("/api/runs/" + report["id"]).json()["verification"]


def test_operation_wait_failure_cancels_only_own_operation():
    class Client:
        def __init__(self):
            self.cancelled = []

        def spawn_instance(self, **kwargs):
            assert kwargs["networking"].enabled is False
            assert kwargs["disposable"] and not kwargs["preserve_env"]
            assert kwargs["resources_limits"].max_layer_bytes == 64 * 1024 * 1024
            return SimpleNamespace(uuid="owned-operation")

        def wait_operation(self, *args, **kwargs):
            raise TimeoutError("timeout")

        def cancel_operation(self, uuid):
            self.cancelled.append(uuid)

    client = Client()
    runner = SandboxExecutor(
        SandboxConfig("key", "project", "image", "url"), client=client
    )
    with pytest.raises(TimeoutError):
        runner.run("pass")
    assert client.cancelled == ["owned-operation"]


def test_saved_examples_are_read_only_and_allowlisted():
    client = TestClient(app)
    examples = client.get("/api/examples").json()
    assert examples
    example = client.get("/api/examples/" + examples[0]["id"]).json()
    assert example["saved_example"] is True
    assert client.get("/api/examples/not-an-example").status_code == 404
