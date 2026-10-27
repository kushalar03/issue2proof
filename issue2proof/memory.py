"""Versioned, executable repository memory backed by observed evidence."""

import hashlib
import json
import math
import re
import sqlite3
import uuid
from datetime import UTC, datetime

import httpx

from .jobs import database, reconcile_system, reserve_system
from .portable import export_bundle, validate_bundle

TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


class EmbeddingProvider:
    def __init__(self):
        import os

        self.key = os.environ.get("NEBIUS_API_KEY")
        if not self.key:
            raise ValueError("Configure NEBIUS_API_KEY for semantic memory retrieval.")
        self.base_url = os.environ.get(
            "NEBIUS_BASE_URL", "https://api.tokenfactory.us-central1.nebius.com/v1"
        )
        self.model = os.environ.get(
            "ISSUE2PROOF_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B"
        )
        self.dimensions = min(
            4096,
            max(
                128,
                int(os.environ.get("ISSUE2PROOF_EMBEDDING_DIMENSIONS", "1024")),
            ),
        )

    def embed(self, texts: list[str]) -> dict:
        if not 1 <= len(texts) <= 101 or sum(map(len, texts)) > 100_000:
            raise ValueError("Embedding batch exceeds the bounded memory request.")
        with httpx.Client(timeout=60) as client:
            response = client.post(
                self.base_url.rstrip("/") + "/embeddings",
                headers={"Authorization": f"Bearer {self.key}"},
                json={
                    "model": self.model,
                    "input": texts,
                    "dimensions": self.dimensions,
                },
            )
            response.raise_for_status()
            payload = response.json()
        rows = sorted(payload.get("data", []), key=lambda item: item.get("index", -1))
        vectors = [item.get("embedding") for item in rows]
        if len(vectors) != len(texts) or any(
            not isinstance(vector, list) or len(vector) != self.dimensions
            for vector in vectors
        ):
            raise ValueError("Embedding provider returned an invalid batch.")
        return {
            "vectors": vectors,
            "model": payload.get("model") or self.model,
            "usage": payload.get("usage") or {},
            "estimated_cost_usd": None,
        }


