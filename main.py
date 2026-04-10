import argparse
import csv
import json
import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

from playwright.sync_api import Page, sync_playwright
from dashboard_builder import build_dashboard

DEFAULT_BROWSER_CHANNEL = "auto"


DEFAULT_PAGE_URL = "https://make.sjtu.edu.cn/admin/statistics/order-count"
ASSIST_PAGE_URL = "https://make.sjtu.edu.cn/admin/statistics/assist-action"
ASSIST_API_URL = "https://make.sjtu.edu.cn/api/statistics/assist-action"
DEFAULT_STATE_PATH = Path("state/auth_state.json")
DEFAULT_OUTPUT_DIR = Path("output")
DEFAULT_DASHBOARD_DIR = Path("dashboard")
DEFAULT_WAIT_MS = 10000
DEFAULT_FILTER_WAIT_MS = 3500
IGNORED_CAPTURE_PATTERNS = []


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def safe_slug(text: str) -> str:
    text = text.strip()
    if not text:
        return "empty"

    out: list[str] = []
    for ch in text:
        if ch.isascii() and (ch.isalnum() or ch in {"-", "_"}):
            out.append(ch.lower())
        elif ch.isspace():
            out.append("_")
        else:
            out.append(f"u{ord(ch):x}")

    slug = re.sub(r"_+", "_", "".join(out)).strip("_")
    return slug or "item"


def save_login_state(page_url: str, state_path: Path, browser_channel: str | None) -> None:
    ensure_parent_dir(state_path)
    with sync_playwright() as p:
        browser = launch_browser(p, headless=False, channel=browser_channel)
        context = browser.new_context()
        page = context.new_page()
        page.goto(page_url, wait_until="domcontentloaded")

        print("[INFO] Browser opened. Please login, then CLOSE the browser to continue.")
        # Block until user closes the browser window.
        try:
            page.wait_for_event("close", timeout=600_000)  # 10 min max
        except Exception:
            pass

        try:
            context.storage_state(path=str(state_path))
        except Exception:
            pass

        try:
            browser.close()
        except Exception:
            pass

    print(f"[OK] Login session saved: {state_path}")


def try_parse_json(response_text: str) -> Any | None:
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        return None


def write_records(records: list[dict[str, Any]], json_file: Path, csv_file: Path) -> None:
    with json_file.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    with csv_file.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "time",
                "url",
                "method",
                "status",
                "content_type",
                "is_json",
                "preview",
            ],
        )
        writer.writeheader()
        for item in records:
            if item["is_json"]:
                preview = json.dumps(item["json_data"], ensure_ascii=False)[:1000]
            else:
                preview = str(item["text_data"])[:1000]
            writer.writerow(
                {
                    "time": item["time"],
                    "url": item["url"],
                    "method": item["method"],
                    "status": item["status"],
                    "content_type": item["content_type"],
                    "is_json": item["is_json"],
                    "preview": preview,
                }
            )


def build_record(resp: Any) -> dict[str, Any]:
    method = resp.request.method
    url = resp.url
    status = resp.status
    content_type = resp.headers.get("content-type", "")

    try:
        body_text = resp.text()
    except Exception:
        body_text = ""

    parsed = None
    if "json" in content_type.lower():
        parsed = try_parse_json(body_text)
    elif body_text[:1] in {"{", "["}:
        parsed = try_parse_json(body_text)

    return {
        "time": datetime.now().isoformat(timespec="seconds"),
        "url": url,
        "method": method,
        "status": status,
        "content_type": content_type,
        "is_json": parsed is not None,
        "json_data": parsed,
        "text_data": body_text if parsed is None else "",
    }


def iter_browser_channels(channel: str | None) -> list[str | None]:
    ch = (channel or "").strip().lower()
    if not ch or ch == "default":
        return [None]
    if ch == "auto":
        order: list[str | None] = []
        if sys.platform.startswith("win"):
            order = ["msedge", "chrome", "chromium", None]
        elif sys.platform == "darwin":
            order = ["chrome", "msedge", "chromium", None]
        else:
            order = ["chromium", "chrome", None]
        return order
    return [ch, None]


