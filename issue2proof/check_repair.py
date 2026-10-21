"""Run the bounded remote model-repair workflow and save its evidence."""

import argparse
import json
from pathlib import Path

from .repair import run_repair


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        choices=["repair", "reject", "unresolved", "ambiguous"],
        default="repair",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/remote-repair.json")
    )
    args = parser.parse_args()
    report = run_repair(args.case)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "verdict": report["verdict"],
                "explanation": report["explanation"],
                "report": str(args.output),
            }
        )
    )
    return 0 if report["verdict"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
