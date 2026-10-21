import hashlib

import pytest
from test_repository import project

from issue2proof.app import save_report
from issue2proof.audit import audit_memories
from issue2proof.memory import capsule_from_report, save_capsule
from issue2proof.sandbox import SandboxConfig


class Context:
    def __init__(self):
        self.stages = []
        self.roles = []

    def check(self):
        pass

    def save(self, report, stage):
        self.stages.append(stage)

    def reserve(self, kind, *, role=None):
        self.roles.append(role)
        return len(self.roles)

    def reconcile(self, reservation, actual):
        pass


class Executor:
    def __init__(self, memory_exit=0, baseline_exit=0):
        self.calls = 0
        self.memory_exit = memory_exit
        self.baseline_exit = baseline_exit

    def execute(self, files, tests, *, install_project=False):
        self.calls += 1
        exit_code = self.baseline_exit if self.calls == 1 else self.memory_exit
        return {
            "evidence_valid": True,
            "exit_code": exit_code,
            "assertion_failures": int(exit_code == 1),
            "summary": {
                "tests": 1,
                "failures": int(exit_code == 1),
                "errors": 0,
                "skipped": 0,
            },
            "output": "passed" if exit_code == 0 else "assertion failed",
        }


@pytest.fixture
def memory_and_revision(tmp_path, monkeypatch):
    monkeypatch.setenv("ISSUE2PROOF_DB", str(tmp_path / "audit.sqlite3"))
    fixed = project()
    regression = "def test_contract():\n    assert True\n"
    fixed.update(
        verdict="checks_passed",
        generated_regression={
            "path": "issue2proof_generated/test_regression.py",
            "source": regression,
            "sha256": hashlib.sha256(regression.encode()).hexdigest(),
        },
        draft_changes={"pricing.py": fixed["sources"]["pricing.py"]},
        candidate_hashes={"pricing.py": "candidate"},
        environment={"image": "image", "requirements": []},
    )
    capsule = save_capsule(capsule_from_report(save_report(fixed)))
    revision = project()
    return capsule, revision


@pytest.mark.parametrize(
    ("memory_exit", "verdict", "status"),
    [(0, "memory_preserved", "preserved"), (1, "memory_conflict", "violated")],
)
def test_memory_audit_replays_frozen_behavior(
    memory_and_revision, memory_exit, verdict, status
):
    capsule, revision = memory_and_revision
    result = audit_memories(
        revision,
        {
            "memory_ids": [capsule["id"]],
            "prepare_dependencies": False,
        },
        Context(),
        Executor(memory_exit),
        SandboxConfig("key", "project", "image", "url"),
    )
    assert result["verdict"] == verdict
    assert result["memory_audit"]["results"][0]["status"] == status


def test_conflict_escalates_from_super_to_ultra(memory_and_revision):
    class Provider:
        def __init__(self):
            self.calls = []

        def request(self, instruction, payload, *, role, max_tokens):
            self.calls.append(role)
            if role == "engineering":
                result = {
                    "summary": "The historical contract failed.",
                    "risk": "high",
                    "likely_cause": "The refactor changed byte-length behavior.",
                    "next_experiment": "Compare Unicode and ASCII bodies.",
                    "escalate": True,
                }
            else:
                result = {
                    "decision": "run_experiment",
                    "rationale": "The available evidence distinguishes neither encoding nor caller behavior.",
                    "next_experiment": "Replay both payload classes on the prior and proposed revisions.",
                    "unresolved": ["Encoding scope"],
                }
            return {
                "result": result,
                "model": role,
                "role": role,
                "estimated_cost_usd": 0.001,
            }

    capsule, revision = memory_and_revision
    context = Context()
    provider = Provider()
    result = audit_memories(
        revision,
        {
            "memory_ids": [capsule["id"]],
            "prepare_dependencies": False,
            "analyze_conflict": True,
            "allow_ultra": True,
        },
        context,
        Executor(memory_exit=1),
        SandboxConfig("key", "project", "image", "url"),
        provider,
    )
    assert result["verdict"] == "memory_conflict"
    assert provider.calls == ["engineering", "reasoning"]
    assert context.roles == ["engineering", "reasoning"]
    assert (
        result["memory_audit"]["analysis"]["reasoning"]["decision"] == "run_experiment"
    )


def test_valid_dirty_baseline_does_not_hide_memory_result(memory_and_revision):
    capsule, revision = memory_and_revision
    result = audit_memories(
        revision,
        {"memory_ids": [capsule["id"]], "prepare_dependencies": False},
        Context(),
        Executor(memory_exit=1, baseline_exit=1),
        SandboxConfig("key", "project", "image", "url"),
    )
    assert result["verdict"] == "memory_conflict"
    assert result["memory_audit"]["baseline_status"] == "already_failing"
