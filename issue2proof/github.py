"""Bounded public GitHub ingestion without accepting arbitrary network targets."""

import re
from urllib.parse import quote, urlsplit

import httpx

from .repository import MAX_ARCHIVE, inspect_archive

PART = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,98}[A-Za-z0-9])?")
REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")


def parse_repository_url(url: str) -> tuple[str, str]:
    parsed = urlsplit(url.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Use a public https://github.com/owner/repository URL.")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        raise ValueError(
            "Use the repository root URL, not a file, issue or pull request URL."
        )
    owner, repository = parts
    if repository.endswith(".git"):
        repository = repository[:-4]
    if not PART.fullmatch(owner) or not PART.fullmatch(repository):
        raise ValueError("GitHub owner or repository name is invalid.")
    return owner, repository


def import_public_repository(
    url: str,
    issue: str,
    *,
    ref: str = "HEAD",
    client: httpx.Client | None = None,
) -> dict:
    owner, repository = parse_repository_url(url)
    if not REF.fullmatch(ref) or ".." in ref or "//" in ref:
        raise ValueError("Git reference is invalid.")
    target = f"https://codeload.github.com/{owner}/{repository}/zip/" + quote(
        ref, safe=""
    )
    own_client = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=False)
    data = bytearray()
    try:
        with client.stream(
            "GET", target, headers={"Accept": "application/zip"}
        ) as response:
            response.raise_for_status()
            declared = response.headers.get("content-length")
            if declared and int(declared) > MAX_ARCHIVE:
                raise ValueError("GitHub archive exceeds the 10 MB upload limit.")
            for chunk in response.iter_bytes():
                if len(data) + len(chunk) > MAX_ARCHIVE:
                    raise ValueError("GitHub archive exceeds the 10 MB upload limit.")
                data.extend(chunk)
    except httpx.HTTPError as error:
        raise ValueError(
            "GitHub repository download failed; verify that it is public and the ref exists."
        ) from error
    finally:
        if own_client:
            client.close()
    report = inspect_archive(bytes(data), issue)
    report["repository"] = {
        "provider": "github",
        "full_name": f"{owner}/{repository}",
        "source_url": f"https://github.com/{owner}/{repository}",
        "ref": ref,
    }
    report["events"].append(
        "Public GitHub archive fetched from the fixed codeload.github.com origin."
    )
    return report
