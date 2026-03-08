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
python run.py
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
