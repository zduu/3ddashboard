from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timedelta
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


DEFAULT_INTERVAL_MINUTES = 30
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
DEFAULT_KEEP_OUTPUT_RUNS = 3
DEFAULT_KEEP_SINGLE_FILES = 3
RUN_ONCE_RELOGIN_REQUIRED = 3
RUN_NOW_DEBOUNCE_SECONDS = 120

IS_FROZEN = getattr(sys, "frozen", False)

SIGNAL_RELOGIN = "relogin.flag"
SIGNAL_STOP = "stop.flag"
SIGNAL_SHOW_PANEL = "show_panel.flag"
SIGNAL_RUN_NOW = "run_now.flag"
PID_FILE = "dashboard.pid"
LOG_FILE = "dashboard.log"
LOCK_FILE = "dashboard.lock"
STATUS_FILE = "status.json"


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


def acquire_single_instance_lock(cwd: Path) -> Any | None:
    lock_path = cwd / LOCK_FILE
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fh = open(lock_path, "a+b")

    try:
        if sys.platform.startswith("win"):
            import msvcrt

            lock_fh.seek(0)
            msvcrt.locking(lock_fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        lock_fh.seek(0)
        lock_fh.truncate()
        lock_fh.write(str(os.getpid()).encode("utf-8"))
        lock_fh.flush()
        return lock_fh
    except OSError:
        lock_fh.close()
        return None


def release_single_instance_lock(cwd: Path, lock_fh: Any | None) -> None:
    if lock_fh is None:
        return

    try:
        if sys.platform.startswith("win"):
            import msvcrt

            lock_fh.seek(0)
            msvcrt.locking(lock_fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass

    try:
        lock_fh.close()
    except Exception:
        pass

    try:
        (cwd / LOCK_FILE).unlink(missing_ok=True)
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


def write_signal(cwd: Path, name: str) -> None:
    (cwd / name).write_text("", encoding="utf-8")


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


def build_dashboard_url(host: str, port: int) -> str:
    display_host = host
    if host in {"0.0.0.0", "::", ""}:
        display_host = "127.0.0.1"
    return f"http://{display_host}:{port}"


def open_local_path(path: Path) -> None:
    target = str(path.resolve())
    try:
        if sys.platform.startswith("win"):
            os.startfile(target)  # type: ignore[attr-defined]
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", target])
            return
        subprocess.Popen(["xdg-open", target])
    except Exception:
        pass


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


def show_already_starting_dialog() -> None:
    """Show a simple notice when another instance is still starting up."""
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("3D打印数据看板", "程序已经启动或正在启动中，请勿重复双击。")
        root.destroy()
    except Exception:
        pass


class RuntimeStatusStore:
    def __init__(self, dashboard_url: str) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {
            "phase": "starting",
            "badge": "启动中",
            "badge_state": "loading",
            "message": "程序已启动，正在准备管理面板。",
            "detail": "请勿重复双击；再次双击会直接唤醒这个面板。",
            "next_run_at": "",
            "last_success_at": "",
            "updated_at": now_iso(),
            "dashboard_url": dashboard_url,
            "service_alive": True,
            "exit_requested": False,
            "force_exit_requested": False,
        }

    def update(self, **fields: Any) -> None:
        with self._lock:
            self._data.update(fields)
            self._data["updated_at"] = now_iso()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)


class ActionTile:
    def __init__(
        self,
        tk: Any,
        parent: Any,
        *,
        text: str,
        command: Any,
        bg: str,
        fg: str,
        active_bg: str,
        active_fg: str,
        font: Any,
        padx: int,
        pady: int,
        wraplength: int,
    ) -> None:
        self.tk = tk
        self.command = command
        self.normal_bg = bg
        self.normal_fg = fg
        self.active_bg = active_bg
        self.active_fg = active_fg

        self.frame = tk.Frame(parent, bg=bg, highlightthickness=0, bd=0, takefocus=1)
        self.label = tk.Label(
            self.frame,
            text=text,
            justify="center",
            anchor="center",
            bg=bg,
            fg=fg,
            font=font,
            padx=padx,
            pady=pady,
            wraplength=wraplength,
        )
        self.label.pack(fill="both", expand=True)

        for widget in (self.frame, self.label):
            widget.bind("<Button-1>", self._on_click)
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)

        self.frame.bind("<Return>", self._on_click)
        self.frame.bind("<space>", self._on_click)

    def grid(self, **kwargs: Any) -> None:
        self.frame.grid(**kwargs)

    def configure(self, **kwargs: Any) -> None:
        if "text" in kwargs:
            self.label.configure(text=kwargs.pop("text"))
        if "bg" in kwargs:
            self.normal_bg = kwargs.pop("bg")
        if "fg" in kwargs:
            self.normal_fg = kwargs.pop("fg")
        if "activebackground" in kwargs:
            self.active_bg = kwargs.pop("activebackground")
        if "activeforeground" in kwargs:
            self.active_fg = kwargs.pop("activeforeground")
        self._apply_normal_style()

    def _apply_normal_style(self) -> None:
        self.frame.configure(bg=self.normal_bg)
        self.label.configure(bg=self.normal_bg, fg=self.normal_fg)

    def _apply_active_style(self) -> None:
        self.frame.configure(bg=self.active_bg)
        self.label.configure(bg=self.active_bg, fg=self.active_fg)

    def _on_click(self, _event: Any) -> None:
        try:
            self.frame.focus_set()
        except Exception:
            pass
        self.command()

    def _on_enter(self, _event: Any) -> None:
        self._apply_active_style()

    def _on_leave(self, _event: Any) -> None:
        self._apply_normal_style()


