#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

USER_AGENT = "otp-graph-builder/1.0"
MOVEUSKADI_GTFS_RT_INDEX_URL = (
    "https://opendata.euskadi.eus/transport/moveuskadi/data-index-gtfs-rt.json"
)
RETRYABLE_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}
MAX_FETCH_ATTEMPTS = 4

REALTIME_UPDATER_TYPES = {
    "real-time-alerts",
    "stop-time-updater",
    "vehicle-positions",
}


@dataclass(frozen=True)
class RealtimeFeedDefinition:
    feed_id: str
    operator: str


REALTIME_FEEDS: tuple[RealtimeFeedDefinition, ...] = (
    RealtimeFeedDefinition(feed_id="bilbobus", operator="BilboBus"),
    RealtimeFeedDefinition(feed_id="bizkaibus", operator="BizkaiBus"),
    RealtimeFeedDefinition(feed_id="metro_bilbao", operator="Metro Bilbao"),
)

FALLBACK_MOVEUSKADI_INDEX: dict[str, object] = {
    "last-update": "fallback",
    "data": {
        "BilboBus": [
            {
                "format": "GTFS-RT",
                "url": "https://opendata.euskadi.eus/transport/moveuskadi/bilbobus/gtfsrt_bilbobus_vehicle_positions.pb",
                "name": "gtfsrt_bilbobus_vehicle_positions.pb",
                "last-update": "fallback",
            }
        ],
        "BizkaiBus": [
            {
                "format": "GTFS-RT",
                "url": "https://opendata.euskadi.eus/transport/moveuskadi/bizkaibus/gtfsrt_Bizkaibus_vehicle_positions.pb",
                "name": "gtfsrt_Bizkaibus_vehicle_positions.pb",
                "last-update": "fallback",
            },
            {
                "format": "GTFS-RT",
                "url": "https://opendata.euskadi.eus/transport/moveuskadi/bizkaibus/gtfsrt_bizkaibus_trip_updates.pb",
                "name": "gtfsrt_bizkaibus_trip_updates.pb",
                "last-update": "fallback",
            },
            {
                "format": "GTFS-RT",
                "url": "https://opendata.euskadi.eus/transport/moveuskadi/bizkaibus/gtfsrt_Bizkaibus_alerts.pb",
                "name": "gtfsrt_Bizkaibus_alerts.pb",
                "last-update": "fallback",
            },
        ],
        "Metro Bilbao": [
            {
                "format": "GTFS-RT",
                "url": "https://opendata.euskadi.eus/transport/moveuskadi/metro_bilbao/gtfsrt_metro_bilbao_trip_updates.pb",
                "name": "gtfsrt_metro_bilbao_trip_updates.pb",
                "last-update": "fallback",
            },
            {
                "format": "GTFS-RT",
                "url": "https://opendata.euskadi.eus/transport/moveuskadi/metro_bilbao/gtfsrt_metro_bilbao_vehicle_positions.pb",
                "name": "gtfsrt_metro_bilbao_vehicle_positions.pb",
                "last-update": "fallback",
            },
        ],
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve Moveuskadi GTFS-RT feeds and inject OTP realtime updaters "
            "into router-config.json."
        )
    )
    parser.add_argument(
        "--index-url",
        default=MOVEUSKADI_GTFS_RT_INDEX_URL,
        help="Moveuskadi GTFS-RT index URL.",
    )
    parser.add_argument(
        "--router-config",
        default="graph-source/router-config.json",
        help="router-config.json path to update.",
    )
    parser.add_argument(
        "--metadata-path",
        default=None,
        help="Optional JSON metadata path for resolved realtime feeds.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve feeds and print metadata without writing router-config.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail instead of using the checked-in fallback if the index cannot be fetched.",
    )
    return parser.parse_args()


def is_retryable_error(error: Exception) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        return error.code in RETRYABLE_HTTP_STATUSES
    return isinstance(error, urllib.error.URLError)


def fetch_bytes(
    request: urllib.request.Request,
    *,
    timeout: int,
    attempts: int = MAX_FETCH_ATTEMPTS,
) -> bytes:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (urllib.error.HTTPError, urllib.error.URLError) as error:
            last_error = error
            if attempt >= attempts or not is_retryable_error(error):
                raise
            delay_seconds = min(2 ** (attempt - 1), 8)
            print(
                f"[retry] {request.full_url} -> {error} "
                f"(attempt {attempt}/{attempts}, waiting {delay_seconds}s)",
                file=sys.stderr,
            )
            time.sleep(delay_seconds)
    assert last_error is not None
    raise last_error


def fetch_json(url: str) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    payload = fetch_bytes(request, timeout=45).decode("utf-8", errors="replace")
    decoded = json.loads(payload)
    if not isinstance(decoded, dict):
        raise ValueError(f"{url} did not return a JSON object")
    return decoded


def load_moveuskadi_index(index_url: str, *, strict: bool) -> tuple[dict[str, object], bool]:
    try:
        return fetch_json(index_url), False
    except Exception as error:
        if strict:
            raise
        print(
            f"[warn] Could not fetch Moveuskadi realtime index: {error}. "
            "Using checked-in fallback URLs.",
            file=sys.stderr,
        )
        return FALLBACK_MOVEUSKADI_INDEX, True


