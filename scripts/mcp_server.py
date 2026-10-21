#!/usr/bin/env python3
"""Expose Issue2Proof repository memory as a local MCP tool over stdio."""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

SERVER_INFO = {"name": "issue2proof", "version": "2.0.0"}
RECALL_TOOL = {
    "name": "recall_repository_memory",
    "description": (
        "Recall verified behavioral contracts before changing a repository. "
        "Returns claims, scope, provenance, boundaries and regression hashes."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "change": {
                "type": "string",
                "description": "The proposed code change or behavior being investigated.",
            },
            "repository": {
                "type": "string",
                "description": "Optional repository key used to restrict recall.",
            },
            "semantic": {
                "type": "boolean",
                "default": True,
                "description": "Use one budgeted Qwen embedding batch; disable for free lexical recall.",
            },
        },
        "required": ["change"],
        "additionalProperties": False,
    },
}
AUDIT_TOOL = {
    "name": "audit_repository_revision",
    "description": (
        "Upload the current local repository revision, replay selected Memory Capsules "
        "in Nebius Sandboxes, and wait briefly for a preserved/violated/uncertain verdict."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "repository_path": {
                "type": "string",
                "description": "Repository directory at or below the MCP process working directory.",
            },
            "change": {
                "type": "string",
                "description": "Description of the proposed revision being audited.",
            },
            "memory_ids": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 10,
                "description": "Capsule IDs returned by recall_repository_memory.",
            },
            "wait_seconds": {
                "type": "integer",
                "minimum": 0,
                "maximum": 300,
                "default": 120,
                "description": "How long to poll before returning the durable job ID.",
            },
            "analyze_conflict": {
                "type": "boolean",
                "default": True,
                "description": "Ask Nemotron Super to explain a replay conflict.",
            },
            "prepare_dependencies": {
                "type": "boolean",
                "default": True,
                "description": "Build a dependency image; disable for self-contained revisions.",
            },
            "allow_ultra": {
                "type": "boolean",
                "default": False,
                "description": "Permit a budgeted Ultra escalation for a high-risk conflict.",
            },
        },
        "required": ["repository_path", "change", "memory_ids"],
        "additionalProperties": False,
    },
}
TOOLS = [RECALL_TOOL, AUDIT_TOOL]


def request_api(path, *, method="GET", body=None, raw=None, timeout=30):
    base_url = os.environ.get("ISSUE2PROOF_URL", "http://127.0.0.1:8000").rstrip("/")
    token = os.environ.get("ISSUE2PROOF_ACCESS_TOKEN", "")
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    headers = {**({"Authorization": "Bearer " + token} if token else {})}
    if body is not None:
        headers["Content-Type"] = "application/json"
    elif raw is not None:
        headers["Content-Type"] = "application/zip"
    request = urllib.request.Request(
        base_url + path, data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response) if response.status != 204 else None
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise RuntimeError(f"Issue2Proof returned HTTP {error.code}: {detail}") from None
    except urllib.error.URLError as error:
        raise RuntimeError(f"Cannot reach Issue2Proof at {base_url}: {error.reason}") from None


def fetch_context(arguments):
    body = {
        "query": arguments["change"],
        "repository_key": arguments.get("repository") or None,
        "semantic": bool(arguments.get("semantic", True)),
        "authorize_nebius": bool(arguments.get("semantic", True)),
        "limit": 5,
    }
    return request_api("/api/integrations/context", method="POST", body=body)


def repository_archive(value):
    root = Path.cwd().resolve()
    repository = Path(value).expanduser().resolve()
    if not repository.is_dir() or not (repository == root or root in repository.parents):
        raise RuntimeError("repository_path must be a directory at or below the MCP working directory.")
    excluded_parts = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}
    excluded_names = {".env", "id_rsa", "id_ed25519"}
    files = []
    total = 0
    for path in sorted(repository.rglob("*")):
        relative = path.relative_to(repository)
        if excluded_parts.intersection(relative.parts) or path.is_dir():
            continue
        if path.is_symlink():
            raise RuntimeError(f"Refusing to archive symbolic link: {relative}")
        if path.name in excluded_names or path.suffix.lower() in {".pem", ".key", ".p12"}:
            continue
        size = path.stat().st_size
        if size > 2_000_000:
            continue
        total += size
        files.append((path, relative))
        if len(files) > 1500 or total > 9_000_000:
            raise RuntimeError("Repository exceeds the bounded MCP audit archive limits.")
    if not files:
        raise RuntimeError("Repository contains no eligible files to audit.")
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, relative in files:
            archive.write(path, relative.as_posix())
    if buffer.tell() > 10_000_000:
        raise RuntimeError("Compressed repository exceeds the 10 MB upload limit.")
    return buffer.getvalue()


