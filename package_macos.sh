#!/usr/bin/env bash

set -euo pipefail

OUTPUT_DIR="${1:-dist}"

write_step() {
  printf '[build] %s\n' "$1"
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

write_step "Cleaning previous build output"
rm -rf "$OUTPUT_DIR" build

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "[build] Error: Python not found: $PYTHON_BIN" >&2
  exit 1
fi

write_step "Installing dependencies"
if [[ ! -d .venv ]]; then
  "$PYTHON_BIN" -m venv .venv
fi

./.venv/bin/pip install --upgrade pip >/dev/null
./.venv/bin/pip install -r requirements.txt pyinstaller >/dev/null

write_step "Installing Playwright (driver only, no bundled browsers)"
./.venv/bin/pip install -r requirements.txt pyinstaller >/dev/null

write_step "Running PyInstaller"
./.venv/bin/pyinstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name dashboard_runner \
  --distpath "$OUTPUT_DIR" \
  --add-data "index_example.html:." \
  --add-data "simple_example.html:." \
  run_universal.py

write_step "Packaging complete. APP located at $OUTPUT_DIR/dashboard_runner.app"
write_step "Note: requires Chrome, Edge, or another usable Chromium browser installed on target machine."
