import pytest
from test_repository import TEST, project

from issue2proof.pipeline import investigate
from issue2proof.sandbox import SandboxConfig

OPTIONS = {
    "independent_test_paths": ["tests/test_private.py"],
    "prepare_dependencies": False,
    "max_repairs": 3,
}


class Context:
    def __init__(self):
        self.stages = []
        self.reservations = []

    def check(self):
        pass

    def save(self, report, stage):
        self.stages.append(stage)

    def reserve(self, kind, *, role=None):
        self.reservations.append((kind, role))
        return len(self.reservations)

    def reconcile(self, reservation, actual):
        pass


class Provider:
    def __init__(self, executor):
        self.executor = executor
        self.calls = []

    def request(self, instruction, payload, *, role="engineering"):
        self.calls.append((instruction, payload))
        if len(self.calls) == 1:
            assert self.executor.calls == 2
            result = {"test_source": TEST, "clarification": None}
        else:
            assert self.executor.calls >= 3
            result = {
                "edits": [
                    {
                        "path": "pricing.py",
                        "old": "return a-b",
                        "new": "return 0"
                        if len(self.calls) == 2
                        else "return max(0, a-b)",
                    }
                ]
            }
        return {"result": result, "model": "mock", "estimated_cost_usd": 0.01}


class Executor:
    def __init__(self):
        self.calls = 0
        self.bundles = []

    def execute(self, files, tests):
        self.calls += 1
        self.bundles.append((files, tests))
        regression = any("issue2proof_generated/" in name for name in tests)
        wrong = "return 0" in files["pricing.py"]
        failed = (self.calls == 3) or (wrong and not regression)
        return {
            "evidence_valid": True,
            "exit_code": int(failed),
            "summary": {"tests": 1, "failures": int(failed), "errors": 0, "skipped": 0},
            "assertion_failures": int(failed),
            "output": "Failure without private test contents" if failed else "passed",
        }


def test_reproduce_first_then_revise_without_disclosing_independent_tests():
    executor = Executor()
    provider = Provider(executor)
    context = Context()
    report = investigate(
        project(),
        OPTIONS,
        context,
        provider,
        executor,
        SandboxConfig("key", "p", "image", "url"),
    )
    assert report["verdict"] == "checks_passed"
    assert len(report["attempts"]) == 2
    assert not report["attempts"][0]["accepted"] and report["attempts"][1]["accepted"]
    assert len(provider.calls) == 3
    assert "PRIVATE_HOLDOUT" not in str(provider.calls)
    assert context.stages.index("reproduction_complete") < context.stages.index(
        "generating_repair_1"
    )
    assert executor.calls == 9


def test_completed_checkpoints_are_not_reexecuted_on_resume():
    executor = Executor()
    provider = Provider(executor)
    context = Context()
    report = investigate(
        project(),
        OPTIONS,
        context,
        provider,
        executor,
        SandboxConfig("key", "p", "image", "url"),
    )
    before = executor.calls
    report = investigate(
        report,
        OPTIONS,
        context,
        provider,
        executor,
        SandboxConfig("key", "p", "image", "url"),
    )
    assert report["verdict"] == "checks_passed"
    assert executor.calls == before and len(provider.calls) == 3


def test_setup_failure_stops_all_inference():
    executor = Executor()
    executor.execute = lambda *args: {"evidence_valid": False, "exit_code": 2}
    provider = Provider(executor)
    report = investigate(
        project(),
        OPTIONS,
        Context(),
        provider,
        executor,
        SandboxConfig("key", "p", "image", "url"),
    )
    assert report["verdict"] == "setup_failed" and not provider.calls


def test_original_hash_tampering_is_rejected():
    report = project()
    report["sources"]["pricing.py"] += "\n# changed"
    with pytest.raises(ValueError, match="changed"):
        investigate(
            report,
            OPTIONS,
            Context(),
            Provider(Executor()),
            Executor(),
            SandboxConfig("key", "p", "image", "url"),
        )


def test_model_response_checkpoint_survives_worker_crash_without_rebilling():
    class Crash(BaseException):
        pass

    class CrashingContext(Context):
        crashed = False

        def save(self, report, stage):
            super().save(report, stage)
            if stage == "model_response_received" and not self.crashed:
                self.crashed = True
                raise Crash()

    report = project()
    executor = Executor()
    provider = Provider(executor)
    context = CrashingContext()
    with pytest.raises(Crash):
        investigate(
            report,
            OPTIONS,
            context,
            provider,
            executor,
            SandboxConfig("key", "p", "image", "url"),
        )
    assert len(provider.calls) == 1 and len(context.reservations) == 1
    result = investigate(
        report,
        OPTIONS,
        context,
        provider,
        executor,
        SandboxConfig("key", "p", "image", "url"),
    )
    assert result["verdict"] == "checks_passed"
    assert len(provider.calls) == 3 and len(context.reservations) == 3


def test_candidate_cannot_reduce_collected_test_counts():
    executor = Executor()
    original = executor.execute

    def shrink(files, tests):
        result = original(files, tests)
        if executor.calls > 3:
            result["summary"]["tests"] = 0
        return result

    executor.execute = shrink
    result = investigate(
        project(),
        {**OPTIONS, "max_repairs": 1},
        Context(),
        Provider(executor),
        executor,
        SandboxConfig("key", "p", "image", "url"),
    )
    assert result["verdict"] == "unresolved"
    assert not result["attempts"][0]["accepted"]
