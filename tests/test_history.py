"""Run with: python3 -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import history  # noqa: E402


def store(status, checked, **fields):
    return {"id": "R1", "name": "Fifth Avenue", "city": "New York", "state": "NY",
            "availability": {"96gb": {"status": status, **fields,
                                      "variants": {"base": {"status": status, "checked": checked}}}}}


class HistoryTest(unittest.TestCase):
    def test_restock_then_sold_out(self):
        events = history.track({"R1": store("available", "2026-09-24T16:00:00+00:00")},
                               {"R1": store("ineligible", "2026-09-24T15:55:00+00:00")},
                               [], "2026-09-24T16:00:00+00:00")
        self.assertEqual([(e["event"], e["model"], e["name"]) for e in events], [("restock", "96gb", "Fifth Avenue")])

        now = {"R1": store("available", "2026-09-24T16:00:00+00:00")}
        history.track(now, {"R1": store("ineligible", "2026-09-24T15:55:00+00:00")}, [], "2026-09-24T16:00:00+00:00")
        a = now["R1"]["availability"]["96gb"]
        self.assertEqual((a["in_since"], a["last_seen"], a["last_restock"]), ("2026-09-24T16:00:00+00:00",) * 3)

        later = {"R1": store("ineligible", "2026-09-24T16:40:00+00:00")}
        events = history.track(later, now, events, "2026-09-24T16:40:00+00:00")
        self.assertEqual(events[-1]["event"], "sold_out")
        self.assertEqual(events[-1]["lasted"], 40)
        a = later["R1"]["availability"]["96gb"]
        self.assertNotIn("in_since", a)
        self.assertEqual(a["last_seen"], "2026-09-24T16:00:00+00:00")  # remembered after selling out

    def test_first_sighting_and_unchecked_make_no_events(self):
        fresh = {"R1": store("available", "2026-09-24T16:00:00+00:00")}
        self.assertEqual(history.track(fresh, {}, [], "2026-09-24T16:00:00+00:00"), [])
        self.assertIn("in_since", fresh["R1"]["availability"]["96gb"])
        unknown = {"R1": {"id": "R1", "availability": {"96gb": {"status": "unknown", "variants": {}}}}}
        self.assertEqual(history.track(unknown, fresh, [], "2026-09-24T16:05:00+00:00"), [])
        self.assertEqual(unknown["R1"]["availability"]["96gb"]["in_since"], "2026-09-24T16:00:00+00:00")

    def test_prune_old_events(self):
        events = [{"t": "2026-09-01T00:00:00+00:00"}, {"t": "2026-09-24T00:00:00+00:00"}]
        self.assertEqual(history.prune(events, "2026-09-24T16:00:00+00:00"), events[1:])


if __name__ == "__main__":
    unittest.main()
