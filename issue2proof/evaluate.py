"""Evaluate reviewed demo fixtures; not a held-out model benchmark."""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from .engine import run_demo

EXPECTED = {
    "repair": "verified",
    "reject": "verified",
    "unresolved": "unresolved",
    "ambiguous": "needs_clarification",
}


def summarize(reports):
    cases = []
    false_acceptances = 0
    bad_candidates = 0
    rejected_bad = 0
    for report in reports:
        for attempt in report["attempts"]:
            supported = attempt["protected_tests_intact"] and all(
                attempt[check]["exit_code"] == 0
                for check in ("regression", "existing", "independent")
            )
            if not supported:
                bad_candidates += 1
                rejected_bad += int(not attempt["accepted"])
            false_acceptances += int(attempt["accepted"] and not supported)
        cases.append(
            {
                "case": report["case"],
                "expected": EXPECTED[report["case"]],
                "actual": report["verdict"],
                "matched": report["verdict"] == EXPECTED[report["case"]],
                "attempts": len(report["attempts"]),
            }
        )
    return {
        "cases": cases,
        "expected_verdicts_matched": sum(case["matched"] for case in cases),
        "total_cases": len(cases),
        "unsupported_candidate_acceptances": false_acceptances,
        "bad_candidates": bad_candidates,
        "bad_candidates_rejected": rejected_bad,
        "passed": all(case["matched"] for case in cases) and false_acceptances == 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/demo-evaluation.json")
    )
    args = parser.parse_args()
    started = time.monotonic()
    reports = [run_demo(case) for case in EXPECTED]
    summary = summarize(reports)
    artifact = {
        "created_at": datetime.now(UTC).isoformat(),
        "mode": "reviewed demo fixtures",
        "limitations": "Prewritten cases, patches, and tests. These results do not measure model repair accuracy on real bugs.",
        "seconds": round(time.monotonic() - started, 3),
        "summary": summary,
        "reports": reports,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), **summary}, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
