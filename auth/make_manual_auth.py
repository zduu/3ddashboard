#!/opt/miniconda3/envs/zhouzhou/bin/python
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULT_CONFIG_FILE = Path("make_auth_config.json")
FIRST_LOGIN_API_URL = "https://make.sjtu.edu.cn/api/user/first-login"
MAKE_ORIGIN = "https://make.sjtu.edu.cn"
JWT_REFRESH_MARGIN_SECONDS = 12 * 60 * 60


def load_json_config(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("config root must be a JSON object")
    return data


def require_string(config: Dict[str, Any], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"config field {key!r} must be a non-empty string")
    return value


def optional_string(config: Dict[str, Any], key: str, default: Optional[str] = None) -> Optional[str]:
    value = config.get(key)
    if value is None:
        return default
    if not isinstance(value, str):
        raise ValueError(f"config field {key!r} must be a string")
    return value


def optional_bool(config: Dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"config field {key!r} must be a boolean")
    return value


def optional_int(config: Dict[str, Any], key: str, default: int) -> int:
    value = config.get(key)
    if value is None:
        return default
    if not isinstance(value, int):
        raise ValueError(f"config field {key!r} must be an integer")
    return value


def optional_string_list(config: Dict[str, Any], key: str) -> Optional[list[str]]:
    value = config.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"config field {key!r} must be an array of strings")
    return value


def import_playwright():
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is not installed. Run:\n"
            "  python3 -m pip install playwright\n"
            "  python3 -m playwright install chromium"
        ) from exc
    return sync_playwright, PlaywrightTimeoutError


def normalize_config(path: Path) -> Dict[str, Any]:
    config = load_json_config(path)
    target_url = require_string(config, "target_url")
    login_url = optional_string(config, "login_url", target_url)
    success_url_prefix = optional_string(config, "success_url_prefix", target_url)
    browser = optional_string(config, "browser", "chromium")
    state_file = Path(optional_string(config, "state_file", "make.storage_state.json"))
    headless = optional_bool(config, "headless", False)
    slow_mo_ms = optional_int(config, "slow_mo_ms", 0)
    login_timeout_seconds = optional_int(config, "login_timeout_seconds", 300)
    post_login_wait_ms = optional_int(config, "post_login_wait_ms", 1500)
    cookie_persist_years = optional_int(config, "cookie_persist_years", 10)
    cookie_persist_domains = optional_string_list(config, "cookie_persist_domains")
    token_refresh_margin_seconds = optional_int(
        config,
        "token_refresh_margin_seconds",
        JWT_REFRESH_MARGIN_SECONDS,
    )
    viewport = config.get("viewport")
    if viewport is not None:
        if not isinstance(viewport, dict):
            raise ValueError("config field 'viewport' must be an object")
        width = viewport.get("width")
        height = viewport.get("height")
        if not isinstance(width, int) or not isinstance(height, int):
            raise ValueError("config field 'viewport' must include integer width and height")
        viewport = {"width": width, "height": height}

    return {
        "target_url": target_url,
        "login_url": login_url,
        "success_url_prefix": success_url_prefix,
        "browser": browser,
        "state_file": state_file,
        "headless": headless,
        "slow_mo_ms": slow_mo_ms,
        "login_timeout_seconds": login_timeout_seconds,
        "post_login_wait_ms": post_login_wait_ms,
        "cookie_persist_years": cookie_persist_years,
        "cookie_persist_domains": cookie_persist_domains,
        "token_refresh_margin_seconds": token_refresh_margin_seconds,
        "viewport": viewport,
    }


def build_browser(playwright: Any, browser_name: str) -> Any:
    browsers = {
        "chromium": playwright.chromium,
        "firefox": playwright.firefox,
        "webkit": playwright.webkit,
    }
    try:
        return browsers[browser_name]
    except KeyError as exc:
        raise ValueError(f"unsupported browser: {browser_name!r}") from exc


def should_persist_cookie(cookie: Dict[str, Any], domains: Optional[list[str]]) -> bool:
    if domains is None:
        return True
    domain = cookie.get("domain", "")
    return any(domain == item or domain.endswith(f".{item}") for item in domains)


