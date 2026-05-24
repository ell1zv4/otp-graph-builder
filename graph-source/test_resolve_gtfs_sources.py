#!/usr/bin/env python3

from __future__ import annotations

import io
import importlib.util
import pathlib
import sys
import unittest
import urllib.error
from unittest import mock


SCRIPT_PATH = pathlib.Path(__file__).with_name("resolve_gtfs_sources.py")
SPEC = importlib.util.spec_from_file_location("resolve_gtfs_sources", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ResolveGtfsSourcesTest(unittest.TestCase):
    def test_select_best_candidate_prefers_newest_update_then_detail_id(self) -> None:
        candidates = [
            {
                "title": "Bizkaibus",
                "detail_id": "1061",
                "updated": "15/05/2026",
                "detail_url": "https://nap.transportes.gob.es/Files/Detail/1061",
            },
            {
                "title": "Bizkaibus",
                "detail_id": "2061",
                "updated": "15/05/2026",
                "detail_url": "https://nap.transportes.gob.es/Files/Detail/2061",
            },
            {
                "title": "Bizkaibus",
                "detail_id": "3050",
                "updated": "20/05/2026",
                "detail_url": "https://nap.transportes.gob.es/Files/Detail/3050",
            },
        ]

        selected = MODULE.select_best_candidate(candidates)

        self.assertEqual(selected["detail_id"], "3050")

    def test_extract_resource_id_ignores_gtfs_rt_blocks(self) -> None:
        detail_html = """
        <div class="card-header text-left container-Blue card-title ">
          GTFS-RT
          <button type="button" data-target="#modal-metadatos-9999"></button>
        </div>
        <div class="card-header text-left container-Blue card-title ">
          GTFS-ZIP
          <button type="button" data-target="#modal-metadatos-1262"></button>
        </div>
        """

        resource_id = MODULE.extract_resource_id(
            detail_html,
            "https://nap.transportes.gob.es/Files/Detail/1061",
        )

        self.assertEqual(resource_id, "1262")

    def test_fetch_bytes_retries_retryable_http_errors(self) -> None:
        request = MODULE.urllib.request.Request("https://example.com/feed")
        attempts: list[int] = []

        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def read(self) -> bytes:
                return b"ok"

        def fake_urlopen(*args, **kwargs):
            attempts.append(len(attempts) + 1)
            if len(attempts) < 3:
                raise urllib.error.HTTPError(
                    request.full_url,
                    500,
                    "Internal Server Error",
                    hdrs=None,
                    fp=io.BytesIO(b""),
                )
            return FakeResponse()

        with (
            mock.patch.object(MODULE.urllib.request, "urlopen", side_effect=fake_urlopen),
            mock.patch.object(MODULE.time, "sleep"),
        ):
            payload = MODULE.fetch_bytes(request, timeout=5, attempts=3)

        self.assertEqual(payload, b"ok")
        self.assertEqual(len(attempts), 3)

    def test_fetch_bytes_does_not_retry_non_retryable_http_errors(self) -> None:
        request = MODULE.urllib.request.Request("https://example.com/feed")

        with (
            mock.patch.object(
                MODULE.urllib.request,
                "urlopen",
                side_effect=urllib.error.HTTPError(
                    request.full_url,
                    404,
                    "Not Found",
                    hdrs=None,
                    fp=io.BytesIO(b""),
                ),
            ),
            mock.patch.object(MODULE.time, "sleep") as sleep_mock,
        ):
            with self.assertRaises(urllib.error.HTTPError):
                MODULE.fetch_bytes(request, timeout=5, attempts=3)

        sleep_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
