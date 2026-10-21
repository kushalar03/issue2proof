import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from issue2proof.sandbox import PAYLOAD_HASH, SandboxConfig, smoke_check


@pytest.mark.parametrize(
    "exit_code,digest,truncated,expected",
    [
        (0, PAYLOAD_HASH, False, True),
        (0, "wrong", False, False),
        (1, PAYLOAD_HASH, False, False),
        (0, PAYLOAD_HASH, True, False),
    ],
)
def test_smoke_requires_complete_execution_and_transfer(
    exit_code, digest, truncated, expected
):
    class Image:
        def run(self, **kwargs):
            # A future change must never leak credentials into the microVM.
            assert kwargs["env"] == {}
            assert kwargs["disposable"] is True
            assert kwargs["preserve_env"] is False
            assert kwargs["timeout"] == 30
            self.result = SimpleNamespace(
                exit_code=exit_code,
                stdout=json.dumps({"sha256": digest}),
                stderr="",
                elapsed_time=timedelta(seconds=1),
                cost=0.01,
                truncated=truncated,
            )
            return self

        def wait(self):
            return self

    client = SimpleNamespace(images=SimpleNamespace(use=lambda image: Image()))
    report = smoke_check(SandboxConfig("secret", "project", "image", "url"), client)
    assert report["ok"] is expected
    assert report["arbitrary_execution_enabled"] is False
    assert "secret" not in json.dumps(report)


def test_configuration_requires_project_and_accepts_quickstart_image(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "test-key")
    monkeypatch.delenv("NEBIUS_PROJECT_ID", raising=False)
    monkeypatch.delenv("NEBIUS_SANDBOX_IMAGE", raising=False)
    with pytest.raises(ValueError, match="NEBIUS_PROJECT_ID"):
        SandboxConfig.from_env()
    monkeypatch.setenv("NEBIUS_PROJECT_ID", "project")
    assert SandboxConfig.from_env().image == "python:3.12-slim"
    monkeypatch.setenv("NEBIUS_SANDBOX_IMAGE", "bad image")
    with pytest.raises(ValueError, match="valid bounded image reference"):
        SandboxConfig.from_env()


def test_sdk_client_construction(monkeypatch):
    # Exercise released SDK configuration without contacting a remote service.
    from contree_sdk.sdk.managers.images._sync import ImagesManagerSync

    def stop(self, image):
        assert self._client._config.operation_timeout == 30
        assert self._client._config.auth.project_id == "project"
        raise RuntimeError("client constructed")

    monkeypatch.setattr(ImagesManagerSync, "use", stop)
    with pytest.raises(RuntimeError, match="client constructed"):
        smoke_check(SandboxConfig("key", "project", "image", "https://example.com"))