def _tables(db: sqlite3.Connection):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS memory_capsules(
      id TEXT PRIMARY KEY,repository_key TEXT NOT NULL,version INTEGER NOT NULL,
      source_run_id TEXT NOT NULL UNIQUE,status TEXT NOT NULL,supersedes TEXT,
      created_at TEXT NOT NULL,capsule TEXT NOT NULL,vector TEXT
    );
    CREATE INDEX IF NOT EXISTS memory_repository ON memory_capsules(repository_key,status,version);
    """)


def repository_key(report: dict) -> str:
    """Return a stable key without incorporating changing file contents."""
    explicit = report.get("repository", {}).get("full_name") or report.get(
        "repository_key"
    )
    if explicit:
        return str(explicit).lower()
    paths = sorted(
        {
            *report.get("sources", {}),
            *report.get("existing_tests", {}),
            *report.get("dependency_manifests", {}),
        }
    )
    digest = hashlib.sha256("\n".join(paths).encode()).hexdigest()[:20]
    return "upload:" + digest


def _operation_ids(value) -> list[str]:
    found = set()

    def walk(item):
        if isinstance(item, dict):
            operation = item.get("operation_id")
            if isinstance(operation, str):
                found.add(operation)
            for nested in item.values():
                walk(nested)
        elif isinstance(item, list):
            for nested in item:
                walk(nested)

    walk(value)
    return sorted(found)


def _changed_paths(report: dict) -> list[str]:
    if report.get("draft_changes"):
        return sorted(report["draft_changes"])
    for attempt in reversed(report.get("attempts", [])):
        if attempt.get("accepted") and attempt.get("changes"):
            return sorted(attempt["changes"])
    return sorted(report.get("sources", {}))[:10]


def capsule_from_report(report: dict, *, key: str | None = None) -> dict:
    """Create memory only from an investigation with executable evidence."""
    if report.get("verdict") != "checks_passed":
        raise ValueError("Only a checks-passed investigation can become active memory.")
    regression = report.get("generated_regression") or {}
    if not regression.get("source") or not regression.get("sha256"):
        raise ValueError("Executable memory requires a frozen regression test.")
    if (
        hashlib.sha256(regression["source"].encode()).hexdigest()
        != regression["sha256"]
    ):
        raise ValueError("Frozen regression hash does not match its source.")
    repo = key or repository_key(report)
    with database() as db:
        _tables(db)
        prior = db.execute(
            "SELECT id,version FROM memory_capsules WHERE repository_key=? AND status='active' ORDER BY version DESC LIMIT 1",
            (repo,),
        ).fetchone()
    capsule = {
        "schema": "issue2proof.memory.v1",
        "repository_key": repo,
        "claim": report.get("original_issue") or report.get("issue"),
        "scope": {
            "paths": _changed_paths(report),
            "dependencies": report.get("environment", {}).get("requirements", []),
        },
        "origin": {
            "run_id": report.get("id"),
            "created_at": report.get("created_at"),
            "commit": report.get("repository", {}).get("commit"),
            "issue_url": report.get("repository", {}).get("issue_url"),
        },
        "evidence": {
            "verdict": report["verdict"],
            "regression": regression,
            "original_file_hashes": report.get("file_hashes", {}),
            "candidate_hashes": report.get("candidate_hashes", {}),
            "environment_image": report.get("environment", {}).get("image"),
            "operation_ids": _operation_ids(report),
        },
        "assumptions": report.get("assumptions", []),
        "rejected_hypotheses": [
            attempt["rejection"]
            for attempt in report.get("attempts", [])
            if attempt.get("rejection")
        ],
        "risk_boundaries": report.get("limitations", []),
        "invalidated_when": [
            "The recorded behavioral contract intentionally changes.",
            "The frozen regression no longer represents the public behavior.",
            "The recorded environment is no longer reproducible.",
        ],
    }
    capsule["id"] = str(uuid.uuid4())
    capsule["version"] = (prior["version"] + 1) if prior else 1
    capsule["supersedes"] = None
    capsule["created_at"] = datetime.now(UTC).isoformat()
    return capsule


def save_capsule(capsule: dict, vector: list[float] | None = None) -> dict:
    if not capsule.get("origin", {}).get("run_id"):
        raise ValueError("Memory provenance requires a source run.")
    if vector is not None and (
        not vector
        or len(vector) > 4096
        or any(
            not isinstance(item, (int, float)) or not math.isfinite(item)
            for item in vector
        )
    ):
        raise ValueError("Invalid memory embedding.")
    with database() as db:
        _tables(db)
        existing = db.execute(
            "SELECT capsule FROM memory_capsules WHERE source_run_id=?",
            (capsule["origin"]["run_id"],),
        ).fetchone()
        if existing:
            return json.loads(existing["capsule"])
        db.execute(
            "INSERT INTO memory_capsules VALUES(?,?,?,?,?,?,?,?,?)",
            (
                capsule["id"],
                capsule["repository_key"],
                capsule["version"],
                capsule["origin"]["run_id"],
                "active",
                capsule.get("supersedes"),
                capsule["created_at"],
                json.dumps(capsule),
                json.dumps(vector) if vector is not None else None,
            ),
        )
    return capsule


def list_capsules(key: str | None = None) -> list[dict]:
    with database() as db:
        _tables(db)
        if key:
            rows = db.execute(
                "SELECT capsule FROM memory_capsules WHERE repository_key=? AND status='active' ORDER BY version DESC",
                (key,),
            )
        else:
            rows = db.execute(
                "SELECT capsule FROM memory_capsules WHERE status='active' ORDER BY created_at DESC LIMIT 100"
            )
        return [json.loads(row["capsule"]) for row in rows]


def export_capsule_bundle(key: str | None = None) -> dict:
    return export_bundle(list_capsules(key))


def import_capsule_bundle(bundle: dict) -> dict:
    capsules = validate_bundle(bundle)
    imported = []
    with database() as db:
        _tables(db)
        for capsule in capsules:
            existing = db.execute(
                "SELECT capsule FROM memory_capsules WHERE source_run_id=? OR id=?",
                (capsule["origin"]["run_id"], capsule["id"]),
            ).fetchone()
            if existing:
                if json.loads(existing["capsule"]) != capsule:
                    raise ValueError(
                        "A capsule ID or source run has different verified content."
                    )
            else:
                db.execute(
                    "INSERT INTO memory_capsules VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        capsule["id"],
                        capsule["repository_key"],
                        capsule["version"],
                        capsule["origin"]["run_id"],
                        "active",
                        capsule.get("supersedes"),
                        capsule["created_at"],
                        json.dumps(capsule),
                        None,
                    ),
                )
            imported.append(capsule["id"])
    return {"validated": len(capsules), "imported_ids": imported}


def get_capsule(capsule_id: str) -> dict:
    with database() as db:
        _tables(db)
        row = db.execute(
            "SELECT capsule FROM memory_capsules WHERE id=?", (capsule_id,)
        ).fetchone()
    if row is None:
        raise KeyError(capsule_id)
    return json.loads(row["capsule"])


def memory_text(capsule: dict) -> str:
    return "\n".join(
        [
            capsule.get("claim") or "",
            capsule.get("ai_index", {}).get("summary", ""),
            " ".join(capsule.get("ai_index", {}).get("keywords", [])),
            " ".join(capsule.get("ai_index", {}).get("change_triggers", [])),
            " ".join(capsule.get("scope", {}).get("paths", [])),
            " ".join(capsule.get("assumptions", [])),
            " ".join(capsule.get("risk_boundaries", [])),
        ]
    )


def _lexical_score(query: str, capsule: dict) -> float:
    wanted = {token.lower() for token in TOKEN.findall(query)}
    available = {token.lower() for token in TOKEN.findall(memory_text(capsule))}
    if not wanted:
        return 0.0
    return len(wanted & available) / math.sqrt(len(wanted) * max(1, len(available)))


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    denominator = math.sqrt(sum(x * x for x in left)) * math.sqrt(
        sum(x * x for x in right)
    )
    return (
        sum(x * y for x, y in zip(left, right, strict=True)) / denominator
        if denominator
        else 0.0
    )


def search_capsules(
    query: str,
    *,
    key: str | None = None,
    query_vector: list[float] | None = None,
    limit: int = 5,
) -> list[dict]:
    if not query.strip():
        raise ValueError("Provide a change description or affected symbols.")
    with database() as db:
        _tables(db)
        sql = "SELECT capsule,vector FROM memory_capsules WHERE status='active'"
        params: tuple = ()
        if key:
            sql += " AND repository_key=?"
            params = (key,)
        rows = list(db.execute(sql, params))
    results = []
    for row in rows:
        capsule = json.loads(row["capsule"])
        lexical = _lexical_score(query, capsule)
        semantic = (
            _cosine(query_vector, json.loads(row["vector"]))
            if query_vector is not None and row["vector"]
            else 0.0
        )
        score = 0.35 * lexical + 0.65 * semantic if query_vector else lexical
        if score > 0:
            results.append({"score": round(score, 6), "capsule": capsule})
    return sorted(results, key=lambda item: item["score"], reverse=True)[:limit]


def semantic_search(
    query: str,
    *,
    key: str | None = None,
    limit: int = 5,
    provider=None,
) -> dict:
    """Embed the query and uncached capsules in one budgeted request."""
    if not query.strip():
        raise ValueError("Provide a change description or affected symbols.")
    with database() as db:
        _tables(db)
        sql = "SELECT id,capsule,vector FROM memory_capsules WHERE status='active'"
        params: tuple = ()
        if key:
            sql += " AND repository_key=?"
            params = (key,)
        rows = list(db.execute(sql + " ORDER BY created_at DESC LIMIT 100", params))
    if not rows:
        return {"model": None, "usage": {}, "results": []}
    missing = [row for row in rows if not row["vector"]]
    texts = [query, *(memory_text(json.loads(row["capsule"])) for row in missing)]
    reservation = reserve_system("embedding")
    response = (provider or EmbeddingProvider()).embed(texts)
    reconcile_system(reservation, response.get("estimated_cost_usd"))
    query_vector, *new_vectors = response["vectors"]
    if missing:
        with database() as db:
            for row, vector in zip(missing, new_vectors, strict=True):
                db.execute(
                    "UPDATE memory_capsules SET vector=? WHERE id=?",
                    (json.dumps(vector), row["id"]),
                )
    return {
        "model": response["model"],
        "usage": response.get("usage", {}),
        "results": search_capsules(
            query, key=key, query_vector=query_vector, limit=limit
        ),
    }


def enrich_capsule(capsule_id: str, provider=None) -> dict:
    """Add a compact AI index while preserving the evidence-backed claim verbatim."""
    from .draft import RepositoryProvider

    capsule = get_capsule(capsule_id)
    context = {
        "claim": capsule.get("claim"),
        "paths": capsule.get("scope", {}).get("paths", []),
        "assumptions": capsule.get("assumptions", []),
        "risk_boundaries": capsule.get("risk_boundaries", []),
        "invalidated_when": capsule.get("invalidated_when", []),
        "regression_path": capsule.get("evidence", {})
        .get("regression", {})
        .get("path"),
    }
    reservation = reserve_system("model:fast")
    response = (provider or RepositoryProvider()).request(
        'Return exactly {"summary": "one precise sentence", "keywords": ["symbol or behavior"], "change_triggers": ["future change that should replay this memory"]}. '
        "Use only supplied facts. Do not claim broader correctness. Provide 3-12 keywords and 1-5 triggers.",
        context,
        role="fast",
        max_tokens=800,
    )
    reconcile_system(reservation, response.get("estimated_cost_usd"))
    result = response.get("result")
    if not isinstance(result, dict) or set(result) != {
        "summary",
        "keywords",
        "change_triggers",
    }:
        raise ValueError("Invalid memory enrichment response schema.")

    def strings(value, minimum, maximum, length=300):
        if (
            not isinstance(value, list)
            or not minimum <= len(value) <= maximum
            or any(
                not isinstance(item, str) or not item.strip() or len(item) > length
                for item in value
            )
        ):
            raise ValueError("Invalid bounded memory enrichment content.")
        return [item.strip() for item in value]

    summary = result["summary"]
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 500:
        raise ValueError("Invalid memory enrichment summary.")
    enriched = {
        **capsule,
        "ai_index": {
            "summary": summary.strip(),
            "keywords": strings(result["keywords"], 3, 12, 100),
            "change_triggers": strings(result["change_triggers"], 1, 5),
            "model": response["model"],
            "role": response["role"],
            "prompt_tokens": response.get("prompt_tokens"),
            "completion_tokens": response.get("completion_tokens"),
        },
    }
    with database() as db:
        _tables(db)
        updated = db.execute(
            "UPDATE memory_capsules SET capsule=?,vector=NULL WHERE id=?",
            (json.dumps(enriched), capsule_id),
        )
        if updated.rowcount != 1:
            raise KeyError(capsule_id)
    return enriched


def supersede_capsule(capsule_id: str, replacement_id: str):
    if capsule_id == replacement_id:
        raise ValueError("A memory cannot supersede itself.")
    with database() as db:
        _tables(db)
        old = db.execute(
            "SELECT repository_key FROM memory_capsules WHERE id=?", (capsule_id,)
        ).fetchone()
        new = db.execute(
            "SELECT repository_key,capsule FROM memory_capsules WHERE id=?",
            (replacement_id,),
        ).fetchone()
        if old is None or new is None or old["repository_key"] != new["repository_key"]:
            raise ValueError("Memories must exist in the same repository.")
        replacement = json.loads(new["capsule"])
        replacement["supersedes"] = capsule_id
        db.execute(
            "UPDATE memory_capsules SET status='superseded' WHERE id=?", (capsule_id,)
        )
        db.execute(
            "UPDATE memory_capsules SET supersedes=?,capsule=? WHERE id=?",
            (capsule_id, json.dumps(replacement), replacement_id),
        )
    return replacement
