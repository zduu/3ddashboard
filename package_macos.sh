#!/usr/bin/env bash

set -euo pipefail

OUTPUT_DIR="${1:-dist}"

write_step() {
  printf '[build] %s\n' "$1"
}

resolve_python_bin() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    printf '%s\n' "$PYTHON_BIN"
    return 0
  fi

  if command -v python >/dev/null 2>&1; then
    command -v python
    return 0
  fi

  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi

  return 1
}

python_identity_json() {
  local python_bin="$1"
  "$python_bin" - <<'PY'
import json
import os
import sys

payload = {
    "executable": os.path.realpath(sys.executable),
    "base_executable": os.path.realpath(getattr(sys, "_base_executable", sys.executable)),
    "version": ".".join(str(part) for part in sys.version_info[:3]),
    "major_minor": ".".join(str(part) for part in sys.version_info[:2]),
}
print(json.dumps(payload, ensure_ascii=False))
PY
}

venv_matches_python() {
  local target_python="$1"

  if [[ ! -x .venv/bin/python ]]; then
    return 1
  fi

  local target_json venv_json
  target_json="$(python_identity_json "$target_python")" || return 1
  venv_json="$(python_identity_json .venv/bin/python)" || return 1

  python3 - "$target_json" "$venv_json" <<'PY'
import json
import sys

target = json.loads(sys.argv[1])
venv = json.loads(sys.argv[2])

same_base = venv["base_executable"] == target["executable"]
same_version = venv["major_minor"] == target["major_minor"]
raise SystemExit(0 if same_base and same_version else 1)
PY
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

write_step "Cleaning previous build output"
rm -rf "$OUTPUT_DIR" build

PYTHON_BIN="$(resolve_python_bin)"
if [[ -z "$PYTHON_BIN" ]] || ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "[build] Error: Python not found." >&2
  exit 1
fi

PYTHON_BIN="$(command -v "$PYTHON_BIN")"
PYTHON_INFO="$(python_identity_json "$PYTHON_BIN")"
PYTHON_PATH="$("$PYTHON_BIN" - "$PYTHON_INFO" <<'PY'
import json, sys
print(json.loads(sys.argv[1])["executable"])
PY
)"
PYTHON_VERSION="$("$PYTHON_BIN" - "$PYTHON_INFO" <<'PY'
import json, sys
print(json.loads(sys.argv[1])["version"])
PY
)"

write_step "Using Python: $PYTHON_PATH (version $PYTHON_VERSION)"

write_step "Installing dependencies"
if [[ -d .venv ]] && ! venv_matches_python "$PYTHON_BIN"; then
  write_step "Recreating .venv because it does not match the selected Python"
  rm -rf .venv
fi

if [[ ! -d .venv ]]; then
  write_step "Creating .venv from $PYTHON_PATH"
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
