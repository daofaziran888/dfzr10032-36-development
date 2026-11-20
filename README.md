# 多源数据采集与RPA自动化平台

面向网页抓取、API接入、增量采集、RPA流程编排、数据校验与采集监控的数据工程平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 数据源配置 | `datasource` | 数据源 | 源端编号、连接类型、接入地址 |
| 网页采集规则 | `crawler` | 采集规则 | 规则编号、目标网址、页面选择器 |
| API接入管理 | `apiclient` | API客户端 | 客户端编号、接口名称、请求方法 |
| 增量采集 | `incremental` | 增量游标 | 游标编号、来源标识、增量字段 |
| RPA任务编排 | `robot_task` | RPA任务 | 任务编号、任务名称、页面定位器 |
| 数据接入通道 | `ingestion` | 接入通道 | 通道编号、通道名称、输入格式 |
| 格式解析器 | `parser` | 解析配置 | 解析编号、输入格式、输出格式 |
| 采集结果校验 | `validator` | 校验规则 | 规则编号、校验字段、校验类型 |
| 采集去重 | `dedup` | 去重策略 | 策略编号、输入来源、去重键 |
| 采集调度 | `schedule` | 调度计划 | 计划编号、关联任务、调度周期 |
| 采集监控 | `monitor` | 监控面板 | 面板编号、采集源总数、今日采集量 |
| 采集日志 | `log_viewer` | 日志条目 | 日志编号、关联任务、日志级别 |
| 凭证管理 | `auth` | 认证凭证 | 凭证编号、凭证类型、关联数据源 |
| 采集转换管道 | `transform` | 转换节点 | 节点编号、输入来源、输出目标 |
| 数据流转编排 | `flow` | 流转管道 | 管道编号、管道名称、起始节点 |
| 数据血缘追踪 | `lineage` | 血缘关系 | 关系编号、上游节点、下游节点 |
| 采集报告 | `report` | 采集报告 / 快照包 | 报告编号、采集源、统计周期 |

## 采集报告快照与更正

采集报告模块除了登记记录，还提供可下载的报告快照包，用于交付给各库核算：

- `GET /api/report/snapshots/download?period=2026-W47`：按统计周期聚合**已确认**的采集结果，
  返回带 `attachment` 的 JSON 包（响应头带 `X-Download-Id`）。包内含来源汇总、逐笔明细和
  `核对` 结果——每个来源的成功量、失败量、记录数都必须等于明细逐笔计数，否则拒绝出包。
- `GET /api/report/snapshots`：已留档的快照清单；`GET /api/report/snapshots/{下载标识}`
  按原标识回查当时的包，`/file` 重新下载。更正之后旧包内容保持不变。
- `POST /api/report/corrections`：登记更正回执（统计周期、采集源、更正前/后失败量）。
  同一来源同一周期的同一次变化只计入一次，重复提交返回原回执；回执记录基础数与应补差额
  （`应补差额` = 更正后 − 更正前）。
- `POST /api/report/claims`：`模式=核销` 按回执逐条核销旧数，同一个回执只核销一次；
  `模式=入账` 按周期领取可入账报告，返回基础失败量、可入账失败量与应补差额，并带出
  关联回执及其已核销批次。
- `GET /api/report/ledger`：核销与入账的台账，可追查回执编号、更正批次与统计周期。

采集监控消费报告快照及其更正，写入来源对账记录：

- `POST /api/monitor/reconciliation/snapshot`：按下载标识消费快照，每个来源一条对账记录；
- `POST /api/monitor/reconciliation/corrections`：按统计周期（可加更正批次）消费更正回执；
- `GET /api/monitor/reconciliation?download_id=&period=&batch=`：按原周期、下载标识或
  更正批次回查对账记录。

内部台账表（`report_result` / `report_snapshot` / `report_receipt` / `report_ledger` /
`monitor_reconciliation`）不参与运营概览的模块统计。

后端测试：`cd backend && python3 -m pytest tests -q`。

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。
