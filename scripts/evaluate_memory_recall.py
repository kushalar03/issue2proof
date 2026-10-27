#!/usr/bin/env python3
"""Run a free multi-repository recall evaluation over verified history."""

import json
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from issue2proof.memory import capsule_from_report
from issue2proof.portable import export_bundle, search_bundle

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    {
        "id": "werkzeug-safe-join",
        "artifact": "real-bug-werkzeug.json",
        "path": "src/werkzeug/security.py",
        "queries": [
            "simplify Windows path security validation",
            "remove reserved device name handling from safe_join",
            "refactor traversal checks for platform paths",
        ],
    },
    {
        "id": "requests-content-length",
        "artifact": "real-bug-requests.json",
        "path": "requests/utils.py",
        "queries": [
            "optimize Unicode request body length",
            "simplify super_len string handling",
            "avoid UTF-8 allocation in content length calculation",
        ],
    },
    {
        "id": "calendar-month-clamp",
        "artifact": "live-dependency-investigation.json",
        "path": "src/calendar_app/__init__.py",
        "queries": [
            "refactor negative calendar month offsets",
            "replace dateutil month arithmetic",
            "simplify end-of-month day clamping",
        ],
    },
    {
        "id": "pricing-discount-floor",
        "artifact": "live-repository-repair.json",
        "path": "pricing.py",
        "queries": [
            "simplify order discount total calculation",
            "remove the total price floor",
            "refactor excess discount handling",
        ],
    },
]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="i2p-recall-") as directory:
        os.environ["ISSUE2PROOF_DB"] = str(Path(directory) / "memory.sqlite3")
        capsules = []
        for case in CASES:
            report = json.loads((ROOT / "artifacts" / case["artifact"]).read_text())
            report.setdefault("id", "evaluation-" + case["id"])
            capsule = capsule_from_report(report, key="evaluation/" + case["id"])
            capsule["id"] = str(
                uuid.uuid5(uuid.NAMESPACE_URL, "issue2proof:evaluation:" + case["id"])
            )
            capsules.append(capsule)
        bundle = export_bundle(capsules)
    trials = []
    for case, expected in zip(CASES, capsules, strict=True):
        for query in case["queries"]:
            lexical = search_bundle(bundle, query, limit=1)
            scoped = search_bundle(bundle, query, changed_paths=[case["path"]], limit=1)
            trials.append(
                {
                    "case": case["id"],
                    "query": query,
                    "changed_path": case["path"],
                    "lexical_top1": lexical[0]["capsule"]["id"] if lexical else None,
                    "lexical_correct": bool(lexical and lexical[0]["capsule"]["id"] == expected["id"]),
                    "path_aware_top1": scoped[0]["capsule"]["id"] if scoped else None,
                    "path_aware_correct": bool(scoped and scoped[0]["capsule"]["id"] == expected["id"]),
                }
            )
    payload = {
        "schema": "issue2proof.memory-recall-evaluation.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "method": {
            "description": "Twelve future-change descriptions across four verified repository histories are recalled from one portable bundle.",
            "metrics": "Top-1 capsule retrieval with query-only lexical recall and lexical recall plus changed-path scope.",
            "limitations": [
                "Queries are authored from known incidents rather than sampled from production pull requests.",
                "This evaluates recall routing, not whether a new revision passes sandbox replay.",
                "Two histories are public upstream bugs and two are purpose-built live sandbox cases.",
            ],
        },
        "summary": {
            "repository_histories": len(CASES),
            "trials": len(trials),
            "lexical_top1_correct": sum(item["lexical_correct"] for item in trials),
            "path_aware_top1_correct": sum(item["path_aware_correct"] for item in trials),
        },
        "cases": [{key: case[key] for key in ("id", "artifact", "path")} for case in CASES],
        "trials": trials,
    }
    destination = ROOT / "artifacts" / "memory-recall-evaluation.json"
    destination.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    main()
