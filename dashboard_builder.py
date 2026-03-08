import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_OUTPUT_DIR = Path("output")
DEFAULT_DASHBOARD_DIR = Path("dashboard")

STATUS_MAP = {
    "wait-for-approval": "待审核",
    "printing": "打印中",
    "pickup": "待取件",
    "complete": "已完成",
    "refused": "已拒绝",
    "canceled": "已取消",
}

ACTION_MAP = {
    "approve-order": "通过审核",
    "done-for-pickup": "标记待取件",
    "refuse-order": "拒绝订单",
    "complete-order": "完成订单",
    "record-fail": "登记异常",
    "resign-user": "助管离岗",
    "update-order-price": "修改价格",
    "recall-order": "撤回订单",
}


def maybe_fix_mojibake(text: str) -> str:
    if not isinstance(text, str):
        return str(text)
    try:
        fixed = text.encode("gbk").decode("utf-8")
    except Exception:
        return text

    def cjk_count(s: str) -> int:
        return sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")

    return fixed if cjk_count(fixed) > cjk_count(text) else text


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_date(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    m = re.search(r"\d{4}-\d{2}-\d{2}", text)
    return m.group(0) if m else ""


def find_latest_source(output_dir: Path) -> tuple[str, Path]:
    runs = [p for p in output_dir.glob("filters_*") if p.is_dir()]
    if runs:
        return "filters", max(runs, key=lambda p: p.stat().st_mtime)

    singles = list(output_dir.glob("responses_*.json"))
    if singles:
        return "single", max(singles, key=lambda p: p.stat().st_mtime)

    raise FileNotFoundError(f"未找到抓取结果目录: {output_dir}")


def collect_record_files(source_type: str, source_path: Path) -> tuple[list[Path], list[dict[str, Any]]]:
    if source_type == "single":
        return [source_path], []

    files = sorted([p for p in source_path.glob("*.json") if p.name != "summary.json"])
    summary_items: list[dict[str, Any]] = []
    summary_path = source_path / "summary.json"
    if summary_path.exists():
        try:
            payload = read_json(summary_path)
            if isinstance(payload, dict) and isinstance(payload.get("items"), list):
                summary_items = [x for x in payload["items"] if isinstance(x, dict)]
        except Exception:
            pass
    return files, summary_items


def has_core_order_data(source_path: Path) -> bool:
    """Whether a filters_* run contains /order-list responses with data."""
    if not source_path.is_dir():
        return False

    for file in sorted(source_path.glob("*.json")):
        if file.name == "summary.json":
            continue
        try:
            rows = read_json(file)
        except Exception:
            continue
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            url = str(row.get("url", ""))
            if "/api/statistics/order-list" not in url:
                continue
            payload = row.get("json_data")
            if not isinstance(payload, dict):
                continue
            result = payload.get("result")
            if isinstance(result, list) and len(result) > 0:
                return True
            if isinstance(result, dict):
                for key in ("list", "data", "items", "rows"):
                    val = result.get(key)
                    if isinstance(val, list) and len(val) > 0:
                        return True
    return False


def is_payload_effectively_empty(payload: dict[str, Any]) -> bool:
    cards = payload.get("指标卡", {}) if isinstance(payload, dict) else {}
    tables = payload.get("表格", {}) if isinstance(payload, dict) else {}
    total = cards.get("统计区间3D订单总量", 0) if isinstance(cards, dict) else 0
    recent = tables.get("最近3D订单", []) if isinstance(tables, dict) else []
    return int(total or 0) <= 0 and len(recent) == 0


def find_latest_valid_filters_run(output_dir: Path, exclude_path: Path | None = None) -> Path | None:
    runs = sorted([p for p in output_dir.glob("filters_*") if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)
    for run in runs:
        if exclude_path is not None and run.resolve() == exclude_path.resolve():
            continue
        if has_core_order_data(run):
            return run
    return None


def flatten_order_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, dict):
        for key in ("list", "data", "items", "rows"):
            v = value.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    return []


def pick_endpoint_results(record_files: list[Path]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "order_list": None,
        "assist_action": None,
    }

    for file in record_files:
        try:
            rows = read_json(file)
        except Exception:
            continue

        if not isinstance(rows, list):
            continue

        for row in rows:
            if not isinstance(row, dict):
                continue
            url = str(row.get("url", ""))
            payload = row.get("json_data")
            if not isinstance(payload, dict):
                continue
            result = payload.get("result")
            if result is None:
                continue

            if "/api/statistics/order-list" in url:
                if out["order_list"] is None:
                    out["order_list"] = result
                else:
                    prev = flatten_order_list(out["order_list"])
                    curr = flatten_order_list(result)
                    if len(curr) >= len(prev):
                        out["order_list"] = result
            elif "/api/statistics/assist-action" in url:
                if out["assist_action"] is None:
                    out["assist_action"] = result
                else:
                    prev = out["assist_action"] if isinstance(out["assist_action"], list) else []
                    curr = result if isinstance(result, list) else []
                    if len(curr) >= len(prev):
                        out["assist_action"] = result

    return out


def is_3d_order(order: dict[str, Any]) -> bool:
    ptype = str(order.get("process_type", "")).strip().lower()
    if ptype in {"thdprint", "3dprint", "3d_print", "3d"}:
        return True

    cfg = order.get("process_config")
    if isinstance(cfg, dict):
        text = " ".join(str(cfg.get(k, "")) for k in ("print_type", "technology", "type")).lower()
        if any(tag in text for tag in ("fdm", "fff", "sla", "sls", "3d")):
            return True

    return False


def status_zh(status: str) -> str:
    s = str(status or "").strip().lower()
    if not s:
        return "未知"
    return STATUS_MAP.get(s, f"其他（{s}）")


def action_zh(action: str) -> str:
    a = str(action or "").strip().lower()
    if not a:
        return "未知"
    return ACTION_MAP.get(a, f"其他操作（{a}）")


def process_for_zh(order: dict[str, Any]) -> str:
    pf = order.get("process_for")
    if isinstance(pf, dict):
        key = str(pf.get("key", "")).strip()
        if key:
            return maybe_fix_mojibake(key)
    return "未分类"


def print_type_zh(order: dict[str, Any]) -> str:
    cfg = order.get("process_config")
    if isinstance(cfg, dict):
        p = str(cfg.get("print_type", "")).strip()
        if p:
            up = p.upper()
            mapping = {
                "FDM": "FDM（熔融沉积）",
                "FDM/FFF": "FDM/FFF（熔丝制造）",
                "SLA": "SLA（光固化）",
                "SLS": "SLS（选择性烧结）",
            }
            return mapping.get(up, f"其他工艺（{p}）")
    return "未标注"


def filter_3d_assist(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in actions:
        operated = row.get("operated_orders")
        if not isinstance(operated, list):
            continue
        if any(isinstance(o, dict) and is_3d_order(o) for o in operated):
            out.append(row)
    return out


def dedupe_orders(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for o in orders:
        key = o.get("id") or o.get("show_id") or f"{o.get('create_at','')}_{o.get('status','')}"
        key_s = str(key)
        if key_s in seen:
            continue
        seen.add(key_s)
        out.append(o)
    return out


def dedupe_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for a in actions:
        key = a.get("id") or f"{a.get('action_type','')}_{a.get('create_at','')}"
        key_s = str(key)
        if key_s in seen:
            continue
        seen.add(key_s)
        out.append(a)
    return out


def daily_counter_to_list(counter: Counter[str]) -> list[dict[str, Any]]:
    return [{"date": d, "count": counter[d]} for d in sorted(counter.keys())]


def counter_to_list(counter: Counter[str]) -> list[dict[str, Any]]:
    return [{"name": k, "count": v} for k, v in counter.most_common()]


def month_count_from_daily(counter: Counter[str], latest_date: str) -> int:
    if not latest_date:
        return 0
    try:
        month_key = latest_date[:7]
    except Exception:
        return 0
    return sum(c for d, c in counter.items() if isinstance(d, str) and d.startswith(month_key))


def build_3d_dataset(
    source_type: str,
    source_path: Path,
    summary_items: list[dict[str, Any]],
    endpoint_results: dict[str, Any],
) -> dict[str, Any]:
    all_orders = flatten_order_list(endpoint_results.get("order_list"))
    orders = dedupe_orders([o for o in all_orders if is_3d_order(o)])

    all_actions = endpoint_results.get("assist_action")
    if not isinstance(all_actions, list):
        all_actions = []
    actions = dedupe_actions(filter_3d_assist([x for x in all_actions if isinstance(x, dict)]))

    order_status = Counter()
    order_purpose = Counter()
    order_print_type = Counter()
    order_daily = Counter()
    recent_orders = []

    for o in orders:
        st = status_zh(str(o.get("status", "")))
        order_status[st] += 1

        pf = process_for_zh(o)
        order_purpose[pf] += 1

        pt = print_type_zh(o)
        order_print_type[pt] += 1

        d = parse_date(o.get("create_at"))
        if d:
            order_daily[d] += 1

        recent_orders.append(
            {
                "订单号": str(o.get("show_id") or o.get("id") or ""),
                "状态": st,
                "用途": pf,
                "工艺": pt,
                "创建时间": str(o.get("create_at", "")),
            }
        )

    recent_orders.sort(key=lambda x: x["创建时间"], reverse=True)
    recent_orders = recent_orders[:8]

    action_type = Counter()
    action_daily = Counter()
    recent_actions = []
    for a in actions:
        tp = action_zh(str(a.get("action_type", "")))
        action_type[tp] += 1

        d = parse_date(a.get("create_at"))
        if d:
            action_daily[d] += 1

        operator = a.get("operator")
        op_name = ""
        if isinstance(operator, dict):
            op_name = str(operator.get("nickname", "")).strip()

        recent_actions.append(
            {
                "操作类型": tp,
                "操作人": op_name,
                "时间": str(a.get("create_at", "")),
            }
        )

    recent_actions.sort(key=lambda x: x["时间"], reverse=True)
    recent_actions = recent_actions[:8]

    sorted_dates = sorted(order_daily.keys())
    start_date = sorted_dates[0] if sorted_dates else ""
    latest_date = sorted_dates[-1] if sorted_dates else ""
    today_count = order_daily.get(latest_date, 0) if latest_date else 0
    month_count = month_count_from_daily(order_daily, latest_date)

    cards = {
        "统计区间3D订单总量": len(orders),
        "本月订单": month_count,
        "今日新增": today_count,
        "待审核": order_status.get("待审核", 0),
        "打印中": order_status.get("打印中", 0),
        "待取件": order_status.get("待取件", 0),
    }

    return {
        "元信息": {
            "生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "数据源类型": "筛选批次" if source_type == "filters" else "单次抓取",
            "数据源路径": str(source_path),
            "统计区间": f"{start_date} ~ {latest_date}" if start_date and latest_date else "未知",
            "最新统计日期": latest_date,
            "指标口径": "仅统计3D打印订单（process_type=thdprint或工艺字段命中3D）",
        },
        "指标卡": cards,
        "趋势": {
            "3D订单日趋势": daily_counter_to_list(order_daily),
            "3D助管操作日趋势": daily_counter_to_list(action_daily),
        },
        "分布": {
            "订单状态": counter_to_list(order_status),
            "订单用途": counter_to_list(order_purpose),
            "打印工艺": counter_to_list(order_print_type),
            "助管操作类型": counter_to_list(action_type),
        },
        "表格": {
            "最近3D订单": recent_orders,
            "最近3D助管操作": recent_actions,
        },
    }


def html_template(payload_json: str) -> str:
    return f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>3D打印数据看板</title>
  <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">
  <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>
  <link href=\"https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Noto+Sans+SC:wght@400;500;700&display=swap\" rel=\"stylesheet\">
  <script src=\"https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js\"></script>
  <style>
    :root {{
      --bg-a: #f2f9ff;
      --bg-b: #ffe5c8;
      --ink: #0f2238;
      --muted: #5f7084;
      --card: rgba(255,255,255,.80);
      --line: rgba(15,34,56,.12);
      --accent-1: #ff5a36;
      --accent-2: #1f8ed8;
      --accent-3: #3f9142;
      --shadow: 0 10px 26px rgba(7,35,66,.12);
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ width: 100%; height: 100%; }}
    body {{
      margin: 0;
      overflow: hidden;
      color: var(--ink);
      font-family: \"Noto Sans SC\", \"Space Grotesk\", sans-serif;
      background:
        radial-gradient(1100px 500px at 5% -15%, #a7ddff 0%, transparent 62%),
        radial-gradient(800px 450px at 98% 0%, #ffd5a7 0%, transparent 64%),
        linear-gradient(130deg, var(--bg-a), var(--bg-b));
    }}

    .wrap {{
      width: 100vw;
      height: 100vh;
      padding: 10px 12px 12px;
      display: grid;
      grid-template-rows: auto auto minmax(0, 1fr);
      gap: 8px;
    }}

    .header {{
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 10px;
    }}
    .title {{
      margin: 0;
      font-family: \"Space Grotesk\", \"Noto Sans SC\", sans-serif;
      font-size: clamp(24px, 2.4vw, 36px);
      line-height: 1.05;
      letter-spacing: -0.02em;
    }}
    .meta {{
      margin-top: 4px;
      color: var(--muted);
      font-size: 13px;
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .pill {{
      border:1px solid var(--line);
      border-radius:999px;
      padding:2px 9px;
      background:rgba(255,255,255,.65);
      white-space: nowrap;
    }}

    .cards {{ display:grid; grid-template-columns: repeat(6, minmax(120px,1fr)); gap:8px; }}
    .card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 12px;
      box-shadow: var(--shadow);
      padding: 8px 10px;
      backdrop-filter: blur(8px);
    }}
    .k {{ font-size: 12px; color: var(--muted); }}
    .v {{
      margin-top: 2px;
      font-family: \"Space Grotesk\", sans-serif;
      font-size: clamp(22px, 2.2vw, 30px);
      font-weight: 700;
      line-height: 1.05;
    }}

    .main {{
      min-height: 0;
      display: grid;
      grid-template-columns: 2.15fr 1fr;
      gap: 8px;
    }}

    .charts {{
      min-height: 0;
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      grid-template-rows: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }}

    .tables {{
      min-height: 0;
      display: grid;
      grid-template-rows: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }}

    .panel {{
      min-height: 0;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 12px;
      box-shadow: var(--shadow);
      padding: 7px 8px 8px;
      overflow: hidden;
    }}
    .panel h3 {{
      margin: 0 2px 4px;
      font-size: 13px;
      line-height: 1.2;
    }}
    .chart {{ width: 100%; height: calc(100% - 18px); }}
    .table-wrap {{ height: calc(100% - 20px); overflow: hidden; }}

    table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
    th, td {{
      text-align: left;
      padding: 4px 4px;
      border-bottom: 1px dashed var(--line);
      word-break: break-all;
      vertical-align: top;
    }}
    th {{ color: var(--muted); font-weight: 500; }}
    .empty {{ color:#8190a0; padding:8px 4px; font-size:11px; }}

    @media (max-width: 1280px), (max-height: 740px) {{
      body {{ overflow: auto; }}
      .wrap {{ height: auto; min-height: 100vh; }}
      .main {{ grid-template-columns: 1fr; }}
      .charts {{ grid-template-columns: repeat(2, minmax(0,1fr)); grid-template-rows: repeat(3, minmax(260px,1fr)); }}
      .tables {{ grid-template-rows: repeat(2, minmax(240px,1fr)); }}
    }}

    @media (max-width: 900px) {{
      html, body {{ height: auto; min-height: 100%; }}
      body {{ overflow: auto; }}
      .wrap {{
        height: auto;
        min-height: 100vh;
        padding: 10px 10px 16px;
        gap: 10px;
      }}
      .header {{ align-items: flex-start; }}
      .meta {{ font-size: 12px; gap: 4px; }}
      .pill {{ padding: 2px 8px; }}
      .cards {{ grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
      .card {{ padding: 8px 8px; }}
      .k {{ font-size: 11px; }}
      .v {{ font-size: clamp(18px, 5.4vw, 24px); }}
      .main {{ grid-template-columns: 1fr; gap: 10px; }}
      .charts {{
        grid-template-columns: 1fr;
        grid-template-rows: none;
        grid-auto-rows: minmax(250px, auto);
      }}
      .tables {{
        grid-template-rows: none;
        grid-auto-rows: minmax(220px, auto);
      }}
      .panel {{ overflow: auto; }}
      .chart {{ height: 250px; min-height: 250px; }}
      .table-wrap {{ height: auto; overflow: auto; }}
      table {{ min-width: 520px; font-size: 12px; }}
      th, td {{ padding: 5px 6px; }}
    }}

    @media (max-width: 480px) {{
      .title {{ font-size: clamp(20px, 6.2vw, 28px); }}
      .cards {{ grid-template-columns: 1fr 1fr; }}
      .meta {{ display: grid; grid-template-columns: 1fr; }}
      table {{ min-width: 460px; font-size: 11px; }}
    }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <section class=\"header\">
      <div>
        <h1 class=\"title\">3D打印运营展示板</h1>
        <div class=\"meta\">
          <span class=\"pill\" id=\"gen\"></span>
          <span class=\"pill\" id=\"src\"></span>
          <span class=\"pill\" id=\"range\"></span>
          <span class=\"pill\" id=\"latest\"></span>
        </div>
      </div>
    </section>

    <section class=\"cards\" id=\"cards\"></section>

    <section class=\"main\">
      <section class=\"charts\">
        <div class=\"panel\"><h3>3D订单日趋势</h3><div class=\"chart\" id=\"c_order_trend\"></div></div>
        <div class=\"panel\"><h3>3D助管操作日趋势</h3><div class=\"chart\" id=\"c_action_trend\"></div></div>
        <div class=\"panel\"><h3>订单状态分布</h3><div class=\"chart\" id=\"c_status\"></div></div>
        <div class=\"panel\"><h3>打印工艺分布</h3><div class=\"chart\" id=\"c_print\"></div></div>
        <div class=\"panel\"><h3>订单用途分布</h3><div class=\"chart\" id=\"c_purpose\"></div></div>
        <div class=\"panel\"><h3>助管操作类型分布</h3><div class=\"chart\" id=\"c_action_type\"></div></div>
      </section>

      <section class=\"tables\">
        <div class=\"panel\"><h3>最近3D订单</h3><div class=\"table-wrap\" id=\"t_orders\"></div></div>
        <div class=\"panel\"><h3>最近3D助管操作</h3><div class=\"table-wrap\" id=\"t_actions\"></div></div>
      </section>
    </section>
  </div>

  <script>
    const EMBEDDED_DATA = {payload_json};
    const IS_FILE_PROTOCOL = window.location.protocol === "file:";
    const REFRESH_MS = 5 * 60 * 1000; // Change here if you want a longer polling interval.
    const chartMap = {{}};
    let lastVersion = "";

    function getChart(id) {{
      if (!chartMap[id]) {{
        chartMap[id] = echarts.init(document.getElementById(id));
      }}
      return chartMap[id];
    }}

    function lineChart(id, list, color) {{
      const chart = getChart(id);
      const x = (list || []).map(i => i.date);
      const y = (list || []).map(i => i.count);
      chart.setOption({{
        animation: false,
        grid: {{left: 38, right: 8, top: 22, bottom: 26}},
        tooltip: {{trigger: "axis"}},
        xAxis: {{type: "category", data: x, axisLabel: {{color: "#5f7084", fontSize: 10, interval: Math.max(0, Math.floor(x.length / 8))}}}},
        yAxis: {{type: "value", axisLabel: {{color: "#5f7084", fontSize: 10}}, splitLine: {{lineStyle: {{color: "rgba(15,34,56,.08)"}}}}}},
        series: [{{
          type: "line",
          data: y,
          smooth: true,
          symbolSize: 6,
          areaStyle: {{opacity: .10}},
          lineStyle: {{width: 2.5, color}},
          itemStyle: {{color}},
          label: {{show: true, position: "top", color: "#3b4e61", fontSize: 10}}
        }}]
      }});
      return chart;
    }}

    function barChart(id, items, color) {{
      const chart = getChart(id);
      const names = (items || []).map(i => i.name);
      const values = (items || []).map(i => i.count);
      chart.setOption({{
        animation: false,
        grid: {{left: 88, right: 28, top: 22, bottom: 14}},
        tooltip: {{trigger: "axis", axisPointer: {{type: "shadow"}}}},
        xAxis: {{type: "value", axisLabel: {{color: "#5f7084", fontSize: 10}}, splitLine: {{lineStyle: {{color: "rgba(15,34,56,.08)"}}}}}},
        yAxis: {{type: "category", data: names, axisLabel: {{color: "#5f7084", fontSize: 10, width: 86, overflow: "truncate"}}}},
        series: [{{
          type: "bar",
          data: values,
          itemStyle: {{color, borderRadius: [0, 7, 7, 0]}},
          label: {{show: true, position: "right", color: "#32475a", fontSize: 10}}
        }}]
      }});
      return chart;
    }}

    function pieChart(id, items) {{
      const chart = getChart(id);
      chart.setOption({{
        animation: false,
        tooltip: {{trigger: "item"}},
        legend: {{bottom: 0, textStyle: {{color: "#5f7084", fontSize: 10}}}},
        series: [{{
          type: "pie",
          radius: ["32%", "66%"],
          center: ["50%", "40%"],
          data: (items || []).map(i => ({{name: i.name, value: i.count}})),
          label: {{show: true, formatter: "{{b}}: {{c}}", color: "#3a4d60", fontSize: 10}},
          labelLine: {{length: 9, length2: 7}}
        }}]
      }});
      return chart;
    }}

    function drawTable(id, rows, maxRows = 8) {{
      const root = document.getElementById(id);
      if (!rows || !rows.length) {{
        root.innerHTML = '<div class="empty">暂无数据</div>';
        return;
      }}
      const data = rows.slice(0, maxRows);
      const cols = Object.keys(data[0]);
      const thead = '<thead><tr>' + cols.map(c => `<th>${{c}}</th>`).join('') + '</tr></thead>';
      const tbody = '<tbody>' + data.map(r => '<tr>' + cols.map(c => `<td>${{r[c] ?? ""}}</td>`).join('') + '</tr>').join('') + '</tbody>';
      root.innerHTML = `<table>${{thead}}${{tbody}}</table>`;
    }}

    function renderDashboard(data) {{
      const meta = data["元信息"] || {{}};
      document.getElementById("gen").textContent = "生成时间：" + (meta["生成时间"] || "--");
      document.getElementById("src").textContent = "数据源：" + (meta["数据源类型"] || "未知");
      document.getElementById("range").textContent = "统计区间：" + (meta["统计区间"] || "--");
      document.getElementById("latest").textContent = "最新统计日期：" + (meta["最新统计日期"] || "--");

      const cardsRoot = document.getElementById("cards");
      cardsRoot.innerHTML = "";
      const cards = data["指标卡"] || {{}};
      Object.entries(cards).forEach(([k,v]) => {{
        const div = document.createElement("div");
        div.className = "card";
        div.innerHTML = `<div class=\"k\">${{k}}</div><div class=\"v\">${{Number(v || 0).toLocaleString("zh-CN")}}</div>`;
        cardsRoot.appendChild(div);
      }});

      const trends = data["趋势"] || {{}};
      const dist = data["分布"] || {{}};
      const tables = data["表格"] || {{}};

      lineChart("c_order_trend", trends["3D订单日趋势"] || [], "#ff5a36");
      lineChart("c_action_trend", trends["3D助管操作日趋势"] || [], "#1f8ed8");
      pieChart("c_status", dist["订单状态"] || []);
      pieChart("c_print", dist["打印工艺"] || []);
      barChart("c_purpose", dist["订单用途"] || [], "#3f9142");
      barChart("c_action_type", dist["助管操作类型"] || [], "#2d80c2");

      drawTable("t_orders", tables["最近3D订单"] || [], 8);
      drawTable("t_actions", tables["最近3D助管操作"] || [], 8);
    }}

    function calcVersion(data) {{
      const meta = data["元信息"] || {{}};
      const cards = data["指标卡"] || {{}};
      return `${{meta["生成时间"] || ""}}|${{meta["最新统计日期"] || ""}}|${{JSON.stringify(cards)}}`;
    }}

    async function loadAndRender() {{
      try {{
        const resp = await fetch(`./data.json?_=${{Date.now()}}`, {{ cache: "no-store" }});
        if (!resp.ok) {{
          throw new Error(`HTTP ${{resp.status}}`);
        }}
        const data = await resp.json();
        const version = calcVersion(data);
        if (version === lastVersion) {{
          return;
        }}
        lastVersion = version;
        renderDashboard(data);
      }} catch (err) {{
        console.error("load dashboard failed", err);
      }}
    }}

    if (EMBEDDED_DATA && typeof EMBEDDED_DATA === "object") {{
      lastVersion = calcVersion(EMBEDDED_DATA);
      renderDashboard(EMBEDDED_DATA);
    }}

    if (!IS_FILE_PROTOCOL) {{
      loadAndRender();
      setInterval(loadAndRender, REFRESH_MS);
    }}

    window.addEventListener("resize", () => Object.values(chartMap).forEach(c => c && c.resize()));
  </script>
</body>
</html>
"""


def build_dashboard(output_dir: Path = DEFAULT_OUTPUT_DIR, dashboard_dir: Path = DEFAULT_DASHBOARD_DIR, run_path: Path | None = None) -> tuple[Path, Path]:
    if run_path is None:
        source_type, source_path = find_latest_source(output_dir)
    else:
        source_path = run_path
        source_type = "filters" if source_path.is_dir() else "single"

    files, summary_items = collect_record_files(source_type, source_path)
    if not files:
        raise RuntimeError(f"未找到可用 JSON 数据文件: {source_path}")

    results = pick_endpoint_results(files)
    payload = build_3d_dataset(source_type, source_path, summary_items, results)

    # Fallback: if current run misses core order-list data, use latest valid historical run.
    if source_type == "filters" and is_payload_effectively_empty(payload):
        fallback_run = find_latest_valid_filters_run(output_dir, exclude_path=source_path)
        if fallback_run is not None:
            fb_files, fb_summary_items = collect_record_files("filters", fallback_run)
            fb_results = pick_endpoint_results(fb_files)
            fb_payload = build_3d_dataset("filters", fallback_run, fb_summary_items, fb_results)
            fb_meta = fb_payload.get("元信息", {}) if isinstance(fb_payload, dict) else {}
            if isinstance(fb_meta, dict):
                fb_meta["回退说明"] = f"本次抓取缺少订单统计数据，已回退到 {fallback_run.name}"
            payload = fb_payload

    dashboard_dir.mkdir(parents=True, exist_ok=True)
    data_path = dashboard_dir / "data.json"
    html_path = dashboard_dir / "index.html"

    with data_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    payload_json = json.dumps(payload, ensure_ascii=False).replace("</script>", "<\\/script>")
    html = html_template(payload_json)
    with html_path.open("w", encoding="utf-8") as f:
        f.write(html)

    return html_path, data_path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="基于抓取数据生成 3D 打印中文看板")
    p.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="抓取输出目录")
    p.add_argument("--dashboard-dir", default=str(DEFAULT_DASHBOARD_DIR), help="看板输出目录")
    p.add_argument("--run-path", default="", help="指定某次抓取目录（filters_*）或 responses_*.json")
    return p


def main() -> int:
    args = build_parser().parse_args()
    out = Path(args.output_dir)
    dash = Path(args.dashboard_dir)
    run_path = Path(args.run_path) if args.run_path else None

    try:
        html_file, data_file = build_dashboard(output_dir=out, dashboard_dir=dash, run_path=run_path)
        print(f"[OK] Dashboard HTML: {html_file}")
        print(f"[OK] Dashboard data: {data_file}")
        return 0
    except Exception as e:
        print(f"[ERROR] {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
