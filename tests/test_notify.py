import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import notify  # noqa: E402

CONFIG = {"alerts": {"models": ["96gb"], "priority_area_models": ["64gb"]},
          "models": [{"key": "96gb", "short": "96GB", "label": "M5 Ultra 96GB", "apple_url": "u96", "variants": []},
                     {"key": "64gb", "short": "64GB", "label": "M5 Max 64GB", "apple_url": "u64",
                      "variants": [{"label": "1TB", "page": "p64"}]}]}
INV = {"cities": [{"name": "Miami", "priority": True, "stores": ["R1"]}, {"name": "NY", "stores": ["R2"]}],
       "stores": {"R1": {"availability": {"64gb": {"in_stock": ["1TB"]}}}, "R2": {"availability": {}}}}


def ev(store, model, kind="restock"):
    return {"store": store, "model": model, "event": kind, "name": "X", "city": "C", "state": "S"}


class PickTest(unittest.TestCase):
    def test_rules(self):
        got = notify.pick([ev("R2", "96gb"), ev("R1", "64gb"), ev("R2", "64gb"), ev("R2", "96gb", "sold_out")], INV, CONFIG)
        self.assertEqual([(a["title"][:4], a["url"], a["miami"]) for a in got], [("96GB", "u96", False), ("64GB", "p64", True)])


if __name__ == "__main__":
    unittest.main()