def launch_browser(p, headless: bool, channel: str | None):
    last_error: Exception | None = None
    for candidate in iter_browser_channels(channel):
        launch_args: dict[str, Any] = {"headless": headless}
        if candidate:
            launch_args["channel"] = candidate
        try:
            browser = p.chromium.launch(**launch_args)
            if candidate:
                print(f"[INFO] Using browser channel: {candidate}")
            else:
                print("[INFO] Using bundled Playwright Chromium")
            return browser
        except Exception as e:
            last_error = e
            print(f"[WARN] Failed to launch channel '{candidate or 'default'}': {e}")
            continue
    raise last_error if last_error else RuntimeError("Unable to launch browser")


def fetch_assist_actions(
    assist_api_url: str,
    state_path: Path,
    output_dir: Path,
) -> Path | None:
    if not state_path.exists():
        raise FileNotFoundError(f"State file not found: {state_path}")

    today = datetime.now().date().isoformat()
    params = urlencode(
        {
            "process_type": "thdprint",
            "start_date": today,
            "end_date": today,
        }
    )
    url = f"{assist_api_url}?{params}"

    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / f"assist_api_{now_tag()}.json"

    with sync_playwright() as p:
        request_context = p.request.new_context(storage_state=str(state_path))
        try:
            print(f"[INFO] Fetching assist actions via request: {url}")
            resp = request_context.get(url)
            status = int(getattr(resp, "status", 0) or 0)
            if status >= 400:
                raise RuntimeError(f"Assist API HTTP {status}: {resp.text()[:300]}")
            data = resp.json()
        finally:
            request_context.dispose()

    with dest.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return dest


