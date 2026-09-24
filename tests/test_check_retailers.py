"""Run with: python3 -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_retailers  # noqa: E402


class MicroCenterStockTest(unittest.TestCase):
    def test_in_stock(self):
        page = '<div><span class="inventoryCnt">5 NEW IN STOCK</span> at Brooklyn</div>'
        self.assertEqual(check_retailers.mc_stock(page), (5, "5 NEW IN STOCK"))

    def test_plus_count_and_markup(self):
        page = '<span class="inventoryCnt"><b>25+</b> NEW IN STOCK</span>'
        self.assertEqual(check_retailers.mc_stock(page), (25, "25+ NEW IN STOCK"))

    def test_sold_out(self):
        page = '<span class="inventoryCnt">SOLD OUT</span>'
        self.assertEqual(check_retailers.mc_stock(page), (0, "SOLD OUT"))

    def test_nothing(self):
        self.assertEqual(check_retailers.mc_stock("<html></html>"), (0, ""))


class TitleMatchTest(unittest.TestCase):
    def test_models(self):
        m = check_retailers.MC_TITLE_MATCH
        title = "Apple Mac Studio Z1U5 (Mid 2026); Apple M5 Ultra 36-Core CPU; 256GB Unified Memory; 1TB"
        self.assertTrue(m["256gb"].search(title))
        self.assertFalse(m["96gb"].search(title))
        self.assertTrue(m["96gb"].search("Apple Mac Studio MHL74LL/A (Mid 2026); M5 Ultra; 96GB"))


if __name__ == "__main__":
    unittest.main()