def rewrite_cookie_expiry(
    storage_state: Dict[str, Any],
    expires_at: float,
    domains: Optional[list[str]],
) -> Dict[str, Any]:
    for cookie in storage_state.get("cookies", []):
        if should_persist_cookie(cookie, domains):
            cookie["expires"] = expires_at
    return storage_state


def compute_cookie_expiry(years: int) -> float:
    return time.time() + years * 365 * 24 * 60 * 60


def format_expiry(expires_at: float) -> str:
    dt_utc = datetime.fromtimestamp(expires_at, tz=timezone.utc)
    dt_local = dt_utc.astimezone()
    return f"{dt_local.isoformat()} (local), {dt_utc.isoformat()} (UTC)"


def rewrite_storage_state_file(path: Path, years: int, domains: Optional[list[str]]) -> tuple[int, float]:
    if not path.exists():
        raise ValueError(f"state file not found: {path}")
    storage_state = load_json_config(path)
    expires_at = compute_cookie_expiry(years)
    storage_state = rewrite_cookie_expiry(storage_state, expires_at, domains)
    path.write_text(json.dumps(storage_state, ensure_ascii=False), encoding="utf-8")
    return len(storage_state.get("cookies", [])), expires_at


def read_storage_state(context: Any) -> Dict[str, Any]:
    try:
        return context.storage_state(indexed_db=True)
    except TypeError:
        return context.storage_state()


def save_storage_state(
    context: Any,
    path: Path,
    years: int,
    domains: Optional[list[str]],
) -> float:
    path.parent.mkdir(parents=True, exist_ok=True)
    storage_state = read_storage_state(context)
    expires_at = compute_cookie_expiry(years)
    storage_state = rewrite_cookie_expiry(storage_state, expires_at, domains)
    path.write_text(json.dumps(storage_state, ensure_ascii=False), encoding="utf-8")
    return expires_at


def load_storage_state_file(path: Path) -> Dict[str, Any]:
    return load_json_config(path)


def save_storage_state_file(path: Path, storage_state: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(storage_state, ensure_ascii=False), encoding="utf-8")


def get_make_origin_state(storage_state: Dict[str, Any]) -> Dict[str, Any]:
    origins = storage_state.setdefault("origins", [])
    if not isinstance(origins, list):
        origins = []
        storage_state["origins"] = origins

    for item in origins:
        if isinstance(item, dict) and item.get("origin") == MAKE_ORIGIN:
            local_storage = item.get("localStorage")
            if not isinstance(local_storage, list):
                item["localStorage"] = []
            return item

    created = {"origin": MAKE_ORIGIN, "localStorage": []}
    origins.append(created)
    return created


