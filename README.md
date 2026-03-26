# SJTU Make 自动抓取 + 3D打印中文看板

默认目标页面：

`https://make.sjtu.edu.cn/admin/statistics/order-count`

当前功能：
- 自动复用登录会话
- 自动遍历筛选按钮并抓取接口数据
- 自动生成中文看板（仅展示 3D 打印相关数据）
- 持续运行任务并每 30 分钟自动更新
- 内置网页服务，浏览器可直接访问看板

## 1. 环境准备

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

## 2. 持续运行模式（推荐）

```powershell
# Windows（双击）
start_win.bat
# Windows（免环境 .exe）
dist\dashboard_runner.exe  # 双击即运行

# Windows（命令行）
python run.py

# mac/Linux（命令行）
./start_mac.sh
```

默认行为：
- 启动网站服务：`http://0.0.0.0:8000`
- 立即执行一次抓取 + 生成看板
- 之后每 30 分钟自动更新一次
- 任务失败不会退出，会在下一轮继续执行

常用参数：

```powershell
python run.py --host 0.0.0.0 --port 8080
python run.py --interval-minutes 30
python run.py --auto-login-if-missing-state
python run.py --single
```

说明：
- `--auto-login-if-missing-state`：当会话文件不存在时先执行登录流程
- `--single`：每轮仅抓首屏请求
- 停止服务按 `Ctrl + C`

快捷启动：
- Windows：双击 `start_win.bat`（自动寻找 Python，窗口不立即关闭）
- Windows（免环境）：双击 `dist\dashboard_runner.exe`（内置 Python + Playwright）
- mac/Linux：在终端运行 `./start_mac.sh`（首次可能需要 `chmod +x start_mac.sh`）

生成免环境 EXE：

```powershell
./package_windows.ps1
```

脚本会自动：
- 创建/复用 `.venv`
- 安装依赖 + PyInstaller + Playwright 浏览器
- 生成 `dist\dashboard_runner.exe` 并携带 `ms-playwright` 目录
- exe 采用 GUI 模式（`pythonw`），运行时不再弹出控制台窗口；日志可查看 `logs/service.log`

CI 发布：
- 推送 `v*` 标签或在 Actions 手动触发 `build-release`，GitHub Actions 会在 Windows 环境运行 `package_windows.ps1`，并把 `dist` 压缩后作为 Release 附件。

Windows 提示 “Python not found” 处理方式：
- 方式 A（推荐）：在项目根目录新建 `PY_PATH.txt`，写入你本机的 Python 路径（如 `C:\\Users\\zhoujie\\.conda\\envs\\zhoujie\\python.exe`），保存后再次双击 `start_win.bat`。
- 方式 B：确保安装了 Windows Python Launcher（可用 `py -3`），或把你的 `python.exe` 加入系统 PATH。

mac/Linux 指定 Python 环境方式：
- 方式 A（推荐）：在项目根目录新建 `PY_PATH.txt`，第一行写 Python 命令或绝对路径（如 `/Users/you/miniconda3/envs/zhoujie/bin/python`），`./start_mac.sh` 会优先使用。
- 方式 B：在终端预先导出环境变量：`export PY_CMD=/Users/you/miniconda3/envs/zhoujie/bin/python`，然后运行 `./start_mac.sh`。
- 方式 C：确保 `python3` 或 `python` 在 PATH 中；若都找不到，脚本会提示你输入 Python 路径。

无弹窗后台运行（Windows）
- 需求：登录完成后可在后台运行，不占用或依赖控制台窗口；再次点击可一键关闭。
- 步骤：
  1) 首次用 `start_win.bat` 完成登录（会弹出浏览器，回车确认）。生成 `state/auth_state.json` 后即可进入无弹窗模式。
  2) 使用 `toggle_service.vbs` 切换运行状态：
     - 若服务未运行：隐藏启动 `run.py`（使用 `pythonw`），日志写入 `logs/service.log`。
     - 若服务已运行：自动结束对应进程（等同“关闭服务”）。
  3) 如需指定 Python 路径，在项目根放置 `PY_PATH.txt`（写入 `python.exe` 路径，脚本会自动换成 `pythonw.exe`）。

无弹窗后台运行（mac/Linux）
- 需求：在终端中后台运行且不占用前台窗口。
- 示例：
  ```bash
  nohup ./start_mac.sh > logs/service.log 2>&1 &
  disown
  ```
  - 日志输出在 `logs/service.log`
  - 结束可用 `pkill -f run_universal.py` 或找到对应 PID 用 `kill`

## 3. 单次执行（手动）

```powershell
python main.py
```

行为：
- 若 `state/auth_state.json` 存在：直接抓取并生成看板
- 若不存在：先打开浏览器手动登录，再自动抓取并生成看板

## 4. 输出位置

抓取结果目录（每次一个新目录）：

`output/filters_时间戳/`

看板文件：

`dashboard/index.html`

看板数据：

`dashboard/data.json`

## 5. 常用命令

```powershell
python main.py login
python main.py fetch
python main.py fetch --headed
python main.py fetch --single
python main.py --no-dashboard
```

说明：
- `fetch` 默认遍历筛选按钮并导出
- `--single` 只抓首屏请求，不点击筛选按钮
- `--headed` 显示浏览器窗口，便于观察
- `--no-dashboard` 只抓数据，不生成看板

## 6. 常用参数

```powershell
python main.py --filter-wait-ms 5000
python main.py --filter-selector ".el-radio-button__inner"
python main.py --browser-channel chrome
# 浏览器渠道说明：默认 `auto` 会依次尝试已安装的 Edge/Chrome/Chromium，全部不可用时自动回落到内置的 Playwright Chromium。
python main.py --assist-page-url https://make.sjtu.edu.cn/admin/statistics/assist-action
# 助管操作页面：若有自定义域名或镜像，可用此参数覆盖；默认会额外抓取一次助管操作页以丰富看板。
```

## 7. 单独重建看板

```powershell
python dashboard_builder.py
```

指定某次抓取目录：

```powershell
python dashboard_builder.py --run-path output/filters_20260307_232718
```

## 8. 排查

1. `State file not found`：先运行 `python main.py login`
2. 某筛选 `record_count=0`：通常是该筛选只切前端缓存，没有新接口请求
3. 自动识别筛选不准：加 `--filter-selector`
4. 会话过期：删除 `state/auth_state.json` 后重新运行

## 9. 合规提醒

仅在你有合法授权的前提下抓取数据，并遵守平台使用政策。
