from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from wazzup.build_info import write_build_info
from wazzup.validate_data import validate_data_dir


def retained_state_url() -> str:
    repository = os.environ.get("GITHUB_REPOSITORY", "DevSecNinja/wazzup")
    server_url = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    release = os.environ.get("STATE_RELEASE", "news-state")
    asset = os.environ.get("STATE_ASSET", "wazzup-state.zip")
    return f"{server_url}/{repository}/releases/download/{release}/{asset}"


def download_retained_state(destination: Path) -> bool:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(retained_state_url(), timeout=30) as response:
            destination.write_bytes(response.read())
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        print(f"No retained news state could be downloaded: {exc}", file=sys.stderr)
        return False
    return True


def safe_extract_zip(zip_path: Path, destination: Path) -> None:
    destination_root = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if destination_root != target and destination_root not in target.parents:
                raise ValueError(f"Archive member escapes destination: {member.filename}")
        archive.extractall(destination)


def main() -> None:
    public_dir = Path(os.environ.get("PUBLIC_DIR", "public"))
    write_build_info(public_dir)

    state_asset = Path(".state") / os.environ.get("STATE_ASSET", "wazzup-state.zip")
    if not download_retained_state(state_asset):
        raise SystemExit("Pages builds require retained state. Run the News hourly workflow first.")
    safe_extract_zip(state_asset, public_dir)
    validate_data_dir(public_dir / "data")
    print(f"validated {public_dir / 'data'}")


if __name__ == "__main__":
    main()
