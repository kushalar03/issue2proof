import httpx
import pytest

from issue2proof.provider import NebiusProvider


def test_missing_configuration(monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.delenv("NEBIUS_MODEL", raising=False)
    with pytest.raises(ValueError, match="Configure"):
        NebiusProvider()


@pytest.mark.parametrize(
    "content,valid",
    [
        ('{"source":"def total(a,b): return max(0,a-b)"}', True),
        ('{"source":"x", "tests":"weakened"}', False),
        ('{"source":42}', False),
    ],
)
def test_response_contract(monkeypatch, content, valid):
    monkeypatch.setenv("NEBIUS_API_KEY", "test-key")
    monkeypatch.setenv("NEBIUS_MODEL", "account-model")
    original_client = httpx.Client

    def handler(request):
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(
            200, json={"choices": [{"message": {"content": content}}]}
        )

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler)),
    )
    if valid:
        assert NebiusProvider().candidate("clamp", "source").startswith("def total")
    else:
        with pytest.raises(ValueError, match="Invalid model response"):
            NebiusProvider().candidate("clamp", "source")


def test_usage_and_default_model(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "test-key")
    monkeypatch.delenv("NEBIUS_MODEL", raising=False)
    original_client = httpx.Client

    def handler(request):
        import json

        body = json.loads(request.content)
        assert body["model"] == "nvidia/nemotron-3-super-120b-a12b"
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"source":"pass"}'},
                    }
                ],
                "usage": {"prompt_tokens": 50000, "completion_tokens": 10000},
            },
        )

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler)),
    )
    result = NebiusProvider().generate("issue", "source")
    assert result.estimated_cost_usd == 0.024
    assert result.prompt_tokens == 50000


def test_truncation_rejected(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "test-key")
    original_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "finish_reason": "length",
                                "message": {"content": '{"source":"pass"}'},
                            }
                        ]
                    },
                )
            )
        ),
    )
    with pytest.raises(ValueError, match="truncated"):
        NebiusProvider().generate("issue", "source")