def capture_data(
    page_url: str,
    state_path: Path,
    output_dir: Path,
    wait_ms: int,
    headless: bool,
    browser_channel: str | None,
    label: str,
) -> tuple[Path, Path]:
    if not state_path.exists():
        raise FileNotFoundError(
            f"State file not found: {state_path}. Run login first."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []

    with sync_playwright() as p:
        browser = launch_browser(p, headless=headless, channel=browser_channel)
        context = browser.new_context(storage_state=str(state_path))
        page = context.new_page()

        def on_response(resp: Any) -> None:
            if resp.request.resource_type not in {"xhr", "fetch"}:
                return
            if any(pattern in resp.url for pattern in IGNORED_CAPTURE_PATTERNS):
                return
            records.append(build_record(resp))

        page.on("response", on_response)
        page.goto(page_url, wait_until="networkidle")
        page.wait_for_timeout(wait_ms)
        browser.close()

    if not records:
        raise RuntimeError("No XHR/Fetch responses captured. Check login and page access.")

    tag = now_tag()
    prefix = safe_slug(label)
    json_file = output_dir / f"responses_{prefix}_{tag}.json"
    csv_file = output_dir / f"responses_{prefix}_{tag}.csv"
    write_records(records, json_file, csv_file)
    return json_file, csv_file


def detect_filter_buttons(page: Page, filter_selector: str | None) -> list[dict[str, Any]]:
    selector = (
        filter_selector
        if filter_selector
        else "button, [role='button'], .el-radio-button, .el-radio-button__inner, "
        ".ant-radio-button-wrapper, .el-tabs__item, .ant-tabs-tab, .el-button"
    )

    items = page.evaluate(
        """
        (selector) => {
            function isVisible(el) {
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
            }

            function nthPath(el) {
                if (!el || el.nodeType !== 1) return '';
                const parts = [];
                while (el && el.nodeType === 1) {
                    const tag = el.tagName.toLowerCase();
                    if (tag === 'html') {
                        parts.unshift('html');
                        break;
                    }

                    let idx = 1;
                    let sib = el.previousElementSibling;
                    while (sib) {
                        if (sib.tagName === el.tagName) idx += 1;
                        sib = sib.previousElementSibling;
                    }
                    parts.unshift(`${tag}:nth-of-type(${idx})`);
                    el = el.parentElement;
                }
                return parts.join(' > ');
            }

            const list = [];
            const seen = new Set();
            const badWords = ['登录', '退出', '保存', '取消', '返回', '删除', '编辑', '新增', '管理'];

            for (const el of document.querySelectorAll(selector)) {
                if (!isVisible(el)) continue;

                const text = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
                if (!text || text.length > 20) continue;
                if (badWords.some(w => text.includes(w))) continue;

                const path = nthPath(el);
                if (!path || seen.has(path)) continue;
                seen.add(path);

                const cls = String(el.className || '');
                const activeHint = `${cls} ${el.getAttribute('aria-selected') || ''} ${el.getAttribute('aria-pressed') || ''}`.toLowerCase();
                const active = /(active|selected|checked|current|true)/.test(activeHint);

                list.push({
                    text,
                    path,
                    parent_path: nthPath(el.parentElement),
                    class_name: cls,
                    tag: el.tagName.toLowerCase(),
                    active,
                });
            }

            return list;
        }
        """,
        selector,
    )

    if filter_selector:
        return items

    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        groups.setdefault(item["parent_path"], []).append(item)

    best: list[dict[str, Any]] = []
    best_score = -10**9

    for group in groups.values():
        n = len(group)
        if n < 2 or n > 12:
            continue

        texts = [g["text"] for g in group]
        unique_count = len(set(texts))
        avg_len = sum(len(t) for t in texts) / n
        class_blob = " ".join(g["class_name"] for g in group).lower()
        active_count = sum(1 for g in group if g["active"])

        score = 0
        score += n * 3
        score += unique_count * 2
        score -= int(avg_len)
        score += active_count * 2
        if any(k in class_blob for k in ["radio", "tab", "button", "btn"]):
            score += 6

        if score > best_score:
            best_score = score
            best = group

    if not best:
        return []

    # Stable traversal order by DOM path.
    return sorted(best, key=lambda x: x["path"])


def capture_data_by_filters(
    page_url: str,
    state_path: Path,
    output_dir: Path,
    wait_ms: int,
    filter_wait_ms: int,
    headless: bool,
    browser_channel: str | None,
    filter_selector: str | None,
) -> tuple[Path, Path]:
    if not state_path.exists():
        raise FileNotFoundError(
            f"State file not found: {state_path}. Run login first."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    tag = now_tag()
    run_dir = output_dir / f"filters_{tag}"
    run_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = launch_browser(p, headless=headless, channel=browser_channel)
        context = browser.new_context(storage_state=str(state_path))
        page = context.new_page()

        current_bucket: list[dict[str, Any]] | None = None

        def on_response(resp: Any) -> None:
            nonlocal current_bucket
            if resp.request.resource_type not in {"xhr", "fetch"}:
                return
            if current_bucket is None:
                return
            if any(pattern in resp.url for pattern in IGNORED_CAPTURE_PATTERNS):
                return
            current_bucket.append(build_record(resp))

        def rewrite_assist_date(route: Any) -> None:
            """Rewrite assist-action requests to query today only."""
            request = route.request
            parsed = urlparse(request.url)
            if "/api/statistics/assist-action" in parsed.path:
                today = datetime.now().date().isoformat()
                qs = parse_qs(parsed.query)
                qs["start_date"] = [today]
                qs["end_date"] = [today]
                new_query = urlencode({k: v[0] for k, v in qs.items()})
                new_url = urlunparse(parsed._replace(query=new_query))
                route.continue_(url=new_url)
            else:
                route.continue_()

        page.route("**/api/statistics/assist-action*", rewrite_assist_date)
        page.on("response", on_response)

        summary_items: list[dict[str, Any]] = []

        current_bucket = []
        page.goto(page_url, wait_until="networkidle")
        page.wait_for_timeout(wait_ms)
        initial_records = list(current_bucket)
        current_bucket = None

        initial_json = run_dir / "00_initial.json"
        initial_csv = run_dir / "00_initial.csv"
        write_records(initial_records, initial_json, initial_csv)
        summary_items.append(
            {
                "index": 0,
                "label": "initial",
                "record_count": len(initial_records),
                "json_file": str(initial_json),
                "csv_file": str(initial_csv),
                "error": "",
            }
        )

        filters = detect_filter_buttons(page, filter_selector)
        print(f"[INFO] Detected filter buttons: {len(filters)}")

        if not filters:
            browser.close()
            summary = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "page_url": page_url,
                "filter_selector": filter_selector or "auto",
                "detected_filter_count": 0,
                "items": summary_items,
                "note": "No filter buttons detected. Only initial data exported.",
            }
            summary_json = run_dir / "summary.json"
            summary_csv = run_dir / "summary.csv"
            with summary_json.open("w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
            with summary_csv.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["index", "label", "record_count", "json_file", "csv_file", "error"],
                )
                writer.writeheader()
                writer.writerows(summary_items)
            return summary_json, summary_csv

        used_labels: set[str] = set()
        for idx, flt in enumerate(filters, start=1):
            raw_label = flt["text"]
            base_label = safe_slug(raw_label)
            label = base_label
            suffix = 2
            while label in used_labels:
                label = f"{base_label}_{suffix}"
                suffix += 1
            used_labels.add(label)

            json_file = run_dir / f"{idx:02d}_{label}.json"
            csv_file = run_dir / f"{idx:02d}_{label}.csv"

            bucket: list[dict[str, Any]] = []
            current_bucket = bucket
            err = ""

            try:
                locator = page.locator(f"css={flt['path']}").first
                locator.scroll_into_view_if_needed(timeout=5000)
                locator.click(timeout=5000)
                try:
                    page.wait_for_load_state("networkidle", timeout=6000)
                except Exception:
                    pass
                page.wait_for_timeout(filter_wait_ms)
            except Exception as e:
                err = str(e)

            current_bucket = None
            write_records(bucket, json_file, csv_file)

            summary_items.append(
                {
                    "index": idx,
                    "label": raw_label,
                    "record_count": len(bucket),
                    "json_file": str(json_file),
                    "csv_file": str(csv_file),
                    "error": err,
                }
            )

        browser.close()

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "page_url": page_url,
        "filter_selector": filter_selector or "auto",
        "detected_filter_count": len(filters),
        "items": summary_items,
    }

    summary_json = run_dir / "summary.json"
    summary_csv = run_dir / "summary.csv"

    with summary_json.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    with summary_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["index", "label", "record_count", "json_file", "csv_file", "error"],
        )
        writer.writeheader()
        writer.writerows(summary_items)

    return summary_json, summary_csv


