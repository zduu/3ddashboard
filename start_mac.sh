#!/usr/bin/env bash

# One-click launcher for macOS (and Linux): runs run_universal.py
# Usage: ./start_mac.sh [extra args]
# Examples:
#   ./start_mac.sh --port 9000
#   ./start_mac.sh --browser-channel chrome

set -euo pipefail

# Resolve to repo root (directory of this script)
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Pick a Python interpreter.
# 优先级：环境变量 PY_CMD > PY_PATH.txt > python3/python
PY="${PY_CMD:-}"

if [[ -z "$PY" && -f "PY_PATH.txt" ]]; then
  # First line of PY_PATH.txt is treated as python command or full path.
  PY="$(head -n 1 PY_PATH.txt | tr -d '\r')"
fi

if [[ -z "$PY" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PY="python3"
  elif command -v python >/dev/null 2>&1; then
    PY="python"
  fi
fi

if [[ -z "$PY" ]]; then
  echo "未找到可用的 Python，请输入 Python 可执行路径（例如 /Users/you/miniconda3/envs/zhoujie/bin/python）：" >&2
  read -r PY
fi

if ! command -v "$PY" >/dev/null 2>&1 && [[ ! -x "$PY" ]]; then
  echo "Error: Python not found or not executable: $PY" >&2
  exit 1
fi

# Run the universal runner (interactive when login is needed)
exec "$PY" run_universal.py "$@"
