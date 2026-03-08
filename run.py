import argparse
import json
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


DEFAULT_INTERVAL_MINUTES = 30
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class LogHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        # Disable browser cache so dashboard updates are visible immediately.
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self) -> None:
        if self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        super().do_GET()

    def log_message(self, format: str, *args: object) -> None:
        msg = format % args
        print(f"[{now_str()}] [WEB] {msg}")


def start_web_server(directory: Path, host: str, port: int) -> ThreadingHTTPServer:
    directory.mkdir(parents=True, exist_ok=True)
    handler = partial(LogHandler, directory=str(directory))
    server = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[{now_str()}] [WEB] Serving {directory.resolve()} at http://{host}:{port}")
    return server


def run_subprocess(cmd: list[str], cwd: Path) -> int:
    print(f"[{now_str()}] [TASK] Running: {' '.join(cmd)}")
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.stdout.strip():
        print(proc.stdout.strip())
    if proc.stderr.strip():
        print(proc.stderr.strip())
    print(f"[{now_str()}] [TASK] Exit code: {proc.returncode}")
    return proc.returncode


def latest_filters_summary(output_dir: Path) -> dict | None:
    runs = [p for p in output_dir.glob("filters_*") if p.is_dir()]
    if not runs:
        return None
    latest = max(runs, key=lambda p: p.stat().st_mtime)
    summary_path = latest / "summary.json"
    if not summary_path.exists():
        return None
    try:
        with summary_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


def should_retry_missing_order_stats(summary: dict | None) -> bool:
    if not summary:
        return False
    items = summary.get("items")
    if not isinstance(items, list):
        return False

    for item in items:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", ""))
        record_count = int(item.get("record_count", 0) or 0)
        json_file = str(item.get("json_file", ""))
        is_order_stats = ("订单统计" in label) or ("u8ba2u5355u7edfu8ba1" in json_file)
        if is_order_stats and record_count <= 0:
            return True
    return False


def build_main_common_args(args: argparse.Namespace) -> list[str]:
    common = [
        "--page-url",
        args.page_url,
        "--state-path",
        args.state_path,
        "--output-dir",
        args.output_dir,
        "--dashboard-dir",
        args.dashboard_dir,
        "--browser-channel",
        args.browser_channel,
        "--filter-wait-ms",
        str(args.filter_wait_ms),
    ]
    if args.filter_selector:
        common.extend(["--filter-selector", args.filter_selector])
    return common


def run_login_if_needed(args: argparse.Namespace, cwd: Path) -> bool:
    state_path = (cwd / args.state_path).resolve()
    if state_path.exists():
        return True

    if not args.auto_login_if_missing_state:
        print(
            f"[{now_str()}] [TASK] State not found: {state_path}. "
            "Run `python main.py login` once, or enable --auto-login-if-missing-state."
        )
        return False

    login_cmd = [args.python_exe, args.main_script, *build_main_common_args(args), "login"]
    code = run_subprocess(login_cmd, cwd)
    return code == 0


def run_once(args: argparse.Namespace, cwd: Path) -> int:
    ok = run_login_if_needed(args, cwd)
    if not ok:
        return 2

    output_dir = (cwd / args.output_dir).resolve()
    cmd = [args.python_exe, args.main_script, *build_main_common_args(args), "fetch"]
    if args.single:
        cmd.append("--single")
    code = run_subprocess(cmd, cwd)
    if code != 0:
        return code

    if args.single or not args.retry_once_on_missing_order_stats:
        return 0

    summary = latest_filters_summary(output_dir)
    if should_retry_missing_order_stats(summary):
        print(f"[{now_str()}] [TASK] Missing order-stats capture detected, retrying once...")
        retry_code = run_subprocess(cmd, cwd)
        if retry_code != 0:
            return retry_code
        retry_summary = latest_filters_summary(output_dir)
        if should_retry_missing_order_stats(retry_summary):
            print(f"[{now_str()}] [TASK] Warning: order-stats capture still missing after retry.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Keep running data capture every N minutes and serve dashboard as a website."
    )
    parser.add_argument("--python-exe", default=sys.executable, help="Python executable path.")
    parser.add_argument("--main-script", default="main.py", help="Main capture script path.")
    parser.add_argument("--interval-minutes", type=int, default=DEFAULT_INTERVAL_MINUTES, help="Update interval minutes.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Web server host.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Web server port.")
    parser.add_argument("--dashboard-dir", default="dashboard", help="Dashboard directory to serve.")
    parser.add_argument("--page-url", default="https://make.sjtu.edu.cn/admin/statistics/order-count", help="Target page URL.")
    parser.add_argument("--state-path", default="state/auth_state.json", help="Login state path.")
    parser.add_argument("--output-dir", default="output", help="Capture output directory.")
    parser.add_argument("--browser-channel", default="msedge", help="Browser channel: msedge/chrome/chromium.")
    parser.add_argument("--filter-selector", default="", help="Optional CSS selector for filter buttons.")
    parser.add_argument("--filter-wait-ms", type=int, default=3500, help="Wait after each filter click in ms.")
    parser.add_argument("--single", action="store_true", help="Capture only initial requests.")
    parser.add_argument(
        "--retry-on-missing-order-stats",
        action="store_true",
        default=True,
        dest="retry_once_on_missing_order_stats",
        help="Retry one extra fetch if order-stats capture is missing. Default: enabled.",
    )
    parser.add_argument(
        "--no-retry-on-missing-order-stats",
        action="store_false",
        dest="retry_once_on_missing_order_stats",
        help="Disable extra retry when order-stats capture is missing.",
    )
    parser.add_argument(
        "--auto-login-if-missing-state",
        action="store_true",
        default=True,
        help="If login state missing, run login flow first. Default: enabled.",
    )
    parser.add_argument(
        "--no-auto-login-if-missing-state",
        action="store_false",
        dest="auto_login_if_missing_state",
        help="Disable auto login when state file is missing.",
    )
    parser.add_argument("--no-run-immediately", action="store_true", help="Do not run immediately; wait for first interval.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    cwd = Path(__file__).resolve().parent
    dashboard_dir = (cwd / args.dashboard_dir).resolve()
    if args.interval_minutes <= 0:
        print("[ERROR] --interval-minutes must be > 0")
        return 1

    server = start_web_server(dashboard_dir, args.host, args.port)
    interval = timedelta(minutes=args.interval_minutes)
    next_run = datetime.now() if not args.no_run_immediately else datetime.now() + interval
    print(f"[{now_str()}] [TASK] Interval: every {args.interval_minutes} minutes")

    try:
        while True:
            now = datetime.now()
            if now >= next_run:
                started = time.time()
                code = run_once(args, cwd)
                elapsed = time.time() - started
                status = "SUCCESS" if code == 0 else "FAILED"
                print(f"[{now_str()}] [TASK] {status}, elapsed: {elapsed:.1f}s")
                next_run = datetime.now() + interval
                print(f"[{now_str()}] [TASK] Next run at: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
            time.sleep(1.0)
    except KeyboardInterrupt:
        print(f"[{now_str()}] [SYS] Stopped by user.")
        server.shutdown()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