def refresh_dashboard(output_dir: Path, dashboard_dir: Path, run_path: Path) -> None:
    html_file, data_file = build_dashboard(
        output_dir=output_dir,
        dashboard_dir=dashboard_dir,
        run_path=run_path,
    )
    print(f"[OK] Dashboard HTML saved: {html_file}")
    print(f"[OK] Dashboard data saved: {data_file}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Capture authenticated data from SJTU make platform page."
    )
    parser.add_argument("--page-url", default=DEFAULT_PAGE_URL, help="Order statistics page URL.")
    parser.add_argument(
        "--assist-page-url",
        default=ASSIST_PAGE_URL,
        help="Assist action statistics page URL.",
    )
    parser.add_argument(
        "--assist-api-url",
        default=ASSIST_API_URL,
        help="Assist action API URL for direct fetch.",
    )
    parser.add_argument(
        "--state-path",
        default=str(DEFAULT_STATE_PATH),
        help="Path for saved login session file.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for exported data files.",
    )
    parser.add_argument(
        "--dashboard-dir",
        default=str(DEFAULT_DASHBOARD_DIR),
        help="Directory for generated dashboard files.",
    )
    parser.add_argument(
        "--browser-channel",
        default=DEFAULT_BROWSER_CHANNEL,
        help="Browser channel: auto/msedge/chrome/chromium. 'auto' will try installed browsers then fallback to bundled Chromium.",
    )
    parser.add_argument(
        "--filter-selector",
        default="",
        help="Optional CSS selector for filter buttons. Empty means auto detect.",
    )
    parser.add_argument(
        "--filter-wait-ms",
        type=int,
        default=DEFAULT_FILTER_WAIT_MS,
        help="Wait time after each filter click, in milliseconds.",
    )
    parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Skip dashboard generation after data capture.",
    )

    sub = parser.add_subparsers(dest="command", required=False)

    sub.add_parser("login", help="Open browser to login and save session.")

    fetch = sub.add_parser("fetch", help="Use saved session and capture page data.")
    fetch.add_argument(
        "--wait-ms",
        type=int,
        default=DEFAULT_WAIT_MS,
        help="Extra wait time after loading page, in milliseconds.",
    )
    fetch.add_argument(
        "--headed",
        action="store_true",
        help="Run with visible browser window for debugging.",
    )
    fetch.add_argument(
        "--single",
        action="store_true",
        help="Only capture initial load without traversing filters.",
    )

    all_cmd = sub.add_parser("all", help="Run login then fetch in one flow.")
    all_cmd.add_argument(
        "--wait-ms",
        type=int,
        default=DEFAULT_WAIT_MS,
        help="Extra wait time after loading page, in milliseconds.",
    )
    all_cmd.add_argument(
        "--single",
        action="store_true",
        help="Only capture initial load without traversing filters.",
    )

    return parser