def get_local_storage_item(origin_state: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    local_storage = origin_state.get("localStorage")
    if not isinstance(local_storage, list):
        return None
    for item in local_storage:
        if isinstance(item, dict) and item.get("name") == name:
            return item
    return None


def upsert_local_storage_item(origin_state: Dict[str, Any], name: str, value: str) -> None:
    local_storage = origin_state.setdefault("localStorage", [])
    if not isinstance(local_storage, list):
        local_storage = []
        origin_state["localStorage"] = local_storage
    item = get_local_storage_item(origin_state, name)
    if item is None:
        local_storage.append({"name": name, "value": value})
        return
    item["value"] = value


def read_app_user_from_storage_state(storage_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    origin_state = get_make_origin_state(storage_state)
    item = get_local_storage_item(origin_state, "app-user")
    if item is None:
        return None
    value = item.get("value")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def write_app_user_to_storage_state(storage_state: Dict[str, Any], app_user: Dict[str, Any]) -> None:
    origin_state = get_make_origin_state(storage_state)
    upsert_local_storage_item(origin_state, "app-user", json.dumps(app_user, ensure_ascii=False))


def decode_jwt_payload(token: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def read_app_user_token_exp(storage_state: Dict[str, Any]) -> Optional[int]:
    app_user = read_app_user_from_storage_state(storage_state)
    if not app_user:
        return None
    token = app_user.get("token")
    if not isinstance(token, str) or not token:
        return None
    payload = decode_jwt_payload(token)
    exp = None if payload is None else payload.get("exp")
    return exp if isinstance(exp, int) else None


def needs_app_user_token_refresh(state_file: Path, refresh_margin_seconds: int) -> tuple[bool, str]:
    if not state_file.exists():
        raise ValueError(f"state file not found: {state_file}")

    storage_state = load_storage_state_file(state_file)
    exp = read_app_user_token_exp(storage_state)
    if exp is None:
        return True, "token_missing"

    remaining = exp - int(time.time())
    if remaining <= 0:
        return True, "token_expired"
    if remaining <= refresh_margin_seconds:
        return True, "token_expiring_soon"
    return False, "token_still_valid"


def merge_first_login_result(state_file: Path, response_body: Dict[str, Any]) -> None:
    result = response_body.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("first-login result missing")

    user_info = result.get("user_info")
    token = result.get("token")
    if not isinstance(user_info, dict) or not isinstance(token, str) or not token:
        raise RuntimeError("first-login did not return a valid token")

    storage_state = load_storage_state_file(state_file)
    app_user = read_app_user_from_storage_state(storage_state) or {}
    app_user.update(user_info)
    app_user["token"] = token
    write_app_user_to_storage_state(storage_state, app_user)
    save_storage_state_file(state_file, storage_state)


def refresh_app_user_token(
    state_file: Path,
    refresh_margin_seconds: int,
    force: bool = False,
) -> tuple[bool, str]:
    should_refresh, reason = needs_app_user_token_refresh(state_file, refresh_margin_seconds)
    if not should_refresh and not force:
        return False, reason

    sync_playwright, _ = import_playwright()
    with sync_playwright() as playwright:
        request_context = playwright.request.new_context(storage_state=str(state_file))
        try:
            resp = request_context.get(FIRST_LOGIN_API_URL)
            status = int(getattr(resp, "status", 0) or 0)
            if status >= 400:
                raise RuntimeError(f"first-login HTTP {status}: {resp.text()[:300]}")
            response_body = resp.json()
        finally:
            request_context.dispose()

    if not isinstance(response_body, dict):
        raise RuntimeError("first-login returned invalid JSON")
    merge_first_login_result(state_file, response_body)
    return True, reason if should_refresh else "forced_refresh"


def format_jwt_expiry(state_file: Path) -> str:
    storage_state = load_storage_state_file(state_file)
    exp = read_app_user_token_exp(storage_state)
    if exp is None:
        return "missing"
    return format_expiry(float(exp))


def make_context(browser: Any, config: Dict[str, Any], state_file: Optional[Path] = None) -> Any:
    kwargs: Dict[str, Any] = {}
    if config["viewport"] is not None:
        kwargs["viewport"] = config["viewport"]
    if state_file is not None and state_file.exists():
        kwargs["storage_state"] = str(state_file)
    return browser.new_context(**kwargs)


def wait_for_login_completion(page: Any, config: Dict[str, Any], timeout_seconds: int, login_start_url: str) -> bool:
    timeout_ms = timeout_seconds * 1000
    deadline = time.monotonic() + timeout_seconds

    try:
        page.wait_for_url(lambda url: url != login_start_url, timeout=timeout_ms)
    except Exception:
        return False

    remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
    success_prefix = config["success_url_prefix"]

    try:
        page.wait_for_url(
            lambda url: url.startswith(success_prefix) and url != login_start_url,
            timeout=remaining_ms,
        )
        page.wait_for_timeout(config["post_login_wait_ms"])
        return True
    except Exception:
        return False


def run_login(config_path: Path) -> int:
    config = normalize_config(config_path)
    sync_playwright, PlaywrightTimeoutError = import_playwright()

    with sync_playwright() as playwright:
        browser_type = build_browser(playwright, config["browser"])
        browser = browser_type.launch(headless=config["headless"], slow_mo=config["slow_mo_ms"])
        context = make_context(browser, config)
        page = context.new_page()
        page.goto(config["login_url"], wait_until="domcontentloaded")
        login_start_url = page.url

        print("Browser opened. Complete the jAccount login manually.")
        print("Open the make authorization page and click the jAccount login entry manually.")
        print(f"Waiting for return to: {config['success_url_prefix']}")
        print("If auto-detection times out, return to this terminal and press Enter to save anyway.")

        login_detected = wait_for_login_completion(
            page,
            config,
            config["login_timeout_seconds"],
            login_start_url,
        )
        if not login_detected:
            input("Login not auto-detected. If the page is already logged in, press Enter to save state. ")

        expires_at = save_storage_state(
            context,
            config["state_file"],
            config["cookie_persist_years"],
            config["cookie_persist_domains"],
        )
        cookie_count = len(context.cookies())
        print(f"State saved to: {config['state_file'].resolve()}")
        print(f"Current page: {page.url}")
        print(f"Cookies saved: {cookie_count}")
        print(f"Cookie expiry set to: {format_expiry(expires_at)}")
        browser.close()
    return 0


def run_open(config_path: Path) -> int:
    config = normalize_config(config_path)
    state_file = config["state_file"]
    if not state_file.exists():
        raise ValueError(f"state file not found: {state_file}")

    refreshed, reason = refresh_app_user_token(
        state_file,
        config["token_refresh_margin_seconds"],
    )
    if refreshed:
        print(f"app-user.token refreshed before open: {reason}")

    sync_playwright, _ = import_playwright()

    with sync_playwright() as playwright:
        browser_type = build_browser(playwright, config["browser"])
        browser = browser_type.launch(headless=config["headless"], slow_mo=config["slow_mo_ms"])
        context = make_context(browser, config, state_file=state_file)
        page = context.new_page()
        page.goto(config["target_url"], wait_until="domcontentloaded")
        print(f"Opened with saved state: {page.url}")
        input("Browse normally. When finished, return to this terminal and press Enter to save updated state. ")
        expires_at = save_storage_state(
            context,
            state_file,
            config["cookie_persist_years"],
            config["cookie_persist_domains"],
        )
        print(f"State refreshed: {state_file.resolve()}")
        print(f"Cookie expiry set to: {format_expiry(expires_at)}")
        print(f"JWT expiry: {format_jwt_expiry(state_file)}")
        browser.close()
    return 0


def run_clear(config_path: Path) -> int:
    config = normalize_config(config_path)
    state_file = config["state_file"]
    if state_file.exists():
        state_file.unlink()
        print(f"Deleted: {state_file.resolve()}")
    else:
        print(f"Nothing to delete: {state_file.resolve()}")
    return 0


def run_rewrite(config_path: Path) -> int:
    config = normalize_config(config_path)
    cookie_count, expires_at = rewrite_storage_state_file(
        config["state_file"],
        config["cookie_persist_years"],
        config["cookie_persist_domains"],
    )
    print(f"Rewrote cookie expiry in: {config['state_file'].resolve()}")
    print(f"Cookies updated: {cookie_count}")
    print(f"Cookie expiry set to: {format_expiry(expires_at)}")
    return 0


def run_refresh(config_path: Path) -> int:
    config = normalize_config(config_path)
    state_file = config["state_file"]
    refreshed, reason = refresh_app_user_token(
        state_file,
        config["token_refresh_margin_seconds"],
        force=True,
    )
    print(f"State refreshed: {state_file.resolve()}")
    print(f"Refresh action: {'performed' if refreshed else 'skipped'} ({reason})")
    print(f"JWT expiry: {format_jwt_expiry(state_file)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Open Make in a Playwright browser, let you log in manually once, "
            "and persist the authenticated browser state for reuse."
        )
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_FILE),
        help="JSON config file path, default: %(default)s",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("login", help="open browser for manual login and save auth state")
    subparsers.add_parser("open", help="open browser with saved auth state loaded")
    subparsers.add_parser("refresh", help="refresh saved app-user token via cookie session")
    subparsers.add_parser("rewrite", help="rewrite saved cookie expiry in the state file")
    subparsers.add_parser("clear", help="delete the saved auth state file")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    config_path = Path(args.config)
    try:
        if args.command == "login":
            return run_login(config_path)
        if args.command == "open":
            return run_open(config_path)
        if args.command == "refresh":
            return run_refresh(config_path)
        if args.command == "rewrite":
            return run_rewrite(config_path)
        if args.command == "clear":
            return run_clear(config_path)
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
