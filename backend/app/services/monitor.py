"""采集监控业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "monitor"
RECON_MODULE = "monitor_reconciliation"
REQUIRED_FIELDS = ["面板编号", "采集源总数", "今日采集量"]
STATUS_ORDER = ["正常", "预警", "告警"]
ACTION_RULES = {"查看详情": "正常"}
NEGATIVE_ACTIONS = []


class MonitorService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
        extra: dict[str, str] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("面板编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if extra:
            for field, val in extra.items():
                rows = [row for row in rows if val in str(row.get(field, ""))]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"监控面板 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于采集监控可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"监控面板已{action}"

    # ---------- 消费报告快照与更正 ----------

    def reconciliation_rows(self) -> list[dict[str, Any]]:
        return store.rows(RECON_MODULE)

    def list_reconciliation(
        self,
        *,
        download_id: str | None = None,
        period: str | None = None,
        batch: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self.reconciliation_rows()
        if download_id:
            rows = [row for row in rows if row.get("下载标识") == download_id]
        if period:
            rows = [row for row in rows if row.get("原统计周期") == period]
        if batch:
            rows = [row for row in rows if row.get("更正批次") == batch]
        return list(rows)

    def consume_snapshot(self, values: dict[str, Any]) -> tuple[list[dict[str, Any]] | None, str]:
        """消费一份已确认的报告快照，按来源写入对账记录；同一快照只记一次。"""
        # 延迟导入，避免报告服务与监控服务在模块加载阶段互相依赖。
        from app.services.report import ReportService

        report_service = ReportService()
        download_id = str(values.get("下载标识") or "").strip()
        if not download_id:
            return None, "请提供要消费的报告快照下载标识"
        snapshot = report_service.get_snapshot(download_id)
        if snapshot is None:
            return None, f"报告快照 {download_id} 不存在或未留档"

        rows = self.reconciliation_rows()
        existing = {row.get("采集源") for row in rows if row.get("类型") == "快照" and row.get("下载标识") == download_id}
        package = snapshot["包"]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        created: list[dict[str, Any]] = []
        for summary in package["来源汇总"]:
            if summary["采集源"] in existing:
                continue
            check = next(
                (item for item in package["核对"]["来源核对"] if item["采集源"] == summary["采集源"]),
                {},
            )
            record = {
                "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
                "对账编号": f"RECON-{len(rows) + 1:04d}",
                "类型": "快照",
                "下载标识": download_id,
                "快照标识": package["快照标识"],
                "原统计周期": package["统计周期"],
                "采集源": summary["采集源"],
                "记录数": summary["记录数"],
                "成功量": summary["成功量"],
                "失败量": summary["失败量"],
                "核对一致": bool(check.get("一致")),
                "更正批次": "",
                "回执编号": "",
                "消费人": str(values.get("消费人") or "采集监控"),
                "消费时间": now,
            }
            rows.append(record)
            created.append(record)
        if not created:
            return [], f"快照 {download_id} 已经消费过，本次未重复写入"
        return created, f"已写入 {len(created)} 条来源对账记录"

    def consume_corrections(self, values: dict[str, Any]) -> tuple[list[dict[str, Any]] | None, str]:
        """消费报告快照的更正回执，按「原周期 + 更正批次」写入对账记录。"""
        from app.services.report import ReportService

        report_service = ReportService()
        period = str(values.get("统计周期") or "").strip()
        batch = str(values.get("更正批次") or "").strip()
        receipts = report_service.list_corrections(period or None, None)
        if batch:
            receipts = [item for item in receipts if item.get("更正批次") == batch]
        if not receipts:
            return None, "没有符合条件的更正回执可消费"

        rows = self.reconciliation_rows()
        seen = {
            (row.get("回执编号"), row.get("更正批次"))
            for row in rows
            if row.get("类型") == "更正"
        }
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        created: list[dict[str, Any]] = []
        for receipt in receipts:
            key = (receipt.get("回执编号"), receipt.get("更正批次"))
            if key in seen:
                continue
            record = {
                "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
                "对账编号": f"RECON-{len(rows) + 1:04d}",
                "类型": "更正",
                "下载标识": receipt.get("关联下载标识") or "",
                "快照标识": receipt.get("关联下载标识") or "",
                "原统计周期": receipt.get("统计周期"),
                "采集源": receipt.get("采集源"),
                "记录数": abs(int(receipt.get("差额") or 0)),
                "成功量": "",
                "失败量": receipt.get("更正后失败量"),
                "核对一致": True,
                "基础失败量": receipt.get("基础失败量"),
                "更正前失败量": receipt.get("更正前失败量"),
                "更正后失败量": receipt.get("更正后失败量"),
                "差额": receipt.get("差额"),
                "更正批次": receipt.get("更正批次"),
                "回执编号": receipt.get("回执编号"),
                "消费人": str(values.get("消费人") or "采集监控"),
                "消费时间": now,
            }
            rows.append(record)
            created.append(record)
            seen.add(key)
        if not created:
            return [], "这些更正回执已经消费过，本次未重复写入"
        return created, f"已写入 {len(created)} 条来源对账记录"
