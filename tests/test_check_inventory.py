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
    {"label": "30-core 1TB", "part": "Z1U500001", "options": "065-AAAA"},
    {"label": "36-core 1TB", "part": "Z1U500002", "options": "065-BBBB"},
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
        a = rows["R095"]["availability"]["96gb"]
        self.assertEqual((a["status"], a["quote"], a["in_stock"]), ("available", "Available Today", ["base"]))
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


class StoreUrlTest(unittest.TestCase):
    def test_prefers_apple_links(self):
        self.assertEqual(check_inventory.store_url(
            {"hoursUrl": "https://www.apple.com/retail/fifthavenue/"}), "https://www.apple.com/retail/fifthavenue/")
        self.assertEqual(check_inventory.store_url(
            {"retailStore": {"storeUrl": "https://www.apple.com/retail/soho/"}}), "https://www.apple.com/retail/soho/")
        self.assertEqual(check_inventory.store_url({"hoursUrl": "http://www.apple.com/retail/fifthavenue"}),
                         "https://www.apple.com/retail/fifthavenue")
        self.assertEqual(check_inventory.store_url({"hoursUrl": "https://example.com/x"}), "")
        self.assertEqual(check_inventory.store_url({}), "")


class CheckCityTest(unittest.TestCase):
    def test_one_model_failing_keeps_the_other(self):
        def fake_fetch(variants, zip_code, referer=None):
            if variants[0]["part"].startswith("Z"):
                raise RuntimeError("HTTP 400")
            return payload(store("R095", "Fifth Avenue", {"MHL74LL/A": {"pickupDisplay": "available"}}))

        with mock.patch.object(check_inventory, "fetch_pickup", fake_fetch), \
                mock.patch.object(check_inventory.time, "sleep"):
            stores, errors = check_inventory.check_city({"zip": "10153"}, [M96, M256])
        self.assertEqual(errors, {"256gb": "HTTP 400"})
        self.assertEqual(stores[0]["availability"]["96gb"]["status"], "available")
        self.assertEqual(stores[0]["availability"]["256gb"]["status"], "error")


class FailFastTest(unittest.TestCase):
    def run_refusals(self, answer):
        calls = []

        def refuse(*args, **kwargs):
            calls.append(1)
            return answer

        errors = []
        with mock.patch.object(check_inventory, "_get_once", refuse), \
                mock.patch.object(check_inventory.time, "sleep"), \
                mock.patch.object(check_inventory, "_failures", 0):
            for _ in range(check_inventory.MAX_CONSECUTIVE_FAILURES + 1):
                with self.assertRaises(RuntimeError) as ctx:
                    check_inventory.http_get("https://example.com")
                errors.append(type(ctx.exception).__name__)
        return calls, errors

    def test_stops_after_repeated_failures(self):
        calls, errors = self.run_refusals((503, "busy"))
        self.assertEqual(len(calls), check_inventory.MAX_CONSECUTIVE_FAILURES * check_inventory.RETRIES)
        self.assertEqual(errors[-1], "AppleUnavailable")

    def test_rate_limit_stops_immediately(self):
        calls, errors = self.run_refusals((541, "Page Not Found"))
        self.assertEqual(len(calls), 1)  # no retry, no second endpoint, nothing after
        self.assertEqual(errors[0], "RateLimited")
        self.assertTrue(all(e == "AppleUnavailable" for e in errors[1:]))


class EndpointTest(unittest.TestCase):
    def setUp(self):
        check_inventory._endpoint = None
        check_inventory._failures = 0

    def test_pickup_message_shape(self):
        data = {"body": {"stores": [store("R1", "A", {"MHL74LL/A": {"pickupDisplay": "available"}})]}}
        rows = check_inventory.parse_stores(data, M96)
        self.assertEqual(rows["R1"]["availability"]["96gb"]["status"], "available")

    def test_falls_back_and_remembers_endpoint(self):
        seen = []

        def fake_get(url, params, headers):
            seen.append((url.rsplit("/", 1)[-1], params.get("option.0"), headers["Referer"]))
            if url.endswith("pickup-message"):
                return 503, "unavailable"
            return 200, json.dumps(payload(store("R1", "A", {})))

        with mock.patch.object(check_inventory, "_get_once", fake_get), \
                mock.patch.object(check_inventory.time, "sleep"):
            variants = [{"part": "RO_MAC_STUDIO_X", "options": "065-AAAA,065-BBBB"}]
            check_inventory.fetch_pickup(variants, "10153", "https://www.apple.com/shop/x")
            check_inventory.fetch_pickup(variants, "10153", "https://www.apple.com/shop/x")
        self.assertEqual([s[0] for s in seen],
                         ["pickup-message", "pickup-message", "fulfillment-messages", "fulfillment-messages"])
        self.assertEqual(seen[-1][1:], ("065-AAAA,065-BBBB", "https://www.apple.com/shop/x"))
        self.assertEqual(check_inventory._endpoint, "fulfillment-messages")


