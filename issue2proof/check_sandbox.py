"""Check remote sandbox execution and transfer using a fixed reviewed payload."""

import json
import sys

from .sandbox import SandboxConfig, smoke_check


def main():
    try:
        config = SandboxConfig.from_env()
    except ValueError as error:
        print(
            json.dumps({"ok": False, "stage": "configuration", "message": str(error)})
        )
        return 1
    try:
        from contree_sdk.sdk.exceptions import ContreeError
    except ImportError:
        print(json.dumps({"ok": False, "message": "Install issue2proof[sandbox]."}))
        return 1
    try:
        report = smoke_check(config)
    except ContreeError as error:
        # SDK exceptions may contain HTTP headers; never print their raw repr.
        print(
            json.dumps(
                {
                    "ok": False,
                    "stage": "sandbox",
                    "error_type": type(error).__name__,
                    "http_status": getattr(error, "status", None),
                    "message": "Check sandbox host access, project permissions, and image availability.",
                }
            )
        )
        return 1
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
