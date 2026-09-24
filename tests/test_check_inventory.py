"""Run with: python3 -m unittest discover tests"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import check_inventory  # noqa: E402

MODELS = [
    {"key": "96gb", "part": "MU973LL/A"},
    {"key": "256gb", "part": None},
]

# Trimmed shape of an Apple fulfillment-messages response.
PAYLOAD = {
    "body": {"content": {"pickupMessage": {"stores": [
        {
            "storeNumber": "R095", "storeName": "Fifth Avenue", "city": "New York",
            "state": "NY", "storeDistanceWithUnit": "0.1 mi",
            "partsAvailability": {"MU973LL/A": {
                "pickupDisplay": "available", "pickupSearchQuote": "Available Today"}},
        },
        {
            "storeNumber": "R102", "storeName": "SoHo", "city": "New York",
            "state": "NY", "storeDistanceWithUnit": "3.4 mi",
            "partsAvailability": {"MU973LL/A": {
                "pickupDisplay": "unavailable", "pickupSearchQuote": "Currently unavailable"}},
        },
        {"storeNumber": "R999", "storeName": "Odd", "partsAvailability": {}},
    ]}}}
}


class ParseStoresTest(unittest.TestCase):
    def test_statuses(self):
        rows = check_inventory.parse_stores(PAYLOAD, MODELS)
        self.assertEqual([r["id"] for r in rows], ["R095", "R102", "R999"])
        self.assertEqual(rows[0]["availability"]["96gb"],
                         {"status": "available", "quote": "Available Today"})
        self.assertEqual(rows[1]["availability"]["96gb"]["status"], "unavailable")
        self.assertEqual(rows[2]["availability"]["96gb"]["status"], "unknown")
        self.assertEqual(rows[0]["availability"]["256gb"], {"status": "not_stocked"})

    def test_empty_payload(self):
        self.assertEqual(check_inventory.parse_stores({}, MODELS), [])

    def test_config_is_valid(self):
        config = json.loads(check_inventory.CONFIG.read_text())
        self.assertEqual({m["key"] for m in config["models"]}, {"96gb", "256gb"})
        zips = [c["zip"] for c in config["cities"]]
        self.assertTrue(all(len(z) == 5 and z.isdigit() for z in zips))
        self.assertEqual(len(zips), len(set(zips)))


if __name__ == "__main__":
    unittest.main()
