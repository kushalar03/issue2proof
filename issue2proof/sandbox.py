"""Remote sandbox lifecycle smoke check; no repository or model code is accepted.

Uses the released ConTree SDK 0.3.6. The smoke operation discards its resulting
image and has a server-side timeout. Arbitrary execution remains disabled until
network and resource restrictions have been validated for the account.
"""

import hashlib
import json
import os
import re
from dataclasses import dataclass, field, replace
from uuid import UUID

IMAGE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,199}$")

PAYLOAD = b"Issue2Proof sandbox file-transfer check\n"
PAYLOAD_HASH = hashlib.sha256(PAYLOAD).hexdigest()
SMOKE_SOURCE = (
    "import hashlib, json, pathlib\n"
    "data = pathlib.Path('/tmp/issue2proof-smoke.txt').read_bytes()\n"
    "print(json.dumps({'sha256': hashlib.sha256(data).hexdigest()}))\n"
)


@dataclass(frozen=True)
class SandboxConfig:
    key: str = field(repr=False)
    project_id: str
    image: str
    base_url: str

    @classmethod
    def from_env(cls):
        names = ("NEBIUS_API_KEY", "NEBIUS_PROJECT_ID")
        values = [os.environ.get(name, "").strip() for name in names]
        missing = [name for name, value in zip(names, values, strict=True) if not value]
        if missing:
            raise ValueError("Configure " + ", ".join(missing) + " for Sandboxes.")
        image = os.environ.get("NEBIUS_SANDBOX_IMAGE", "python:3.12-slim").strip()
        if not IMAGE_REFERENCE.fullmatch(image):
            raise ValueError(
                "NEBIUS_SANDBOX_IMAGE is not a valid bounded image reference."
            )
        return cls(
            *values,
            image,
            os.environ.get(
                "NEBIUS_SANDBOX_URL", "https://api.tokenfactory.nebius.com/sandboxes"
            ),
        )


def resolve_image(config: SandboxConfig) -> SandboxConfig:
    """Resolve a friendly quickstart tag for clients that require an image UUID."""
    try:
        UUID(config.image)
        return config
    except ValueError:
        pass
    from contree_sdk import ContreeSync
    from contree_sdk.auth import IAMAuth
    from contree_sdk.config import ContreeConfig

    client = ContreeSync(
        config=ContreeConfig(
            auth=IAMAuth(
                token=config.key,
                project_id=config.project_id,
                base_url=config.base_url,
            ),
            transport_timeout=20,
            operation_timeout=30,
        )
    )
    image = client.images.use(config.image, strict=True)
    if not image.uuid:
        raise ValueError("Sandbox image tag did not resolve to an immutable image.")
    return replace(config, image=str(image.uuid))


def smoke_check(config: SandboxConfig, client=None) -> dict:
    if client is None:
        from contree_sdk import ContreeSync
        from contree_sdk.auth import IAMAuth
        from contree_sdk.config import ContreeConfig

        client = ContreeSync(
            config=ContreeConfig(
                auth=IAMAuth(
                    token=config.key,
                    project_id=config.project_id,
                    base_url=config.base_url,
                ),
                transport_timeout=20,
                operation_timeout=30,
                default_truncate_output_at=20000,
            )
        )
    image = client.images.use(config.image)
    execution = image.run(
        command="/usr/bin/env",
        args=["python3", "-I", "-c", SMOKE_SOURCE],
        files={"/tmp/issue2proof-smoke.txt": PAYLOAD},
        env={},
        timeout=30,
        disposable=True,
        preserve_env=False,
        truncate_output_at=20000,
    ).wait()
    result = execution.result
    # A successful exit alone does not establish successful file transfer.
    try:
        transferred = json.loads(result.stdout).get("sha256") == PAYLOAD_HASH
    except (ValueError, TypeError, AttributeError):
        transferred = False
    return {
        "ok": result.exit_code == 0 and transferred and not result.truncated,
        "mode": "remote reviewed smoke check",
        "image": config.image,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "seconds": result.elapsed_time.total_seconds(),
        "cost": result.cost,
        "output_truncated": result.truncated,
        "payload_sha256": PAYLOAD_HASH,
        "file_transfer_verified": transferred,
        "disposable": True,
        "timeout_seconds": 30,
        "arbitrary_execution_enabled": False,
        "limitations": [
            "Network isolation and memory/CPU quotas are not yet validated.",
            "This smoke check does not verify a repair or execute model output.",
        ],
    }
