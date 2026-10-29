import copy
import hashlib

import pytest
from fastapi.testclient import TestClient
from test_repository import project

from issue2proof.app import app, save_report
from issue2proof.memory import (
    capsule_from_report,
    enrich_capsule,
    export_capsule_bundle,
    get_capsule,
    import_capsule_bundle,
    list_capsules,
    save_capsule,
    search_capsules,
    semantic_search,
    supersede_capsule,
)
from issue2proof.portable import search_bundle, validate_bundle


@pytest.fixture
def report(tmp_path, monkeypatch):
    monkeypatch.setenv("ISSUE2PROOF_DB", str(tmp_path / "memory.sqlite3"))
    monkeypatch.setenv("ISSUE2PROOF_WORKER", "0")
    monkeypatch.delenv("ISSUE2PROOF_ACCESS_TOKEN", raising=False)
    item = project()
    regression = "def test_unicode_length():\n    assert 6 == 6\n"
    item.update(
        verdict="checks_passed",
        issue="Unicode payload length must use encoded bytes.",
        generated_regression={
            "path": "issue2proof_generated/test_regression.py",
            "source": regression,
            "sha256": hashlib.sha256(regression.encode()).hexdigest(),
        },
        draft_changes={"src/pricing.py": "def total():\n    return 2\n"},
        candidate_hashes={"src/pricing.py": "candidate-hash"},
        environment={"image": "immutable-image", "requirements": ["urllib3==2.2.3"]},
        limitations=["Other encodings were not evaluated."],
        pipeline={"reproduction": {"operation_id": "operation-1"}},
    )
    return save_report(item)


def test_capsule_is_versioned_searchable_and_idempotent(report):
    first = save_capsule(capsule_from_report(report))
    assert first["version"] == 1
    assert first["evidence"]["operation_ids"] == ["operation-1"]
    assert save_capsule(capsule_from_report(report))["id"] == first["id"]
    assert get_capsule(first["id"])["claim"].startswith("Unicode")
    result = search_capsules("encoded unicode content length")
    assert result[0]["capsule"]["id"] == first["id"]
    assert len(list_capsules(first["repository_key"])) == 1


def test_embedding_ranking_and_supersession(report):
    first = capsule_from_report(report)
    save_capsule(first, [1.0, 0.0])
    second_report = copy.deepcopy(report)
    second_report["id"] = "new-run"
    second_report["issue"] = "Calendar month end must clamp the day."
    second = capsule_from_report(second_report, key=first["repository_key"])
    save_capsule(second, [0.0, 1.0])
    results = search_capsules(
        "behavioral change", key=first["repository_key"], query_vector=[0.0, 1.0]
    )
    assert results[0]["capsule"]["id"] == second["id"]
    supersede_capsule(first["id"], second["id"])
    assert [item["id"] for item in list_capsules()] == [second["id"]]
    assert get_capsule(second["id"])["supersedes"] == first["id"]


def test_semantic_search_batches_and_caches_embeddings(report):
    class Provider:
        def __init__(self):
            self.calls = []

        def embed(self, texts):
            self.calls.append(texts)
            vectors = [
                [0.0, 1.0] if index == 0 else [0.0, 1.0] for index in range(len(texts))
            ]
            return {
                "vectors": vectors,
                "model": "embedding-mock",
                "usage": {"prompt_tokens": 10},
                "estimated_cost_usd": 0.001,
            }

    capsule = save_capsule(capsule_from_report(report))
    provider = Provider()
    result = semantic_search(
        "unicode byte length", key=capsule["repository_key"], provider=provider
    )
    assert result["model"] == "embedding-mock"
    assert result["results"][0]["capsule"]["id"] == capsule["id"]
    assert len(provider.calls[0]) == 2
    semantic_search("unicode body", key=capsule["repository_key"], provider=provider)
    assert len(provider.calls[1]) == 1


