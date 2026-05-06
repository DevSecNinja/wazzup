from __future__ import annotations

import ast
import sys
from pathlib import Path


def main() -> None:
    failures: list[str] = []
    for path in [*Path("src").rglob("*.py"), *Path("scripts").rglob("*.py"), *Path("tests").rglob("*.py")]:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            failures.append(f"{path}:{exc.lineno}: {exc.msg}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        raise SystemExit(1)
    print("lint passed")


if __name__ == "__main__":
    main()
