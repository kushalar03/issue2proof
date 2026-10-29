import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "mcp_server.py"
SPEC = importlib.util.spec_from_file_location("issue2proof_mcp_server", MODULE_PATH)
assert SPEC and SPEC.loader
MCP_SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MCP_SERVER)
process = MCP_SERVER.process


def test_mcp_lists_and_calls_repository_memory_tool():
    listed = process({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert listed["result"]["tools"][0]["name"] == "recall_repository_memory"
    assert listed["result"]["tools"][1]["name"] == "audit_repository_revision"

    seen = {}

    def recall(arguments):
        seen.update(arguments)
        return {"schema": "issue2proof.agent-context.v1", "memories": [{"id": "m1"}]}

    called = process(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "recall_repository_memory",
                "arguments": {"change": "Refactor safe_join", "repository": "pallets/werkzeug"},
            },
        },
        recall=recall,
    )
    assert seen["change"] == "Refactor safe_join"
    assert called["result"]["structuredContent"]["memories"][0]["id"] == "m1"
    assert not called["result"].get("isError", False)


def test_mcp_calls_repository_audit_tool():
    seen = {}

    def audit(arguments):
        seen.update(arguments)
        return {"job_id": "j1", "state": "completed", "verdict": "memory_preserved"}

    called = process(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "audit_repository_revision",
                "arguments": {
                    "repository_path": ".",
                    "change": "Refactor safe_join",
                    "memory_ids": ["m1"],
                },
            },
        },
        audit=audit,
    )
    assert seen["repository_path"] == "."
    assert called["result"]["structuredContent"]["verdict"] == "memory_preserved"
    assert not called["result"].get("isError", False)


def test_mcp_archive_refuses_credentials(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text("print('safe')\n")
    (tmp_path / "runtime-config.json").write_text('{"private_key":"secret"}')
    with pytest.raises(RuntimeError, match="credential marker"):
        MCP_SERVER.repository_archive(str(tmp_path))


def test_mcp_service_url_requires_https_off_localhost(monkeypatch):
    monkeypatch.setenv("ISSUE2PROOF_URL", "http://example.com")
    with pytest.raises(RuntimeError, match="HTTPS"):
        MCP_SERVER.service_url()
    monkeypatch.setenv("ISSUE2PROOF_URL", "http://127.0.0.1:8000")
    assert MCP_SERVER.service_url() == "http://127.0.0.1:8000"
