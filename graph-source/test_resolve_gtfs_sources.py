#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest


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


if __name__ == "__main__":
    unittest.main()
