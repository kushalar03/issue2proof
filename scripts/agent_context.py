"""Fetch a vendor-neutral Issue2Proof memory packet for an agent or CI job."""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--change", required=True, help="Proposed change or risk")
    parser.add_argument("--repository", help="Stable owner/repository memory key")
    parser.add_argument("--semantic", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("ISSUE2PROOF_ACCESS_TOKEN")
    if not token:
        parser.error("Set ISSUE2PROOF_ACCESS_TOKEN in the process environment.")
    payload = {
        "query": args.change,
        "repository_key": args.repository,
        "limit": 5,
        "semantic": args.semantic,
        "authorize_nebius": args.semantic,
    }
    request = urllib.request.Request(
        args.url.rstrip("/") + "/api/integrations/context",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:  # noqa: S310 - operator-provided Issue2Proof URL
            packet = json.load(response)
    except urllib.error.HTTPError as error:
        message = error.read().decode(errors="replace")[:1000]
        print(f"Issue2Proof request failed ({error.code}): {message}", file=sys.stderr)
        return 1
    print(json.dumps(packet, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