class BuildToOrderTest(unittest.TestCase):
    def test_default_kit(self):
        html = ('"defaultKit":{"part":"RO_MACSTUDIO_M5MAX_M5ULTRA_BET_BES_2026","options":'
                '{"memory":"065-CLQ7","thunderbolt":"065-CLT9","storage":"065-CLQX"}}')
        self.assertEqual(check_inventory.discover(html), {
            "part": "RO_MACSTUDIO_M5MAX_M5ULTRA_BET_BES_2026", "options": "065-CLQ7,065-CLT9,065-CLQX"})

    def test_request_plan(self):
        m1 = {"key": "a", "variants": [{"part": "MHL74LL/A"}]}
        m2 = {"key": "b", "variants": [{"part": "RO_X", "options": "065-A"},
                                      {"part": "RO_X", "options": "065-B"}, {"part": None}]}
        m3 = {"key": "c", "variants": [{"part": "MHL64LL/A"}]}
        plan = check_inventory.request_plan([m1, m2, m3])
        self.assertEqual([[v["part"] for v in vs] for vs, _ in plan],
                         [["MHL74LL/A", "MHL64LL/A"], ["RO_X"], ["RO_X"]])
        self.assertEqual([[m["key"] for m, _ in members] for _, members in plan], [["a", "c"], ["b"], ["b"]])

    def test_bto_answers_merge_best_status(self):
        model = {"key": "256gb", "variants": [
            {"label": "a", "part": "RO_X", "options": "065-A"}, {"label": "b", "part": "RO_X", "options": "065-B"}]}

        def fake_fetch(variants, zip_code, referer=None):
            status = "available" if variants[0]["options"] == "065-B" else "ineligible"
            # keyed by something other than the product code, to exercise the fallback
            return payload(store("R1", "A", {"RO_X_CTO": {"pickupDisplay": status}}))

        with mock.patch.object(check_inventory, "fetch_pickup", fake_fetch), \
                mock.patch.object(check_inventory.time, "sleep"):
            stores, errors = check_inventory.check_city({"zip": "10153"}, [model])
        self.assertEqual(errors, {})
        a = stores[0]["availability"]["256gb"]
        self.assertEqual((a["status"], a["in_stock"]), ("available", ["b"]))


class RotationTest(unittest.TestCase):
    MODEL = {"key": "256gb", "variants": [
        {"label": l, "part": "RO_X", "options": o} for l, o in (("a", "1"), ("b", "2"), ("c", "3"))]}
    STD = {"key": "96gb", "variants": [{"label": "base", "part": "MHL74LL/A"}]}

    def picked(self, city, run):
        m = check_inventory.city_models([self.STD, self.MODEL], city, run, 2)
        return m[0]["variants"], [v["label"] for v in m[1]["variants"]]

    def test_standard_always_and_bto_rotates(self):
        self.assertEqual(self.picked(0, 0), (self.STD["variants"], ["a"]))
        self.assertEqual(self.picked(1, 0)[1], [])          # other slice this run
        self.assertEqual(self.picked(1, 1)[1], ["b"])
        seen = {tuple(self.picked(0, run)[1]) for run in range(0, 12, 2)}
        self.assertEqual(seen, {("a",), ("b",), ("c",)})    # city 0 cycles through every setup


class CarryForwardTest(unittest.TestCase):
    MODELS = [{"key": "256gb", "variants": []}]

    def test_recent_setups_and_cities_carry(self):
        now = check_inventory.datetime(2026, 9, 24, 15, 0, tzinfo=check_inventory.timezone.utc)
        recent, old = "2026-09-24T14:40:00+00:00", "2026-09-24T12:00:00+00:00"
        prev_store = {"id": "R1", "availability": {"256gb": {"variants": {
            "a": {"status": "available", "quote": "Today", "checked": recent},
            "b": {"status": "unavailable", "quote": "", "checked": old}}}}}
        previous = {"cities": [
            {"name": "NY", "state": "NY", "checked": recent, "stores": [prev_store]},
            {"name": "LA", "state": "CA", "checked": recent, "stores": [{"id": "R2", "availability": {}}]}]}
        results = [
            {"name": "NY", "state": "NY", "stores": [{"id": "R1", "availability": {"256gb": {
                "status": "unknown", "quote": "", "in_stock": [], "variants": {}}}}]},
            {"name": "LA", "state": "CA", "stores": []}]
        check_inventory.carry_forward(results, previous, self.MODELS, now)
        a = results[0]["stores"][0]["availability"]["256gb"]
        self.assertEqual((a["status"], a["in_stock"], sorted(a["variants"])), ("available", ["a"], ["a"]))
        self.assertEqual(results[1]["stores"][0]["id"], "R2")
        self.assertEqual(results[1]["checked"], recent)


class FindPartTest(unittest.TestCase):
    def test_discover_bto(self):
        html = 'x "RO_MAC_STUDIO_M5_ULTRA_2026" y "/shop/fulfillment-messages?parts.0=RO_MAC_STUDIO_M5_ULTRA_2026&option.0=065-ABCD%2C065-EF12"'
        self.assertEqual(check_inventory.discover(html),
                         {"part": "RO_MAC_STUDIO_M5_ULTRA_2026", "options": "065-ABCD,065-EF12"})
        self.assertEqual(check_inventory.discover('{"partNumber":"MHL74LL/A"}'), {"part": "MHL74LL/A"})
        self.assertEqual(check_inventory.discover("nothing"), {})

    def test_standard_and_bto(self):
        self.assertEqual(check_inventory.find_part('{"partNumber":"MHL74LL/A"}'), "MHL74LL/A")
        self.assertEqual(check_inventory.find_part('x "part": "Z1U500038" y'), "Z1U500038")
        self.assertIsNone(check_inventory.find_part("<html>nothing</html>"))


class ConfigTest(unittest.TestCase):
    def test_config_is_valid(self):
        config = json.loads(check_inventory.CONFIG.read_text())
        self.assertEqual({m["key"] for m in config["models"]}, {"96gb", "256gb", "64gb", "128gb", "m5max36"})
        for model in config["models"]:
            self.assertTrue(model["apple_url"].startswith("https://www.apple.com/"))
            for v in model["variants"]:
                self.assertTrue(v.get("part") or v.get("page"), v)
        zips = [c["zip"] for c in config["cities"]]
        self.assertTrue(all(len(z) == 5 and z.isdigit() for z in zips))
        self.assertEqual(len(zips), len(set(zips)))


if __name__ == "__main__":
    unittest.main()
