"""Load optional local deployment settings as data, never shell instructions."""

import os
from pathlib import Path


def load_environment(path=Path(".env")):
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        value = line.strip()
        if not value or value.startswith("#") or "=" not in value:
            continue
        name, content = value.split("=", 1)
        if not name.replace("_", "").isalnum() or name[0].isdigit():
            continue
        content = content.strip()
        if len(content) >= 2 and content[0] == content[-1] and content[0] in {'"', "'"}:
            content = content[1:-1]
        if content:
            os.environ.setdefault(name, content)
