#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

GRAPHQL_ENDPOINT_CANDIDATES = (
    "/gtfs/v1",
    "/routers/default/index/graphql",
    "/otp/gtfs/v1",
    "/otp/routers/default/index/graphql",
)

REST_ENDPOINT_CANDIDATES = (
    "/routers/default/plan",
    "/otp/routers/default/plan",
)

HEALTH_ENDPOINT_CANDIDATES = (
    "/actuator/health",
    "/health",
    "/",
)

STOPS_QUERY = """
query SmokeStops {
  stops(name: "", first: 5) {
    gtfsId
    name
    lat
    lon
  }
}
"""

PLAN_QUERY = """
query SmokeCanonicalPlan(
  $fromLat: Float!
  $fromLon: Float!
  $toLat: Float!
  $toLon: Float!
  $date: String!
  $time: String!
  $searchWindow: Long!
  $numItineraries: Int!
  $maxWalkDistance: Float!
) {
  plan(
    from: { lat: $fromLat, lon: $fromLon }
    to: { lat: $toLat, lon: $toLon }
    date: $date
    time: $time
    arriveBy: false
    searchWindow: $searchWindow
    numItineraries: $numItineraries
    walkSpeed: 1.2
    walkReluctance: 2.4
    maxWalkDistance: $maxWalkDistance
    transportModes: [{ mode: WALK }, { mode: TRANSIT }]
  ) {
    itineraries {
      startTime
      endTime
      legs {
        mode
        transitLeg
        route {
          shortName
          longName
        }
        from {
          name
        }
        to {
          name
        }
      }
    }
  }
}
"""

BUS_MODE = "bus"
METRO_MODE = "metro"
TRAIN_MODE = "train"
REQUIRED_CORE_MODES = frozenset({BUS_MODE, METRO_MODE, TRAIN_MODE})


@dataclass(frozen=True)
class CanonicalRouteCase:
    label: str
    origin_name: str
    destination_name: str
    origin_lat: float
    origin_lon: float
    destination_lat: float
    destination_lon: float
    expected_mode: str
    max_walk_distance: int = 1200
    search_window_seconds: int = 3 * 60 * 60
    num_itineraries: int = 12


@dataclass(frozen=True)
class ObservedItinerary:
    modes: tuple[str, ...]
    lines: tuple[str, ...]
    from_name: str
    to_name: str


