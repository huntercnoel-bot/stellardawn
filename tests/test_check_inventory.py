"""Run with: python3 -m unittest discover tests"""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_inventory  # noqa: E402

M96 = {"key": "96gb", "variants": [{"label": "base", "part": "MHL74LL/A"}]}
M256 = {"key": "256gb", "variants": [
    {"label": "30-core 1TB", "part": "Z1U500001"},
    {"label": "36-core 1TB", "part": "Z1U500002"},
    {"label": "not resolved", "part": None},
]}


def store(number, name, parts):
    return {"storeNumber": number, "storeName": name, "city": "New York", "state": "NY",
            "storeDistanceWithUnit": "1.0 mi", "partsAvailability": parts}


def payload(*stores):
    return {"body": {"content": {"pickupMessage": {"stores": list(stores)}}}}


class ParseStoresTest(unittest.TestCase):
    def test_single_variant(self):
        rows = check_inventory.parse_stores(payload(
            store("R095", "Fifth Avenue", {"MHL74LL/A": {
                "pickupDisplay": "available", "pickupSearchQuote": "Available Today"}}),
            store("R102", "SoHo", {"MHL74LL/A": {"pickupDisplay": "unavailable"}}),
            store("R999", "Odd", {}),
        ), M96)
        self.assertEqual(rows["R095"]["availability"]["96gb"],
                         {"status": "available", "quote": "Available Today", "in_stock": ["base"]})
        self.assertEqual(rows["R102"]["availability"]["96gb"]["status"], "unavailable")
        self.assertEqual(rows["R999"]["availability"]["96gb"]["status"], "unknown")

    def test_best_variant_wins(self):
        rows = check_inventory.parse_stores(payload(store("R1", "A", {
            "Z1U500001": {"pickupDisplay": "unavailable"},
            "Z1U500002": {"pickupDisplay": "available", "pickupSearchQuote": "Today"},
        })), M256)
        a = rows["R1"]["availability"]["256gb"]
        self.assertEqual((a["status"], a["quote"], a["in_stock"]), ("available", "Today", ["36-core 1TB"]))

    def test_empty_payload(self):
        self.assertEqual(check_inventory.parse_stores({}, M96), {})


class CheckCityTest(unittest.TestCase):
    def test_one_model_failing_keeps_the_other(self):
        def fake_fetch(parts, zip_code):
            if parts[0].startswith("Z"):
                raise RuntimeError("HTTP 400")
            return payload(store("R095", "Fifth Avenue", {"MHL74LL/A": {"pickupDisplay": "available"}}))

        with mock.patch.object(check_inventory, "fetch_pickup", fake_fetch), \
                mock.patch.object(check_inventory.time, "sleep"):
            stores, errors = check_inventory.check_city({"zip": "10153"}, [M96, M256])
        self.assertEqual(errors, {"256gb": "HTTP 400"})
        self.assertEqual(stores[0]["availability"]["96gb"]["status"], "available")
        self.assertEqual(stores[0]["availability"]["256gb"]["status"], "error")


class FindPartTest(unittest.TestCase):
    def test_standard_and_bto(self):
        self.assertEqual(check_inventory.find_part('{"partNumber":"MHL74LL/A"}'), "MHL74LL/A")
        self.assertEqual(check_inventory.find_part('x "part": "Z1U500038" y'), "Z1U500038")
        self.assertIsNone(check_inventory.find_part("<html>nothing</html>"))


class ConfigTest(unittest.TestCase):
    def test_config_is_valid(self):
        config = json.loads(check_inventory.CONFIG.read_text())
        self.assertEqual({m["key"] for m in config["models"]}, {"96gb", "256gb"})
        for model in config["models"]:
            for v in model["variants"]:
                self.assertTrue(v.get("part") or v.get("page"), v)
        zips = [c["zip"] for c in config["cities"]]
        self.assertTrue(all(len(z) == 5 and z.isdigit() for z in zips))
        self.assertEqual(len(zips), len(set(zips)))


if __name__ == "__main__":
    unittest.main()
