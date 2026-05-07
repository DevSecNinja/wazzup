from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence


def run_git(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""


def build_payload() -> dict[str, str]:
    commit_sha = os.environ.get("GITHUB_SHA") or run_git("rev-parse", "HEAD") or "dev"
    short_sha = commit_sha[:7] if commit_sha != "dev" else "dev"
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    build_id = f"{short_sha}-{run_id}" if run_id else short_sha
    repo = os.environ.get("GITHUB_REPOSITORY", "DevSecNinja/wazzup")
    server_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    commit_url = "" if commit_sha == "dev" else f"{server_url}/{repo}/commit/{commit_sha}"
    return {
        "appName": "Wazzup",
        "buildId": build_id,
        "commitSha": commit_sha,
        "shortSha": short_sha,
        "commitUrl": commit_url,
        "generatedAt": generated_at,
        "repository": repo,
        "repositoryUrl": f"{server_url}/{repo}",
    }


def write_build_info(public_dir: Path) -> dict[str, str]:
    public_dir.mkdir(parents=True, exist_ok=True)
    payload = build_payload()
    (public_dir / "build-info.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main(argv: Sequence[str] | None = None) -> None:
    del argv
    payload = write_build_info(Path(os.environ.get("PUBLIC_DIR", "public")))
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