def realtime_kind(entry: dict[str, object]) -> str | None:
    name = str(entry.get("name", "")).lower()
    url = str(entry.get("url", "")).lower()
    candidate = f"{name} {url}"
    if "alerts" in candidate:
        return "alerts"
    if "trip_updates" in candidate or "trip-updates" in candidate:
        return "trip_updates"
    if "vehicle_positions" in candidate or "vehicle-positions" in candidate:
        return "vehicle_positions"
    return None


def select_entries_for_operator(
    index: dict[str, object],
    operator: str,
) -> list[dict[str, object]]:
    data = index.get("data")
    if not isinstance(data, dict):
        return []
    entries = data.get(operator)
    if entries is None:
        normalized_operator = operator.strip().casefold()
        for candidate_operator, candidate_entries in data.items():
            if str(candidate_operator).strip().casefold() == normalized_operator:
                entries = candidate_entries
                break
    if not isinstance(entries, list):
        return []

    selected_by_kind: dict[str, dict[str, object]] = {}
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue
        if str(raw_entry.get("format", "")).upper() != "GTFS-RT":
            continue
        kind = realtime_kind(raw_entry)
        if kind is None:
            continue
        selected_by_kind.setdefault(kind, raw_entry)

    order = {"alerts": 0, "trip_updates": 1, "vehicle_positions": 2}
    return sorted(
        selected_by_kind.values(),
        key=lambda entry: order.get(realtime_kind(entry) or "", 99),
    )


def updater_for_entry(
    *,
    feed_id: str,
    entry: dict[str, object],
) -> dict[str, object] | None:
    kind = realtime_kind(entry)
    url = str(entry.get("url", "")).strip()
    if not url:
        return None

    if kind == "alerts":
        return {
            "type": "real-time-alerts",
            "frequency": "1m",
            "url": url,
            "feedId": feed_id,
            "fuzzyTripMatching": True,
        }
    if kind == "trip_updates":
        return {
            "type": "stop-time-updater",
            "frequency": "1m",
            "backwardsDelayPropagationType": "REQUIRED_NO_DATA",
            "url": url,
            "feedId": feed_id,
            "fuzzyTripMatching": True,
        }
    if kind == "vehicle_positions":
        return {
            "type": "vehicle-positions",
            "frequency": "1m",
            "url": url,
            "feedId": feed_id,
            "fuzzyTripMatching": True,
            "features": ["position", "stop-position"],
        }
    return None


def build_realtime_updaters(
    index: dict[str, object],
    feed_definitions: Iterable[RealtimeFeedDefinition] = REALTIME_FEEDS,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    updaters: list[dict[str, object]] = []
    metadata: list[dict[str, object]] = []

    for feed in feed_definitions:
        entries = select_entries_for_operator(index, feed.operator)
        for entry in entries:
            updater = updater_for_entry(feed_id=feed.feed_id, entry=entry)
            if updater is None:
                continue
            updaters.append(updater)
            metadata.append(
                {
                    "feedId": feed.feed_id,
                    "operator": feed.operator,
                    "kind": realtime_kind(entry),
                    "name": entry.get("name", ""),
                    "url": entry.get("url", ""),
                    "lastUpdate": entry.get("last-update", ""),
                }
            )

    return updaters, metadata


def remove_generated_realtime_updaters(
    updaters: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    preserved: list[dict[str, object]] = []
    for updater in updaters:
        updater_type = str(updater.get("type", ""))
        if updater_type in REALTIME_UPDATER_TYPES:
            continue
        preserved.append(updater)
    return preserved


def update_router_config(
    router_config: dict[str, object],
    realtime_updaters: list[dict[str, object]],
) -> dict[str, object]:
    existing = router_config.get("updaters")
    existing_updaters = existing if isinstance(existing, list) else []
    preserved = remove_generated_realtime_updaters(
        updater for updater in existing_updaters if isinstance(updater, dict)
    )
    return {
        **router_config,
        "updaters": [*preserved, *realtime_updaters],
    }


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    index, used_fallback = load_moveuskadi_index(args.index_url, strict=args.strict)
    realtime_updaters, resolved_feeds = build_realtime_updaters(index)
    if not realtime_updaters:
        print("No Moveuskadi GTFS-RT feeds matched the configured OTP feeds.", file=sys.stderr)
        return 1

    metadata: dict[str, object] = {
        "source": args.index_url,
        "sourceLastUpdate": index.get("last-update", ""),
        "usedFallback": used_fallback,
        "resolvedFeeds": resolved_feeds,
    }

    if args.dry_run:
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
        return 0

    router_config_path = Path(args.router_config)
    router_config = json.loads(router_config_path.read_text(encoding="utf-8"))
    updated_config = update_router_config(router_config, realtime_updaters)
    write_json(router_config_path, updated_config)

    if args.metadata_path:
        write_json(Path(args.metadata_path), metadata)

    print(
        f"Configured {len(realtime_updaters)} Moveuskadi GTFS-RT updaters "
        f"for {len({item['feedId'] for item in resolved_feeds})} OTP feeds."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