CANONICAL_ROUTE_CASES = (
    CanonicalRouteCase(
        label="Metro Bilbao: Moyua -> Kabiezes",
        origin_name="Moyua",
        destination_name="Kabiezes",
        origin_lat=43.26259,
        origin_lon=-2.93308,
        destination_lat=43.32238,
        destination_lon=-3.03777,
        expected_mode=METRO_MODE,
    ),
    CanonicalRouteCase(
        label="Cercanias Renfe: Abando -> Muskiz",
        origin_name="Bilbao-Intermodal Abando",
        destination_name="Muskiz",
        origin_lat=43.2601304,
        origin_lon=-2.9285592,
        destination_lat=43.3215111,
        destination_lon=-3.1123207,
        expected_mode=TRAIN_MODE,
        max_walk_distance=1000,
    ),
    CanonicalRouteCase(
        label="Bizkaibus: Puente Bizkaia -> Sarriena",
        origin_name="Bizkaia Zubia/Puente Bizkaia",
        destination_name="Sarriena (Irlandesas)",
        origin_lat=43.3239867296496,
        origin_lon=-3.01547359044326,
        destination_lat=43.3336570997499,
        destination_lon=-2.98265054113283,
        expected_mode=BUS_MODE,
        max_walk_distance=1000,
    ),
    CanonicalRouteCase(
        label="Bilbobus: Sarriko -> Atxuri",
        origin_name="Sarriko",
        destination_name="Atxuri",
        origin_lat=43.27465834860157,
        origin_lon=-2.95853584786794,
        destination_lat=43.2536275283666,
        destination_lon=-2.921382509474181,
        expected_mode=BUS_MODE,
        max_walk_distance=900,
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run OTP smoke tests against a locally started server.",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8080",
        help="Base URL of the OTP server.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=90,
        help="How long to wait for OTP to become healthy.",
    )
    return parser.parse_args()


def normalize_base_url(raw: str) -> str:
    value = raw.strip()
    return value[:-1] if value.endswith("/") else value


def http_get_json(url: str) -> tuple[int, object]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "otp-smoke-test/1.0"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        status = response.getcode()
        body = response.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        payload = body
    return status, payload


def http_post_json(url: str, payload: dict[str, object]) -> tuple[int, object]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "otp-smoke-test/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        status = response.getcode()
        response_body = response.read().decode("utf-8", errors="replace")
    return status, json.loads(response_body)


def wait_for_health(base_url: str, timeout_seconds: int) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        for path in HEALTH_ENDPOINT_CANDIDATES:
            try:
                status, _payload = http_get_json(f"{base_url}{path}")
                if 200 <= status < 300:
                    print(f"[health] OTP healthy on {path}")
                    return path
            except Exception as error:  # noqa: BLE001
                last_error = error
        time.sleep(3)
    raise RuntimeError(f"OTP did not become healthy in time: {last_error}")


def resolve_graphql_endpoint(base_url: str) -> tuple[str, dict[str, object]]:
    payload = {"query": STOPS_QUERY}
    last_error: Exception | None = None
    for path in GRAPHQL_ENDPOINT_CANDIDATES:
        try:
            status, response_payload = http_post_json(f"{base_url}{path}", payload)
            if status < 200 or status >= 300:
                raise RuntimeError(f"unexpected status {status}")
            if not isinstance(response_payload, dict):
                raise RuntimeError("GraphQL response was not JSON")
            if response_payload.get("errors"):
                raise RuntimeError(str(response_payload["errors"]))
            print(f"[graphql] using endpoint {path}")
            return path, response_payload
        except Exception as error:  # noqa: BLE001
            last_error = error
    raise RuntimeError(f"Could not reach any GraphQL endpoint: {last_error}")


def extract_reference_stop(payload: dict[str, object]) -> tuple[float, float, str]:
    stops = (
        ((payload.get("data") or {}).get("stops"))
        if isinstance(payload.get("data"), dict)
        else None
    )
    if not isinstance(stops, list) or not stops:
        raise RuntimeError("GraphQL stop query returned no stops")

    for stop in stops:
        if not isinstance(stop, dict):
            continue
        lat = stop.get("lat")
        lon = stop.get("lon")
        name = str(stop.get("name") or stop.get("gtfsId") or "unknown stop")
        if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            print(f"[graphql] found stop {name} at {lat:.5f},{lon:.5f}")
            return float(lat), float(lon), name

    raise RuntimeError("GraphQL stop query returned no usable coordinates")


def resolve_rest_endpoint(base_url: str, lat: float, lon: float) -> str:
    service_time = dt.datetime.now().replace(second=0, microsecond=0)
    from_lat = lat + 0.0012
    from_lon = lon + 0.0012
    params = {
        "fromPlace": f"{from_lat:.6f},{from_lon:.6f}",
        "toPlace": f"{lat:.6f},{lon:.6f}",
        "time": service_time.strftime("%H:%M:%S"),
        "date": service_time.strftime("%Y-%m-%d"),
        "mode": "WALK",
        "arriveBy": "false",
        "numItineraries": "1",
        "maxWalkDistance": "2000",
        "locale": "es",
    }

    query = urllib.parse.urlencode(params)
    last_error: Exception | None = None
    for path in REST_ENDPOINT_CANDIDATES:
        request_url = f"{base_url}{path}?{query}"
        try:
            status, payload = http_get_json(request_url)
            if status < 200 or status >= 300:
                raise RuntimeError(f"unexpected status {status}")
            if not isinstance(payload, dict):
                raise RuntimeError("REST plan response was not JSON")
            plan = payload.get("plan")
            itineraries = plan.get("itineraries") if isinstance(plan, dict) else None
            if not isinstance(itineraries, list) or not itineraries:
                raise RuntimeError("REST plan query returned no itineraries")
            print(f"[rest] using endpoint {path}")
            return path
        except Exception as error:  # noqa: BLE001
            last_error = error
    raise RuntimeError(f"Could not resolve a REST plan endpoint: {last_error}")


def candidate_service_datetimes(now: dt.datetime) -> list[dt.datetime]:
    weekday_dates: list[dt.date] = []
    weekend_dates: list[dt.date] = []
    for offset in range(0, 14):
        candidate = (now + dt.timedelta(days=offset)).date()
        if candidate.weekday() < 5:
            if candidate not in weekday_dates:
                weekday_dates.append(candidate)
        elif candidate not in weekend_dates:
            weekend_dates.append(candidate)
        if len(weekday_dates) >= 5 and len(weekend_dates) >= 2:
            break

    slots_by_kind = {
        "weekday": ((8, 30), (12, 30), (18, 30)),
        "weekend": ((12, 30), (18, 30)),
    }

    ordered_dates = [*weekday_dates, *weekend_dates[:2]]
    candidates: list[dt.datetime] = []
    for candidate_date in ordered_dates:
        slot_kind = "weekday" if candidate_date.weekday() < 5 else "weekend"
        for hour, minute in slots_by_kind[slot_kind]:
            candidates.append(
                dt.datetime(
                    candidate_date.year,
                    candidate_date.month,
                    candidate_date.day,
                    hour,
                    minute,
                )
            )
    return candidates


def build_plan_variables(
    route_case: CanonicalRouteCase,
    service_time: dt.datetime,
) -> dict[str, object]:
    return {
        "fromLat": route_case.origin_lat,
        "fromLon": route_case.origin_lon,
        "toLat": route_case.destination_lat,
        "toLon": route_case.destination_lon,
        "date": service_time.strftime("%Y-%m-%d"),
        "time": service_time.strftime("%H:%M:%S"),
        "searchWindow": route_case.search_window_seconds,
        "numItineraries": route_case.num_itineraries,
        "maxWalkDistance": float(route_case.max_walk_distance),
    }


def query_graphql_plan(
    base_url: str,
    graphql_path: str,
    route_case: CanonicalRouteCase,
    service_time: dt.datetime,
) -> list[ObservedItinerary]:
    status, payload = http_post_json(
        f"{base_url}{graphql_path}",
        {
            "operationName": "SmokeCanonicalPlan",
            "query": PLAN_QUERY,
            "variables": build_plan_variables(route_case, service_time),
        },
    )
    if status < 200 or status >= 300:
        raise RuntimeError(f"GraphQL plan returned status {status}")
    if not isinstance(payload, dict):
        raise RuntimeError("GraphQL plan response was not JSON")
    if payload.get("errors"):
        raise RuntimeError(str(payload["errors"]))

    itineraries = (
        ((payload.get("data") or {}).get("plan") or {}).get("itineraries")
        if isinstance(payload.get("data"), dict)
        else None
    )
    if not isinstance(itineraries, list):
        return []
    return [
        observation
        for item in itineraries
        if (observation := observed_itinerary_from_graphql(item)) is not None
    ]


def query_rest_plan(
    base_url: str,
    rest_path: str,
    route_case: CanonicalRouteCase,
    service_time: dt.datetime,
) -> list[ObservedItinerary]:
    params = {
        "fromPlace": f"{route_case.origin_lat:.6f},{route_case.origin_lon:.6f}",
        "toPlace": f"{route_case.destination_lat:.6f},{route_case.destination_lon:.6f}",
        "time": service_time.strftime("%H:%M:%S"),
        "date": service_time.strftime("%Y-%m-%d"),
        "mode": "TRANSIT,WALK",
        "arriveBy": "false",
        "numItineraries": str(route_case.num_itineraries),
        "searchWindow": str(route_case.search_window_seconds),
        "maxWalkDistance": str(route_case.max_walk_distance),
        "locale": "es",
    }
    request_url = f"{base_url}{rest_path}?{urllib.parse.urlencode(params)}"
    status, payload = http_get_json(request_url)
    if status < 200 or status >= 300:
        raise RuntimeError(f"REST plan returned status {status}")
    if not isinstance(payload, dict):
        raise RuntimeError("REST plan response was not JSON")

    error_payload = payload.get("error")
    if isinstance(error_payload, dict):
        raise RuntimeError(str(error_payload.get("msg") or error_payload))

    plan = payload.get("plan")
    itineraries = plan.get("itineraries") if isinstance(plan, dict) else None
    if not isinstance(itineraries, list):
        return []
    return [
        observation
        for item in itineraries
        if (observation := observed_itinerary_from_rest(item)) is not None
    ]


def observed_itinerary_from_graphql(value: object) -> ObservedItinerary | None:
    if not isinstance(value, dict):
        return None
    legs = value.get("legs")
    if not isinstance(legs, list) or not legs:
        return None

    normalized_modes: list[str] = []
    lines: list[str] = []
    first_from_name = ""
    last_to_name = ""
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        mode = normalize_mode_name(str(leg.get("mode") or ""))
        if mode:
            normalized_modes.append(mode)
        route = leg.get("route")
        short_name = ""
        long_name = ""
        if isinstance(route, dict):
            short_name = str(route.get("shortName") or "").strip()
            long_name = str(route.get("longName") or "").strip()
        if short_name:
            lines.append(short_name)
        elif long_name:
            lines.append(long_name)
        from_name = ((leg.get("from") or {}).get("name") if isinstance(leg.get("from"), dict) else "") or ""
        to_name = ((leg.get("to") or {}).get("name") if isinstance(leg.get("to"), dict) else "") or ""
        if not first_from_name and isinstance(from_name, str):
            first_from_name = from_name.strip()
        if isinstance(to_name, str) and to_name.strip():
            last_to_name = to_name.strip()

    if not normalized_modes:
        return None
    return ObservedItinerary(
        modes=tuple(deduplicate_preserving_order(normalized_modes)),
        lines=tuple(deduplicate_preserving_order(lines)),
        from_name=first_from_name,
        to_name=last_to_name,
    )


def observed_itinerary_from_rest(value: object) -> ObservedItinerary | None:
    if not isinstance(value, dict):
        return None
    legs = value.get("legs")
    if not isinstance(legs, list) or not legs:
        return None

    normalized_modes: list[str] = []
    lines: list[str] = []
    first_from_name = ""
    last_to_name = ""
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        mode = normalize_mode_name(str(leg.get("mode") or ""))
        if mode:
            normalized_modes.append(mode)
        short_name = str(leg.get("routeShortName") or "").strip()
        long_name = str(leg.get("routeLongName") or "").strip()
        route_name = str(leg.get("route") or "").strip()
        if short_name:
            lines.append(short_name)
        elif long_name:
            lines.append(long_name)
        elif route_name:
            lines.append(route_name)
        from_name = ((leg.get("from") or {}).get("name") if isinstance(leg.get("from"), dict) else "") or ""
        to_name = ((leg.get("to") or {}).get("name") if isinstance(leg.get("to"), dict) else "") or ""
        if not first_from_name and isinstance(from_name, str):
            first_from_name = from_name.strip()
        if isinstance(to_name, str) and to_name.strip():
            last_to_name = to_name.strip()

    if not normalized_modes:
        return None
    return ObservedItinerary(
        modes=tuple(deduplicate_preserving_order(normalized_modes)),
        lines=tuple(deduplicate_preserving_order(lines)),
        from_name=first_from_name,
        to_name=last_to_name,
    )


def normalize_mode_name(raw_mode: str) -> str:
    normalized = raw_mode.strip().upper().replace("-", "_").replace(" ", "_")
    if not normalized:
        return "unknown"
    if any(token in normalized for token in ("BUS", "COACH", "TROLLEYBUS")):
        return BUS_MODE
    if any(
        token in normalized
        for token in (
            "SUBWAY",
            "METRO",
            "TRAM",
            "FUNICULAR",
            "MONORAIL",
            "LIGHT_RAIL",
            "CABLE_CAR",
            "GONDOLA",
        )
    ):
        return METRO_MODE
    if any(token in normalized for token in ("RAIL", "TRAIN", "SUBURBAN", "COMMUTER")):
        return TRAIN_MODE
    if any(token in normalized for token in ("WALK", "FOOT", "PEDESTRIAN")):
        return "walk"
    return normalized.lower()


def deduplicate_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def summarize_observations(observations: list[ObservedItinerary]) -> str:
    if not observations:
        return "sin itinerarios"

    parts: list[str] = []
    for observation in observations[:3]:
        modes = "+".join(observation.modes) or "unknown"
        lines = ",".join(observation.lines) or "sin-linea"
        from_name = observation.from_name or "origen"
        to_name = observation.to_name or "destino"
        parts.append(f"{from_name}->{to_name} [{modes}] ({lines})")
    return "; ".join(parts)


def run_canonical_route_case(
    base_url: str,
    graphql_path: str,
    rest_path: str,
    route_case: CanonicalRouteCase,
) -> str:
    last_failure_summary = "sin intentos"
    last_error: Exception | None = None

    for service_time in candidate_service_datetimes(dt.datetime.now()):
        try:
            graphql_observations = query_graphql_plan(
                base_url,
                graphql_path,
                route_case,
                service_time,
            )
            if any(route_case.expected_mode in observation.modes for observation in graphql_observations):
                print(
                    f"[canonical] {route_case.label} OK via GraphQL en "
                    f"{service_time:%Y-%m-%d %H:%M} -> "
                    f"{summarize_observations(graphql_observations)}"
                )
                return "graphql"
            if graphql_observations:
                last_failure_summary = summarize_observations(graphql_observations)
        except Exception as error:  # noqa: BLE001
            last_error = error

        try:
            rest_observations = query_rest_plan(
                base_url,
                rest_path,
                route_case,
                service_time,
            )
            if any(route_case.expected_mode in observation.modes for observation in rest_observations):
                print(
                    f"[canonical] {route_case.label} OK via REST en "
                    f"{service_time:%Y-%m-%d %H:%M} -> "
                    f"{summarize_observations(rest_observations)}"
                )
                return "rest"
            if rest_observations:
                last_failure_summary = summarize_observations(rest_observations)
        except Exception as error:  # noqa: BLE001
            last_error = error

    raise RuntimeError(
        f"{route_case.label} no mostro cobertura {route_case.expected_mode}. "
        f"Ultimo resumen: {last_failure_summary}. Ultimo error: {last_error}"
    )


def smoke_test_canonical_routes(
    base_url: str,
    graphql_path: str,
    rest_path: str,
) -> None:
    covered_modes: set[str] = set()
    covered_sources: list[str] = []

    for route_case in CANONICAL_ROUTE_CASES:
        source = run_canonical_route_case(base_url, graphql_path, rest_path, route_case)
        covered_sources.append(f"{route_case.label} [{source}]")
        covered_modes.add(route_case.expected_mode)

    missing_modes = REQUIRED_CORE_MODES.difference(covered_modes)
    if missing_modes:
        raise RuntimeError(f"Missing canonical coverage for modes: {sorted(missing_modes)}")

    print(
        "[canonical] cobertura verificada para "
        f"{', '.join(sorted(REQUIRED_CORE_MODES))}: "
        f"{'; '.join(covered_sources)}"
    )


def main() -> int:
    args = parse_args()
    base_url = normalize_base_url(args.base_url)
    wait_for_health(base_url, args.timeout_seconds)
    graphql_path, stops_payload = resolve_graphql_endpoint(base_url)
    lat, lon, stop_name = extract_reference_stop(stops_payload)
    rest_path = resolve_rest_endpoint(base_url, lat, lon)
    print(f"[baseline] REST walking probe succeeded using stop {stop_name}")
    smoke_test_canonical_routes(base_url, graphql_path, rest_path)
    print("[success] OTP canonical smoke tests passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.URLError as error:
        print(f"[error] network failure: {error}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as error:  # noqa: BLE001
        print(f"[error] {error}", file=sys.stderr)
        raise SystemExit(1)
