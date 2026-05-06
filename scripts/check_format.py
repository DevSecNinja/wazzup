from __future__ import annotations

import sys
from pathlib import Path

TEXT_SUFFIXES = {".py", ".md", ".yml", ".yaml", ".json", ".toml", ".css", ".js", ".html", ".webmanifest"}
EXCLUDED_PARTS = {".git", "__pycache__", ".pytest_cache", "public/data", ".venv"}


def is_excluded(path: Path) -> bool:
    text = path.as_posix()
    return any(part in path.parts for part in EXCLUDED_PARTS) or text.startswith("public/data/")


def main() -> None:
    failures: list[str] = []
    for path in Path(".").rglob("*"):
        if not path.is_file() or is_excluded(path) or path.suffix not in TEXT_SUFFIXES:
            continue
        data = path.read_bytes()
        if data and not data.endswith(b"\n"):
            failures.append(f"{path}: missing trailing newline")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            failures.append(f"{path}: not UTF-8")
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            if line.rstrip() != line:
                failures.append(f"{path}:{line_number}: trailing whitespace")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        raise SystemExit(1)
    print("format check passed")


if __name__ == "__main__":
    main()
