"""Portable, integrity-checked Memory Capsule bundles."""

import hashlib
import json
import math
import re
from datetime import UTC, datetime

TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
SCHEMA = "issue2proof.memory-bundle.v1"
MAX_CAPSULES = 100
MAX_BYTES = 5_000_000


def _canonical(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def capsule_digest(capsule: dict) -> str:
    return hashlib.sha256(_canonical(capsule)).hexdigest()


def export_bundle(capsules: list[dict]) -> dict:
    """Package capsules with hashes that survive storage and agent boundaries."""
    if not isinstance(capsules, list) or len(capsules) > MAX_CAPSULES:
        raise ValueError(f"A bundle can contain at most {MAX_CAPSULES} capsules.")
    entries = [
        {"sha256": capsule_digest(capsule), "capsule": capsule}
        for capsule in capsules
    ]
    bundle = {
        "schema": SCHEMA,
        "created_at": datetime.now(UTC).isoformat(),
        "capsule_count": len(entries),
        "entries": entries,
        "manifest_sha256": hashlib.sha256(
            _canonical([entry["sha256"] for entry in entries])
        ).hexdigest(),
    }
    if len(_canonical(bundle)) > MAX_BYTES:
        raise ValueError("Memory bundle exceeds the 5 MB limit.")
    return bundle


def validate_bundle(bundle: dict) -> list[dict]:
    """Validate the envelope, manifest, capsule schema and frozen regressions."""
    if not isinstance(bundle, dict) or bundle.get("schema") != SCHEMA:
        raise ValueError(f"Expected portable bundle schema {SCHEMA}.")
    if len(_canonical(bundle)) > MAX_BYTES:
        raise ValueError("Memory bundle exceeds the 5 MB limit.")
    entries = bundle.get("entries")
    if not isinstance(entries, list) or len(entries) > MAX_CAPSULES:
        raise ValueError(f"A bundle can contain at most {MAX_CAPSULES} capsules.")
    if bundle.get("capsule_count") != len(entries):
        raise ValueError("Memory bundle capsule count does not match its entries.")
    hashes = []
    capsules = []
    ids = set()
    runs = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"sha256", "capsule"}:
            raise ValueError("Memory bundle contains an invalid entry.")
        capsule = entry["capsule"]
        if not isinstance(capsule, dict) or capsule.get("schema") != "issue2proof.memory.v1":
            raise ValueError("Memory bundle contains an unsupported capsule schema.")
        required = ("id", "repository_key", "version", "created_at", "origin", "evidence")
        if any(not capsule.get(name) for name in required):
            raise ValueError("Memory Capsule is missing required provenance.")
        if capsule["id"] in ids:
            raise ValueError("Memory bundle contains duplicate capsule IDs.")
        ids.add(capsule["id"])
        origin = capsule.get("origin") or {}
        regression = (capsule.get("evidence") or {}).get("regression") or {}
        if not origin.get("run_id"):
            raise ValueError("Memory Capsule is missing its source run.")
        if origin["run_id"] in runs:
            raise ValueError("Memory bundle contains duplicate source runs.")
        runs.add(origin["run_id"])
        source = regression.get("source")
        frozen_hash = regression.get("sha256")
        if not isinstance(source, str) or hashlib.sha256(source.encode()).hexdigest() != frozen_hash:
            raise ValueError("Memory Capsule frozen regression hash is invalid.")
        digest = capsule_digest(capsule)
        if entry["sha256"] != digest:
            raise ValueError("Memory Capsule content does not match its bundle hash.")
        hashes.append(digest)
        capsules.append(capsule)
    manifest = hashlib.sha256(_canonical(hashes)).hexdigest()
    if bundle.get("manifest_sha256") != manifest:
        raise ValueError("Memory bundle manifest hash is invalid.")
    return capsules


def _text(capsule: dict) -> str:
    index = capsule.get("ai_index") or {}
    return "\n".join(
        [
            capsule.get("claim") or "",
            index.get("summary") or "",
            " ".join(index.get("keywords") or []),
            " ".join(index.get("change_triggers") or []),
            " ".join((capsule.get("scope") or {}).get("paths") or []),
            " ".join(capsule.get("assumptions") or []),
            " ".join(capsule.get("risk_boundaries") or []),
        ]
    )


def search_bundle(
    bundle: dict,
    query: str,
    *,
    changed_paths: list[str] | None = None,
    repository_key: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """Run free local recall for pull-request gates and disconnected agents."""
    capsules = validate_bundle(bundle)
    wanted = {token.lower() for token in TOKEN.findall(query)}
    path_tokens = {
        token.lower()
        for path in changed_paths or []
        for token in TOKEN.findall(path)
    }
    wanted.update(path_tokens)
    if not wanted:
        raise ValueError("Provide a change description or changed path.")
    results = []
    for capsule in capsules:
        if repository_key and capsule["repository_key"] != repository_key:
            continue
        available = {token.lower() for token in TOKEN.findall(_text(capsule))}
        overlap = wanted & available
        score = len(overlap) / math.sqrt(len(wanted) * max(1, len(available)))
        scoped = set((capsule.get("scope") or {}).get("paths") or [])
        path_match = any(
            changed == known
            or changed.startswith(known.rstrip("/") + "/")
            or known.startswith(changed.rstrip("/") + "/")
            for changed in changed_paths or []
            for known in scoped
        )
        if path_match:
            score = max(score, 0.75)
        if score > 0:
            results.append(
                {
                    "score": round(score, 6),
                    "path_match": path_match,
                    "capsule": capsule,
                }
            )
    return sorted(results, key=lambda item: item["score"], reverse=True)[: max(1, min(limit, 20))]
