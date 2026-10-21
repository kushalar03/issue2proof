import io
import json
import stat
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient

from issue2proof.app import app
from issue2proof.draft import RepositoryProvider, generate_draft
from issue2proof.github import import_public_repository, parse_repository_url
from issue2proof.repository import inspect_archive

ORIGINAL = "def total(a, b):\n    return a-b\n"
FIX = "def total(a, b):\n    return max(0, a-b)\n"
TEST = "from pricing import total\n\ndef test_clamp():\n    assert total(10, 20) == 0\n"


def archive(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as result:
        for name, source in files.items():
            result.writestr(name, source)
    return stream.getvalue()


def project():
    return inspect_archive(
        archive(
            {
                "project/pricing.py": ORIGINAL,
                "project/tests/test_existing.py": TEST,
                "project/tests/test_private.py": "PRIVATE_HOLDOUT",
                "project/requirements.txt": "pytest==8.4.2",
                "project/.env": "NEBIUS_API_KEY=never-upload-this",
            }
        ),
        "Clamp excess discounts to zero.",
    )


def test_public_github_import_is_fixed_origin_and_bounded():
    requested = []

    def handler(request):
        requested.append(str(request.url))
        return httpx.Response(200, content=archive({"repo/pricing.py": ORIGINAL}))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = import_public_repository(
            "https://github.com/example/project.git",
            "Fix calculation.",
            ref="feature/fix",
            client=client,
        )
    assert requested == [
        "https://codeload.github.com/example/project/zip/feature%2Ffix"
    ]
    assert report["repository"]["full_name"] == "example/project"
    assert report["sources"] == {"pricing.py": ORIGINAL}


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/owner/repo",
        "https://example.com/owner/repo",
        "https://github.com/owner/repo/issues/1",
        "https://user@github.com/owner/repo",
        "https://github.com/owner/repo?download=1",
    ],
)
def test_github_import_rejects_non_repository_targets(url):
    with pytest.raises(ValueError):
        parse_repository_url(url)


def test_archive_inventory_never_retains_hidden_file_contents():
    report = project()
    assert report["sources"] == {"pricing.py": ORIGINAL}
    assert report["dependency_manifests"] == {"requirements.txt": "pytest==8.4.2"}
    assert report["excluded_files"] == ["project/.env"]
    assert "never-upload-this" not in json.dumps(report)
    assert report["verdict"] == "awaiting_model"
    assert len(report["file_hashes"]["pricing.py"]) == 64


@pytest.mark.parametrize(
    "name",
    [
        "../pricing.py",
        "/pricing.py",
        "dir/../pricing.py",
        "dir\\pricing.py",
        "a//pricing.py",
        "./pricing.py",
        "C:/pricing.py",
    ],
)
def test_unsafe_paths_rejected(name):
    with pytest.raises(ValueError, match="unsafe path"):
        inspect_archive(archive({name: ORIGINAL}), "Fix the bug.")


def test_symlink_rejected():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as zipped:
        entry = zipfile.ZipInfo("pricing.py")
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        zipped.writestr(entry, "/etc/passwd")
    with pytest.raises(ValueError, match="Symlinks"):
        inspect_archive(data.getvalue(), "Fix.")


@pytest.mark.parametrize(
    "data,message",
    [
        (b"not a zip", "valid unencrypted ZIP"),
        (archive({"pricing.py": b"\xff"}), "UTF-8"),
        (archive({"pricing.py": "x" * 200001}), "expanded text limits"),
        (archive({"README.md": "No implementation"}), "implementation file"),
        (archive({"test_only.py": TEST}), "implementation file"),
        (archive({"pricing.py": ORIGINAL, "pyproject.toml": "[broken"}), "valid TOML"),
    ],
)
def test_invalid_archives_rejected(data, message):
    with pytest.raises(ValueError, match=message):
        inspect_archive(data, "Fix the bug.")


class Provider:
    def __init__(self, repair=None, reproduction=None):
        self.calls = []
        self.repair = repair or {"changes": {"pricing.py": FIX}}
        self.reproduction = reproduction or {"test_source": TEST, "clarification": None}

    def request(self, instruction, context):
        self.calls.append((instruction, context))
        return {
            "result": self.reproduction if len(self.calls) == 1 else self.repair,
            "model": "test-model",
            "estimated_cost_usd": None,
        }


def test_draft_keeps_independent_tests_private_and_never_claims_verification():
    report = project()
    report["independent_test_paths"] = ["tests/test_private.py"]
    provider = Provider()
    draft = generate_draft(report, provider)
    assert draft["verdict"] == "awaiting_sandbox"
    assert len(provider.calls) == 2
    assert "PRIVATE_HOLDOUT" not in json.dumps(provider.calls)
    assert draft["draft_changes"] == {"pricing.py": FIX}
    assert (
        draft["test_hashes"]["tests/test_private.py"]
        == report["file_hashes"]["tests/test_private.py"]
    )
    assert (
        draft["generated_regression"]["sha256"]
        == draft["test_hashes"][draft["generated_regression"]["path"]]
    )
    assert report["verdict"] == "awaiting_model"


