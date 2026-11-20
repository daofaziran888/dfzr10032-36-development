"""采集报告接口：报告登记、按周期出包下载、更正回执与核销领取。"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.report import ReportService

router = APIRouter(prefix="/api/report", tags=["采集报告"])

service = ReportService()

LIST_FIELDS = ["报告编号", "采集源", "统计周期", "总采集量", "成功量", "失败量", "平均耗秒", "生成时间"]
STATUSES = ["生成中", "已生成", "已发送"]


def _download_response(package: dict[str, Any]) -> Response:
    body = json.dumps(package, ensure_ascii=False, indent=2).encode("utf-8")
    filename = f"{package['统计周期']}-{package['快照标识']}.json"
    return Response(
        content=body,
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Download-Id": package["快照标识"],
        },
    )


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出采集报告清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "report", "total": total, "items": items}


@router.get("/snapshots")
def list_snapshots(period: str | None = Query(default=None, description="按统计周期过滤")) -> dict[str, Any]:
    """列出已留档的报告快照，便于按原下载标识回查。"""
    items = service.list_snapshots(period)
    return {"items": items, "total": len(items)}


@router.get("/snapshots/download")
def download_snapshot(period: str = Query(description="统计周期，例如 2026-W47")) -> Response:
    """按统计周期聚合已确认采集结果并下载快照包；同时留档供后续回查。"""
    package, message = service.download_package(period)
    if package is None:
        raise HTTPException(status_code=400, detail=message)
    return _download_response(package)


@router.get("/snapshots/{download_id}")
def get_snapshot(download_id: str) -> dict[str, Any]:
    """按下载标识回查快照包，内容保持当时出包的样子。"""
    snapshot = service.get_snapshot(download_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"快照 {download_id} 不存在或未留档")
    return snapshot["包"]


@router.get("/snapshots/{download_id}/file")
def download_archived_snapshot(download_id: str) -> Response:
    """下载已留档的快照包，用于按原标识重新取回旧文件。"""
    snapshot = service.get_snapshot(download_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"快照 {download_id} 不存在或未留档")
    return _download_response(snapshot["包"])


@router.get("/corrections")
def list_corrections(
    period: str | None = Query(default=None),
    source: str | None = Query(default=None),
) -> dict[str, Any]:
    """列出更正回执，可追查原周期与更正批次。"""
    items = service.list_corrections(period, source)
    return {"items": items, "total": len(items)}


@router.post("/corrections")
def submit_correction(payload: EntryPayload) -> ActionResult:
    """登记一条更正回执：同一来源同一周期的同一次变化只计入一次。"""
    receipt, message, duplicate = service.submit_correction(payload.values)
    if receipt is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry={**receipt, "重复提交": duplicate})


@router.get("/corrections/{batch}")
def get_correction(batch: str) -> dict[str, Any]:
    """按更正批次读取回执。"""
    receipt = service.get_correction(batch)
    if receipt is None:
        raise HTTPException(status_code=404, detail=f"更正批次 {batch} 不存在")
    return receipt


@router.post("/claims")
def claim(payload: EntryPayload) -> dict[str, Any]:
    """按周期领取：核销已记旧数的差额，或领取本周可入账的报告。"""
    result, message = service.claim(payload.values)
    if result is None:
        return {"ok": False, "message": message}
    return result


@router.get("/ledger")
def list_ledger(
    period: str | None = Query(default=None),
    operator: str | None = Query(default=None),
) -> dict[str, Any]:
    """来源对账台账：核销与入账各记一条，可追查回执、批次和周期。"""
    items = service.list_ledger(period, operator)
    return {"items": items, "total": len(items)}


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按报告编号检索"),
    status: str | None = Query(default=None, description="生成中、已生成、已发送"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按报告编号与状态过滤采集报告列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    extra = {k: v for k, v in request.query_params.items() if k not in ("keyword", "status", "page", "size") and v.strip()}
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size, extra=extra)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条采集报告明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"采集报告 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条采集报告，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="采集报告已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条采集报告执行重新生成；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
