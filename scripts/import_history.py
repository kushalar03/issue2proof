#!/usr/bin/env python3
"""Create Memory Capsules from checks-passed Issue2Proof report history."""

import argparse
import json
from pathlib import Path

from issue2proof.history import import_verified_reports
from issue2proof.memory import export_capsule_bundle


def records_from(paths: list[Path]) -> list[dict]:
    records = []
    files = []
    for path in paths:
        files.extend(sorted(path.rglob("*.json")) if path.is_dir() else [path])
    for path in files:
        value = json.loads(path.read_text())
        records.extend(value if isinstance(value, list) else [value])
    return records


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import only reports with checks-passed, hash-valid regressions."
    )
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--repository-key")
    parser.add_argument("--bundle-output", type=Path)
    args = parser.parse_args()
    result = import_verified_reports(records_from(args.paths), key=args.repository_key)
    if args.bundle_output:
        args.bundle_output.parent.mkdir(parents=True, exist_ok=True)
        args.bundle_output.write_text(
            json.dumps(export_capsule_bundle(args.repository_key), indent=2) + "\n"
        )
        result["bundle"] = str(args.bundle_output)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
