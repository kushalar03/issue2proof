"""Inspect repository archives in memory. Never extract, import or execute them."""

import hashlib
import io
import stat
import tomllib
import zipfile
from pathlib import PurePosixPath

MAX_ARCHIVE = 10_000_000
MAX_CONTENT = 2_000_000
MAX_FILES = 1500
MANIFESTS = {
    "pyproject.toml",
    "requirements.txt",
    "requirements.lock",
    "setup.cfg",
    "setup.py",
    "Pipfile",
    "poetry.lock",
    "uv.lock",
}
IGNORED = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
}


def inspect_archive(data: bytes, issue: str) -> dict:
    if not issue.strip() or len(issue) > 4000:
        raise ValueError("Provide a bug report of 1–4,000 characters.")
    if len(data) > MAX_ARCHIVE:
        raise ValueError("Archive exceeds the 10 MB upload limit.")
    files = {}
    excluded = []
    expanded = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_FILES:
                raise ValueError("Archive exceeds the 1,500-entry limit.")
            for entry in entries:
                name = entry.filename
                path = PurePosixPath(name)
                if (
                    str(path) != name.rstrip("/")
                    or "\\" in name
                    or "\x00" in name
                    or path.is_absolute()
                    or any(part in {"..", "."} for part in name.split("/"))
                    or ":" in name
                ):
                    raise ValueError("Archive contains an unsafe path.")
                if stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
                    raise ValueError(
                        "Symlinks and encrypted ZIP entries are unsupported."
                    )
                if entry.is_dir():
                    continue
                if "issue2proof_generated" in path.parts:
                    raise ValueError(
                        "issue2proof_generated is reserved for generated regression artifacts."
                    )
                expanded += entry.file_size
                if expanded > MAX_CONTENT or entry.file_size > 200_000:
                    raise ValueError(
                        "Archive exceeds the expanded text limits (2 MB total, 200 KB per file)."
                    )
                if name in files:
                    raise ValueError("Archive contains duplicate paths.")
                # Hidden files are never included in model context or stored as contents.
                if any(
                    part in IGNORED or part.startswith(".") for part in path.parts
                ) or path.suffix in {".pem", ".key", ".p12", ".pfx"}:
                    excluded.append(name)
                    continue
                if (
                    path.suffix
                    not in {
                        ".py",
                        ".json",
                        ".csv",
                        ".txt",
                        ".yaml",
                        ".yml",
                        ".ini",
                        ".cfg",
                        ".rst",
                        ".md",
                    }
                    and path.name not in MANIFESTS
                ):
                    excluded.append(name)
                    continue
                content = archive.read(entry).decode("utf-8")
                if "\x00" in content:
                    raise ValueError("Repository text contains NUL bytes.")
                files[name] = content
    except (zipfile.BadZipFile, UnicodeDecodeError, RuntimeError, NotImplementedError):
        raise ValueError(
            "Upload a valid unencrypted ZIP containing UTF-8 Python files."
        ) from None
    if not files:
        raise ValueError("No supported Python or dependency files found.")
    paths = list(files)
    if (
        all("/" in name for name in paths)
        and len({name.split("/")[0] for name in paths}) == 1
    ):
        files = {name.split("/", 1)[1]: content for name, content in files.items()}
    sources = {
        name: content
        for name, content in files.items()
        if name.endswith(".py")
        and not is_test(name)
        and PurePosixPath(name).name != "setup.py"
    }
    tests = {name: content for name, content in files.items() if is_test(name)}
    resources = {
        name: content
        for name, content in files.items()
        if not name.endswith(".py") and PurePosixPath(name).name not in MANIFESTS
    }
    dependencies = {
        name: content
        for name, content in files.items()
        if PurePosixPath(name).name in MANIFESTS
    }
    if not sources:
        raise ValueError("Repository needs at least one Python implementation file.")
    # Reject invalid TOML without installing dependencies or running setup hooks.
    for name, content in dependencies.items():
        if name.endswith("pyproject.toml"):
            try:
                tomllib.loads(content)
            except tomllib.TOMLDecodeError:
                raise ValueError("pyproject.toml is not valid TOML.") from None
    return {
        "case": "repository",
        "mode": "repository draft",
        "issue": issue.strip(),
        "verdict": "awaiting_model",
        "explanation": "Repository inspected. No code or dependency setup was executed.",
        "attempts": [],
        "events": ["Archive inspected in memory; no files extracted or executed."],
        "sources": sources,
        "resources": resources,
        "existing_tests": tests,
        "dependency_manifests": dependencies,
        "file_hashes": {
            name: hashlib.sha256(content.encode()).hexdigest()
            for name, content in files.items()
        },
        "archive_sha256": hashlib.sha256(data).hexdigest(),
        "excluded_files": excluded,
        "limitations": [
            "Drafts are not verified repairs. Remote execution and independently collected evidence are pending.",
            "Included files may contain sensitive data. Review them before sending anything to Nebius.",
        ],
    }


def is_test(name: str) -> bool:
    path = PurePosixPath(name)
    return (
        "tests" in path.parts
        or path.name.startswith("test_")
        or path.name.endswith("_test.py")
        or path.name == "conftest.py"
    )
