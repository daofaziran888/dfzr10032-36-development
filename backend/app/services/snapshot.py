"""采集报告快照的纯计算：把已确认采集结果按统计周期聚合成可下载的报告包。

这一层不依赖内存仓库，方便在示例数据、接口与测试之间复用同一套聚合口径。
包里的「来源汇总」与「明细」必须能相互核算：汇总的成功量、失败量、记录数
都等于明细逐笔计数的结果，否则拒绝出包。
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from typing import Any

PACKAGE_TYPE = "采集报告快照"
PACKAGE_VERSION = "1.0"
PERIOD_PATTERN = re.compile(r"^\d{4}-W(0[1-9]|[1-4]\d|5[0-3])$")
SUCCESS = "成功"
FAILURE = "失败"


def is_valid_period(period: str) -> bool:
    return bool(PERIOD_PATTERN.match(period or ""))


def confirmed_rows(rows: list[dict[str, Any]], period: str) -> list[dict[str, Any]]:
    """只保留指定周期内、状态为已确认的采集结果。"""
    return [
        row
        for row in rows
        if str(row.get("统计周期") or "") == period and row.get("status") == "已确认"
    ]


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按来源汇总；每个来源的成功量与失败量之和必须等于记录数。"""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("采集源"))].append(row)

    summaries: list[dict[str, Any]] = []
    for source in sorted(grouped):
        source_rows = grouped[source]
        success = sum(1 for row in source_rows if row.get("采集结果") == SUCCESS)
        failure = sum(1 for row in source_rows if row.get("采集结果") == FAILURE)
        if success + failure != len(source_rows):
            raise ValueError(f"来源「{source}」存在无法归类的采集结果，拒绝出包")
        durations = [float(row.get("耗秒") or 0) for row in source_rows]
        summaries.append(
            {
                "采集源": source,
                "记录数": len(source_rows),
                "成功量": success,
                "失败量": failure,
                "平均耗秒": round(sum(durations) / len(durations), 2) if durations else 0,
            }
        )
    return summaries


def detail_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """生成包内明细；只带报告核算需要的字段，保持逐笔可核对。"""
    detail = [
        {
            "明细编号": row.get("明细编号"),
            "采集源": row.get("采集源"),
            "统计周期": row.get("统计周期"),
            "采集结果": row.get("采集结果"),
            "记录主键": row.get("记录主键"),
            "耗秒": row.get("耗秒"),
            "采集时间": row.get("采集时间"),
            "更正批次": row.get("更正批次"),
        }
        for row in rows
    ]
    return sorted(detail, key=lambda item: str(item.get("明细编号") or ""))


def _checksum(detail: list[dict[str, Any]]) -> str:
    payload = json.dumps(detail, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_package(
    *,
    period: str,
    rows: list[dict[str, Any]],
    download_id: str,
    generated_at: str,
) -> dict[str, Any]:
    """按统计周期构建快照包；来源汇总与包内明细不一致时抛 ValueError。"""
    if not is_valid_period(period):
        raise ValueError(f"统计周期「{period}」格式不正确，应为 2026-W47 这样的周标识")

    period_rows = confirmed_rows(rows, period)
    if not period_rows:
        raise ValueError(f"统计周期 {period} 没有已确认的采集结果，无法生成快照")

    detail = detail_rows(period_rows)
    summaries = summarize(period_rows)

    source_checks: list[dict[str, Any]] = []
    for summary in summaries:
        source_detail = [item for item in detail if item.get("采集源") == summary["采集源"]]
        checked = {
            "采集源": summary["采集源"],
            "汇总记录数": summary["记录数"],
            "明细记录数": len(source_detail),
            "汇总成功量": summary["成功量"],
            "明细成功量": sum(1 for item in source_detail if item.get("采集结果") == SUCCESS),
            "汇总失败量": summary["失败量"],
            "明细失败量": sum(1 for item in source_detail if item.get("采集结果") == FAILURE),
        }
        checked["一致"] = (
            checked["汇总记录数"] == checked["明细记录数"]
            and checked["汇总成功量"] == checked["明细成功量"]
            and checked["汇总失败量"] == checked["明细失败量"]
        )
        source_checks.append(checked)

    totals = {
        "记录数": sum(item["记录数"] for item in summaries),
        "成功量": sum(item["成功量"] for item in summaries),
        "失败量": sum(item["失败量"] for item in summaries),
    }
    detail_success = sum(1 for item in detail if item.get("采集结果") == SUCCESS)
    detail_failure = sum(1 for item in detail if item.get("采集结果") == FAILURE)
    consistent = (
        bool(source_checks)
        and all(item["一致"] for item in source_checks)
        and totals["记录数"] == len(detail)
        and totals["成功量"] == detail_success
        and totals["失败量"] == detail_failure
        and all(item.get("统计周期") == period for item in detail)
    )
    if not consistent:
        raise ValueError("来源汇总与包内明细无法逐笔核对，拒绝出包")

    return {
        "包类型": PACKAGE_TYPE,
        "包版本": PACKAGE_VERSION,
        "快照标识": download_id,
        "统计周期": period,
        "生成时间": generated_at,
        "来源汇总": summaries,
        "合计": totals,
        "明细": detail,
        "核对": {
            "统计周期": period,
            "明细条数": len(detail),
            "汇总记录数": totals["记录数"],
            "汇总成功量": totals["成功量"],
            "汇总失败量": totals["失败量"],
            "来源核对": source_checks,
            "一致": consistent,
        },
        "明细指纹": _checksum(detail),
    }
