"""Prepare wheel-only dependencies remotely without executing repository setup hooks."""

import hashlib
import json
import tomllib
from dataclasses import replace

from packaging.requirements import InvalidRequirement, Requirement


def dependency_plan(manifests: dict[str, str]) -> dict:
    raw = []
    for name, content in manifests.items():
        if name.rsplit("/", 1)[-1] in {"requirements.txt", "requirements.lock"}:
            for line in content.splitlines():
                line = line.split(" #", 1)[0].strip()
                if line and not line.startswith("#"):
                    raw.append(line)
    if not raw:
        for name, content in manifests.items():
            if name.rsplit("/", 1)[-1] == "pyproject.toml":
                config = tomllib.loads(content)
                if "dependencies" in config.get("project", {}).get("dynamic", []):
                    raise ValueError(
                        "Dynamic dependency metadata requires an explicit requirements.txt."
                    )
                raw.extend(config.get("project", {}).get("dependencies", []))
    has_project = any(
        name.rsplit("/", 1)[-1] in {"pyproject.toml", "setup.py", "setup.cfg"}
        for name in manifests
    )
    if has_project:
        build_requirements = []
        for name, content in manifests.items():
            if name.rsplit("/", 1)[-1] == "pyproject.toml":
                build_requirements.extend(
                    tomllib.loads(content).get("build-system", {}).get("requires", [])
                )
        if not build_requirements:
            build_requirements = ["setuptools==75.8.0", "wheel==0.45.1"]
        elif any("setuptools" in item for item in build_requirements) and not any(
            item.startswith("wheel") for item in build_requirements
        ):
            build_requirements.append("wheel==0.45.1")
        raw.extend(build_requirements)
    if not any(
        Requirement(value).name.lower() == "pytest"
        for value in raw
        if not value.startswith(("-", ".", "/")) and " @ " not in value
    ):
        # The trusted controller invokes pytest even when the repository has no
        # dependency manifest. Install a fixed wheel into the prepared image.
        raw.append("pytest==8.4.2")
    if len(raw) > 32:
        raise ValueError(
            "At most 32 direct dependencies are supported per environment."
        )
    requirements = []
    for value in raw:
        try:
            requirement = Requirement(value)
        except (InvalidRequirement, TypeError):
            raise ValueError(
                "Use PEP 508 package requirements without pip options or local paths."
            ) from None
        if requirement.url:
            raise ValueError(
                "URL, VCS and local dependencies are not permitted. Use published wheel packages."
            )
        requirements.append(str(requirement))
    requirements = sorted(set(requirements))
    return {
        "requirements": requirements,
        "sha256": hashlib.sha256(json.dumps(requirements).encode()).hexdigest(),
        "policy": "PyPI wheels only; no source distributions, repository hooks, local paths or alternate indexes.",
    }


INSTALLER = r"""
import importlib.metadata, json, subprocess, sys
plan=json.load(sys.stdin)
args=[sys.executable,'-m','pip','install','--only-binary=:all:','--index-url','https://pypi.org/simple','--disable-pip-version-check','--no-cache-dir','--target','/opt/i2p-deps',*plan['requirements']]
result=subprocess.run(args,capture_output=True,text=True,timeout=110,env={'PATH':'/usr/local/bin:/usr/bin:/bin'})
installed={distribution.metadata['Name']:distribution.version for distribution in importlib.metadata.distributions(path=['/opt/i2p-deps'])}
print(json.dumps({'exit_code':result.returncode,'output':(result.stdout+result.stderr)[-16000:],'installed':installed,'policy':'wheels-only'}))
raise SystemExit(result.returncode)
"""


def build_environment(report, config, context=None):
    from .execution import SandboxExecutor

    plan = dependency_plan(report.get("dependency_manifests", {}))
    if not plan["requirements"]:
        return config, {
            **plan,
            "image": config.image,
            "prepared": False,
            "installed": {},
        }
    runner = SandboxExecutor(config, context=context)
    try:
        remote = runner.run(
            INSTALLER, plan, timeout=120, network=True, disposable=False
        )
    finally:
        runner.close()
    evidence = {
        **plan,
        **remote,
        "repository_code_executed": False,
        "network_enabled_during_wheel_install": True,
    }
    report["environment"] = evidence
    if context:
        context.save(report, "environment_prepared")
    if (
        remote["exit_code"] != 0
        or remote["output_truncated"]
        or not remote["result_image"]
    ):
        raise ValueError("Wheel-only dependency preparation failed.")
    details = json.loads(remote["stdout"])
    evidence.update(
        installed=details["installed"],
        output=details["output"],
        prepared=True,
        image=remote["result_image"],
    )
    return replace(config, image=remote["result_image"]), evidence
