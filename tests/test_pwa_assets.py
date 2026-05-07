from __future__ import annotations

import json
import unittest
from pathlib import Path


class PwaAssetTests(unittest.TestCase):
    def test_manifest_declares_install_icons(self) -> None:
        manifest = json.loads(Path("public/manifest.webmanifest").read_text(encoding="utf-8"))
        icon_sources = {icon["src"] for icon in manifest["icons"]}
        self.assertIn("icons/icon-192.png", icon_sources)
        self.assertIn("icons/icon-512.png", icon_sources)
        for source in icon_sources:
            self.assertTrue((Path("public") / source).exists(), source)
        self.assertTrue(Path("public/icons/apple-touch-icon.png").exists())
        self.assertTrue(Path("public/icons/favicon.svg").exists())

    def test_app_uses_24_hour_browser_time_and_build_versioned_sw(self) -> None:
        app = Path("public/app.js").read_text(encoding="utf-8")
        self.assertIn("hourCycle: 'h23'", app)
        self.assertIn("updateViaCache: 'none'", app)
        self.assertIn("sw.js?v=", app)
        self.assertIn("FALLBACK_TIME_ZONE = 'Europe/Amsterdam'", app)
        self.assertIn("MAX_HEADLINE_LENGTH", app)
        self.assertIn("normalizeBullet", app)
        self.assertIn("temperatureClass", app)
        self.assertIn("bullet--", app)
        self.assertIn("renderYesterday", app)

    def test_homepage_uses_simple_header_and_yesterday_card(self) -> None:
        html = Path("public/index.html").read_text(encoding="utf-8")
        self.assertNotIn("topbar__links", html)
        self.assertNotIn("Previous hours", html)
        self.assertIn("id=\"yesterday\"", html)

    def test_footer_contains_repo_commit_and_star_targets(self) -> None:
        html = Path("public/index.html").read_text(encoding="utf-8")
        self.assertIn("id=\"commitLink\"", html)
        self.assertIn("id=\"starCountText\"", html)
        self.assertIn("https://github.com/DevSecNinja/wazzup", html)

    def test_service_worker_cache_uses_registration_build_id(self) -> None:
        sw = Path("public/sw.js").read_text(encoding="utf-8")
        self.assertIn("searchParams.get('v')", sw)
        self.assertIn("const CACHE_NAME = `wazzup-${BUILD_ID}`", sw)


if __name__ == "__main__":
    unittest.main()
