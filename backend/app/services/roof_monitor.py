"""顶板离层量监测：小时上报、缺测缺口、补采续接、连续超限判定与顶板日报。

口径约定：
- 传感器按小时上报，采集时刻一律归一到整点（"YYYY-MM-DD HH:00"）。
- 缺测就是缺测：查询只返回真实上报行，缺口单独列出，任何环节都不拿零值顶替。
- 补采按采集时刻接续原记录，同一工作面同一时刻只保留最新一版。
- 连续超限判定必须分清「数据中断」与「离层加速」，两种原因分开处置。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.store import store

READINGS_TABLE = "roof_readings"
GAPS_TABLE = "roof_gaps"

# 预警口径：离层量超过 100mm 视为超出预警区间；连续 3 个小时点超限触发判定；
# 窗口内末值较首值增加 10mm 以上认定为离层加速。
WARNING_THRESHOLD = 100.0
CONSECUTIVE_HOURS = 3
ACCEL_DELTA = 10.0

HOUR_FORMAT = "%Y-%m-%d %H:00"
_GAP_OPEN = "待回填"
_GAP_CLOSED = "已回填"

_PARSE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H",
)


def _parse_hour(text: Any) -> datetime | None:
    """把外部传入的时刻解析并归一到整点；认不出的格式返回 None。"""
    raw = str(text or "").strip()
    if not raw:
        return None
    for fmt in _PARSE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).replace(minute=0, second=0, microsecond=0)
        except ValueError:
            continue
    return None


def _fmt_hour(moment: datetime) -> str:
    return moment.strftime(HOUR_FORMAT)


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _hour_span(start: datetime, end: datetime) -> list[datetime]:
    """[start, end] 闭区间内的整点序列。"""
    hours: list[datetime] = []
    cursor = start
    while cursor <= end:
        hours.append(cursor)
        cursor += timedelta(hours=1)
    return hours


def _gap_segments(missing: list[datetime]) -> list[dict[str, Any]]:
    """把缺失的整点合并成连续缺口段。"""
    segments: list[list[datetime]] = []
    for hour in missing:
        if segments and hour - segments[-1][1] == timedelta(hours=1):
            segments[-1][1] = hour
        else:
            segments.append([hour, hour])
    return [
        {
            "缺口开始": _fmt_hour(start),
            "缺口结束": _fmt_hour(end),
            "缺口小时数": int((end - start).total_seconds() // 3600) + 1,
        }
        for start, end in segments
    ]


class RoofMonitorService:
    def _readings(self, workface: str | None = None) -> list[dict[str, Any]]:
        rows = store.aux_rows(READINGS_TABLE)
        if workface:
            rows = [row for row in rows if row.get("所在工作面") == workface]
        return sorted(rows, key=lambda row: str(row.get("采集时刻", "")))

    def workfaces(self) -> list[str]:
        """当前有监测数据的工作面清单，供查询下拉使用。"""
        names = {str(row.get("所在工作面", "")) for row in store.aux_rows(READINGS_TABLE)}
        return sorted(name for name in names if name)

    # ------------------------------------------------------------------
    # 时段查询：没有上报就明说暂无数据，缺口时段单列，绝不补零。
    # ------------------------------------------------------------------
    def list_readings(
        self,
        *,
        workface: str,
        start: str,
        end: str,
    ) -> tuple[dict[str, Any] | None, str]:
        if not workface.strip():
            return None, "请先指定所在工作面"
        start_at = _parse_hour(start)
        end_at = _parse_hour(end)
        if start_at is None or end_at is None:
            return None, "时段格式无法识别，请按 YYYY-MM-DD HH:00 填写"
        if end_at < start_at:
            return None, "结束时刻不能早于开始时刻"

        items = []
        for row in self._readings(workface):
            moment = _parse_hour(row.get("采集时刻"))
            if moment is not None and start_at <= moment <= end_at:
                items.append(row)
        reported = {_parse_hour(row.get("采集时刻")) for row in items}
        missing = [hour for hour in _hour_span(start_at, end_at) if hour not in reported]
        gaps = _gap_segments(missing)

        result: dict[str, Any] = {
            "所在工作面": workface,
            "时段开始": _fmt_hour(start_at),
            "时段结束": _fmt_hour(end_at),
            "items": items,
            "gaps": gaps,
            "缺口小时数": sum(int(gap["缺口小时数"]) for gap in gaps),
            "message": "",
        }
        if not items:
            result["message"] = "暂无数据：该时段内没有任何上报，缺口时段见下方列表，未用零值顶替"
        elif gaps:
            result["message"] = "该时段存在缺测，缺口时段见下方列表，缺测小时未用零值顶替"
        return result, ""

    # ------------------------------------------------------------------
    # 上报/补采：同工作面同采集时刻接续原记录，只留最新一版。
    # ------------------------------------------------------------------
    def ingest_reading(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        workface = str(values.get("所在工作面") or "").strip()
        if not workface:
            return None, "缺少必填字段：所在工作面"
        moment = _parse_hour(values.get("采集时刻"))
        if moment is None:
            return None, "采集时刻缺失或格式无法识别，请按 YYYY-MM-DD HH:00 填写"
        raw_value = values.get("离层量")
        if raw_value is None or str(raw_value).strip() == "":
            return None, "离层量缺失：缺测时段应留空并登记缺口，不允许拿零值顶替"
        try:
            separation = float(raw_value)
        except (TypeError, ValueError):
            return None, f"离层量「{raw_value}」不是有效数值"
        mode = str(values.get("上报方式") or "实时上报").strip() or "实时上报"

        rows = store.aux_rows(READINGS_TABLE)
        hour_key = _fmt_hour(moment)
        existing = next(
            (row for row in rows if row.get("所在工作面") == workface and row.get("采集时刻") == hour_key),
            None,
        )
        if existing is not None:
            previous = existing.get("离层量")
            existing["离层量"] = separation
            existing["上报方式"] = mode
            existing["版本"] = int(existing.get("版本", 1)) + 1
            existing["更新时间"] = _now_text()
            message = (
                f"{workface} {hour_key} 已接续原记录（第 {existing['版本']} 版，"
                f"原值 {previous}mm 已替换为 {separation}mm），未新增重复行"
            )
            entry: dict[str, Any] = existing
        else:
            entry = {
                "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
                "所在工作面": workface,
                "采集时刻": hour_key,
                "离层量": separation,
                "上报方式": mode,
                "版本": 1,
                "更新时间": _now_text(),
            }
            rows.append(entry)
            message = f"{workface} {hour_key} 离层量 {separation}mm 已登记（{mode}）"

        backfilled = self.sync_gaps(workface)
        if backfilled:
            message += f"；按采集时间回填缺口 {backfilled} 段"
        return entry, message

    # ------------------------------------------------------------------
    # 缺口：按采集时间重扫，存量缺口记录随补采回填。
    # ------------------------------------------------------------------
    def _current_gap_segments(self, workface: str) -> list[dict[str, Any]]:
        rows = self._readings(workface)
        if not rows:
            return []
        start = _parse_hour(rows[0].get("采集时刻"))
        end = _parse_hour(rows[-1].get("采集时刻"))
        assert start is not None and end is not None
        reported = {_parse_hour(row.get("采集时刻")) for row in rows}
        missing = [hour for hour in _hour_span(start, end) if hour not in reported]
        return _gap_segments(missing)

    def sync_gaps(self, workface: str) -> int:
        """重扫工作面上报数据，回填被补采覆盖的存量缺口，返回本次回填的段数。"""
        current = {
            (seg["缺口开始"], seg["缺口结束"]): seg for seg in self._current_gap_segments(workface)
        }
        gaps = store.aux_rows(GAPS_TABLE)
        backfilled = 0
        for gap in gaps:
            if gap.get("所在工作面") != workface or gap.get("状态") != _GAP_OPEN:
                continue
            if (gap.get("缺口开始"), gap.get("缺口结束")) not in current:
                gap["状态"] = _GAP_CLOSED
                gap["回填时间"] = _now_text()
                backfilled += 1
        open_keys = {
            (gap.get("缺口开始"), gap.get("缺口结束"))
            for gap in gaps
            if gap.get("所在工作面") == workface and gap.get("状态") == _GAP_OPEN
        }
        for (start, end), seg in current.items():
            if (start, end) in open_keys:
                continue
            gaps.append({
                "id": max((int(gap.get("id", 0)) for gap in gaps), default=0) + 1,
                "所在工作面": workface,
                "缺口开始": start,
                "缺口结束": end,
                "缺口小时数": seg["缺口小时数"],
                "状态": _GAP_OPEN,
                "登记时间": _now_text(),
                "回填时间": "",
            })
        return backfilled

    def list_gaps(
        self,
        *,
        workface: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = list(store.aux_rows(GAPS_TABLE))
        if workface:
            rows = [row for row in rows if row.get("所在工作面") == workface]
        if status:
            rows = [row for row in rows if row.get("状态") == status]
        return sorted(rows, key=lambda row: str(row.get("缺口开始", "")), reverse=True)

    # ------------------------------------------------------------------
    # 连续超限判定：数据中断与离层加速分开下结论、分开处置。
    # ------------------------------------------------------------------
    def assess(self, workface: str) -> dict[str, Any]:
        rows = self._readings(workface)
        if not rows:
            return {
                "所在工作面": workface,
                "判定窗口": "",
                "结论": "无数据",
                "依据": "该工作面没有任何上报记录，无法判定",
                "处置建议": "先恢复传感器上报，再谈超限判定",
                "判定时间": _now_text(),
            }
        latest = _parse_hour(rows[-1].get("采集时刻"))
        assert latest is not None
        window = _hour_span(latest - timedelta(hours=CONSECUTIVE_HOURS - 1), latest)
        by_hour = {_parse_hour(row.get("采集时刻")): row for row in rows}
        window_text = f"{_fmt_hour(window[0])} ~ {_fmt_hour(window[-1])}"

        missing = [hour for hour in window if hour not in by_hour]
        present = [by_hour[hour] for hour in window if hour in by_hour]
        over_limit = [row for row in present if float(row.get("离层量", 0)) > WARNING_THRESHOLD]

        if missing:
            missing_text = "、".join(_fmt_hour(hour) for hour in missing)
            if len(over_limit) == len(present) and present:
                conclusion = "数据中断"
                basis = (
                    f"判定窗口 {window_text} 内 {missing_text} 缺测，"
                    f"已有 {len(present)} 个读数全部超出预警值 {WARNING_THRESHOLD:.0f}mm，"
                    "但缺测打断了连续性，无法确认是真超限还是中断假象"
                )
                suggestion = "挂起预警升级，优先补采缺口时段后复判，不按离层加速处置"
            else:
                conclusion = "未构成连续超限"
                basis = (
                    f"判定窗口 {window_text} 内 {missing_text} 缺测，"
                    f"已有读数未全部超出预警值 {WARNING_THRESHOLD:.0f}mm"
                )
                suggestion = "维持常态监测，缺口时段按补采流程回填"
        elif len(over_limit) == CONSECUTIVE_HOURS:
            first = float(present[0]["离层量"])
            last = float(present[-1]["离层量"])
            delta = last - first
            series = "→".join(f"{float(row['离层量']):.0f}" for row in present)
            if delta >= ACCEL_DELTA:
                conclusion = "离层加速"
                basis = (
                    f"判定窗口 {window_text} 数据完整，离层量 {series}mm 连续 {CONSECUTIVE_HOURS} 小时"
                    f"超出预警值 {WARNING_THRESHOLD:.0f}mm，末值较首值增加 {delta:.0f}mm，判定为真实离层加速"
                )
                suggestion = "确认离层加速，升级离层预警并安排支护加固，与数据中断分开处置"
            else:
                conclusion = "持续超限"
                basis = (
                    f"判定窗口 {window_text} 数据完整，离层量 {series}mm 连续 {CONSECUTIVE_HOURS} 小时"
                    f"超出预警值 {WARNING_THRESHOLD:.0f}mm，但增量 {delta:.0f}mm 未达加速标准"
                )
                suggestion = "维持离层预警，加密观测频次，暂不按离层加速升级"
        else:
            conclusion = "无连续超限"
            basis = (
                f"判定窗口 {window_text} 数据完整，"
                f"未出现连续 {CONSECUTIVE_HOURS} 小时超出预警值 {WARNING_THRESHOLD:.0f}mm"
            )
            suggestion = "维持常态监测"
        return {
            "所在工作面": workface,
            "判定窗口": window_text,
            "结论": conclusion,
            "依据": basis,
            "处置建议": suggestion,
            "判定时间": _now_text(),
        }

    def assess_all(self) -> list[dict[str, Any]]:
        return [self.assess(workface) for workface in self.workfaces()]

    # ------------------------------------------------------------------
    # 顶板日报：缺口统计与判定结论动态汇总，缺口变化自动跟着变。
    # ------------------------------------------------------------------
    def daily_report(self, date: str) -> tuple[dict[str, Any] | None, str]:
        try:
            day = datetime.strptime(str(date or "").strip(), "%Y-%m-%d").date()
        except ValueError:
            return None, "日报日期格式无法识别，请按 YYYY-MM-DD 填写"
        prefix = day.strftime("%Y-%m-%d")
        gap_items = [
            gap for gap in self.list_gaps() if str(gap.get("缺口开始", "")).startswith(prefix)
        ]
        open_items = [gap for gap in gap_items if gap.get("状态") == _GAP_OPEN]
        closed_items = [gap for gap in gap_items if gap.get("状态") == _GAP_CLOSED]
        report = {
            "日期": prefix,
            "缺口统计": {
                "缺口总数": len(gap_items),
                "待回填条数": len(open_items),
                "待回填小时": sum(int(gap.get("缺口小时数", 0)) for gap in open_items),
                "已回填条数": len(closed_items),
                "已回填小时": sum(int(gap.get("缺口小时数", 0)) for gap in closed_items),
            },
            "缺口明细": gap_items,
            "判定结论": self.assess_all(),
            "生成时间": _now_text(),
        }
        return report, ""
