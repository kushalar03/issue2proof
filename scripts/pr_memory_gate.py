#!/usr/bin/env python3
"""Recall and optionally replay Issue2Proof memory for a pull request."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from issue2proof.portable import search_bundle, validate_bundle  # noqa: E402


def event_context(event_path: Path | None) -> tuple[str, list[str]]:
    event = {}
    if event_path and event_path.exists():
        event = json.loads(event_path.read_text())
    pull = event.get("pull_request") or {}
    text = "\n".join(
        value
        for value in (pull.get("title"), pull.get("body"))
        if isinstance(value, str) and value.strip()
    )
    base = (pull.get("base") or {}).get("sha")
    head = (pull.get("head") or {}).get("sha") or "HEAD"
    paths = []
    if base:
        completed = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...{head}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0:
            paths = [line for line in completed.stdout.splitlines() if line]
    return text, paths


def remote_audit(args, bundle: dict, query: str, matches: list[dict]) -> dict:
    os.environ["ISSUE2PROOF_URL"] = args.url
    if args.token:
        os.environ["ISSUE2PROOF_ACCESS_TOKEN"] = args.token
    from scripts.mcp_server import audit_revision, request_api

    request_api("/api/memories/import", method="POST", body=bundle)
    context = request_api(
        "/api/integrations/context",
        method="POST",
        body={
            "query": query,
            "repository_key": args.repository_key or None,
            "semantic": args.semantic,
            "authorize_nebius": args.semantic,
            "limit": args.limit,
        },
    )
    memory_ids = [item["id"] for item in context.get("memories", [])]
    if not memory_ids:
        memory_ids = [item["capsule"]["id"] for item in matches]
    return audit_revision(
        {
            "repository_path": str(Path.cwd()),
            "change": query,
            "memory_ids": memory_ids[:10],
            "wait_seconds": args.wait_seconds,
            "analyze_conflict": True,
            "prepare_dependencies": True,
            "allow_ultra": False,
        }
    )


def markdown(result: dict) -> str:
    lines = ["## Issue2Proof Memory Gate", "", f"**Verdict:** `{result['verdict']}`", ""]
    if result.get("changed_paths"):
        lines.extend(["Changed paths: " + ", ".join(f"`{item}`" for item in result["changed_paths"][:20]), ""])
    matches = result.get("matches") or []
    if matches:
        lines.extend(["| Relevance | Verified behavioral claim |", "|---:|---|"])
        for item in matches:
            claim = str(item["claim"]).replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {item['score']:.3f} | {claim} |")
    else:
        lines.append("No related executable memory was found in the supplied bundle.")
    if result.get("audit"):
        lines.extend(["", "### Sandbox replay", "", f"`{json.dumps(result['audit'], sort_keys=True)}`"])
    lines.extend(["", "A passing gate covers only the selected frozen behaviors."])
    return "\n".join(lines) + "\n"


def write_github(name: str, value: str) -> None:
    destination = os.environ.get("GITHUB_OUTPUT")
    if destination:
        with open(destination, "a") as output:
            output.write(f"{name}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, default=Path(".issue2proof/memory.json"))
    parser.add_argument("--change", default="")
    parser.add_argument("--repository-key")
    parser.add_argument("--url", default=os.environ.get("ISSUE2PROOF_URL", ""))
    parser.add_argument("--token", default=os.environ.get("ISSUE2PROOF_ACCESS_TOKEN", ""))
    parser.add_argument("--semantic", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--wait-seconds", type=int, default=180)
    parser.add_argument("--report", type=Path, default=Path("issue2proof-gate.json"))
    args = parser.parse_args()
    if not args.bundle.exists():
        raise SystemExit(f"Memory bundle not found: {args.bundle}")
    bundle = json.loads(args.bundle.read_text())
    capsules = validate_bundle(bundle)
    event_text, paths = event_context(
        Path(os.environ["GITHUB_EVENT_PATH"]) if os.environ.get("GITHUB_EVENT_PATH") else None
    )
    query = args.change.strip() or event_text.strip() or "Review changed repository paths"
    matches = search_bundle(
        bundle,
        query,
        changed_paths=paths,
        repository_key=args.repository_key or None,
        limit=args.limit,
    )
    matches = [item for item in matches if item["path_match"] or item["score"] >= 0.05]
    result = {
        "schema": "issue2proof.pr-memory-gate.v1",
        "verdict": "no_relevant_memory" if not matches else "recall_required",
        "query": query,
        "changed_paths": paths,
        "bundle_capsules": len(capsules),
        "matches": [
            {
                "id": item["capsule"]["id"],
                "score": item["score"],
                "path_match": item["path_match"],
                "claim": item["capsule"].get("claim"),
                "regression_sha256": item["capsule"]["evidence"]["regression"]["sha256"],
            }
            for item in matches
        ],
    }
    if matches and args.audit:
        if not args.url:
            raise SystemExit("--audit requires ISSUE2PROOF_URL or --url.")
        result["audit"] = remote_audit(args, bundle, query, matches)
        result["verdict"] = result["audit"].get("verdict") or "audit_incomplete"
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    summary = markdown(result)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as output:
            output.write(summary)
    else:
        print(summary)
    write_github("verdict", str(result["verdict"]))
    write_github("matches", str(len(matches)))
    write_github("report", str(args.report))
    return 1 if result["verdict"] in {"memory_conflict", "memory_uncertain", "failed", "audit_setup_failed", "audit_incomplete"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
