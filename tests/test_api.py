from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


API_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "gbfs_stations"
    / "api.py"
)
# The tests exercise the pure parsing and freshness layer only. Home Assistant
# provides aiohttp at runtime; a minimal import stub keeps this unit suite
# dependency-free.
sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))
SPEC = importlib.util.spec_from_file_location("gbfs_stations_api", API_PATH)
assert SPEC is not None and SPEC.loader is not None
api = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = api
SPEC.loader.exec_module(api)


def payload(timestamp: int | None, station_ids: tuple[str, ...] = ("station-a",)) -> dict:
    result = {
        "data": {
            "stations": [
                {
                    "station_id": station_id,
                    "num_bikes_available": 3,
                    "last_reported": timestamp,
                }
                for station_id in station_ids
            ]
        }
    }
    if timestamp is not None:
        result["last_updated"] = timestamp
    return result


class ApiFreshnessTests(unittest.TestCase):
    def test_missing_timestamp_is_not_fresh(self) -> None:
        with patch.object(api.time, "time", return_value=1_000):
            candidate = api.evaluate(
                api.FeedLocation("https://example.test/gbfs"),
                payload(None),
                required_stations=("station-a",),
                max_age=300,
            )
        self.assertTrue(candidate.complete)
        self.assertFalse(candidate.fresh)
        self.assertFalse(candidate.trustworthy)

    def test_timestamp_too_far_in_future_is_rejected(self) -> None:
        with patch.object(api.time, "time", return_value=1_000):
            candidate = api.evaluate(
                api.FeedLocation("https://example.test/gbfs"),
                payload(1_000 + api.CLOCK_TOLERANCE + 1),
                required_stations=("station-a",),
                max_age=300,
            )
        self.assertFalse(candidate.fresh)

    def test_small_clock_skew_is_accepted(self) -> None:
        with patch.object(api.time, "time", return_value=1_000):
            candidate = api.evaluate(
                api.FeedLocation("https://example.test/gbfs"),
                payload(1_000 + api.CLOCK_TOLERANCE),
                required_stations=("station-a",),
                max_age=300,
            )
        self.assertTrue(candidate.fresh)

    def test_missing_selected_station_makes_candidate_untrustworthy(self) -> None:
        with patch.object(api.time, "time", return_value=1_000):
            candidate = api.evaluate(
                api.FeedLocation("https://example.test/gbfs"),
                payload(1_000),
                required_stations=("station-a", "station-b"),
                max_age=300,
            )
        self.assertFalse(candidate.complete)
        self.assertFalse(candidate.trustworthy)

    def test_iso_timestamp_is_supported(self) -> None:
        self.assertEqual(
            api.parse_timestamp("2026-09-13T12:29:24Z"),
            1_789_302_564,
        )


if __name__ == "__main__":
    unittest.main()
