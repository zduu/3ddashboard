import argparse
import json
import os
import shutil
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
DEFAULT_KEEP_OUTPUT_RUNS = 9
DEFAULT_KEEP_SINGLE_FILES = 9

IS_FROZEN = getattr(sys, "frozen", False)

SIGNAL_RELOGIN = "relogin.flag"
SIGNAL_STOP = "stop.flag"
PID_FILE = "dashboard.pid"
LOG_FILE = "dashboard.log"


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def setup_logging(cwd: Path) -> None:
    """Redirect stdout/stderr to log file when running as frozen EXE."""
    if not IS_FROZEN:
        return
    log_path = cwd / LOG_FILE
    try:
        log_fh = open(log_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = log_fh
        sys.stderr = log_fh
    except Exception:
        pass


def write_pid(cwd: Path) -> None:
    (cwd / PID_FILE).write_text(str(os.getpid()), encoding="utf-8")


def remove_pid(cwd: Path) -> None:
    try:
        (cwd / PID_FILE).unlink(missing_ok=True)
    except Exception:
        pass


def check_signal(cwd: Path, name: str) -> bool:
    flag = cwd / name
    if flag.exists():
        try:
            flag.unlink()
        except Exception:
            pass
        return True
    return False


def is_service_running(cwd: Path) -> bool:
    """Check if a service instance is already running via PID file."""
    pid_path = cwd / PID_FILE
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except Exception:
        return False
    # Check if process is alive.
    if sys.platform.startswith("win"):
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def show_control_dialog(cwd: Path) -> str | None:
    """Show a tkinter dialog when service is already running. Returns action."""
    import tkinter as tk
    from tkinter import messagebox

    result = {"action": None}

    root = tk.Tk()
    root.title("3D打印数据看板")
    root.resizable(False, False)

    # Center window.
    w, h = 300, 200
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")

    tk.Label(root, text="服务正在运行中", font=("Microsoft YaHei", 14)).pack(pady=(20, 15))

    def do_action(action: str) -> None:
        result["action"] = action
        root.destroy()

    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=5)
    tk.Button(btn_frame, text="重新登录", width=14, command=lambda: do_action("relogin")).pack(pady=4)
    tk.Button(btn_frame, text="终止服务", width=14, command=lambda: do_action("stop")).pack(pady=4)

    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
    return result["action"]


