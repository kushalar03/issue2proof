"""Build a source/evidence release without credentials or local state."""

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT.parents[1] / "issue2proof-final.zip"
SKIP_DIRS = {
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".git",
    "raw-video",
    "memory-raw-video",
    "demo-voice-segments",
}
OLD_MEDIA = {
    "demo.mp4",
    "demo-screen.webm",
    "narration.wav",
    "narration.txt",
    "final-screen.webm",
    "final-narration.wav",
    "memory-demo-screen.webm",
    "memory-demo-voice.wav",
}


def included(path):
    rel = path.relative_to(ROOT)
    return (
        path.is_file()
        and not path.is_symlink()
        and not any(x in SKIP_DIRS or x.endswith(".egg-info") for x in rel.parts)
        and not (path.name.startswith(".env") and path.name != ".env.example")
        and not any(x in path.name for x in (".sqlite3", "auth.ini"))
        and path.name not in OLD_MEDIA
        and path.name != "release-manifest.json"
    )


def main():
    files = sorted(p for p in ROOT.rglob("*") if included(p))
    manifest = {
        "version": "2.0.0",
        "files": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in files
        },
        "publication_status": "Version 2.0 is validated locally and against live Nebius services. The public interactive application is deployed over HTTPS; video upload and final Devpost submission require account-owner action.",
    }
    target = ROOT / "submission/release-manifest.json"
    target.write_text(json.dumps(manifest, indent=2) + "\n")
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as archive:
        for p in files + [target]:
            archive.write(p, Path("issue2proof") / p.relative_to(ROOT))
    with zipfile.ZipFile(OUTPUT) as archive:
        assert archive.testzip() is None
        assert not any(
            ".sqlite3" in n or "/.env" in n and not n.endswith("/.env.example")
            for n in archive.namelist()
        )
    digest = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    OUTPUT.with_suffix(".zip.sha256").write_text(f"{digest}  {OUTPUT.name}\n")
    print(
        f"{OUTPUT}: {len(files) + 1} files, {OUTPUT.stat().st_size} bytes, SHA256 {digest}"
    )


if __name__ == "__main__":
    main()
