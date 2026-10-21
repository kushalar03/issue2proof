"""One bounded inference call on the built-in fixture; never executes model output."""

import json
import sys
from dataclasses import asdict

import httpx

from .fixtures import CASES, ORIGINAL
from .provider import NebiusProvider


def main():
    try:
        candidate = NebiusProvider().generate(CASES["repair"]["issue"], ORIGINAL)
    except httpx.HTTPStatusError as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "http_status": error.response.status_code,
                    "message": "Nebius request failed. Check API access, credits, and model availability.",
                }
            )
        )
        return 1
    except httpx.RequestError:
        print(
            json.dumps(
                {
                    "ok": False,
                    "message": "Cannot reach Nebius. Check the environment network policy.",
                }
            )
        )
        return 1
    except (ValueError, KeyError, IndexError, TypeError):
        print(
            json.dumps(
                {
                    "ok": False,
                    "message": "Missing configuration or invalid model response. No code was executed.",
                }
            )
        )
        return 1
    report = asdict(candidate)
    report.update(
        ok=True,
        executed=False,
        cost_basis="Estimate at Super input $0.30/M and output $0.90/M; excludes sandbox charges.",
        next_step="Validate candidate in an isolated sandbox before claiming a repair.",
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
