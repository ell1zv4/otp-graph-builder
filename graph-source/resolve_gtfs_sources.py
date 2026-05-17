#!/usr/bin/env python3

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

USER_AGENT = "otp-graph-builder/1.0"
NAP_BASE_URL = "https://nap.transportes.gob.es"
NAP_LIST_URL = f"{NAP_BASE_URL}/Files/List"
NAP_DOWNLOAD_URL = f"{NAP_BASE_URL}/api/Fichero/download"

LIST_CARD_RE = re.compile(
    r'<a class="item-listado card mb-3" href="\./Detail/(?P<detail_id>\d+)">'
    r"(?P<body>.*?)"
    r"</a>",
    re.IGNORECASE | re.DOTALL,
)
TITLE_RE = re.compile(
    r'<h3 class="card-title hidden-title ">\s*(?P<title>[^<]+?)\s*</h3>',
    re.IGNORECASE | re.DOTALL,
)
UPDATED_RE = re.compile(
    r"Actualizado el (?P<updated>\d{1,2}/\d{1,2}/\d{4})",
    re.IGNORECASE,
)
RESOURCE_ID_RE = re.compile(
    r'<div class="card-header text-left container-Blue card-title ">\s*'
    r"GTFS(?:-ZIP)?"
    r"[\s\S]{0,2000}?"
    r"modal-metadatos-(?P<resource_id>\d+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FeedDefinition:
    name: str
    query: str
    output_name: str
    title_tokens: tuple[str, ...]
    filters: tuple[tuple[str, str], ...]


FEEDS: tuple[FeedDefinition, ...] = (
    FeedDefinition(
        name="Bilbobus",
        query="Bilbobus",
        output_name="bilbobus.zip",
        title_tokens=("bilbobus",),
        filters=(("filterTT", "1"), ("filterR", "48"), ("filterTF", "Fichero-1")),
    ),
    FeedDefinition(
        name="Bizkaibus",
        query="Bizkaibus",
        output_name="bizkaibus.zip",
        title_tokens=("bizkaibus",),
        filters=(("filterTT", "1"), ("filterR", "48"), ("filterTF", "Fichero-1")),
    ),
    FeedDefinition(
        name="Metro Bilbao",
        query="Metro Bilbao",
        output_name="metro_bilbao.zip",
        title_tokens=("metro", "bilbao"),
        filters=(("filterTT", "2"), ("filterR", "48"), ("filterTF", "Fichero-1")),
    ),
    FeedDefinition(
        name="Cercanias Renfe",
        query="Cercanias Renfe",
        output_name="renfe_cercanias.zip",
        title_tokens=("cercanias", "renfe"),
        filters=(("filterTT", "2"), ("filterR", "48"), ("filterTF", "Fichero-1")),
    ),
    FeedDefinition(
        name="Funicular de Artxanda",
        query="Artxanda",
        output_name="funicular_artxanda.zip",
        title_tokens=("funicular", "artxanda"),
        filters=(("filterTT", "2"), ("filterR", "48"), ("filterTF", "Fichero-1")),
    ),
    FeedDefinition(
        name="ALSA autobuses",
        query="ALSA",
        output_name="alsa_autobuses.zip",
        title_tokens=("alsa", "autobuses"),
        filters=(("filterTT", "1"), ("filterR", "48"), ("filterTF", "Fichero-1")),
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resolve the latest NAP GTFS resources for the OTP graph build."
    )
    parser.add_argument(
        "--output-dir",
        default="graph-source",
        help="Directory where GTFS ZIPs will be written.",
    )
    parser.add_argument(
        "--metadata-path",
        default=None,
        help="Optional JSON file to write the resolved source metadata to.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve metadata without downloading ZIP files.",
    )
    return parser.parse_args()


def normalize_text(value: str) -> str:
    decoded = html.unescape(value)
    normalized = unicodedata.normalize("NFKD", decoded)
    without_marks = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    compact = re.sub(r"\s+", " ", without_marks)
    return compact.strip().lower()


def build_list_url(feed: FeedDefinition) -> str:
    params = [("orderby", "Recientes"), ("search", feed.query), *feed.filters]
    return f"{NAP_LIST_URL}?{urllib.parse.urlencode(params)}"


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_candidates(list_html: str, feed: FeedDefinition) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for match in LIST_CARD_RE.finditer(list_html):
        body = match.group("body")
        title_match = TITLE_RE.search(body)
        if title_match is None:
            continue
        title = html.unescape(title_match.group("title")).strip()
        normalized_title = normalize_text(title)
        if not all(token in normalized_title for token in feed.title_tokens):
            continue
        updated_match = UPDATED_RE.search(body)
        updated = updated_match.group("updated") if updated_match else None
        detail_id = match.group("detail_id")
        candidates.append(
            {
                "title": title,
                "detail_id": detail_id,
                "updated": updated,
                "detail_url": f"{NAP_BASE_URL}/Files/Detail/{detail_id}",
            }
        )
    return candidates


def extract_resource_id(detail_html: str, detail_url: str) -> str:
    match = RESOURCE_ID_RE.search(detail_html)
    if match is None:
        raise RuntimeError(f"Could not find the GTFS resource id in {detail_url}")
    return match.group("resource_id")


def resolve_feed(feed: FeedDefinition) -> dict[str, str]:
    list_url = build_list_url(feed)
    list_html = fetch_text(list_url)
    candidates = parse_candidates(list_html, feed)
    if not candidates:
        raise RuntimeError(
            f"No NAP candidates matched {feed.name!r}. URL inspected: {list_url}"
        )

    selected = candidates[0].copy()
    detail_html = fetch_text(selected["detail_url"])
    selected["resource_id"] = extract_resource_id(detail_html, selected["detail_url"])
    selected["name"] = feed.name
    selected["query"] = feed.query
    selected["output_name"] = feed.output_name
    selected["list_url"] = list_url
    selected["download_url"] = f"{NAP_DOWNLOAD_URL}/{selected['resource_id']}"
    return selected


def require_api_key() -> str:
    api_key = os.environ.get("API_KEY") or os.environ.get("NAP_API_KEY")
    if not api_key:
        raise RuntimeError("API_KEY or NAP_API_KEY must be set to download GTFS files.")
    return api_key


def download_resource(resource_id: str, destination: Path, api_key: str) -> None:
    request = urllib.request.Request(
        f"{NAP_DOWNLOAD_URL}/{resource_id}",
        headers={"User-Agent": USER_AGENT, "apikey": api_key},
    )
    with tempfile.NamedTemporaryFile(delete=False) as temporary:
        temporary_path = Path(temporary.name)

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            with temporary_path.open("wb") as sink:
                shutil.copyfileobj(response, sink)
        validate_gtfs_zip(temporary_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temporary_path), destination)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def validate_gtfs_zip(path: Path) -> None:
    if path.stat().st_size < 5_000:
        raise RuntimeError(f"{path.name} is too small to be a valid GTFS ZIP.")
    if not zipfile.is_zipfile(path):
        raise RuntimeError(f"{path.name} is not a ZIP archive.")

    with zipfile.ZipFile(path) as archive:
        file_names = {
            Path(member).name.lower()
            for member in archive.namelist()
            if not member.endswith("/")
        }
    if "stops.txt" not in file_names:
        raise RuntimeError(f"{path.name} does not contain stops.txt.")


def write_metadata(path: Path, feeds: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "feeds": list(feeds),
        "resolvedBy": "resolve_gtfs_sources.py",
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    metadata_path = (
        Path(args.metadata_path).resolve()
        if args.metadata_path
        else output_dir / "resolved-sources.json"
    )

    resolved_feeds: list[dict[str, str]] = []
    for feed in FEEDS:
        resolved = resolve_feed(feed)
        resolved_feeds.append(resolved)
        print(
            f"[resolve] {resolved['name']}: detail {resolved['detail_id']} -> "
            f"resource {resolved['resource_id']} -> {resolved['output_name']} "
            f"(updated {resolved.get('updated') or 'unknown'})"
        )

    write_metadata(metadata_path, resolved_feeds)
    print(f"[resolve] wrote metadata to {metadata_path}")

    if args.dry_run:
        return 0

    api_key = require_api_key()
    for resolved in resolved_feeds:
        destination = output_dir / resolved["output_name"]
        download_resource(resolved["resource_id"], destination, api_key)
        print(f"[download] saved {destination.name}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - script entrypoint
        print(f"[error] {exc}", file=sys.stderr)
        raise SystemExit(1)