def cleanup_old_runs(output_dir: Path, keep: int = 3) -> None:
    """Remove old filter/response runs, keeping only the most recent *keep*."""
    runs = sorted(
        [p for p in output_dir.iterdir() if p.is_dir() and p.name.startswith("filters_")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in runs[keep:]:
        try:
            shutil.rmtree(old)
            print(f"[CLEAN] Removed old run: {old.name}")
        except Exception as e:
            print(f"[WARN] Failed to remove {old.name}: {e}")

    singles = sorted(
        [p for p in output_dir.iterdir() if p.is_file() and p.name.startswith("responses_")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in singles[keep * 2:]:
        try:
            old.unlink()
            print(f"[CLEAN] Removed old file: {old.name}")
        except Exception as e:
            print(f"[WARN] Failed to remove {old.name}: {e}")

    assist_files = sorted(
        [p for p in output_dir.iterdir() if p.is_file() and p.name.startswith("assist_api_")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in assist_files[keep:]:
        try:
            old.unlink()
            print(f"[CLEAN] Removed old file: {old.name}")
        except Exception as e:
            print(f"[WARN] Failed to remove {old.name}: {e}")


def run_fetch(
    page_url: str,
    assist_page_url: str,
    assist_api_url: str,
    state_path: Path,
    output_dir: Path,
    dashboard_dir: Path,
    wait_ms: int,
    filter_wait_ms: int,
    headless: bool,
    browser_channel: str | None,
    filter_selector: str | None,
    single: bool,
    generate_dashboard: bool,
) -> int:
    orders_path: Path | None = None

    if single:
        json_file, csv_file = capture_data(
            page_url=page_url,
            state_path=state_path,
            output_dir=output_dir,
            wait_ms=wait_ms,
            headless=headless,
            browser_channel=browser_channel,
            label="orders",
        )
        print(f"[OK] JSON saved: {json_file}")
        print(f"[OK] CSV saved:  {csv_file}")
        orders_path = json_file
    else:
        summary_json, summary_csv = capture_data_by_filters(
            page_url=page_url,
            state_path=state_path,
            output_dir=output_dir,
            wait_ms=wait_ms,
            filter_wait_ms=filter_wait_ms,
            headless=headless,
            browser_channel=browser_channel,
            filter_selector=filter_selector,
        )
        print(f"[OK] Summary JSON saved: {summary_json}")
        print(f"[OK] Summary CSV saved:  {summary_csv}")
        orders_path = summary_json.parent

    assist_json: Path | None = None
    try:
        assist_json = fetch_assist_actions(
            assist_api_url=assist_api_url,
            state_path=state_path,
            output_dir=output_dir,
        )
        if assist_json:
            print(f"[OK] Assist JSON saved: {assist_json}")
    except Exception as assist_err:
        print(f"[WARN] Assist-action capture failed: {assist_err}")

    if assist_json and orders_path is not None:
        target = orders_path if orders_path.is_dir() else orders_path.parent
        latest_path = target / "assist_latest.json"
        try:
            shutil.copy2(assist_json, latest_path)
        except Exception as copy_err:
            print(f"[WARN] Failed to store assist data alongside run: {copy_err}")

        dest = target / "04_u52a9u7ba1u7edfu8ba1.json"
        try:
            shutil.copy2(assist_json, dest)
        except Exception as copy_err:
            print(f"[WARN] Failed to store {dest.name}: {copy_err}")

    if generate_dashboard and orders_path is not None:
        refresh_dashboard(output_dir, dashboard_dir, orders_path)

    # Keep only the 3 most recent runs in output_dir.
    cleanup_old_runs(output_dir, keep=3)

    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    state_path = Path(args.state_path)
    output_dir = Path(args.output_dir)
    dashboard_dir = Path(args.dashboard_dir)
    channel = args.browser_channel if args.browser_channel else None
    filter_selector = args.filter_selector.strip() or None
    generate_dashboard = not args.no_dashboard

    try:
        if args.command is None:
            if state_path.exists():
                print("[AUTO] Found saved session, running filter traversal fetch.")
                return run_fetch(
                    page_url=args.page_url,
                    assist_page_url=args.assist_page_url,
                    assist_api_url=args.assist_api_url,
                    state_path=state_path,
                    output_dir=output_dir,
                    dashboard_dir=dashboard_dir,
                    wait_ms=DEFAULT_WAIT_MS,
                    filter_wait_ms=args.filter_wait_ms,
                    headless=True,
                    browser_channel=channel,
                    filter_selector=filter_selector,
                    single=False,
                    generate_dashboard=generate_dashboard,
                )

            print("[AUTO] No saved session, running login + filter traversal fetch.")
            save_login_state(args.page_url, state_path, channel)
            return run_fetch(
                page_url=args.page_url,
                assist_page_url=args.assist_page_url,
                assist_api_url=args.assist_api_url,
                state_path=state_path,
                output_dir=output_dir,
                dashboard_dir=dashboard_dir,
                wait_ms=DEFAULT_WAIT_MS,
                filter_wait_ms=args.filter_wait_ms,
                headless=True,
                browser_channel=channel,
                filter_selector=filter_selector,
                single=False,
                generate_dashboard=generate_dashboard,
            )

        if args.command == "login":
            save_login_state(args.page_url, state_path, channel)
            return 0

        if args.command == "fetch":
            return run_fetch(
                page_url=args.page_url,
                assist_page_url=args.assist_page_url,
                assist_api_url=args.assist_api_url,
                state_path=state_path,
                output_dir=output_dir,
                dashboard_dir=dashboard_dir,
                wait_ms=args.wait_ms,
                filter_wait_ms=args.filter_wait_ms,
                headless=not args.headed,
                browser_channel=channel,
                filter_selector=filter_selector,
                single=args.single,
                generate_dashboard=generate_dashboard,
            )

        if args.command == "all":
            save_login_state(args.page_url, state_path, channel)
            return run_fetch(
                page_url=args.page_url,
                assist_page_url=args.assist_page_url,
                assist_api_url=args.assist_api_url,
                state_path=state_path,
                output_dir=output_dir,
                dashboard_dir=dashboard_dir,
                wait_ms=args.wait_ms,
                filter_wait_ms=args.filter_wait_ms,
                headless=True,
                browser_channel=channel,
                filter_selector=filter_selector,
                single=args.single,
                generate_dashboard=generate_dashboard,
            )
    except KeyboardInterrupt:
        print("Interrupted.")
        return 130
    except Exception as e:
        print(f"[ERROR] {e}")
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