def ensure_dashboard_placeholder(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    index_file = directory / "index.html"
    simple_dir = directory / "simple"
    simple_dir.mkdir(parents=True, exist_ok=True)
    simple_index_file = simple_dir / "index.html"

    placeholder_html = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Dashboard Loading</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; display: grid; place-items: center; min-height: 100vh; background: #f5f7fb; color: #1f2937; }
    .box { text-align: center; padding: 24px; background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; }
    .hint { color: #6b7280; margin-top: 8px; }
  </style>
</head>
<body>
  <div class="box">
    <h2>看板准备中...</h2>
    <div class="hint">正在执行首次抓取，完成后请刷新页面。</div>
  </div>
</body>
</html>
"""
    if not index_file.exists():
        index_file.write_text(placeholder_html, encoding="utf-8")
    if not simple_index_file.exists():
        simple_index_file.write_text(placeholder_html, encoding="utf-8")


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
        if self.path == "/simple":
            self.path = "/simple/"
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


def run_subprocess(cmd: list[str], cwd: Path, interactive: bool = False) -> int:
    print(f"[{now_str()}] [TASK] Running: {' '.join(cmd)}")
    if interactive:
        proc = subprocess.run(cmd, cwd=str(cwd))
    else:
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


def resolve_runtime_root(script_path: Path) -> Path:
    if IS_FROZEN:
        return Path(sys.executable).resolve().parent
    return script_path.resolve().parent


def ensure_playwright_browsers_path(base_dir: Path) -> None:
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    candidate = base_dir / "ms-playwright"
    if candidate.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(candidate)


def run_main_inline(cli_args: list[str]) -> int:
    from main import main as main_entry

    original_argv = sys.argv[:]
    try:
        sys.argv = ["main.py", *cli_args]
        return main_entry()
    finally:
        sys.argv = original_argv


def run_main_command(args: argparse.Namespace, cwd: Path, extra_cli: list[str], interactive: bool = False) -> int:
    cli = [*build_main_common_args(args), *extra_cli]
    if IS_FROZEN:
        prev = Path.cwd()
        try:
            os.chdir(cwd)
            return run_main_inline(cli)
        finally:
            os.chdir(prev)
    cmd = [args.python_exe, args.main_script, *cli]
    return run_subprocess(cmd, cwd, interactive=interactive)


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


def cleanup_output_dir(output_dir: Path, keep_output_runs: int, keep_single_files: int) -> tuple[int, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    removed_dirs = 0
    removed_files = 0

    runs = sorted(
        [p for p in output_dir.glob("filters_*") if p.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    # Always remove empty run directories.
    for run in runs:
        try:
            if any(run.iterdir()):
                continue
        except Exception:
            continue
        shutil.rmtree(run, ignore_errors=True)
        removed_dirs += 1

    runs = sorted(
        [p for p in output_dir.glob("filters_*") if p.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for run in runs[keep_output_runs:]:
        shutil.rmtree(run, ignore_errors=True)
        removed_dirs += 1

    singles = sorted(
        [p for p in output_dir.glob("responses_*.json") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    for json_file in singles[keep_single_files:]:
        tag = json_file.stem[len("responses_") :]
        csv_file = output_dir / f"responses_{tag}.csv"
        if json_file.exists():
            json_file.unlink(missing_ok=True)
            removed_files += 1
        if csv_file.exists():
            csv_file.unlink(missing_ok=True)
            removed_files += 1

    # Remove orphan csv files whose paired json is gone.
    for csv_file in [p for p in output_dir.glob("responses_*.csv") if p.is_file()]:
        tag = csv_file.stem[len("responses_") :]
        json_file = output_dir / f"responses_{tag}.json"
        if not json_file.exists():
            csv_file.unlink(missing_ok=True)
            removed_files += 1

    return removed_dirs, removed_files


def has_usable_state(state_path: Path) -> bool:
    if not state_path.exists() or not state_path.is_file():
        return False
    try:
        with state_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    cookies = data.get("cookies")
    origins = data.get("origins")
    has_cookies = isinstance(cookies, list) and len(cookies) > 0
    has_origins = isinstance(origins, list) and len(origins) > 0
    return has_cookies or has_origins


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
    if has_usable_state(state_path):
        return True

    if not args.auto_login_if_missing_state:
        print(
            f"[{now_str()}] [TASK] State not found: {state_path}. "
            "Run `python main.py login` once, or enable --auto-login-if-missing-state."
        )
        return False

    code = run_main_command(args, cwd, ["login"], interactive=True)
    return code == 0


def run_once(args: argparse.Namespace, cwd: Path) -> int:
    ok = run_login_if_needed(args, cwd)
    if not ok:
        return 2

    output_dir = (cwd / args.output_dir).resolve()
    extra = ["fetch"]
    if args.single:
        extra.append("--single")
    code = run_main_command(args, cwd, extra)
    if code != 0:
        if args.auto_login_if_missing_state:
            print(f"[{now_str()}] [TASK] Fetch failed, retrying after re-login once...")
            login_code = run_main_command(args, cwd, ["login"], interactive=True)
            if login_code == 0:
                code = run_main_command(args, cwd, extra)
                if code == 0:
                    return 0
        return code

    if args.single or not args.retry_once_on_missing_order_stats:
        return 0

    summary = latest_filters_summary(output_dir)
    if should_retry_missing_order_stats(summary):
        print(f"[{now_str()}] [TASK] Missing order-stats capture detected, retrying once...")
        retry_code = run_main_command(args, cwd, extra)
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
    parser.add_argument(
        "--python-exe",
        default=sys.executable,
        help="Python executable path (ignored when packaged).",
    )
    parser.add_argument("--main-script", default="main.py", help="Main capture script path.")
    parser.add_argument("--interval-minutes", type=int, default=DEFAULT_INTERVAL_MINUTES, help="Update interval minutes.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Web server host.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Web server port.")
    parser.add_argument("--dashboard-dir", default="dashboard", help="Dashboard directory to serve.")
    parser.add_argument("--page-url", default="https://make.sjtu.edu.cn/admin/statistics/order-count", help="Target page URL.")
    parser.add_argument("--state-path", default="state/auth_state.json", help="Login state path.")
    parser.add_argument("--output-dir", default="output", help="Capture output directory.")
    parser.add_argument("--browser-channel", default="auto", help="Browser channel: auto/chrome/msedge/chromium.")
    parser.add_argument("--filter-selector", default="", help="Optional CSS selector for filter buttons.")
    parser.add_argument("--filter-wait-ms", type=int, default=3500, help="Wait after each filter click in ms.")
    parser.add_argument(
        "--keep-output-runs",
        type=int,
        default=DEFAULT_KEEP_OUTPUT_RUNS,
        help=f"Keep latest N filters_* run dirs in output. Default: {DEFAULT_KEEP_OUTPUT_RUNS}.",
    )
    parser.add_argument(
        "--keep-single-files",
        type=int,
        default=DEFAULT_KEEP_SINGLE_FILES,
        help=f"Keep latest N responses_*.json/.csv pairs. Default: {DEFAULT_KEEP_SINGLE_FILES}.",
    )
    parser.add_argument("--no-clean-output", action="store_true", help="Disable automatic cleanup for output directory.")
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


def show_error_dialog(title: str, message: str) -> None:
    """Show an error dialog visible to the user (before logging redirect)."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        pass


def ensure_login(args: argparse.Namespace, cwd: Path) -> bool:
    """Ensure login state exists BEFORE entering background mode.

    Returns True if state is ready, False if login failed.
    """
    state_path = (cwd / args.state_path).resolve()
    if has_usable_state(state_path):
        return True

    # No state — run login with visible browser (not in background yet).
    try:
        code = run_main_command(args, cwd, ["login"], interactive=True)
        if code == 0 and has_usable_state(state_path):
            return True
        # Login returned but state is not valid — user may have closed browser
        # before completing login.
        show_error_dialog("登录失败", "未检测到有效登录状态。\n请重新运行，在浏览器中完成登录后再关闭浏览器。")
    except Exception as e:
        show_error_dialog("登录失败", f"浏览器启动或登录过程出错：\n{e}")
    return False


def main() -> int:
    args = build_parser().parse_args()
    cwd = Path(__file__).resolve().parent
    if IS_FROZEN:
        cwd = Path(sys.executable).resolve().parent

    # If service is already running, show control dialog instead of starting again.
    if is_service_running(cwd):
        action = show_control_dialog(cwd)
        if action == "relogin":
            (cwd / SIGNAL_RELOGIN).write_text("", encoding="utf-8")
        elif action == "stop":
            (cwd / SIGNAL_STOP).write_text("", encoding="utf-8")
        return 0

    # Step 1: Ensure login BEFORE going silent — browser must be visible.
    if not ensure_login(args, cwd):
        return 1

    # Step 2: Now go into background mode — redirect output to log file.
    setup_logging(cwd)
    write_pid(cwd)

    dashboard_dir = (cwd / args.dashboard_dir).resolve()
    output_dir = (cwd / args.output_dir).resolve()
    ensure_dashboard_placeholder(dashboard_dir)
    if args.interval_minutes <= 0:
        print("[ERROR] --interval-minutes must be > 0")
        remove_pid(cwd)
        return 1
    if args.keep_output_runs <= 0 or args.keep_single_files <= 0:
        print("[ERROR] --keep-output-runs and --keep-single-files must be > 0")
        remove_pid(cwd)
        return 1

    # Clean stale signal files from previous runs.
    check_signal(cwd, SIGNAL_RELOGIN)
    check_signal(cwd, SIGNAL_STOP)

    server = start_web_server(dashboard_dir, args.host, args.port)
    interval = timedelta(minutes=args.interval_minutes)
    next_run = datetime.now() if not args.no_run_immediately else datetime.now() + interval
    last_interrupt_ts = 0.0
    if not args.no_clean_output:
        d, f = cleanup_output_dir(output_dir, args.keep_output_runs, args.keep_single_files)
        if d or f:
            print(f"[{now_str()}] [CLEAN] Removed {d} old run dirs and {f} old files.")
    print(f"[{now_str()}] [TASK] Interval: every {args.interval_minutes} minutes")

    while True:
        try:
            # Check stop signal.
            if check_signal(cwd, SIGNAL_STOP):
                print(f"[{now_str()}] [SYS] Stop signal received, shutting down.")
                server.shutdown()
                remove_pid(cwd)
                return 0

            # Check re-login signal.
            if check_signal(cwd, SIGNAL_RELOGIN):
                print(f"[{now_str()}] [SYS] Re-login signal received.")
                run_main_command(args, cwd, ["login"], interactive=True)
                print(f"[{now_str()}] [SYS] Re-login complete.")
                next_run = datetime.now()

            now = datetime.now()
            if now >= next_run:
                started = time.time()
                code = run_once(args, cwd)
                elapsed = time.time() - started
                status = "SUCCESS" if code == 0 else "FAILED"
                print(f"[{now_str()}] [TASK] {status}, elapsed: {elapsed:.1f}s")
                if not args.no_clean_output:
                    d, f = cleanup_output_dir(output_dir, args.keep_output_runs, args.keep_single_files)
                    if d or f:
                        print(f"[{now_str()}] [CLEAN] Removed {d} old run dirs and {f} old files.")
                next_run = datetime.now() + interval
                print(f"[{now_str()}] [TASK] Next run at: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
            time.sleep(1.0)
        except KeyboardInterrupt:
            ts = time.time()
            if ts - last_interrupt_ts <= 3.0:
                print(f"[{now_str()}] [SYS] Stopped by user.")
                server.shutdown()
                remove_pid(cwd)
                return 0
            last_interrupt_ts = ts
            print(f"[{now_str()}] [SYS] Interrupt received. Press Ctrl+C again within 3s to stop.")
            next_run = datetime.now()


if __name__ == "__main__":
    raise SystemExit(main())
