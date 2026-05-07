from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from wazzup.build_info import build_payload, write_build_info


class BuildInfoTests(unittest.TestCase):
    def test_build_payload_uses_github_environment(self) -> None:
        previous = {key: os.environ.get(key) for key in ["GITHUB_SHA", "GITHUB_RUN_ID", "GITHUB_REPOSITORY", "GITHUB_SERVER_URL"]}
        os.environ["GITHUB_SHA"] = "abcdef1234567890"
        os.environ["GITHUB_RUN_ID"] = "42"
        os.environ["GITHUB_REPOSITORY"] = "DevSecNinja/wazzup"
        os.environ["GITHUB_SERVER_URL"] = "https://github.com"
        try:
            payload = build_payload()
            self.assertEqual("abcdef1", payload["shortSha"])
            self.assertEqual("abcdef1-42", payload["buildId"])
            self.assertEqual("https://github.com/DevSecNinja/wazzup/commit/abcdef1234567890", payload["commitUrl"])
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_write_build_info_creates_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload = write_build_info(Path(tmp_dir))
            content = (Path(tmp_dir) / "build-info.json").read_text(encoding="utf-8")
            self.assertIn(payload["buildId"], content)


if __name__ == "__main__":
    unittest.main()
