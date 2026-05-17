#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

python3 "$SCRIPT_DIR/resolve_gtfs_sources.py" \
  --output-dir "$SCRIPT_DIR" \
  "$@"