def test_fast_model_enriches_index_without_rewriting_evidence(report):
    class Provider:
        def request(self, instruction, context, *, role, max_tokens):
            assert role == "fast"
            assert max_tokens == 800
            return {
                "result": {
                    "summary": "Encoded byte length is preserved for Unicode payloads.",
                    "keywords": ["unicode", "encoded bytes", "content length"],
                    "change_triggers": ["Changing request body serialization"],
                },
                "model": "nemotron-nano-mock",
                "role": role,
                "prompt_tokens": 50,
                "completion_tokens": 30,
                "estimated_cost_usd": 0.001,
            }

    capsule = save_capsule(capsule_from_report(report), [1.0, 0.0])
    enriched = enrich_capsule(capsule["id"], Provider())
    assert enriched["claim"] == capsule["claim"]
    assert enriched["evidence"] == capsule["evidence"]
    assert enriched["ai_index"]["role"] == "fast"
    assert (
        search_capsules("request body serialization")[0]["capsule"]["id"]
        == capsule["id"]
    )


def test_memory_api_requires_completed_evidence(report):
    client = TestClient(app)
    response = client.post(f"/api/runs/{report['id']}/memory", json={})
    assert response.status_code == 201
    assert client.get("/api/memories").json()[0]["origin"]["run_id"] == report["id"]
    assert (
        client.post(
            "/api/memories/search", json={"query": "unicode byte length"}
        ).json()[0]["capsule"]["origin"]["run_id"]
        == report["id"]
    )

    incomplete = save_report(project())
    response = client.post(f"/api/runs/{incomplete['id']}/memory", json={})
    assert response.status_code == 422


def test_agent_context_packet_withholds_regression_source(report):
    client = TestClient(app)
    capsule = client.post(f"/api/runs/{report['id']}/memory", json={}).json()
    response = client.post(
        "/api/integrations/context",
        json={"query": "Change Unicode request body serialization"},
    )
    assert response.status_code == 200
    packet = response.json()
    assert packet["schema"] == "issue2proof.agent-context.v1"
    assert packet["memories"][0]["id"] == capsule["id"]
    assert packet["memories"][0]["regression"]["source_withheld"] is True
    assert "source" not in packet["memories"][0]["regression"]


def test_portable_bundle_round_trip_and_tamper_detection(report, tmp_path, monkeypatch):
    capsule = save_capsule(capsule_from_report(report))
    bundle = export_capsule_bundle(capsule["repository_key"])
    assert validate_bundle(bundle) == [capsule]
    assert search_bundle(
        bundle, "refactor serialization", changed_paths=["src/pricing.py"]
    )[0]["capsule"]["id"] == capsule["id"]

    monkeypatch.setenv("ISSUE2PROOF_DB", str(tmp_path / "imported.sqlite3"))
    result = import_capsule_bundle(bundle)
    assert result == {"validated": 1, "imported_ids": [capsule["id"]]}
    assert import_capsule_bundle(bundle) == result

    tampered = copy.deepcopy(bundle)
    tampered["entries"][0]["capsule"]["claim"] = "Changed claim"
    with pytest.raises(ValueError, match="bundle hash"):
        validate_bundle(tampered)


def test_portable_bundle_api(report):
    from issue2proof.app import export_memories, import_memories

    capsule = save_capsule(capsule_from_report(report))
    bundle = export_memories(capsule["repository_key"])
    assert bundle["capsule_count"] == 1
    assert import_memories(bundle)["validated"] == 1


def test_public_import_requires_server_authenticated_bundle(report, tmp_path, monkeypatch):
    monkeypatch.setenv("ISSUE2PROOF_ACCESS_TOKEN", "private-signing-token-at-least-24-characters")
    capsule = save_capsule(capsule_from_report(report))
    bundle = export_capsule_bundle(capsule["repository_key"])
    assert bundle["authentication"]["algorithm"] == "hmac-sha256"
    monkeypatch.setenv("ISSUE2PROOF_DB", str(tmp_path / "signed-import.sqlite3"))
    assert import_capsule_bundle(bundle)["validated"] == 1
    forged = copy.deepcopy(bundle)
    forged["entries"][0]["capsule"]["claim"] = "Fabricated evidence"
    with pytest.raises(ValueError, match="authentication"):
        import_capsule_bundle(forged)
