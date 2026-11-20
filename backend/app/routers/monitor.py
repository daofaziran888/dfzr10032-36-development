"""采集监控接口：维护监控面板，覆盖查看详情等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.monitor import MonitorService

router = APIRouter(prefix="/api/monitor", tags=["采集监控"])

service = MonitorService()

LIST_FIELDS = ["面板编号", "采集源总数", "今日采集量", "成功率", "平均延迟", "失败重试", "异常告警", "更新时间"]
STATUSES = ["正常", "预警", "告警"]


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出采集监控清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "monitor", "total": total, "items": items}


@router.get("/reconciliation")
def list_reconciliation(
    download_id: str | None = Query(default=None, description="按报告快照下载标识回查"),
    period: str | None = Query(default=None, description="按原统计周期回查"),
    batch: str | None = Query(default=None, description="按更正批次回查"),
) -> dict[str, Any]:
    """来源对账记录：消费报告快照与更正后写入，可追查原周期和更正批次。"""
    items = service.list_reconciliation(download_id=download_id, period=period, batch=batch)
    return {"items": items, "total": len(items)}


@router.post("/reconciliation/snapshot")
def consume_snapshot(payload: EntryPayload) -> dict[str, Any]:
    """消费一份已确认的采集报告快照，按来源写入对账记录。"""
    items, message = service.consume_snapshot(payload.values)
    return {"ok": items is not None, "message": message, "items": items or []}


@router.post("/reconciliation/corrections")
def consume_corrections(payload: EntryPayload) -> dict[str, Any]:
    """消费报告快照的更正回执，写入带原周期与更正批次的来源对账记录。"""
    items, message = service.consume_corrections(payload.values)
    return {"ok": items is not None, "message": message, "items": items or []}


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按面板编号检索"),
    status: str | None = Query(default=None, description="正常、预警、告警"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按面板编号与状态过滤采集监控列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    extra = {k: v for k, v in request.query_params.items() if k not in ("keyword", "status", "page", "size") and v.strip()}
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size, extra=extra)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条监控面板明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"监控面板 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条监控面板，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="监控面板已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条监控面板执行查看详情；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
