"""采集报告业务规则：报告登记、快照出包、更正回执与核销领取都收在这里。

几个关键口径：
- 快照包按统计周期聚合「已确认」的采集结果，包内明细可逐笔核算来源汇总；
- 已出包的快照原样留档，之后即使发生更正，按原下载标识回查仍是当时的数据；
- 更正按「来源 + 周期 + 更正前/后失败量」判定幂等，同一个变化只计入一次；
- 更正回执记录基础数与应补差额，核销和入账各记一条台账，便于两人先后领取时说清。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.snapshot import (
    FAILURE,
    SUCCESS,
    build_package,
    confirmed_rows,
    is_valid_period,
)
from app.store import store

MODULE = "report"
RESULT_MODULE = "report_result"
SNAPSHOT_MODULE = "report_snapshot"
RECEIPT_MODULE = "report_receipt"
LEDGER_MODULE = "report_ledger"

REQUIRED_FIELDS = ["报告编号", "采集源", "统计周期"]
STATUS_ORDER = ["生成中", "已生成", "已发送"]
ACTION_RULES = {"重新生成": "已生成"}
NEGATIVE_ACTIONS = []

CORRECTION_REQUIRED = ["统计周期", "采集源", "更正前失败量", "更正后失败量"]
CLAIM_MODES = ["核销", "入账"]
BASELINE_DOWNLOAD_ID = "SNPS-20261120-0001"


def _next_batch(rows: list[dict[str, Any]], prefix: str, date_part: str) -> str:
    """按前缀+日期生成批次号；只有生成时就定下的批量核销才是新批次。"""
    used = {
        str(row.get("核销批次"))
        for row in rows
        if str(row.get("核销批次") or "").startswith(f"{prefix}-{date_part}-")
    }
    sequence = 1
    while f"{prefix}-{date_part}-{sequence:02d}" in used:
        sequence += 1
    return f"{prefix}-{date_part}-{sequence:02d}"


def _next_sequence(rows: list[dict[str, Any]], prefix: str, date_part: str) -> str:
    """按前缀+日期生成递增编号，避免依赖数据库自增；用于回执号与单条台账号。"""
    same_day = [str(row.get("编号", "")) for row in rows if str(row.get("编号", "")).startswith(f"{prefix}-{date_part}-")]
    used = 0
    for value in same_day:
        try:
            used = max(used, int(value.rsplit("-", 1)[-1]))
        except ValueError:
            continue
    return f"{prefix}-{date_part}-{used + 1:02d}"


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


class ReportService:
    def __init__(self) -> None:
        self.ensure_baseline_archive()

    # ---------- 报告登记 ----------

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
            rows = [row for row in rows if keyword in str(row.get("报告编号", ""))]
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
            return None, f"采集报告 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于采集报告可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"采集报告已{action}"

    # ---------- 快照下载 ----------

    def _results(self) -> list[dict[str, Any]]:
        return store.rows(RESULT_MODULE)

    def _snapshots(self) -> list[dict[str, Any]]:
        return store.rows(SNAPSHOT_MODULE)

    def ensure_baseline_archive(self) -> dict[str, Any] | None:
        """第一次启动时把已经交给各库核算的周报留档，供按原下载标识回查。"""
        rows = self._snapshots()
        existing = next((row for row in rows if row.get("下载标识") == BASELINE_DOWNLOAD_ID), None)
        if existing is not None:
            return existing
        period = "2026-W47"
        if not confirmed_rows(self._results(), period):
            return None
        package = build_package(
            period=period,
            rows=self._results(),
            download_id=BASELINE_DOWNLOAD_ID,
            generated_at="2026-11-20 08:00:00",
        )
        archive = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "下载标识": BASELINE_DOWNLOAD_ID,
            "统计周期": period,
            "生成时间": package["生成时间"],
            "明细条数": len(package["明细"]),
            "成功量": package["合计"]["成功量"],
            "失败量": package["合计"]["失败量"],
            "来源汇总": package["来源汇总"],
            "状态": "已发送",
            "包": package,
        }
        rows.append(archive)
        return archive

    def list_snapshots(self, period: str | None = None) -> list[dict[str, Any]]:
        self.ensure_baseline_archive()
        rows = self._snapshots()
        if period:
            rows = [row for row in rows if row.get("统计周期") == period]
        return [
            {
                "下载标识": row["下载标识"],
                "统计周期": row["统计周期"],
                "生成时间": row["生成时间"],
                "明细条数": row["明细条数"],
                "成功量": row["成功量"],
                "失败量": row["失败量"],
                "状态": row.get("状态"),
            }
            for row in sorted(rows, key=lambda item: str(item.get("下载标识")))
        ]

    def get_snapshot(self, download_id: str) -> dict[str, Any] | None:
        self.ensure_baseline_archive()
        return next((row for row in self._snapshots() if row.get("下载标识") == download_id), None)

    def download_package(self, period: str) -> tuple[dict[str, Any] | None, str]:
        """按统计周期出包并留档；每次下载生成新的下载标识，旧档不受影响。"""
        if not is_valid_period(period):
            return None, f"统计周期「{period}」格式不正确，应为 2026-W47 这样的周标识"
        self.ensure_baseline_archive()
        rows = self._snapshots()
        now = datetime.now()
        sequence = len([row for row in rows if str(row.get("下载标识", "")).startswith("SNPS-")]) + 1
        while True:
            download_id = f"SNPS-{now:%Y%m%d}-{sequence:04d}"
            if all(row.get("下载标识") != download_id for row in rows):
                break
            sequence += 1
        try:
            package = build_package(
                period=period,
                rows=self._results(),
                download_id=download_id,
                generated_at=now.strftime("%Y-%m-%d %H:%M:%S"),
            )
        except ValueError as exc:
            return None, str(exc)
        rows.append(
            {
                "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
                "下载标识": download_id,
                "统计周期": period,
                "生成时间": package["生成时间"],
                "明细条数": len(package["明细"]),
                "成功量": package["合计"]["成功量"],
                "失败量": package["合计"]["失败量"],
                "来源汇总": package["来源汇总"],
                "状态": "已下载",
                "包": package,
            }
        )
        return package, ""

    # ---------- 更正回执 ----------

    def _receipts(self) -> list[dict[str, Any]]:
        return store.rows(RECEIPT_MODULE)

    def _ledger(self) -> list[dict[str, Any]]:
        return store.rows(LEDGER_MODULE)

    def _source_rows(self, period: str, source: str) -> list[dict[str, Any]]:
        return [row for row in confirmed_rows(self._results(), period) if row.get("采集源") == source]

    def list_corrections(self, period: str | None = None, source: str | None = None) -> list[dict[str, Any]]:
        rows = self._receipts()
        if period:
            rows = [row for row in rows if row.get("统计周期") == period]
        if source:
            rows = [row for row in rows if row.get("采集源") == source]
        return [self._receipt_view(row) for row in rows]

    def get_correction(self, batch: str) -> dict[str, Any] | None:
        row = next((item for item in self._receipts() if item.get("更正批次") == batch), None)
        return self._receipt_view(row) if row else None

    def _receipt_view(self, receipt: dict[str, Any]) -> dict[str, Any]:
        """回执对外视图：基础数、应补差额、已经核销的批次一目了然。"""
        view = {key: value for key, value in receipt.items() if key != "id"}
        view["应补差额"] = receipt.get("差额")
        writeoffs = [
            item
            for item in self._ledger()
            if item.get("回执编号") == receipt.get("回执编号") and item.get("类型") == "核销"
        ]
        view["核销记录"] = writeoffs
        view["已核销条数"] = len(writeoffs)
        view["核销批次"] = sorted({str(item.get("核销批次")) for item in writeoffs})
        return view

    def submit_correction(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str, bool]:
        """登记更正；同一来源同一周期的同一次变化只计入一次，重复到达直接返回原回执。"""
        missing = [field for field in CORRECTION_REQUIRED if str(values.get(field) or "").strip() == ""]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}", False

        period = str(values.get("统计周期") or "").strip()
        source = str(values.get("采集源") or "").strip()
        before = _to_int(values.get("更正前失败量"))
        after = _to_int(values.get("更正后失败量"))
        if before is None or after is None:
            return None, "更正前失败量与更正后失败量必须是整数", False
        if before == after:
            return None, "更正前后失败量相同，没有需要处理的变化", False
        if not is_valid_period(period):
            return None, f"统计周期「{period}」格式不正确，应为 2026-W47 这样的周标识", False
        if before < 0 or after < 0:
            return None, "失败量不能为负数", False

        receipt = next(
            (
                item
                for item in self._receipts()
                if item.get("统计周期") == period
                and item.get("采集源") == source
                and item.get("更正前失败量") == before
                and item.get("更正后失败量") == after
            ),
            None,
        )
        if receipt is not None:
            return self._receipt_view(receipt), "该更正已经登记过，未重复计入", True

        batch = str(values.get("更正批次") or "").strip()
        if batch:
            existing_batch = next((item for item in self._receipts() if item.get("更正批次") == batch), None)
            if existing_batch is not None:
                same_change = (
                    existing_batch.get("统计周期") == period
                    and existing_batch.get("采集源") == source
                    and existing_batch.get("更正前失败量") == before
                    and existing_batch.get("更正后失败量") == after
                )
                if same_change:
                    return self._receipt_view(existing_batch), "该更正批次已经登记过，未重复计入", True
                return None, f"更正批次 {batch} 已用于其它更正，请更换批次号", False

        source_rows = self._source_rows(period, source)
        if not source_rows:
            return None, f"统计周期 {period} 下没有来源「{source}」的已确认采集结果", False
        base_failure = sum(1 for row in source_rows if row.get("采集结果") == FAILURE)
        base_success = sum(1 for row in source_rows if row.get("采集结果") == SUCCESS)
        if before != base_failure:
            return None, f"更正前失败量 {before} 与当前有效失败量 {base_failure} 不一致，请核对后重报", False

        delta = after - before
        # 差额为正说明失败量增加，要把成功明细改为失败；为负则反过来。
        if delta > 0:
            candidates = [row for row in source_rows if row.get("采集结果") == SUCCESS]
            target_result = FAILURE
        else:
            candidates = [row for row in source_rows if row.get("采集结果") == FAILURE]
            target_result = SUCCESS
        if len(candidates) < abs(delta):
            return None, f"需要调整 {abs(delta)} 条明细，但当前只有 {len(candidates)} 条可调整，无法完成更正", False

        now = datetime.now()
        date_part = now.strftime("%Y%m%d")
        sequence = len(self._receipts()) + 1
        while True:
            batch = str(values.get("更正批次") or "").strip() or f"CORR-{date_part}-{sequence:02d}"
            if all(item.get("更正批次") != batch for item in self._receipts()):
                break
            sequence += 1
        receipt_no = _next_sequence(self._receipts(), "RCPT", date_part)
        # 回执关联的是报告交给各库核算时的那份快照；没有指定就取该周期的留档包。
        self.ensure_baseline_archive()
        linked_download_id = str(values.get("下载标识") or "").strip()
        if not linked_download_id:
            archive = next(
                (
                    item
                    for item in self._snapshots()
                    if item.get("统计周期") == period
                ),
                None,
            )
            linked_download_id = str((archive or {}).get("下载标识") or "")
        changed: list[str] = []
        for row in candidates[: abs(delta)]:
            row["采集结果"] = target_result
            row["更正批次"] = batch
            changed.append(str(row.get("明细编号")))

        receipt = {
            "id": max((int(item.get("id", 0)) for item in self._receipts()), default=0) + 1,
            "编号": receipt_no,
            "回执编号": receipt_no,
            "更正批次": batch,
            "统计周期": period,
            "采集源": source,
            "关联下载标识": linked_download_id,
            "基础成功量": base_success,
            "基础失败量": base_failure,
            "更正前失败量": before,
            "更正后失败量": after,
            "差额": delta,
            "影响明细": changed,
            "状态": "待核销",
            "核销批次": [],
            "核销条数": 0,
            "登记人": str(values.get("登记人") or "值班管理员"),
            "登记时间": now.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._receipts().append(receipt)
        return self._receipt_view(receipt), f"更正回执 {receipt_no} 已登记，差额 {delta:+d}", False

    # ---------- 核销 / 入账领取 ----------

    def claim(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        operator = str(values.get("领取人") or values.get("operator") or "").strip()
        mode = str(values.get("模式") or values.get("mode") or "").strip()
        period = str(values.get("统计周期") or "").strip()
        if not operator:
            return None, "请填写领取人"
        if mode not in CLAIM_MODES:
            return None, f"领取模式只能是 {'、'.join(CLAIM_MODES)}"
        if not period:
            return None, "请指定统计周期"
        if not is_valid_period(period):
            return None, f"统计周期「{period}」格式不正确，应为 2026-W47 这样的周标识"

        receipts = [
            item
            for item in self._receipts()
            if item.get("统计周期") == period
            and (not values.get("更正批次") or item.get("更正批次") == values.get("更正批次"))
        ]
        ledger = self._ledger()
        created: list[dict[str, Any]] = []

        if mode == "核销":
            pending = [
                item
                for item in receipts
                if not [
                    entry
                    for entry in ledger
                    if entry.get("回执编号") == item.get("回执编号") and entry.get("类型") == "核销"
                ]
            ]
            if not pending:
                # 没有待核销回执时也把回执原样带回，两位结算员先后来领都能看到基础数与批次。
                linked = receipts
                return self._claim_view(operator, period, mode, linked, [], "没有待核销的更正回执"), ""
            date_part = datetime.now().strftime("%Y%m%d")
            writeoff_batch = _next_batch(ledger, "WOFF", date_part)
            for receipt in pending:
                for unit in range(abs(int(receipt.get("差额") or 0))):
                    entry = {
                        "id": max((int(item.get("id", 0)) for item in ledger), default=0) + 1,
                        "编号": _next_sequence(ledger, "LEDG", date_part),
                        "类型": "核销",
                        "领取人": operator,
                        "统计周期": period,
                        "采集源": receipt.get("采集源"),
                        "回执编号": receipt.get("回执编号"),
                        "更正批次": receipt.get("更正批次"),
                        "核销批次": writeoff_batch,
                        "基础失败量": receipt.get("基础失败量"),
                        "应补差额": receipt.get("差额"),
                        "数量": 1,
                        "差额": 1 if int(receipt.get("差额") or 0) > 0 else -1,
                        "登记时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    ledger.append(entry)
                    created.append(entry)
                receipt["核销批次"] = sorted(set(list(receipt.get("核销批次") or []) + [writeoff_batch]))
                receipt["核销条数"] = int(receipt.get("核销条数") or 0) + abs(int(receipt.get("差额") or 0))
                receipt["状态"] = "已核销"
            return self._claim_view(
                operator, period, mode, pending, created,
                f"已按更正回执核销 {len(created)} 条",
            ), ""

        # 入账：按周期领取本周可入账的报告，已经核销的批次随回执说明。
        reports = [
            row
            for row in store.rows(MODULE)
            if str(row.get("统计周期")) == period and row.get("status") in ("已生成", "已发送")
        ]
        if not reports:
            return None, f"统计周期 {period} 没有可入账的采集报告"
        already = {
            (entry.get("领取人"), entry.get("统计周期"), entry.get("报告编号"))
            for entry in ledger
            if entry.get("类型") == "入账"
        }
        date_part = datetime.now().strftime("%Y%m%d")
        for report in reports:
            key = (operator, period, report.get("报告编号"))
            if key in already:
                continue
            baseline = self._report_baseline(report)
            effective = self._effective_failure(period, str(report.get("采集源")))
            entry = {
                "id": max((int(item.get("id", 0)) for item in ledger), default=0) + 1,
                "编号": _next_sequence(ledger, "LEDG", date_part),
                "类型": "入账",
                "领取人": operator,
                "统计周期": period,
                "采集源": report.get("采集源"),
                "报告编号": report.get("报告编号"),
                "回执编号": "",
                "更正批次": "",
                "基础失败量": baseline,
                "应补差额": effective - baseline,
                "数量": 1,
                "差额": effective - _to_int(report.get("失败量") or 0),
                "登记时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            ledger.append(entry)
            created.append(entry)
            already.add(key)
        message = f"已领取 {len(reports)} 份可入账报告" if created else "本周报告已领取过，未重复入账"
        return self._claim_view(operator, period, mode, receipts, created, message, reports), ""

    def _report_baseline(self, report: dict[str, Any]) -> int:
        """报告交给各库核算时的基础失败量：优先取对应快照里的来源汇总。"""
        period = str(report.get("统计周期") or "")
        source = str(report.get("采集源") or "")
        archive = next(
            (
                item
                for item in self._snapshots()
                if item.get("统计周期") == period
                and any(summary.get("采集源") == source for summary in item.get("来源汇总") or [])
            ),
            None,
        )
        if archive is not None:
            summary = next(summary for summary in archive["来源汇总"] if summary.get("采集源") == source)
            return int(summary.get("失败量") or 0)
        return _to_int(report.get("失败量") or 0)

    def _effective_failure(self, period: str, source: str) -> int:
        return sum(
            1
            for row in confirmed_rows(self._results(), period)
            if row.get("采集源") == source and row.get("采集结果") == FAILURE
        )

    def _claim_view(
        self,
        operator: str,
        period: str,
        mode: str,
        receipts: list[dict[str, Any]],
        created: list[dict[str, Any]],
        message: str,
        reports: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        receipt_views = []
        for receipt in receipts:
            writeoffs = [entry for entry in self._ledger() if entry.get("回执编号") == receipt.get("回执编号") and entry.get("类型") == "核销"]
            receipt_views.append(
                {
                    "回执编号": receipt.get("回执编号"),
                    "更正批次": receipt.get("更正批次"),
                    "采集源": receipt.get("采集源"),
                    "关联下载标识": receipt.get("关联下载标识"),
                    "基础成功量": receipt.get("基础成功量"),
                    "基础失败量": receipt.get("基础失败量"),
                    "更正前失败量": receipt.get("更正前失败量"),
                    "更正后失败量": receipt.get("更正后失败量"),
                    "应补差额": receipt.get("差额"),
                    "核销状态": receipt.get("状态"),
                    "核销批次": list(receipt.get("核销批次") or []),
                    "核销条数": sum(1 for entry in writeoffs),
                    "核销人": sorted({str(entry.get("领取人")) for entry in writeoffs}),
                }
            )
        report_views = []
        for report in reports or []:
            baseline = self._report_baseline(report)
            effective = self._effective_failure(period, str(report.get("采集源")))
            report_views.append(
                {
                    "报告编号": report.get("报告编号"),
                    "采集源": report.get("采集源"),
                    "统计周期": report.get("统计周期"),
                    "基础失败量": baseline,
                    "可入账失败量": effective,
                    "应补差额": effective - baseline,
                }
            )
        return {
            "ok": True,
            "message": message,
            "领取人": operator,
            "统计周期": period,
            "模式": mode,
            "核销条数": sum(abs(int(entry.get("差额") or 1)) for entry in created if entry.get("类型") == "核销"),
            "核销批次": sorted({str(entry.get("核销批次")) for entry in created if entry.get("类型") == "核销"}),
            "回执": receipt_views,
            "报告": report_views,
            "台账": created,
        }

    def list_ledger(self, period: str | None = None, operator: str | None = None) -> list[dict[str, Any]]:
        rows = self._ledger()
        if period:
            rows = [row for row in rows if row.get("统计周期") == period]
        if operator:
            rows = [row for row in rows if row.get("领取人") == operator]
        return [row for row in rows if row.get("回执编号") or row.get("报告编号")]