class ControlPanelApp:
    def __init__(self, cwd: Path, args: argparse.Namespace, status_store: RuntimeStatusStore) -> None:
        import tkinter as tk
        from tkinter import messagebox

        self.cwd = cwd
        self.args = args
        self.status_store = status_store
        self.tk = tk
        self.messagebox = messagebox
        self.root = tk.Tk()
        self.root.title("3D打印数据看板")
        self.root.resizable(False, False)
        self.root.configure(bg="#f4efe6")
        self.root.geometry(self._center_geometry(760, 520))
        self.root.minsize(760, 520)
        self.root.protocol("WM_DELETE_WINDOW", self._handle_close_request)
        if sys.platform == "darwin":
            try:
                self.root.createcommand("tk::mac::Quit", self._handle_close_request)
            except Exception:
                pass

        shell = tk.Frame(self.root, bg="#f4efe6")
        shell.pack(fill="both", expand=True, padx=22, pady=22)

        action_grid = tk.Frame(shell, bg="#f4efe6")
        action_grid.pack(fill="both", expand=True)
        for idx in range(2):
            action_grid.grid_columnconfigure(idx, weight=1)
            action_grid.grid_rowconfigure(idx, weight=1)

        self.open_btn = self._make_action_button(
            action_grid,
            "打开看板",
            "",
            self.open_dashboard,
            0,
            0,
            primary=True,
            large=True,
        )
        self.refresh_btn = self._make_action_button(
            action_grid,
            "数据更新",
            "",
            self.request_run_now,
            0,
            1,
            large=True,
        )
        self.relogin_btn = self._make_action_button(
            action_grid,
            "重新登录",
            "",
            self.request_relogin,
            1,
            0,
            large=True,
        )
        self.stop_btn = self._make_action_button(
            action_grid,
            "停止服务",
            "",
            self.request_stop,
            1,
            1,
            danger=True,
            large=True,
        )

        self._refresh_ui()
        self.root.after(500, self._poll)

    def _make_action_button(
        self,
        parent: Any,
        title: str,
        subtitle: str,
        command: Any,
        row: int,
        column: int,
        *,
        primary: bool = False,
        danger: bool = False,
        large: bool = False,
    ) -> Any:
        bg = "#ffffff"
        fg = "#24323f"
        active = "#f4f7fa"
        if primary:
            bg = "#d97a2b"
            fg = "#ffffff"
            active = "#c96c21"
        elif danger:
            bg = "#f9e0dc"
            fg = "#8f2d1f"
            active = "#f2d0ca"

        width = 18
        height = 3
        padx = 12
        pady = 10
        font = ("Microsoft YaHei", 10, "bold")
        wraplength = 135
        if large:
            width = 18
            height = 7
            padx = 18
            pady = 18
            font = ("Microsoft YaHei", 20, "bold")
            wraplength = 220

        label_text = title if not subtitle else f"{title}\n{subtitle}"

        btn = ActionTile(
            self.tk,
            parent,
            text=label_text,
            command=command,
            bg=bg,
            fg=fg,
            font=font,
            active_bg=active,
            active_fg=fg,
            padx=padx,
            pady=pady,
            wraplength=wraplength,
        )
        btn.grid(row=row, column=column, sticky="nsew", padx=(0 if column == 0 else 10, 0), pady=(0 if row == 0 else 10, 0))
        return btn

    def _center_geometry(self, width: int, height: int) -> str:
        x = max(0, (self.root.winfo_screenwidth() - width) // 2)
        y = max(0, (self.root.winfo_screenheight() - height) // 2)
        return f"{width}x{height}+{x}+{y}"

    def _iconify_only(self) -> None:
        self.root.iconify()

    def _handle_close_request(self) -> None:
        snapshot = self.status_store.snapshot()
        if not snapshot.get("service_alive", True):
            self.status_store.update(exit_requested=True)
            return

        choice = self.messagebox.askyesnocancel(
            "关闭 3D打印数据看板",
            "选择“是”将停止服务并退出程序。\n选择“否”只隐藏窗口，服务继续运行。\n选择“取消”保持当前窗口。",
        )
        if choice is True:
            self.request_stop()
            return
        if choice is False:
            self._iconify_only()

    def show_panel(self) -> None:
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.attributes("-topmost", True)
            self.root.after(250, lambda: self.root.attributes("-topmost", False))
        except Exception:
            pass
        try:
            self.root.focus_force()
        except Exception:
            pass

    def open_dashboard(self) -> None:
        webbrowser.open(build_dashboard_url(self.args.host, self.args.port))

    def copy_dashboard_url(self) -> None:
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(build_dashboard_url(self.args.host, self.args.port))
            self.status_store.update(detail="看板地址已复制到剪贴板。")
            self.show_panel()
        except Exception:
            pass

    def open_log(self) -> None:
        open_local_path(self.cwd / LOG_FILE)

    def open_output_dir(self) -> None:
        open_local_path(self.cwd / self.args.output_dir)

    def request_relogin(self) -> None:
        write_signal(self.cwd, SIGNAL_RELOGIN)
        self.show_panel()

    def request_run_now(self) -> None:
        write_signal(self.cwd, SIGNAL_RUN_NOW)
        self.show_panel()

    def request_stop(self) -> None:
        snapshot = self.status_store.snapshot()
        if not snapshot.get("service_alive", True):
            self.status_store.update(exit_requested=True)
            return
        self.status_store.update(force_exit_requested=True, exit_requested=True)
        write_signal(self.cwd, SIGNAL_STOP)
        try:
            self.root.after(50, self.root.destroy)
        except Exception:
            pass

    def _apply_badge_style(self, badge_state: str) -> None:
        styles = {
            "loading": ("#fef3c7", "#92400e"),
            "error": ("#fee2e2", "#991b1b"),
            "live": ("#dcfce7", "#166534"),
            "success": ("#dcfce7", "#166534"),
        }
        bg, fg = styles.get(badge_state, ("#e2e8f0", "#334155"))
        self.badge_label.configure(bg=bg, fg=fg)

    def _phase_title(self, phase: str) -> str:
        mapping = {
            "starting": "正在启动服务",
            "updating": "正在抓取并刷新看板数据",
            "ok": "服务运行中",
            "error": "服务运行异常",
            "relogin_required": "当前需要重新登录",
            "relogin_in_progress": "正在重新登录",
            "stopping": "正在停止服务",
        }
        return mapping.get(phase, "服务状态更新中")

    def _format_countdown(self, next_run_at: str) -> str:
        if not next_run_at:
            return "待定"
        try:
            target = datetime.strptime(next_run_at, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return "待定"
        remaining = int((target - datetime.now()).total_seconds())
        if remaining <= 0:
            return "即将开始"
        hours, rem = divmod(remaining, 3600)
        minutes, seconds = divmod(rem, 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def _refresh_ui(self) -> None:
        snapshot = self.status_store.snapshot()
        phase = str(snapshot.get("phase", "starting"))
        badge = str(snapshot.get("badge", "启动中"))
        self.root.title(f"3D打印数据看板 - {badge}")

        service_alive = bool(snapshot.get("service_alive", True))
        self.stop_btn.configure(text="停止服务" if service_alive else "退出程序")
        if phase == "relogin_required":
            self.relogin_btn.configure(bg="#f9e0dc", fg="#8f2d1f", activebackground="#f2d0ca", activeforeground="#8f2d1f")
        else:
            self.relogin_btn.configure(bg="#ffffff", fg="#24323f", activebackground="#f4f7fa", activeforeground="#24323f")

    def _poll(self) -> None:
        if check_signal(self.cwd, SIGNAL_SHOW_PANEL):
            self.show_panel()
        self._refresh_ui()
        if self.status_store.snapshot().get("exit_requested"):
            self.root.destroy()
            return
        self.root.after(500, self._poll)

    def run(self) -> None:
        self.show_panel()
        self.root.mainloop()


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def write_dashboard_status(
    dashboard_dir: Path,
    *,
    phase: str,
    badge: str,
    badge_state: str,
    message: str,
    detail: str = "",
    next_run_at: str = "",
    last_success_at: str = "",
) -> None:
    dashboard_dir.mkdir(parents=True, exist_ok=True)
    simple_dir = dashboard_dir / "simple"
    simple_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "phase": phase,
        "badge": badge,
        "badge_state": badge_state,
        "message": message,
        "detail": detail,
        "next_run_at": next_run_at,
        "last_success_at": last_success_at,
        "updated_at": now_iso(),
    }

    for path in (dashboard_dir / STATUS_FILE, simple_dir / STATUS_FILE):
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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
    .box { width: min(680px, calc(100vw - 32px)); text-align: left; padding: 24px; background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; box-shadow: 0 18px 42px rgba(15, 23, 42, 0.08); }
    .box[data-phase="relogin_required"] { border: 2px solid #ef4444; box-shadow: 0 22px 48px rgba(127, 29, 29, 0.16); }
    .badge { display: inline-flex; align-items: center; min-height: 28px; padding: 0 12px; border-radius: 999px; font-size: 12px; font-weight: 700; letter-spacing: 0.04em; background: #e0f2fe; color: #0c4a6e; }
    .badge[data-state="error"] { background: #fee2e2; color: #991b1b; }
    .badge[data-state="loading"] { background: #fef3c7; color: #92400e; }
    .badge[data-state="success"] { background: #dcfce7; color: #166534; }
    h2 { margin: 14px 0 8px; font-size: 28px; }
    .hint { color: #475569; margin-top: 10px; line-height: 1.6; }
    .sub { color: #64748b; font-size: 14px; }
    .alert { display: none; margin-top: 18px; padding: 16px 18px; border-radius: 12px; border: 2px solid #fca5a5; background: linear-gradient(180deg, #fff1f2 0%, #ffe4e6 100%); color: #7f1d1d; }
    .alert strong { display: block; margin-bottom: 8px; font-size: 18px; }
    .alert p { margin: 0; font-size: 15px; line-height: 1.7; }
  </style>
</head>
<body>
  <div class="box" id="status_box">
    <div class="badge" id="status_badge" data-state="loading">启动中</div>
    <h2 id="status_title">看板准备中...</h2>
    <div class="hint" id="status_message">正在执行首次抓取，完成后请刷新页面。</div>
    <div class="hint sub" id="status_detail">首次启动、重新登录或更新后，页面可能延迟 10-60 秒，请勿重复操作。</div>
    <div class="alert" id="status_alert">
      <strong>需要重新登录</strong>
      <p id="status_alert_text">请点击“重新登录”，在浏览器中完成登录后关闭浏览器，然后等待 10-60 秒自动刷新。</p>
    </div>
  </div>
  <script>
    const boxEl = document.getElementById("status_box");
    const badgeEl = document.getElementById("status_badge");
    const titleEl = document.getElementById("status_title");
    const messageEl = document.getElementById("status_message");
    const detailEl = document.getElementById("status_detail");
    const alertEl = document.getElementById("status_alert");
    const alertTextEl = document.getElementById("status_alert_text");

    function applyStatus(status) {
      const phase = String((status && status.phase) || "");
      const badge = String((status && status.badge) || "启动中");
      const badgeState = String((status && status.badge_state) || "loading");
      const message = String((status && status.message) || "正在执行首次抓取，完成后请刷新页面。");
      const detail = String((status && status.detail) || "首次启动、重新登录或更新后，页面可能延迟 10-60 秒，请勿重复操作。");

      badgeEl.textContent = badge;
      badgeEl.dataset.state = badgeState;
      boxEl.dataset.phase = phase;
      messageEl.textContent = message;
      detailEl.textContent = detail;

      if (phase === "relogin_required") {
        titleEl.textContent = "需要重新登录";
        alertEl.style.display = "block";
        alertTextEl.textContent = `${message} ${detail}`.trim();
      } else if (phase === "error") {
        titleEl.textContent = "更新失败";
        alertEl.style.display = "none";
      } else if (phase === "ok") {
        titleEl.textContent = "看板已准备完成";
        alertEl.style.display = "none";
      } else {
        titleEl.textContent = "看板准备中...";
        alertEl.style.display = "none";
      }
    }

    async function loadStatus() {
      try {
        const resp = await fetch(`./status.json?_=${Date.now()}`, { cache: "no-store" });
        if (!resp.ok) {
          return;
        }
        applyStatus(await resp.json());
      } catch (err) {
        // Ignore transient polling failures on the placeholder page.
      }
    }

    loadStatus();
    setInterval(loadStatus, 5000);
  </script>
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


def find_listen_pids_by_port(port: int) -> list[int]:
    if port <= 0:
        return []

    if sys.platform.startswith("win"):
        try:
            proc = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except Exception:
            return []

        pids: set[int] = set()
        target = f":{port}"
        for line in proc.stdout.splitlines():
            text = line.strip()
            if "LISTENING" not in text.upper() or target not in text:
                continue
            parts = text.split()
            if len(parts) < 5:
                continue
            try:
                pids.add(int(parts[-1]))
            except ValueError:
                continue
        return sorted(pids)

    try:
        proc = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception:
        return []

    pids: set[int] = set()
    for line in proc.stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            pids.add(int(text))
        except ValueError:
            continue
    return sorted(pids)


def terminate_pid(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False

    try:
        if sys.platform.startswith("win"):
            proc = subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            return proc.returncode == 0

        os.kill(pid, 15)
        for _ in range(20):
            try:
                os.kill(pid, 0)
            except OSError:
                return True
            time.sleep(0.1)
        os.kill(pid, 9)
        for _ in range(10):
            try:
                os.kill(pid, 0)
            except OSError:
                return True
            time.sleep(0.1)
    except OSError:
        return True
    except Exception:
        return False
    return False


def auto_free_port(host: str, port: int) -> list[int]:
    del host
    released: list[int] = []
    for pid in find_listen_pids_by_port(port):
        if terminate_pid(pid):
            released.append(pid)
    return released


def ensure_port_available(host: str, port: int) -> None:
    bind_host = host if host not in {"0.0.0.0", "::"} else ""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((bind_host, port))
    except OSError as exc:
        raise RuntimeError(
            f"端口 {port} 已被占用。\n"
            f"请先关闭已经运行的看板程序，或改用其他端口，例如：\n"
            f"  python run_universal.py --port {port + 1}"
        ) from exc
    finally:
        probe.close()


def run_subprocess(cmd: list[str], cwd: Path, interactive: bool = False) -> int:
    print(f"[{now_str()}] [TASK] Running: {' '.join(cmd)}")
    if interactive:
        proc = subprocess.run(cmd, cwd=str(cwd))
    else:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        if proc.stdout is not None:
            for line in proc.stdout:
                text = line.rstrip()
                if text:
                    print(text)
        proc.wait()
    print(f"[{now_str()}] [TASK] Exit code: {proc.returncode}")
    return int(proc.returncode)


def resolve_runtime_root(script_path: Path) -> Path:
    if IS_FROZEN:
        exe_path = Path(sys.executable).resolve()
        parts = exe_path.parts
        if sys.platform == "darwin":
            for idx, part in enumerate(parts):
                if part.endswith(".app"):
                    return Path(*parts[: idx + 1]).resolve().parent
        return exe_path.parent
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
            data["_run_dir"] = str(latest.resolve())
            return data
    except Exception:
        return None
    return None


def _looks_like_target_order_item(item: dict[str, Any]) -> bool:
    label = str(item.get("label", ""))
    json_file = str(item.get("json_file", ""))
    csv_file = str(item.get("csv_file", ""))
    haystack = "\n".join((label, json_file, csv_file))
    return any(token in haystack for token in ("订单统计", "u8ba2u5355u7edfu8ba1"))


def _resolve_summary_item_file(run_dir: Path | None, file_value: str) -> Path | None:
    if not file_value:
        return None
    path = Path(file_value)
    if path.is_absolute():
        return path
    if run_dir is None:
        return None
    candidates = [
        run_dir / path.name,
        run_dir.parent.parent / path,
        run_dir.parent / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _summary_item_has_capture_data(item: dict[str, Any], run_dir: Path | None) -> bool:
    raw_count = item.get("record_count", 0)
    try:
        record_count = int(raw_count or 0)
    except Exception:
        record_count = 0
    if record_count > 0:
        return True

    csv_path = _resolve_summary_item_file(run_dir, str(item.get("csv_file", "")))
    if csv_path and csv_path.exists():
        try:
            with csv_path.open("r", encoding="utf-8-sig") as f:
                rows = [line.strip() for line in f if line.strip()]
            if len(rows) > 1:
                return True
        except Exception:
            pass

    json_path = _resolve_summary_item_file(run_dir, str(item.get("json_file", "")))
    if json_path and json_path.exists():
        try:
            with json_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, list):
                return len(payload) > 0
            if isinstance(payload, dict):
                return len(payload) > 0
            if isinstance(payload, str):
                return bool(payload.strip())
            return payload is not None
        except Exception:
            pass

    return False


def should_retry_missing_order_stats(summary: dict | None) -> bool:
    if not summary:
        return False
    items = summary.get("items")
    if not isinstance(items, list):
        return False
    run_dir_value = summary.get("_run_dir")
    run_dir = Path(run_dir_value) if isinstance(run_dir_value, str) and run_dir_value else None
    non_initial_count = 0
    empty_non_initial_count = 0

    for item in items:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", ""))
        has_data = _summary_item_has_capture_data(item, run_dir)
        if _looks_like_target_order_item(item) and not has_data:
            return True
        if label != "initial":
            non_initial_count += 1
            if not has_data:
                empty_non_initial_count += 1
    if non_initial_count >= 3 and empty_non_initial_count == non_initial_count:
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

    for pattern in ("assist_api_*.json", "admin_orders_recent_*.json"):
        files = sorted(
            [p for p in output_dir.glob(pattern) if p.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old_file in files[keep_single_files:]:
            old_file.unlink(missing_ok=True)
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
    if not (has_cookies or has_origins):
        return False

    auth_cookie_names = {"JAAuthCookie", "keepalive", "JATrustCookie"}
    has_auth_cookie = False
    if isinstance(cookies, list):
        for item in cookies:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", ""))
            value = str(item.get("value", ""))
            if name in auth_cookie_names and value:
                has_auth_cookie = True
                break

    has_app_user_token = False
    if isinstance(origins, list):
        for origin in origins:
            if not isinstance(origin, dict) or origin.get("origin") != "https://make.sjtu.edu.cn":
                continue
            local_storage = origin.get("localStorage")
            if not isinstance(local_storage, list):
                continue
            for item in local_storage:
                if not isinstance(item, dict) or item.get("name") != "app-user":
                    continue
                raw_value = item.get("value")
                if not isinstance(raw_value, str) or not raw_value.strip():
                    continue
                try:
                    app_user = json.loads(raw_value)
                except Exception:
                    continue
                if isinstance(app_user, dict) and str(app_user.get("token", "")).strip():
                    has_app_user_token = True
                    break
            if has_app_user_token:
                break

    return has_auth_cookie or has_app_user_token


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
        print(f"[{now_str()}] [TASK] Missing order capture detected, retrying once...")
        retry_code = run_main_command(args, cwd, extra)
        if retry_code != 0:
            return retry_code
        retry_summary = latest_filters_summary(output_dir)
        if should_retry_missing_order_stats(retry_summary):
            print(f"[{now_str()}] [TASK] Warning: filtered capture is still blank after retry, login is likely invalid.")
            return RUN_ONCE_RELOGIN_REQUIRED
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


def ensure_login(args: argparse.Namespace, cwd: Path) -> tuple[bool, str]:
    state_path = (cwd / args.state_path).resolve()
    if has_usable_state(state_path):
        return True, ""

    try:
        code = run_main_command(args, cwd, ["login"], interactive=True)
        if code == 0 and has_usable_state(state_path):
            return True, ""
    except Exception as e:
        return False, f"浏览器启动或登录过程出错：{e}"
    return False, "未检测到有效登录状态。请在浏览器中完成登录后再关闭浏览器。"


def publish_runtime_status(
    status_store: RuntimeStatusStore,
    dashboard_dir: Path,
    *,
    phase: str,
    badge: str,
    badge_state: str,
    message: str,
    detail: str = "",
    next_run_at: str = "",
    last_success_at: str = "",
) -> None:
    status_store.update(
        phase=phase,
        badge=badge,
        badge_state=badge_state,
        message=message,
        detail=detail,
        next_run_at=next_run_at,
        last_success_at=last_success_at,
    )
    write_dashboard_status(
        dashboard_dir,
        phase=phase,
        badge=badge,
        badge_state=badge_state,
        message=message,
        detail=detail,
        next_run_at=next_run_at,
        last_success_at=last_success_at,
    )


def run_service_loop(args: argparse.Namespace, cwd: Path, status_store: RuntimeStatusStore) -> None:
    dashboard_dir = (cwd / args.dashboard_dir).resolve()
    output_dir = (cwd / args.output_dir).resolve()
    state_path = (cwd / args.state_path).resolve()
    server: ThreadingHTTPServer | None = None
    last_success_at = ""
    last_run_finished_ts = 0.0

    write_pid(cwd)
    status_store.update(
        phase="starting",
        badge="启动中",
        badge_state="loading",
        message="管理面板已启动，正在准备运行环境。",
        detail="请勿重复双击；再次双击会直接唤醒这个面板。",
    )

    try:
        setup_logging(cwd)
        ensure_dashboard_placeholder(dashboard_dir)

        if args.interval_minutes <= 0:
            publish_runtime_status(
                status_store,
                dashboard_dir,
                phase="error",
                badge="启动失败",
                badge_state="error",
                message="启动参数无效，无法继续运行。",
                detail="--interval-minutes 必须大于 0。",
                last_success_at=last_success_at,
            )
            return

        if args.keep_output_runs <= 0 or args.keep_single_files <= 0:
            publish_runtime_status(
                status_store,
                dashboard_dir,
                phase="error",
                badge="启动失败",
                badge_state="error",
                message="输出保留参数无效，无法继续运行。",
                detail="--keep-output-runs 和 --keep-single-files 必须大于 0。",
                last_success_at=last_success_at,
            )
            return

        released_pids = auto_free_port(args.host, args.port)
        if released_pids:
            joined = ", ".join(str(pid) for pid in released_pids)
            print(f"[{now_str()}] [WEB] Released occupied port {args.port} from PID(s): {joined}")

        try:
            ensure_port_available(args.host, args.port)
        except RuntimeError as exc:
            publish_runtime_status(
                status_store,
                dashboard_dir,
                phase="error",
                badge="端口被占用",
                badge_state="error",
                message="程序无法启动本地看板服务。",
                detail=str(exc),
                last_success_at=last_success_at,
            )
            return

        publish_runtime_status(
            status_store,
            dashboard_dir,
            phase="starting",
            badge="登录检查中",
            badge_state="loading",
            message="正在检查登录状态。",
            detail="如果需要登录，稍后会自动打开浏览器。",
            last_success_at=last_success_at,
        )
        ok, login_error = ensure_login(args, cwd)
        if not ok:
            publish_runtime_status(
                status_store,
                dashboard_dir,
                phase="relogin_required",
                badge="需要重新登录",
                badge_state="error",
                message="当前登录状态不可用，必须重新登录后才能继续抓取数据。",
                detail=f"{login_error} 请点击“重新登录”，在浏览器中完成登录后关闭浏览器，然后等待 10-60 秒自动刷新。",
                last_success_at=last_success_at,
            )
            return

        check_signal(cwd, SIGNAL_RELOGIN)
        check_signal(cwd, SIGNAL_STOP)
        check_signal(cwd, SIGNAL_RUN_NOW)

        server = start_web_server(dashboard_dir, args.host, args.port)
        interval = timedelta(minutes=args.interval_minutes)
        next_run = datetime.now() if not args.no_run_immediately else datetime.now() + interval
        last_interrupt_ts = 0.0

        publish_runtime_status(
            status_store,
            dashboard_dir,
            phase="starting",
            badge="启动中",
            badge_state="loading",
            message="程序已启动，正在准备展示页。",
            detail="首次启动、重新登录或更新后，页面可能延迟 10-60 秒，请勿重复操作。",
            next_run_at=next_run.strftime("%Y-%m-%d %H:%M:%S"),
            last_success_at=last_success_at,
        )
        if not args.no_clean_output:
            d, f = cleanup_output_dir(output_dir, args.keep_output_runs, args.keep_single_files)
            if d or f:
                print(f"[{now_str()}] [CLEAN] Removed {d} old run dirs and {f} old files.")
        print(f"[{now_str()}] [TASK] Interval: every {args.interval_minutes} minutes")

        while True:
            try:
                if check_signal(cwd, SIGNAL_STOP):
                    print(f"[{now_str()}] [SYS] Stop signal received, shutting down.")
                    publish_runtime_status(
                        status_store,
                        dashboard_dir,
                        phase="stopping",
                        badge="停止中",
                        badge_state="loading",
                        message="正在停止服务，请稍候。",
                        detail="窗口即将关闭。",
                        next_run_at="",
                        last_success_at=last_success_at,
                    )
                    return

                run_now_requested = check_signal(cwd, SIGNAL_RUN_NOW)
                if run_now_requested:
                    now_ts = time.time()
                    print(f"[{now_str()}] [SYS] Received immediate-update signal.")
                    if last_run_finished_ts and (now_ts - last_run_finished_ts) < RUN_NOW_DEBOUNCE_SECONDS:
                        remaining = int(RUN_NOW_DEBOUNCE_SECONDS - (now_ts - last_run_finished_ts))
                        print(f"[{now_str()}] [SYS] Ignored immediate-update signal: last update finished too recently ({remaining}s remaining).")
                        publish_runtime_status(
                            status_store,
                            dashboard_dir,
                            phase="ok" if last_success_at else "starting",
                            badge="运行中" if last_success_at else "启动中",
                            badge_state="live" if last_success_at else "loading",
                            message="刚完成一次数据更新，已忽略重复的立即更新请求。",
                            detail=f"请等待约 {remaining} 秒后再点“数据更新”，不要连续触发。",
                            next_run_at=next_run.strftime("%Y-%m-%d %H:%M:%S"),
                            last_success_at=last_success_at,
                        )
                    else:
                        next_run = datetime.now()
                        print(f"[{now_str()}] [SYS] Accepted immediate-update signal, scheduling update now.")
                        publish_runtime_status(
                            status_store,
                            dashboard_dir,
                            phase="updating",
                            badge="即将更新",
                            badge_state="loading",
                            message="已收到立即更新请求，正在准备抓取最新数据。",
                            detail="请等待 10-60 秒，不要重复点击。",
                            next_run_at=next_run.strftime("%Y-%m-%d %H:%M:%S"),
                            last_success_at=last_success_at,
                        )

                if check_signal(cwd, SIGNAL_RELOGIN):
                    print(f"[{now_str()}] [SYS] Re-login signal received.")
                    publish_runtime_status(
                        status_store,
                        dashboard_dir,
                        phase="relogin_in_progress",
                        badge="重新登录中",
                        badge_state="loading",
                        message="请在弹出的浏览器中完成登录。",
                        detail="登录完成后关闭浏览器，然后等待 10-60 秒自动刷新页面，请勿重复点击。",
                        next_run_at=next_run.strftime("%Y-%m-%d %H:%M:%S"),
                        last_success_at=last_success_at,
                    )
                    login_code = run_main_command(args, cwd, ["login"], interactive=True)
                    if login_code == 0 and has_usable_state(state_path):
                        print(f"[{now_str()}] [SYS] Re-login complete.")
                        next_run = datetime.now()
                        publish_runtime_status(
                            status_store,
                            dashboard_dir,
                            phase="updating",
                            badge="登录已更新",
                            badge_state="loading",
                            message="登录已完成，正在抓取最新数据。",
                            detail="展示页可能延迟 10-60 秒刷新，请勿重复点击。",
                            next_run_at=next_run.strftime("%Y-%m-%d %H:%M:%S"),
                            last_success_at=last_success_at,
                        )
                    else:
                        publish_runtime_status(
                            status_store,
                            dashboard_dir,
                            phase="error",
                            badge="重新登录未完成",
                            badge_state="error",
                            message="这次重新登录没有完成，当前还没有刷新出新数据。",
                            detail="如果你刚关闭浏览器，请等待 10-60 秒；若长时间无变化，再点击“重新登录”。",
                            next_run_at=next_run.strftime("%Y-%m-%d %H:%M:%S"),
                            last_success_at=last_success_at,
                        )

                now = datetime.now()
                if now >= next_run:
                    publish_runtime_status(
                        status_store,
                        dashboard_dir,
                        phase="updating",
                        badge="更新中",
                        badge_state="loading",
                        message="正在抓取和生成最新展示数据。",
                        detail="页面可能延迟 10-60 秒刷新，请勿重复操作。",
                        next_run_at=next_run.strftime("%Y-%m-%d %H:%M:%S"),
                        last_success_at=last_success_at,
                    )
                    started = time.time()
                    code = run_once(args, cwd)
                    elapsed = time.time() - started
                    last_run_finished_ts = time.time()
                    status = "SUCCESS" if code == 0 else "FAILED"
                    print(f"[{now_str()}] [TASK] {status}, elapsed: {elapsed:.1f}s")
                    if not args.no_clean_output:
                        d, f = cleanup_output_dir(output_dir, args.keep_output_runs, args.keep_single_files)
                        if d or f:
                            print(f"[{now_str()}] [CLEAN] Removed {d} old run dirs and {f} old files.")
                    next_run = datetime.now() + interval
                    print(f"[{now_str()}] [TASK] Next run at: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
                    if code == 0:
                        last_success_at = now_str()
                        publish_runtime_status(
                            status_store,
                            dashboard_dir,
                            phase="ok",
                            badge="运行中",
                            badge_state="live",
                            message="更新成功。若页面内容未立即变化，请等待 10-60 秒自动刷新，不要重复操作。",
                            detail=f"上次成功更新时间：{last_success_at}。下次自动更新：{next_run.strftime('%Y-%m-%d %H:%M:%S')}。",
                            next_run_at=next_run.strftime("%Y-%m-%d %H:%M:%S"),
                            last_success_at=last_success_at,
                        )
                    elif code == RUN_ONCE_RELOGIN_REQUIRED:
                        publish_runtime_status(
                            status_store,
                            dashboard_dir,
                            phase="relogin_required",
                            badge="需要重新登录",
                            badge_state="error",
                            message="检测到关键筛选结果异常为空，当前登录状态很可能已经失效。",
                            detail="请立即点击“重新登录”，在浏览器中完成登录后关闭浏览器，然后等待 10-60 秒自动刷新。",
                            next_run_at=next_run.strftime("%Y-%m-%d %H:%M:%S"),
                            last_success_at=last_success_at,
                        )
                    else:
                        publish_runtime_status(
                            status_store,
                            dashboard_dir,
                            phase="error" if has_usable_state(state_path) else "relogin_required",
                            badge="更新失败" if has_usable_state(state_path) else "需要重新登录",
                            badge_state="error",
                            message="本次更新没有成功。若只是刚操作完，请先等待 10-60 秒，不要重复点击。",
                            detail="如果页面长时间空白或一直不更新，再点击“重新登录”。",
                            next_run_at=next_run.strftime("%Y-%m-%d %H:%M:%S"),
                            last_success_at=last_success_at,
                        )
                time.sleep(1.0)
            except KeyboardInterrupt:
                ts = time.time()
                if ts - last_interrupt_ts <= 3.0:
                    print(f"[{now_str()}] [SYS] Stopped by user.")
                    publish_runtime_status(
                        status_store,
                        dashboard_dir,
                        phase="stopping",
                        badge="停止中",
                        badge_state="loading",
                        message="正在停止服务，请稍候。",
                        detail="窗口即将关闭。",
                        next_run_at="",
                        last_success_at=last_success_at,
                    )
                    return
                last_interrupt_ts = ts
                print(f"[{now_str()}] [SYS] Interrupt received. Press Ctrl+C again within 3s to stop.")
                next_run = datetime.now()
    except Exception as e:
        print(f"[ERROR] {e}")
        publish_runtime_status(
            status_store,
            dashboard_dir,
            phase="error",
            badge="程序异常",
            badge_state="error",
            message="服务运行中发生异常。",
            detail=str(e),
            last_success_at=last_success_at,
        )
    finally:
        if server is not None:
            try:
                server.shutdown()
            except Exception:
                pass
            try:
                server.server_close()
            except Exception:
                pass
        remove_pid(cwd)
        status_store.update(service_alive=False)
        if status_store.snapshot().get("phase") == "stopping":
            status_store.update(exit_requested=True)


def main() -> int:
    args = build_parser().parse_args()
    cwd = resolve_runtime_root(Path(__file__))

    instance_lock = acquire_single_instance_lock(cwd)
    if instance_lock is None:
        write_signal(cwd, SIGNAL_SHOW_PANEL)
        return 0

    status_store = RuntimeStatusStore(build_dashboard_url(args.host, args.port))
    app = ControlPanelApp(cwd, args, status_store)
    worker = threading.Thread(
        target=run_service_loop,
        args=(args, cwd, status_store),
        name="dashboard-service",
        daemon=True,
    )
    worker.start()

    try:
        app.run()
    finally:
        if worker.is_alive():
            write_signal(cwd, SIGNAL_STOP)
            if not status_store.snapshot().get("force_exit_requested"):
                worker.join(timeout=5.0)
        release_single_instance_lock(cwd, instance_lock)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
