from __future__ import annotations

import unittest
from pathlib import Path


ASSET_BUDGETS = {
    "public/index.html": 16_000,
    "public/styles.css": 36_000,
    "public/app.js": 90_000,
    "public/sw.js": 18_000,
    "public/manifest.webmanifest": 6_000,
}


class PerformanceBudgetTests(unittest.TestCase):
    def test_static_pwa_assets_stay_within_size_budgets(self) -> None:
        for path, budget in ASSET_BUDGETS.items():
            with self.subTest(path=path):
                size = Path(path).stat().st_size
                self.assertLessEqual(size, budget, f"{path} is {size} bytes; budget is {budget} bytes")

    def test_initial_static_shell_stays_small(self) -> None:
        total = sum(Path(path).stat().st_size for path in ASSET_BUDGETS)
        self.assertLessEqual(total, 150_000, f"static shell is {total} bytes; budget is 150000 bytes")


if __name__ == "__main__":
    unittest.main()
