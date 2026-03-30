import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

DEFAULT_OUTPUT_DIR = Path("output")
DEFAULT_DASHBOARD_DIR = Path("dashboard")

RESOLUTION_ADAPTIVE_CSS = """
    /* dashboard-builder resolution adaptation */
    :root {
      --display-title-min: 26px;
      --display-title-fluid: 2.45vw;
      --display-title-max: 38px;
      --display-meta-size: 13px;
      --display-meta-gap: 6px;
      --display-pill-pad-y: 2px;
      --display-pill-pad-x: 9px;
      --display-card-gap: 12px;
      --display-card-pad-y: 10px;
      --display-card-pad-x: 12px;
      --display-card-key-size: 12px;
      --display-card-value-min: 22px;
      --display-card-value-fluid: 2.2vw;
      --display-card-value-max: 30px;
      --display-panel-pad-top: 7px;
      --display-panel-pad-side: 8px;
      --display-panel-pad-bottom: 8px;
      --display-panel-title-size: 13px;
      --display-panel-title-gap: 4px;
      --display-table-size: 10.5px;
      --display-cell-pad-y: 4px;
      --display-cell-pad-x: 4px;
      --display-empty-size: 11px;
      --display-chart-min-height: 260px;
      --display-panel-grid-min-height: 280px;
      --display-trend-grid-min-height: 320px;
      --display-table-grid-min-height: 320px;
    }

    .title {
      font-size: clamp(var(--display-title-min), var(--display-title-fluid), var(--display-title-max)) !important;
    }
    .meta {
      font-size: var(--display-meta-size) !important;
      gap: var(--display-meta-gap) !important;
    }
    .pill {
      padding: var(--display-pill-pad-y) var(--display-pill-pad-x) !important;
    }
    .cards {
      gap: var(--display-card-gap) !important;
    }
    .card {
      padding: var(--display-card-pad-y) var(--display-card-pad-x) !important;
    }
    .k {
      font-size: var(--display-card-key-size) !important;
    }
    .v {
      font-size: clamp(var(--display-card-value-min), var(--display-card-value-fluid), var(--display-card-value-max)) !important;
    }
    .panel-grid {
      grid-auto-rows: minmax(var(--display-panel-grid-min-height), auto) !important;
    }
    .quad-trend .panel-grid {
      grid-auto-rows: minmax(var(--display-trend-grid-min-height), auto) !important;
    }
    .panel-grid.tables-grid {
      grid-auto-rows: minmax(var(--display-table-grid-min-height), auto) !important;
    }
    .panel {
      padding: var(--display-panel-pad-top) var(--display-panel-pad-side) var(--display-panel-pad-bottom) !important;
    }
    .panel h3 {
      margin-bottom: var(--display-panel-title-gap) !important;
      font-size: var(--display-panel-title-size) !important;
    }
    .chart {
      min-height: var(--display-chart-min-height) !important;
    }
    table {
      font-size: var(--display-table-size) !important;
    }
    th, td {
      padding: var(--display-cell-pad-y) var(--display-cell-pad-x) !important;
    }
    .empty {
      font-size: var(--display-empty-size) !important;
    }
    .global-echart-tooltip {
      font-size: calc(13.5px * var(--stage-scale, 1)) !important;
    }
    body.fixed-scale-mode {
      display: flex;
      justify-content: center;
      align-items: flex-start;
      overflow: auto !important;
    }
    .dashboard-frame {
      position: relative;
      flex: 0 0 auto;
    }
    .dashboard-stage {
      position: absolute;
      left: 0;
      top: 0;
      transform-origin: top left;
      will-change: transform;
    }
    body.fixed-scale-mode .wrap {
      width: 2048px !important;
      min-height: 1152px !important;
      height: 1152px !important;
      grid-template-rows: repeat(2, minmax(0, 1fr)) !important;
    }
    body.fixed-scale-mode .quad {
      overflow: hidden !important;
    }
    body.fixed-scale-mode .panel-grid {
      flex: 1 1 0;
      height: 100%;
      grid-template-rows: repeat(2, minmax(0, 1fr)) !important;
      grid-auto-rows: auto !important;
    }
    body.fixed-scale-mode .quad-trend .panel-grid {
      grid-template-rows: repeat(2, minmax(0, 1fr)) !important;
    }
    body.fixed-scale-mode .panel-grid.tables-grid {
      grid-template-rows: repeat(2, minmax(0, 1fr)) !important;
    }
    body.fixed-scale-mode .chart {
      min-height: 0 !important;
      height: 100% !important;
    }
    body.fixed-scale-mode .table-wrap {
      height: 100% !important;
      overflow: hidden !important;
    }
    @media (max-width: 900px) {
      .panel-grid,
      .quad-trend .panel-grid,
      .panel-grid.tables-grid {
        grid-auto-rows: minmax(220px, auto) !important;
      }
      .chart {
        min-height: 240px !important;
      }
    }
    @media (max-height: 920px) {
      body[data-display-profile="base"] {
        --outer-pad: 12px;
        --seam-pad: 20px;
        --panel-gap: 10px;
        --display-title-min: 22px;
        --display-title-fluid: 2.05vw;
        --display-title-max: 32px;
        --display-meta-size: 12px;
        --display-meta-gap: 4px;
        --display-pill-pad-y: 2px;
        --display-pill-pad-x: 7px;
        --display-card-gap: 10px;
        --display-card-pad-y: 8px;
        --display-card-pad-x: 10px;
        --display-card-key-size: 11px;
        --display-card-value-min: 18px;
        --display-card-value-fluid: 1.8vw;
        --display-card-value-max: 24px;
        --display-panel-pad-top: 6px;
        --display-panel-pad-side: 7px;
        --display-panel-pad-bottom: 7px;
        --display-panel-title-size: 12px;
        --display-panel-title-gap: 3px;
        --display-table-size: 10px;
        --display-cell-pad-y: 3px;
        --display-cell-pad-x: 4px;
        --display-empty-size: 11px;
        --display-chart-min-height: 120px;
        --display-panel-grid-min-height: 180px;
        --display-trend-grid-min-height: 220px;
        --display-table-grid-min-height: 220px;
      }
    }
    @media (max-height: 820px) {
      body[data-display-profile="base"] {
        --display-card-gap: 8px;
        --display-title-min: 20px;
        --display-title-fluid: 1.8vw;
        --display-title-max: 28px;
        --display-chart-min-height: 96px;
        --display-panel-grid-min-height: 160px;
        --display-trend-grid-min-height: 190px;
        --display-table-grid-min-height: 190px;
      }
    }
"""

