"""顶板管理接口：维护顶板监测，覆盖离层预警、变形报警、加固完成等动作。

离层量监测子模块：小时上报查询、补采续接、缺口记录、连续超限判定与顶板日报。
注意静态路径（/readings、/gaps 等）必须注册在 /{entry_id} 之前，否则会被当成编号截胡。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.roof import RoofService
from app.services.roof_monitor import RoofMonitorService

router = APIRouter(prefix="/api/roof", tags=["顶板管理"])

service = RoofService()
monitor = RoofMonitorService()

LIST_FIELDS = ["监测编号", "所在工作面", "离层量", "锚杆受力", "收敛变形", "监测日期", "监测人员", "顶板状态"]
STATUSES = ["稳定", "离层预警", "变形超标", "已加固"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按监测编号检索"),
    status: str | None = Query(default=None, description="稳定、离层预警、变形超标、已加固"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按监测编号与状态过滤顶板管理列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出顶板管理清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "roof", "total": total, "items": items}


@router.get("/readings")
def list_readings(
    workface: str = Query(description="所在工作面"),
    start: str = Query(description="时段开始，YYYY-MM-DD HH:00"),
    end: str = Query(description="时段结束，YYYY-MM-DD HH:00"),
) -> dict[str, Any]:
    """查询工作面时段内的离层量上报：只返回真实上报行，缺测时段单列，绝不补零。"""
    result, error = monitor.list_readings(workface=workface, start=start, end=end)
    if result is None:
        raise HTTPException(status_code=400, detail=error)
    return result


@router.post("/readings", response_model=ActionResult)
def ingest_reading(payload: EntryPayload) -> ActionResult:
    """登记一条离层量上报/补采：同工作面同采集时刻接续原记录，只保留最新一版。"""
    entry, message = monitor.ingest_reading(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/gaps")
def list_gaps(
    workface: str | None = Query(default=None, description="按工作面过滤"),
    status: str | None = Query(default=None, description="待回填、已回填"),
) -> dict[str, Any]:
    """缺口记录列表：补采到达后存量缺口按采集时间回填，状态随之翻转。"""
    items = monitor.list_gaps(workface=workface, status=status)
    return {"items": items, "total": len(items)}


@router.get("/assessment")
def assess_workface(
    workface: str | None = Query(default=None, description="缺省时返回全部工作面"),
) -> dict[str, Any]:
    """连续超限判定：数据中断与离层加速分开下结论、分开处置。"""
    if workface:
        return {"items": [monitor.assess(workface)]}
    return {"items": monitor.assess_all()}


@router.get("/daily-report")
def daily_report(
    date: str = Query(description="日报日期，YYYY-MM-DD"),
) -> dict[str, Any]:
    """顶板日报：缺口统计与判定结论动态汇总，缺口变化自动跟着变。"""
    report, error = monitor.daily_report(date)
    if report is None:
        raise HTTPException(status_code=400, detail=error)
    return report


@router.get("/workfaces")
def list_workfaces() -> dict[str, Any]:
    """有监测数据的工作面清单，供查询条件下拉使用。"""
    names = monitor.workfaces()
    return {"items": names, "total": len(names)}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条顶板监测明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"顶板监测 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条顶板监测，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="顶板监测已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条顶板监测执行离层预警、变形报警、加固完成；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