@pytest.mark.parametrize(
    "repair",
    [
        {"changes": {"tests/test_existing.py": "pass"}},
        {"changes": {"../evil.py": "pass"}},
        {"changes": {"requirements.txt": "evil-package"}},
        {"changes": {"pricing.py": "def invalid("}},
        {"changes": {"pricing.py": ORIGINAL}},
        {"changes": {}, "unexpected": True},
    ],
)
def test_invalid_candidate_cannot_be_downloadable_or_verified(repair):
    draft = generate_draft(project(), Provider(repair=repair))
    assert draft["verdict"] == "draft_failed"
    assert "draft_changes" not in draft


def test_ambiguity_stops_before_repair_request():
    provider = Provider(
        reproduction={
            "test_source": None,
            "clarification": "Should the result clamp or raise?",
        }
    )
    report = generate_draft(project(), provider)
    assert report["verdict"] == "needs_clarification"
    assert len(provider.calls) == 1


def test_context_budget_prevents_paid_requests():
    report = project()
    report["sources"]["pricing.py"] = "a" * 36000
    provider = Provider()
    with pytest.raises(ValueError, match="35,000"):
        generate_draft(report, provider)
    assert not provider.calls


def test_transport_error_details_are_not_exposed():
    class Broken:
        def request(self, instruction, context):
            raise RuntimeError("Authorization: Bearer private-token")

    report = generate_draft(project(), Broken())
    assert report["verdict"] == "draft_failed"
    assert "private-token" not in json.dumps(report)


def test_upload_draft_export_and_duplicate_request_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("ISSUE2PROOF_LEGACY_API", "1")
    monkeypatch.setenv("ISSUE2PROOF_DB", str(tmp_path / "runs.db"))
    client = TestClient(app)
    uploaded = client.post(
        "/api/projects",
        params={"issue": "Clamp excess discounts to zero."},
        content=archive({"pricing.py": ORIGINAL, "tests/test_existing.py": TEST}),
    ).json()
    run_id = uploaded["id"]
    assert client.get("/api/runs/" + run_id).json() == uploaded
    assert client.get("/api/runs/" + run_id + "/artifacts").status_code == 409
    assert client.post("/api/projects/" + run_id + "/draft", json={}).status_code == 422
    provider = Provider()
    monkeypatch.setattr("issue2proof.draft.RepositoryProvider", lambda: provider)
    invalid = client.post(
        "/api/projects/" + run_id + "/draft",
        json={"send_to_nebius": True, "independent_test_paths": ["missing.py"]},
    )
    assert invalid.status_code == 422
    assert not provider.calls
    response = client.post(
        "/api/projects/" + run_id + "/draft",
        json={
            "send_to_nebius": True,
            "independent_test_paths": ["tests/test_existing.py"],
        },
    )
    assert response.status_code == 200
    assert response.json()["verdict"] == "awaiting_sandbox"
    assert all(not context["existing_tests"] for _, context in provider.calls)
    assert (
        client.post(
            "/api/projects/" + run_id + "/draft", json={"send_to_nebius": True}
        ).status_code
        == 409
    )
    assert len(provider.calls) == 2
    artifact = client.get("/api/runs/" + run_id + "/artifacts")
    with zipfile.ZipFile(io.BytesIO(artifact.content)) as zipped:
        assert zipped.read("candidate.patch").decode().startswith("--- a/pricing.py")
        assert "UNVERIFIED" in zipped.read("README.txt").decode()
        assert json.loads(zipped.read("evidence.json"))["verdict"] == "awaiting_sandbox"
    assert (
        client.post(
            "/api/projects", params={"issue": "bug"}, content=b"x" * 10000001
        ).status_code
        == 413
    )


def test_repository_model_request_contract(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "fake-key")
    original_client = httpx.Client

    def handler(request):
        payload = json.loads(request.content)
        assert "untrusted data" in payload["messages"][0]["content"]
        assert payload["max_tokens"] == 8192
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"test_source": null, "clarification": "What should happen?"}'
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            },
        )

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler)),
    )
    result = RepositoryProvider().request("Return JSON.", {"issue": "bug"})
    assert result["result"]["test_source"] is None
    assert result["estimated_cost_usd"] is not None


def test_duplicate_paths_and_reserved_artifacts_rejected():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as zipped:
        zipped.writestr("pricing.py", ORIGINAL)
        with pytest.warns(UserWarning):
            zipped.writestr("pricing.py", FIX)
    with pytest.raises(ValueError, match="duplicate paths"):
        inspect_archive(data.getvalue(), "Fix.")
    with pytest.raises(ValueError, match="reserved"):
        inspect_archive(
            archive(
                {
                    "pricing.py": ORIGINAL,
                    "issue2proof_generated/test_regression.py": TEST,
                }
            ),
            "Fix.",
        )


def test_assertion_must_be_inside_the_generated_test():
    provider = Provider(
        reproduction={
            "test_source": "assert False\ndef test_bug():\n    pass\n",
            "clarification": None,
        }
    )
    result = generate_draft(project(), provider)
    assert result["verdict"] == "draft_failed"
    assert len(provider.calls) == 1


def test_patch_accounts_for_missing_final_newline():
    from issue2proof.draft import unified_patch

    patch = unified_patch("pricing.py", "x = 1", "x = 2")
    assert patch.count("\\ No newline at end of file") == 2
    assert "-x = 1\n" in patch and "+x = 2\n" in patch
