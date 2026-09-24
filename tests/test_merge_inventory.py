"""Run with: python3 -m unittest discover tests"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_inventory  # noqa: E402
import merge_inventory  # noqa: E402


class MergeTest(unittest.TestCase):
    def test_merge_parts_in_config_order(self):
        cities = json.loads(check_inventory.CONFIG.read_text())["cities"]
        a = {"updated": "2026-09-24T15:00:00+00:00", "source": "pickup-message",
             "models": [{"key": "256gb", "variants": [{"label": "x", "part": "RO"}]}],
             "cities": [{**cities[1], "stores": []}]}
        b = {"updated": "2026-09-24T15:01:00+00:00", "source": None,
             "models": [{"key": "256gb", "variants": [{"label": "x", "part": "RO", "options": "065-A"}]}],
             "cities": [{**cities[0], "stores": []}, {**cities[2], "stores": []}]}
        merged = merge_inventory.merge([a, b])
        self.assertEqual([c["name"] for c in merged["cities"]], [c["name"] for c in cities[:3]])
        self.assertEqual(merged["updated"], "2026-09-24T15:01:00+00:00")
        self.assertEqual(merged["source"], "pickup-message")
        self.assertEqual(merged["models"][0]["variants"][0]["options"], "065-A")


class PackTest(unittest.TestCase):
    def test_round_trip_and_combine(self):
        def st(label, status, checked):
            return {"id": "R1", "name": "Fifth Avenue", "availability": {"256gb": {
                "variants": {label: {"status": status, "quote": "", "checked": checked}}}}}
        snap = {"cities": [{"name": "A", "stores": [st("a", "ineligible", "t1")]},
                           {"name": "B", "stores": [st("b", "available", "t1")]}]}
        packed = check_inventory.pack(snap)
        self.assertEqual([c["stores"] for c in packed["cities"]], [["R1"], ["R1"]])
        a = packed["stores"]["R1"]["availability"]["256gb"]
        self.assertEqual((a["status"], sorted(a["variants"])), ("available", ["a", "b"]))
        out = check_inventory.unpack(json.loads(json.dumps(packed)))
        self.assertEqual([c["stores"][0]["id"] for c in out["cities"]], ["R1", "R1"])
        self.assertNotIn("stores", out)


if __name__ == "__main__":
    unittest.main()
