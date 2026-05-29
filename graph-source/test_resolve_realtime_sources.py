#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest


SCRIPT_PATH = pathlib.Path(__file__).with_name("resolve_realtime_sources.py")
SPEC = importlib.util.spec_from_file_location("resolve_realtime_sources", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ResolveRealtimeSourcesTest(unittest.TestCase):
    def test_build_realtime_updaters_maps_moveuskadi_entries_to_otp_types(self) -> None:
        index = {
            "last-update": "2026-05-29 09:46:39",
            "data": {
                "BizkaiBus": [
                    {
                        "format": "GTFS-RT",
                        "name": "gtfsrt_Bizkaibus_alerts.pb",
                        "url": "https://example.test/bizkaibus/alerts.pb",
                        "last-update": "2026-05-29 09:46:37",
                    },
                    {
                        "format": "GTFS-RT",
                        "name": "gtfsrt_bizkaibus_trip_updates.pb",
                        "url": "https://example.test/bizkaibus/trip_updates.pb",
                        "last-update": "2026-05-29 09:46:36",
                    },
                    {
                        "format": "GTFS-RT",
                        "name": "gtfsrt_Bizkaibus_vehicle_positions.pb",
                        "url": "https://example.test/bizkaibus/vehicle_positions.pb",
                        "last-update": "2026-05-29 09:46:38",
                    },
                ]
            },
        }

        updaters, metadata = MODULE.build_realtime_updaters(
            index,
            [
                MODULE.RealtimeFeedDefinition(
                    feed_id="bizkaibus",
                    operator="BizkaiBus",
                )
            ],
        )

        self.assertEqual(
            [updater["type"] for updater in updaters],
            ["real-time-alerts", "stop-time-updater", "vehicle-positions"],
        )
        self.assertTrue(all(updater["feedId"] == "bizkaibus" for updater in updaters))
        self.assertEqual([item["kind"] for item in metadata], [
            "alerts",
            "trip_updates",
            "vehicle_positions",
        ])

    def test_update_router_config_preserves_gbfs_and_replaces_old_realtime(self) -> None:
        router_config = {
            "updaters": [
                {"type": "vehicle-rental", "network": "bizkaibizi"},
                {
                    "type": "stop-time-updater",
                    "url": "https://stale.example.test/trip_updates.pb",
                    "feedId": "bizkaibus",
                },
            ],
            "routingDefaults": {"numItineraries": 12},
        }
        realtime_updaters = [
            {
                "type": "stop-time-updater",
                "url": "https://fresh.example.test/trip_updates.pb",
                "feedId": "bizkaibus",
            }
        ]

        updated = MODULE.update_router_config(router_config, realtime_updaters)

        self.assertEqual(updated["routingDefaults"], {"numItineraries": 12})
        self.assertEqual(len(updated["updaters"]), 2)
        self.assertEqual(updated["updaters"][0]["type"], "vehicle-rental")
        self.assertEqual(
            updated["updaters"][1]["url"],
            "https://fresh.example.test/trip_updates.pb",
        )


if __name__ == "__main__":
    unittest.main()
