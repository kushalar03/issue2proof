"""Generate a private deployment configuration without printing secrets."""

import argparse
import os
import secrets
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".env"))
    args = parser.parse_args()
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as config:
        config.write(
            "ISSUE2PROOF_ACCESS_TOKEN="
            + secrets.token_urlsafe(32)
            + "\nDOMAIN=\nNEBIUS_API_KEY=\nNEBIUS_PROJECT_ID=\nNEBIUS_SANDBOX_IMAGE=python:3.12-slim\nISSUE2PROOF_DAILY_BUDGET_USD=10\nISSUE2PROOF_TOTAL_BUDGET_USD=25\nISSUE2PROOF_PROTECTED_RESERVE_USD=5\nISSUE2PROOF_RETENTION_DAYS=7\n"
        )
    print(
        f"Created private configuration at {args.output}. Edit locally; never commit it or paste the token into chat."
    )


if __name__ == "__main__":
    main()