RESOLUTION_ADAPTIVE_SCRIPT = """
    const FIXED_STAGE_WIDTH = 2048;
    const FIXED_STAGE_HEIGHT = 1152;
    const FIXED_REFERENCE_PROFILE = "qhd";
    const DISPLAY_PROFILES = [
      {
        name: "base",
        minWidth: 0,
        minHeight: 0,
        cssVars: {
          "--outer-pad": "18px",
          "--seam-pad": "30px",
          "--panel-gap": "14px",
          "--display-title-min": "26px",
          "--display-title-fluid": "2.45vw",
          "--display-title-max": "38px",
          "--display-meta-size": "13px",
          "--display-meta-gap": "6px",
          "--display-pill-pad-y": "2px",
          "--display-pill-pad-x": "9px",
          "--display-card-gap": "12px",
          "--display-card-pad-y": "10px",
          "--display-card-pad-x": "12px",
          "--display-card-key-size": "12px",
          "--display-card-value-min": "22px",
          "--display-card-value-fluid": "2.2vw",
          "--display-card-value-max": "30px",
          "--display-panel-pad-top": "7px",
          "--display-panel-pad-side": "8px",
          "--display-panel-pad-bottom": "8px",
          "--display-panel-title-size": "13px",
          "--display-panel-title-gap": "4px",
          "--display-table-size": "10.5px",
          "--display-cell-pad-y": "4px",
          "--display-cell-pad-x": "4px",
          "--display-empty-size": "11px",
          "--display-chart-min-height": "260px",
          "--display-panel-grid-min-height": "280px",
          "--display-trend-grid-min-height": "320px",
          "--display-table-grid-min-height": "320px"
        },
        chart: {
          tooltipFontSize: 12,
          lineGridLeft: 38,
          lineGridRight: 8,
          lineGridTop: 22,
          lineGridBottom: 26,
          axisFontSize: 10,
          axisMargin: 10,
          seriesLabelFontSize: 10,
          lineSymbolSize: 6,
          lineWidth: 2.5,
          barGridLeft: 86,
          barGridRight: 18,
          barGridTop: 22,
          barGridBottom: 24,
          barCategoryFontSize: 9,
          barLabelWidth: 82,
          barLabelLineHeight: 11,
          pieLegendFontSize: 10,
          pieLegendItemWidth: 10,
          pieLegendItemHeight: 10,
          pieLabelFontSize: 9,
          pieLabelWidth: 112,
          pieLabelLineHeight: 12,
          pieRadius: ["28%", "58%"],
          pieCenter: ["46%", "40%"],
          pieLabelLineLength: 8,
          pieLabelLineLength2: 6
        }
      },
      {
        name: "qhd",
        minWidth: 2048,
        minHeight: 1280,
        cssVars: {
          "--outer-pad": "16px",
          "--seam-pad": "18px",
          "--panel-gap": "10px",
          "--display-title-min": "30px",
          "--display-title-fluid": "2.15vw",
          "--display-title-max": "46px",
          "--display-meta-size": "15px",
          "--display-meta-gap": "8px",
          "--display-pill-pad-y": "3px",
          "--display-pill-pad-x": "11px",
          "--display-card-gap": "14px",
          "--display-card-pad-y": "12px",
          "--display-card-pad-x": "14px",
          "--display-card-key-size": "13.5px",
          "--display-card-value-min": "26px",
          "--display-card-value-fluid": "2.05vw",
          "--display-card-value-max": "36px",
          "--display-panel-pad-top": "8px",
          "--display-panel-pad-side": "9px",
          "--display-panel-pad-bottom": "9px",
          "--display-panel-title-size": "14.5px",
          "--display-panel-title-gap": "4px",
          "--display-table-size": "11.5px",
          "--display-cell-pad-y": "5px",
          "--display-cell-pad-x": "5px",
          "--display-empty-size": "12px",
          "--display-chart-min-height": "280px",
          "--display-panel-grid-min-height": "300px",
          "--display-trend-grid-min-height": "320px",
          "--display-table-grid-min-height": "320px"
        },
        chart: {
          tooltipFontSize: 13.5,
          lineGridLeft: 46,
          lineGridRight: 12,
          lineGridTop: 26,
          lineGridBottom: 32,
          axisFontSize: 11.5,
          axisMargin: 12,
          seriesLabelFontSize: 12,
          lineSymbolSize: 7,
          lineWidth: 3,
          barGridLeft: 102,
          barGridRight: 24,
          barGridTop: 26,
          barGridBottom: 32,
          barCategoryFontSize: 10.5,
          barLabelWidth: 96,
          barLabelLineHeight: 13,
          pieLegendFontSize: 12,
          pieLegendItemWidth: 12,
          pieLegendItemHeight: 12,
          pieLabelFontSize: 11,
          pieLabelWidth: 140,
          pieLabelLineHeight: 14,
          pieRadius: ["28%", "60%"],
          pieCenter: ["44%", "40%"],
          pieLabelLineLength: 10,
          pieLabelLineLength2: 8
        }
      },
      {
        name: "uhd",
        minWidth: 3200,
        minHeight: 1800,
        cssVars: {
          "--outer-pad": "32px",
          "--seam-pad": "48px",
          "--panel-gap": "22px",
          "--display-title-min": "42px",
          "--display-title-fluid": "2.15vw",
          "--display-title-max": "74px",
          "--display-meta-size": "20px",
          "--display-meta-gap": "12px",
          "--display-pill-pad-y": "5px",
          "--display-pill-pad-x": "15px",
          "--display-card-gap": "20px",
          "--display-card-pad-y": "18px",
          "--display-card-pad-x": "20px",
          "--display-card-key-size": "18px",
          "--display-card-value-min": "38px",
          "--display-card-value-fluid": "2vw",
          "--display-card-value-max": "58px",
          "--display-panel-pad-top": "14px",
          "--display-panel-pad-side": "16px",
          "--display-panel-pad-bottom": "16px",
          "--display-panel-title-size": "20px",
          "--display-panel-title-gap": "8px",
          "--display-table-size": "15.5px",
          "--display-cell-pad-y": "7px",
          "--display-cell-pad-x": "8px",
          "--display-empty-size": "15px",
          "--display-chart-min-height": "420px",
          "--display-panel-grid-min-height": "430px",
          "--display-trend-grid-min-height": "500px",
          "--display-table-grid-min-height": "500px"
        },
        chart: {
          tooltipFontSize: 18,
          lineGridLeft: 68,
          lineGridRight: 18,
          lineGridTop: 36,
          lineGridBottom: 46,
          axisFontSize: 16,
          axisMargin: 16,
          seriesLabelFontSize: 16,
          lineSymbolSize: 9,
          lineWidth: 4,
          barGridLeft: 146,
          barGridRight: 34,
          barGridTop: 36,
          barGridBottom: 44,
          barCategoryFontSize: 14.5,
          barLabelWidth: 150,
          barLabelLineHeight: 18,
          pieLegendFontSize: 16,
          pieLegendItemWidth: 16,
          pieLegendItemHeight: 16,
          pieLabelFontSize: 14.5,
          pieLabelWidth: 196,
          pieLabelLineHeight: 19,
          pieRadius: ["31%", "63%"],
          pieCenter: ["42%", "39%"],
          pieLabelLineLength: 14,
          pieLabelLineLength2: 12
        }
      },
      {
        name: "ultra",
        minWidth: 4480,
        minHeight: 2520,
        cssVars: {
          "--outer-pad": "34px",
          "--seam-pad": "52px",
          "--panel-gap": "24px",
          "--display-title-min": "42px",
          "--display-title-fluid": "1.75vw",
          "--display-title-max": "70px",
          "--display-meta-size": "19px",
          "--display-meta-gap": "12px",
          "--display-pill-pad-y": "5px",
          "--display-pill-pad-x": "15px",
          "--display-card-gap": "22px",
          "--display-card-pad-y": "18px",
          "--display-card-pad-x": "20px",
          "--display-card-key-size": "17px",
          "--display-card-value-min": "38px",
          "--display-card-value-fluid": "1.65vw",
          "--display-card-value-max": "56px",
          "--display-panel-pad-top": "14px",
          "--display-panel-pad-side": "17px",
          "--display-panel-pad-bottom": "17px",
          "--display-panel-title-size": "19px",
          "--display-panel-title-gap": "8px",
          "--display-table-size": "15px",
          "--display-cell-pad-y": "7px",
          "--display-cell-pad-x": "8px",
          "--display-empty-size": "15px",
          "--display-chart-min-height": "420px",
          "--display-panel-grid-min-height": "440px",
          "--display-trend-grid-min-height": "500px",
          "--display-table-grid-min-height": "500px"
        },
        chart: {
          tooltipFontSize: 18,
          lineGridLeft: 68,
          lineGridRight: 18,
          lineGridTop: 36,
          lineGridBottom: 46,
          axisFontSize: 16,
          axisMargin: 16,
          seriesLabelFontSize: 16,
          lineSymbolSize: 9,
          lineWidth: 4,
          barGridLeft: 142,
          barGridRight: 34,
          barGridTop: 36,
          barGridBottom: 44,
          barCategoryFontSize: 14,
          barLabelWidth: 146,
          barLabelLineHeight: 18,
          pieLegendFontSize: 16,
          pieLegendItemWidth: 16,
          pieLegendItemHeight: 16,
          pieLabelFontSize: 14.5,
          pieLabelWidth: 196,
          pieLabelLineHeight: 19,
          pieRadius: ["31%", "63%"],
          pieCenter: ["42%", "40%"],
          pieLabelLineLength: 14,
          pieLabelLineLength2: 12
        }
      }
    ];

    let currentDisplayProfile = DISPLAY_PROFILES[0];
    let displaySyncTimer = 0;

    function selectDisplayProfile() {
      return DISPLAY_PROFILES.find((profile) => profile.name === FIXED_REFERENCE_PROFILE) || DISPLAY_PROFILES[0];
    }

    function applyDisplayProfile(force = false) {
      const selected = selectDisplayProfile();
      if (!force && currentDisplayProfile.name === selected.name) {
        return false;
      }
      currentDisplayProfile = selected;
      document.body.setAttribute("data-display-profile", selected.name);
      Object.entries(selected.cssVars).forEach(([key, value]) => {
        document.documentElement.style.setProperty(key, value);
      });
      return true;
    }

    function ensureFixedScaleStage() {
      const wrap = document.querySelector(".wrap");
      if (!wrap) {
        return null;
      }
      let frame = document.querySelector(".dashboard-frame");
      let stage = document.querySelector(".dashboard-stage");
      if (frame && stage) {
        return {frame, stage, wrap};
      }
      frame = document.createElement("div");
      frame.className = "dashboard-frame";
      stage = document.createElement("div");
      stage.className = "dashboard-stage";
      const parent = wrap.parentNode;
      parent.insertBefore(frame, wrap);
      frame.appendChild(stage);
      stage.appendChild(wrap);
      return {frame, stage, wrap};
    }

    function clearFixedScaleStage() {
      const frame = document.querySelector(".dashboard-frame");
      const stage = document.querySelector(".dashboard-stage");
      const wrap = document.querySelector(".wrap");
      if (frame && stage && wrap && wrap.parentNode === stage && frame.parentNode) {
        frame.parentNode.insertBefore(wrap, frame);
        frame.remove();
      }
      document.body.classList.remove("fixed-scale-mode");
      document.documentElement.style.removeProperty("--stage-scale");
      if (wrap) {
        wrap.style.width = "";
        wrap.style.height = "";
        wrap.style.minHeight = "";
      }
    }

    function syncFixedScaleStage() {
      const refs = ensureFixedScaleStage();
      if (!refs) {
        return;
      }
      const {frame, stage} = refs;
      const viewportWidth = Math.max(window.innerWidth || 0, 320);
      const viewportHeight = Math.max(window.innerHeight || 0, 320);
      const scale = Math.max(Math.min(viewportWidth / FIXED_STAGE_WIDTH, viewportHeight / FIXED_STAGE_HEIGHT), 0.1);
      document.body.classList.add("fixed-scale-mode");
      document.documentElement.style.setProperty("--stage-scale", String(scale));
      frame.style.width = `${Math.round(FIXED_STAGE_WIDTH * scale)}px`;
      frame.style.height = `${Math.round(FIXED_STAGE_HEIGHT * scale)}px`;
      stage.style.width = `${FIXED_STAGE_WIDTH}px`;
      stage.style.height = `${FIXED_STAGE_HEIGHT}px`;
      stage.style.transform = `scale(${scale})`;
    }

    function updateLineChartDisplay(chart) {
      const m = currentDisplayProfile.chart;
      chart.setOption({
        grid: {left: m.lineGridLeft, right: m.lineGridRight, top: m.lineGridTop, bottom: m.lineGridBottom, containLabel: true},
        tooltip: {textStyle: {fontSize: m.tooltipFontSize}},
        xAxis: {axisLabel: {fontSize: m.axisFontSize, margin: m.axisMargin}},
        yAxis: {axisLabel: {fontSize: m.axisFontSize, margin: m.axisMargin}},
        series: [{
          symbolSize: m.lineSymbolSize,
          lineStyle: {width: m.lineWidth},
          label: {fontSize: m.seriesLabelFontSize}
        }]
      });
    }

    function updateBarChartDisplay(chart) {
      const m = currentDisplayProfile.chart;
      chart.setOption({
        grid: {left: m.barGridLeft, right: m.barGridRight, top: m.barGridTop, bottom: m.barGridBottom, containLabel: false},
        tooltip: {textStyle: {fontSize: m.tooltipFontSize}},
        xAxis: {axisLabel: {fontSize: m.axisFontSize, margin: m.axisMargin}},
        yAxis: {
          axisLabel: {
            fontSize: m.barCategoryFontSize,
            width: m.barLabelWidth,
            lineHeight: m.barLabelLineHeight
          }
        },
        series: [{
          label: {fontSize: m.seriesLabelFontSize}
        }]
      });
    }

    function updatePieChartDisplay(chart) {
      const m = currentDisplayProfile.chart;
      chart.setOption({
        tooltip: {textStyle: {fontSize: m.tooltipFontSize}},
        legend: {
          textStyle: {fontSize: m.pieLegendFontSize},
          itemWidth: m.pieLegendItemWidth,
          itemHeight: m.pieLegendItemHeight
        },
        series: [{
          radius: m.pieRadius,
          center: m.pieCenter,
          label: {
            fontSize: m.pieLabelFontSize,
            width: m.pieLabelWidth,
            lineHeight: m.pieLabelLineHeight
          },
          labelLine: {
            length: m.pieLabelLineLength,
            length2: m.pieLabelLineLength2
          }
        }]
      });
    }

    function updateChartsForDisplayProfile() {
      Object.entries(chartMap).forEach(([id, chart]) => {
        if (!chart) {
          return;
        }
        if (id === "c_order_trend" || id === "c_action_trend") {
          updateLineChartDisplay(chart);
          return;
        }
        if (id === "c_purpose" || id === "c_department") {
          updateBarChartDisplay(chart);
          return;
        }
        if (id === "c_status" || id === "c_print") {
          updatePieChartDisplay(chart);
        }
      });
    }

    function syncDisplayProfile() {
      applyDisplayProfile(true);
      applyViewportMode();
      Object.values(chartMap).forEach((chart) => {
        if (chart) {
          chart.resize();
        }
      });
      updateChartsForDisplayProfile();
    }

    function scheduleDisplaySync(delay = 60) {
      if (displaySyncTimer) {
        window.clearTimeout(displaySyncTimer);
      }
      displaySyncTimer = window.setTimeout(() => {
        syncDisplayProfile();
      }, delay);
    }

    applyDisplayProfile(true);
"""