def audit_revision(arguments):
    memory_ids = arguments.get("memory_ids")
    if (
        not isinstance(memory_ids, list)
        or not 1 <= len(memory_ids) <= 10
        or any(not isinstance(item, str) or not item for item in memory_ids)
    ):
        raise RuntimeError("memory_ids must contain one to ten capsule IDs.")
    archive = repository_archive(arguments["repository_path"])
    query = urllib.parse.urlencode({"issue": arguments["change"]})
    report = request_api("/api/projects?" + query, method="POST", raw=archive, timeout=60)
    run_id = report["id"]
    job = request_api(
        f"/api/projects/{urllib.parse.quote(run_id)}/audit-memory",
        method="POST",
        body={
            "memory_ids": memory_ids,
            "execute_remote": True,
            "prepare_dependencies": bool(arguments.get("prepare_dependencies", True)),
            "max_model_calls": 2 if arguments.get("allow_ultra", False) else 1,
            "max_sandbox_calls": 8,
            "max_repairs": 1,
            "budget_usd": 0.75,
            "analyze_conflict": bool(arguments.get("analyze_conflict", True)),
            "allow_ultra": bool(arguments.get("allow_ultra", False)),
        },
        timeout=30,
    )
    deadline = time.monotonic() + min(max(arguments.get("wait_seconds", 120), 0), 300)
    while job.get("state") in {"queued", "running"} and time.monotonic() < deadline:
        time.sleep(2)
        job = request_api(f"/api/jobs/{urllib.parse.quote(job['id'])}")
    result = {
        "run_id": run_id,
        "job_id": job["id"],
        "state": job.get("state"),
        "stage": job.get("stage"),
        "error": job.get("error"),
    }
    if job.get("state") == "completed":
        completed = request_api(f"/api/runs/{urllib.parse.quote(run_id)}")
        result.update(
            verdict=completed.get("verdict"),
            explanation=completed.get("explanation"),
            memory_audit=completed.get("memory_audit"),
            limitations=completed.get("limitations", []),
        )
    return result


def response(message_id, result=None, error=None):
    packet = {"jsonrpc": "2.0", "id": message_id}
    if error is not None:
        packet["error"] = error
    else:
        packet["result"] = result
    return packet


def process(message, recall=fetch_context, audit=audit_revision):
    method = message.get("method")
    message_id = message.get("id")
    if method == "initialize":
        requested = message.get("params", {}).get("protocolVersion", "2024-11-05")
        return response(
            message_id,
            {
                "protocolVersion": requested,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        )
    if method == "ping":
        return response(message_id, {})
    if method == "tools/list":
        return response(message_id, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params", {})
        name = params.get("name")
        if name not in {tool["name"] for tool in TOOLS}:
            return response(message_id, error={"code": -32602, "message": "Unknown tool"})
        arguments = params.get("arguments", {})
        if not isinstance(arguments.get("change"), str) or not arguments["change"].strip():
            return response(
                message_id,
                error={"code": -32602, "message": "change must be a non-empty string"},
            )
        if name == AUDIT_TOOL["name"] and not isinstance(
            arguments.get("repository_path"), str
        ):
            return response(
                message_id,
                error={"code": -32602, "message": "repository_path must be a string"},
            )
        try:
            packet = audit(arguments) if name == AUDIT_TOOL["name"] else recall(arguments)
        except RuntimeError as error:
            return response(
                message_id,
                {
                    "content": [{"type": "text", "text": str(error)}],
                    "isError": True,
                },
            )
        return response(
            message_id,
            {
                "content": [{"type": "text", "text": json.dumps(packet, indent=2)}],
                "structuredContent": packet,
            },
        )
    if message_id is None:
        return None
    return response(message_id, error={"code": -32601, "message": "Method not found"})


def main():
    for line in sys.stdin:
        try:
            message = json.loads(line)
            result = process(message)
        except (json.JSONDecodeError, TypeError) as error:
            result = response(None, error={"code": -32700, "message": str(error)})
        if result is not None:
            sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
