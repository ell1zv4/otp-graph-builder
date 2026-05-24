#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest
from unittest import mock


SCRIPT_PATH = pathlib.Path(__file__).with_name("smoke_test_otp.py")
SPEC = importlib.util.spec_from_file_location("smoke_test_otp", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SmokeTestOtpTest(unittest.TestCase):
    def test_resolve_graphql_endpoint_falls_back_to_next_probe_query(self) -> None:
        observed_payloads: list[dict[str, object]] = []
        responses = iter(
            [
                (
                    200,
                    {
                        "errors": [
                            {
                                "message": "Validation error (UnknownArgument@[stops])",
                            }
                        ]
                    },
                ),
                (
                    200,
                    {
                        "data": {
                            "stops": [
                                {
                                    "gtfsId": "STOP:MOYUA",
                                    "name": "Moyua",
                                    "lat": 43.2630,
                                    "lon": -2.9350,
                                }
                            ]
                        }
                    },
                ),
            ]
        )

        def fake_http_post_json(
            _url: str, payload: dict[str, object]
        ) -> tuple[int, object]:
            observed_payloads.append(payload)
            return next(responses)

        with mock.patch.object(MODULE, "http_post_json", side_effect=fake_http_post_json):
            path, response = MODULE.resolve_graphql_endpoint("http://otp.test")

        self.assertEqual(path, "/gtfs/v1")
        self.assertEqual(len(observed_payloads), 2)
        self.assertEqual(observed_payloads[0]["variables"], {"name": "Moyua"})
        self.assertEqual(observed_payloads[1]["variables"], {"name": "Bilbao"})
        self.assertEqual(response["data"]["stops"][0]["name"], "Moyua")

    def test_resolve_rest_endpoint_returns_none_when_legacy_rest_is_unavailable(self) -> None:
        with mock.patch.object(
            MODULE,
            "http_get_json",
            side_effect=RuntimeError("unexpected status 404"),
        ):
            path = MODULE.resolve_rest_endpoint("http://otp.test", 43.2630, -2.9350)

        self.assertIsNone(path)


if __name__ == "__main__":
    unittest.main()