STATUS_MAP = {
    "wait-for-approval": "待审核",
    "printing": "打印中",
    "pickup": "待取件",
    "complete": "已完成",
    "refused": "已拒绝",
    "canceled": "已取消",
}

ACTION_MAP = {
    "approve-order": "审核通过",
    "done-for-pickup": "打印完成",
    "refuse-order": "拒绝订单",
    "complete-order": "取件完成",
    "record-fail": "登记异常",
    "resign-user": "助管离岗",
    "update-order-price": "修改价格",
    "recall-order": "撤回订单",
    # Fallback types inferred from order tag history when assist-action endpoint is unavailable.
    "status-wait-for-approval": "待审核",
    "status-printing": "打印中",
    "status-pickup": "待取件",
    "status-complete": "已完成",
    "status-refused": "已拒绝",
    "status-canceled": "已取消",
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


def department_zh(order: dict[str, Any]) -> str:
    user = order.get("user")
    if isinstance(user, dict):
        org = user.get("organize")
        if isinstance(org, dict):
            name = str(org.get("name", "")).strip()
            if name:
                return maybe_fix_mojibake(name)

    # Some payloads may include organize at top-level
    org = order.get("organize")
    if isinstance(org, dict):
        name = str(org.get("name", "")).strip()
        if name:
            return maybe_fix_mojibake(name)

    return "未标注"


def filter_3d_assist(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in actions:
        operated = row.get("operated_orders")
        if isinstance(operated, list) and any(isinstance(o, dict) and is_3d_order(o) for o in operated):
            out.append(row)
            continue

        # Some payloads may not include operated_orders; try direct order-like fields.
        fallback_order = {
            "process_type": row.get("process_type", ""),
            "process_config": row.get("process_config"),
        }
        if is_3d_order(fallback_order):
            out.append(row)
    return out


def normalize_operator_payload(operator: Any) -> dict[str, Any] | None:
    if isinstance(operator, dict):
        return operator
    if operator is None:
        return None
    text = str(operator).strip()
    if not text:
        return None
    return {"nickname": text}


def extract_operator_name(operator: Any) -> str:
    if isinstance(operator, str):
        return maybe_fix_mojibake(operator.strip())
    if not isinstance(operator, dict):
        return ""

    candidates: list[Any] = [
        operator.get("nickname"),
        operator.get("name"),
        operator.get("username"),
        operator.get("realname"),
        operator.get("operator"),
        operator.get("account"),
    ]
    sjtu = operator.get("sjtu_info")
    if isinstance(sjtu, dict):
        candidates.extend([sjtu.get("name"), sjtu.get("account")])

    for item in candidates:
        text = str(item or "").strip()
        if text:
            return maybe_fix_mojibake(text)
    return ""


def build_actions_from_order_tags(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for order in orders:
        if not isinstance(order, dict):
            continue
        tags = order.get("taginfo_list")
        if not isinstance(tags, list):
            continue

        order_show_id = str(order.get("show_id") or order.get("id") or "")
        order_type = str(order.get("process_type", "")).strip()
        order_cfg = order.get("process_config")

        for idx, tag in enumerate(tags, start=1):
            if not isinstance(tag, dict):
                continue
            status = str(tag.get("status") or order.get("status") or "").strip().lower()
            if not status:
                continue

            tag_time = str(tag.get("time") or order.get("update_at") or order.get("create_at") or "")
            operator_name = str(tag.get("operator") or "").strip()
            if not operator_name:
                operator_name = extract_operator_name(order.get("operator"))
            if not operator_name:
                order_actions = order.get("actions")
                if isinstance(order_actions, list):
                    for hist in reversed(order_actions):
                        if not isinstance(hist, dict):
                            continue
                        operator_name = extract_operator_name(hist.get("operator"))
                        if not operator_name:
                            operator_name = extract_operator_name(hist.get("admin"))
                        if operator_name:
                            break
            tag_type = str(tag.get("process_type") or order_type).strip()

            out.append(
                {
                    "id": f"tag-{order_show_id}-{idx}-{tag_time}-{operator_name}-{status}",
                    "action_type": f"status-{status}",
                    "create_at": tag_time,
                    "operator": {"nickname": operator_name},
                    "operated_orders": [
                        {
                            "process_type": tag_type,
                            "process_config": order_cfg,
                        }
                    ],
                }
            )
    return out


def build_actions_from_order_history(orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for order in orders:
        if not isinstance(order, dict):
            continue
        history = order.get("actions")
        if not isinstance(history, list):
            continue

        order_show_id = str(order.get("show_id") or order.get("id") or "")
        process_type = order.get("process_type")
        process_cfg = order.get("process_config")

        for idx, item in enumerate(history, start=1):
            if not isinstance(item, dict):
                continue
            action_type = str(
                item.get("action_type")
                or item.get("action")
                or item.get("type")
                or item.get("status")
                or ""
            ).strip().lower()
            status = str(item.get("status") or order.get("status") or "").strip().lower()
            if not action_type and status:
                action_type = f"status-{status}"
            if not action_type:
                continue

            timestamp = str(
                item.get("create_at")
                or item.get("created_at")
                or item.get("time")
                or order.get("update_at")
                or order.get("create_at")
                or ""
            )

            operator_payload = normalize_operator_payload(item.get("operator"))
            if operator_payload is None:
                operator_payload = normalize_operator_payload(item.get("admin"))
            if operator_payload is None:
                name = extract_operator_name(item.get("operator") or item.get("admin"))
                if name:
                    operator_payload = {"nickname": name}

            out.append(
                {
                    "id": item.get("id") or f"hist-{order_show_id}-{idx}-{action_type}-{timestamp}",
                    "action_type": action_type,
                    "create_at": timestamp,
                    "operator": operator_payload,
                    "operated_orders": [
                        {
                            "process_type": item.get("process_type") or process_type,
                            "process_config": item.get("process_config") or process_cfg,
                        }
                    ],
                }
            )
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


def counter_with_other(counter: Counter[str], top_n: int, other_label: str) -> list[dict[str, Any]]:
    items = counter.most_common()
    if top_n <= 0 or len(items) <= top_n:
        return [{"name": k, "count": v} for k, v in items]
    kept = items[:top_n]
    other_total = sum(v for _, v in items[top_n:])
    if other_total > 0:
        kept.append((other_label, other_total))
    return [{"name": k, "count": v} for k, v in kept]


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
    actions = filter_3d_assist([x for x in all_actions if isinstance(x, dict)])
    if not actions:
        actions = build_actions_from_order_history(orders)
    if not actions:
        actions = build_actions_from_order_tags(orders)
    actions = dedupe_actions(actions)

    order_status = Counter()
    order_purpose = Counter()
    order_print_type = Counter()
    order_dept = Counter()
    order_daily = Counter()
    recent_orders = []

    for o in orders:
        st = status_zh(str(o.get("status", "")))
        order_status[st] += 1

        pf = process_for_zh(o)
        order_purpose[pf] += 1

        dept = department_zh(o)
        order_dept[dept] += 1

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

    # Build action-update daily trend from order update_at (independent of assist-action date range).
    action_update_daily: Counter[str] = Counter()
    for o in orders:
        d = parse_date(o.get("update_at"))
        if d:
            action_update_daily[d] += 1

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
        op_name = extract_operator_name(operator)
        if not op_name:
            op_name = extract_operator_name(a.get("admin"))

        recent_actions.append(
            {
                "操作详情": tp,
                "操作人": op_name,
                "时间": str(a.get("create_at", "")),
            }
        )

    recent_actions.sort(key=lambda x: x["时间"], reverse=True)
    recent_actions = recent_actions[:10]

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
            "3D订单操作日趋势": daily_counter_to_list(action_update_daily),
        },
        "分布": {
            "订单状态": counter_to_list(order_status),
            "订单用途": counter_to_list(order_purpose),
            "学院分布": counter_with_other(order_dept, 7, "其余学院"),
            "打印工艺": counter_to_list(order_print_type),
            "助管操作类型": counter_to_list(action_type),
        },
        "表格": {
            "最近3D订单": recent_orders,
            "最近3D助管操作": recent_actions,
        },
    }


def render_template(
    payload_json: str,
    template_path: Path | None = None,
    fallback_templates: list[Path] | None = None,
    transform_template: Callable[[str], str] | None = None,
) -> str:
    candidates: list[Path] = []

    def append_candidate(path: Path | None) -> None:
        if path is None:
            return
        if any(existing.resolve() == path.resolve() for existing in candidates):
            return
        candidates.append(path)

    bundled_root = getattr(sys, "_MEIPASS", "")
    append_candidate(template_path)
    for fallback_template in fallback_templates or []:
        if bundled_root:
            append_candidate(Path(bundled_root) / fallback_template.name)
        append_candidate(fallback_template)

    template_text: str | None = None
    for path in candidates:
        if path.exists() and path.is_file():
            template_text = path.read_text(encoding="utf-8")
            break

    if template_text is None:
        raise FileNotFoundError(
            "未找到 HTML 模板文件，请先准备 index_example.html 或 dashboard/index.html 后再生成看板。"
        )

    if transform_template is not None:
        template_text = transform_template(template_text)

    pattern = re.compile(
        r"const EMBEDDED_DATA = .*?;\n(\s*const IS_FILE_PROTOCOL = )",
        re.DOTALL,
    )
    rendered, count = pattern.subn(
        f"const EMBEDDED_DATA = {payload_json};\n\\1",
        template_text,
        count=1,
    )
    if count != 1:
        raise RuntimeError("HTML 模板中未找到 EMBEDDED_DATA 注入点。")
    return rendered


def html_template(payload_json: str, template_path: Path | None = None) -> str:
    return render_template(
        payload_json,
        template_path=template_path,
        fallback_templates=[
            Path("index_example.html"),
            DEFAULT_DASHBOARD_DIR / "index.html",
        ],
        transform_template=inject_resolution_adaptation,
    )


def simple_html_template(payload_json: str, template_path: Path | None = None) -> str:
    return render_template(
        payload_json,
        template_path=template_path,
        fallback_templates=[Path("simple_example.html")],
        transform_template=None,
    )


def replace_once(text: str, old: str, new: str, error_message: str) -> str:
    if old not in text:
        raise RuntimeError(error_message)
    return text.replace(old, new, 1)


def inject_resolution_adaptation(template_text: str) -> str:
    if "dashboard-builder resolution adaptation" in template_text:
        return template_text

    template_text = replace_once(
        template_text,
        "\n  </style>",
        f"{RESOLUTION_ADAPTIVE_CSS}\n  </style>",
        "HTML 模板中未找到样式结束标记，无法注入分辨率适配样式。",
    )

    template_text = replace_once(
        template_text,
        '    let lastVersion = "";\n',
        f'    let lastVersion = "";\n{RESOLUTION_ADAPTIVE_SCRIPT}\n',
        "HTML 模板中未找到脚本注入点，无法注入分辨率适配逻辑。",
    )

    template_text = replace_once(
        template_text,
        "    function applyViewportMode() {\n"
        "      if (isFullscreenLike()) {\n"
        "        syncDashboardLayout();\n"
        "      } else {\n"
        "        clearDashboardLayout();\n"
        "      }\n"
        "    }\n",
        "    function applyViewportMode() {\n"
        "      if (isFullscreenLike()) {\n"
        "        syncFixedScaleStage();\n"
        "        syncDashboardLayout();\n"
        "        return;\n"
        "      }\n"
        "      clearFixedScaleStage();\n"
        "      clearDashboardLayout();\n"
        "    }\n",
        "HTML 模板中未找到视口模式函数，无法切换到固定比例缩放模式。",
    )

    template_text = replace_once(
        template_text,
        '      drawTable("t_orders", tables["最近3D订单"] || [], 7);\n'
        '      drawTable("t_actions", tables["最近3D助管操作"] || [], 8);\n',
        '      drawTable("t_orders", tables["最近3D订单"] || [], 7);\n'
        '      drawTable("t_actions", tables["最近3D助管操作"] || [], 8);\n'
        '      scheduleDisplaySync(0);\n',
        "HTML 模板中未找到渲染结束片段，无法接入分辨率适配刷新。",
    )

    template_text = replace_once(
        template_text,
        '    document.addEventListener("fullscreenchange", () => {\n'
        "      applyViewportMode();\n"
        "      Object.values(chartMap).forEach(c => c && c.resize());\n"
        "    });\n",
        '    document.addEventListener("fullscreenchange", () => {\n'
        "      applyViewportMode();\n"
        "      Object.values(chartMap).forEach(c => c && c.resize());\n"
        "      scheduleDisplaySync(120);\n"
        "    });\n"
        '    window.addEventListener("resize", () => {\n'
        "      scheduleDisplaySync(80);\n"
        "    });\n"
        '    window.addEventListener("load", () => {\n'
        "      scheduleDisplaySync(120);\n"
        "    });\n",
        "HTML 模板中未找到全屏事件片段，无法补充分辨率适配监听。",
    )

    return template_text



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

    assist_override = None
    if source_type == "filters":
        candidate = source_path / "assist_latest.json"
        if candidate.exists():
            assist_override = candidate
    else:
        candidate = source_path.parent / "assist_latest.json"
        if candidate.exists():
            assist_override = candidate

    if assist_override is not None:
        try:
            data = read_json(assist_override)
            if isinstance(data, dict) and isinstance(data.get("result"), list):
                extra = data["result"]
                existing = results.get("assist_action")
                if isinstance(existing, list):
                    seen_ids = {a.get("id") for a in existing if isinstance(a, dict) and a.get("id")}
                    for item in extra:
                        if isinstance(item, dict) and item.get("id") not in seen_ids:
                            existing.append(item)
                else:
                    results["assist_action"] = extra
        except Exception:
            pass
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
    simple_dir = dashboard_dir / "simple"
    simple_dir.mkdir(parents=True, exist_ok=True)
    simple_data_path = simple_dir / "data.json"
    simple_html_path = simple_dir / "index.html"

    with data_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    with simple_data_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    payload_json = json.dumps(payload, ensure_ascii=False).replace("</script>", "<\\/script>")
    example_template = Path("index_example.html")
    preferred_template = example_template if example_template.exists() else None
    html = html_template(payload_json, template_path=preferred_template)
    with html_path.open("w", encoding="utf-8") as f:
        f.write(html)

    simple_example_template = Path("simple_example.html")
    preferred_simple_template = simple_example_template if simple_example_template.exists() else None
    simple_html = simple_html_template(payload_json, template_path=preferred_simple_template)
    with simple_html_path.open("w", encoding="utf-8") as f:
        f.write(simple_html)

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
        print(f"[OK] Simple Dashboard HTML: {dash / 'simple' / 'index.html'}")
        print(f"[OK] Simple Dashboard data: {dash / 'simple' / 'data.json'}")
        return 0
    except Exception as e:
        print(f"[ERROR] {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
