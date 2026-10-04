"""顶板管理接口：维护顶板监测，覆盖离层预警、变形报警、加固完成等动作。

逐时离层量的缺测识别、补采续接与顶板日报也挂在这里；/faces、/readings、
/daily-report、/export 这些字面路径必须放在 /{entry_id} 之前，否则会被当成编号。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult, RoofReadingsPayload
from app.services.roof import RoofService
from app.services.roof_telemetry import RoofTelemetryService

router = APIRouter(prefix="/api/roof", tags=["顶板管理"])

service = RoofService()
telemetry = RoofTelemetryService()

LIST_FIELDS = ["监测编号", "所在工作面", "离层量", "锚杆受力", "收敛变形", "监测日期", "监测人员", "顶板状态"]
STATUSES = ["稳定", "离层预警", "变形超标", "已加固"]


@router.get("/faces", response_model=dict)
def list_faces() -> dict[str, Any]:
    """已知工作面清单：附最新采集时刻，供页面定位到最近有数据的一天。"""
    return {"items": telemetry.faces()}


@router.get("/readings", response_model=dict)
def list_readings(
    face: str = Query(description="工作面名称"),
    date: str = Query(description="监测日期，形如 2026-10-03"),
) -> dict[str, Any]:
    """逐时序列：缺测小时明示「暂无数据」并列出缺口时段，离层量留空不补零。"""
    result = telemetry.series(face, date)
    if result is None:
        raise HTTPException(status_code=400, detail=f"监测日期「{date}」无法识别，请按 年-月-日 提供")
    return result


@router.post("/readings", response_model=ActionResult)
def ingest_readings(payload: RoofReadingsPayload) -> ActionResult:
    """上报/补采离层量：按（工作面， 采集时刻）续接原记录，只留最新一版。

    补采数据按采集时刻回填存量缺口；任何一条不合法整批不写并逐条说明。
    """
    if not payload.items:
        return ActionResult(ok=False, message="没有可入库的上报记录")
    accepted, problems, summary = telemetry.ingest([item.model_dump() for item in payload.items])
    if problems:
        return ActionResult(ok=False, message=f"上报未入库：{'；'.join(problems)}")
    message = (
        f"已入库{summary['新建']}条、续接{summary['续接']}条（只保留最新一版），"
        f"按采集时刻回填存量缺口{summary['回填缺口小时']}小时"
    )
    return ActionResult(ok=True, message=message, entry={"items": accepted, **summary})


@router.get("/daily-report", response_model=dict)
def daily_report(date: str = Query(description="日报日期，形如 2026-10-03")) -> dict[str, Any]:
    """顶板日报：各工作面缺口时段、缺口统计与超限判定结论，随补采实时变化。"""
    report = telemetry.daily_report(date)
    if report is None:
        raise HTTPException(status_code=400, detail=f"日报日期「{date}」无法识别，请按 年-月-日 提供")
    return report


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出顶板管理清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "roof", "total": total, "items": items}


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
