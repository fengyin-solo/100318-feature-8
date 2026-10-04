"""顶板离层量逐时监测：缺测识别、补采续接、超限判定与顶板日报。

约定：
- 离层量按小时上报，采集时刻一律规整到整点，同一工作面同一小时只保留最新一版；
- 缺测时段用「没有记录」表达，任何环节都不许拿零值顶替；
- 补采数据按采集时刻回填到原来的序列里，续接原记录，不并排新增。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.store import store

MODULE = "roof_readings"

WARN_LIMIT = 100.0  # 离层量预警区间上限（mm），达到或超过视为超出预警区间
CONTINUOUS_HOURS = 3  # 连续超限达到该小时数才形成一次判定
HOURS_PER_DAY = 24

HOUR_FORMAT = "%Y-%m-%dT%H:%M"

# 判定原因与处置口径：数据中断与真实离层加速分开处理
CAUSE_GAP = "数据中断"
CAUSE_ACCEL = "离层加速"
CAUSE_HIGH = "持续高位"
DISPOSAL = {
    CAUSE_GAP: "按采集时刻补采缺口时段并核查传感器与供电，连续性待核实，暂不升级预警",
    CAUSE_ACCEL: "判定为真实离层加速，升级离层预警，通知支护加固并加密监测频次",
    CAUSE_HIGH: "离层量持续高位但未见加速，保持预警跟踪，按班次复核",
}


def _parse_hour(value: Any) -> datetime | None:
    """把采集时刻规整到整点；解析不了的时刻不允许入库。"""
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in (HOUR_FORMAT, "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(minute=0, second=0, microsecond=0)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).replace(minute=0, second=0, microsecond=0)
    except ValueError:
        return None


def _hour_text(moment: datetime) -> str:
    return moment.strftime(HOUR_FORMAT)


def _numeric(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


class RoofTelemetryService:
    """逐时离层量的读写与判定规则，全部围绕（工作面， 采集时刻）这条主键展开。"""

    # ---- 基础读取 -------------------------------------------------

    def _face_hours(self, face: str) -> dict[datetime, dict[str, Any]]:
        hours: dict[datetime, dict[str, Any]] = {}
        for row in store.rows(MODULE):
            if row.get("工作面") != face:
                continue
            moment = _parse_hour(row.get("采集时刻"))
            if moment is not None:
                hours[moment] = row
        return hours

    def faces(self) -> list[dict[str, Any]]:
        """已知工作面清单：附最新采集时刻，供页面默认定位到最近有数据的一天。"""
        latest: dict[str, datetime] = {}
        for row in store.rows(MODULE):
            face = str(row.get("工作面") or "").strip()
            moment = _parse_hour(row.get("采集时刻"))
            if not face or moment is None:
                continue
            if face not in latest or moment > latest[face]:
                latest[face] = moment
        return [
            {"工作面": face, "最新采集时刻": _hour_text(latest[face])}
            for face in sorted(latest)
        ]

    # ---- 补采续接 -------------------------------------------------

    def ingest(self, items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str], dict[str, int]]:
        """登记一批逐时上报。

        返回（入库明细， 校验问题， 汇总）。有任何一条不合法就整批不写，
        避免补采一半留下更难解释的序列。
        """
        problems: list[str] = []
        now_hour = datetime.now().replace(minute=0, second=0, microsecond=0)
        normalized: list[dict[str, Any]] = []
        seen: set[tuple[str, datetime]] = set()
        for index, item in enumerate(items, start=1):
            face = str(item.get("工作面") or "").strip()
            moment = _parse_hour(item.get("采集时刻"))
            value = _numeric(item.get("离层量"))
            if not face:
                problems.append(f"第{index}条缺少工作面")
                continue
            if moment is None:
                problems.append(f"第{index}条采集时刻「{item.get('采集时刻')}」无法识别")
                continue
            if moment > now_hour:
                problems.append(f"第{index}条采集时刻{_hour_text(moment)}晚于当前时间，不予接收")
                continue
            if value is None or value < 0:
                problems.append(f"第{index}条离层量「{item.get('离层量')}」不是有效数值")
                continue
            key = (face, moment)
            if key in seen:
                problems.append(f"第{index}条与前面同为{face}{_hour_text(moment)}，同一小时只留一版")
                continue
            seen.add(key)
            normalized.append({"工作面": face, "时刻": moment, "离层量": value})
        if problems:
            return [], problems, {"新建": 0, "续接": 0, "回填缺口小时": 0}

        rows = store.rows(MODULE)
        accepted: list[dict[str, Any]] = []
        summary = {"新建": 0, "续接": 0, "回填缺口小时": 0}
        for item in normalized:
            face, moment, value = item["工作面"], item["时刻"], item["离层量"]
            existing = next(
                (row for row in rows if row.get("工作面") == face and _parse_hour(row.get("采集时刻")) == moment),
                None,
            )
            if existing is not None:
                # 续接原来那条：原地更新、版本加一，只留最新一版，不并排留两条
                existing["离层量"] = value
                existing["版本"] = int(existing.get("版本", 1)) + 1
                existing["上报时间"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                summary["续接"] += 1
                accepted.append({**existing, "采集时刻": _hour_text(moment), "处理方式": "续接"})
                continue
            face_hours = self._face_hours(face)
            backfill = bool(face_hours) and moment < max(face_hours)
            row = {
                "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
                "工作面": face,
                "采集时刻": _hour_text(moment),
                "离层量": value,
                "补采": backfill,
                "版本": 1,
                "上报时间": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            }
            rows.append(row)
            summary["新建"] += 1
            if backfill:
                # 按采集时刻回填存量缺口，缺口统计随之下调
                summary["回填缺口小时"] += 1
            accepted.append({**row, "处理方式": "补采回填" if backfill else "新建"})
        return accepted, [], summary

    # ---- 缺测识别 -------------------------------------------------

    def _gaps(self, face_hours: dict[datetime, dict[str, Any]], start: datetime, end: datetime) -> list[dict[str, Any]]:
        """[start, end] 内的缺测时段：连续缺测的小时并成一段，按采集时间排列。"""
        gaps: list[dict[str, Any]] = []
        moment = start
        gap_start: datetime | None = None
        while moment <= end:
            if moment in face_hours:
                if gap_start is not None:
                    gaps.append({
                        "开始": _hour_text(gap_start),
                        "结束": _hour_text(moment - timedelta(hours=1)),
                        "缺测小时": int((moment - gap_start).total_seconds() // 3600),
                    })
                    gap_start = None
            elif gap_start is None:
                gap_start = moment
            moment += timedelta(hours=1)
        if gap_start is not None:
            gaps.append({
                "开始": _hour_text(gap_start),
                "结束": _hour_text(end),
                "缺测小时": int((end - gap_start).total_seconds() // 3600) + 1,
            })
        return gaps

    def series(self, face: str, date: str) -> dict[str, Any] | None:
        """某个工作面一天的逐时序列：缺测小时明示「暂无数据」，离层量留空不补零。"""
        day = _parse_hour(date)
        if day is None:
            return None
        face_hours = self._face_hours(face)
        start = day.replace(hour=0)
        end = start + timedelta(hours=HOURS_PER_DAY - 1)
        slots: list[dict[str, Any]] = []
        moment = start
        while moment <= end:
            row = face_hours.get(moment)
            if row is None:
                slots.append({"时刻": _hour_text(moment), "离层量": None, "状态": "暂无数据", "补采": False, "版本": 0})
            else:
                value = _numeric(row.get("离层量"))
                slots.append({
                    "时刻": _hour_text(moment),
                    "离层量": value,
                    "状态": "超限" if value is not None and value >= WARN_LIMIT else "正常",
                    "补采": bool(row.get("补采")),
                    "版本": int(row.get("版本", 1)),
                })
            moment += timedelta(hours=1)
        gaps = self._gaps(face_hours, start, end)
        return {
            "工作面": face,
            "日期": day.strftime("%Y-%m-%d"),
            "预警上限": WARN_LIMIT,
            "slots": slots,
            "gaps": gaps,
            "verdicts": self._determinations(face, face_hours, start, end),
        }

    # ---- 超限判定 -------------------------------------------------

    def _determinations(
        self,
        face: str,
        face_hours: dict[datetime, dict[str, Any]],
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """连续超出预警区间的判定：分清数据中断与真实离层加速，分开处置。

        缺测小时不开启也不终结候选区间——中断两侧的超限记录会连成一段，
        但这段的连续性无法确认，按数据中断处理而不是直接升级。
        """
        runs: list[dict[str, Any]] = []
        run: dict[str, Any] | None = None
        moment = start
        while moment <= end:
            row = face_hours.get(moment)
            value = _numeric(row.get("离层量")) if row else None
            if value is not None and value >= WARN_LIMIT:
                if run is None:
                    run = {"start": moment, "last": moment, "values": [], "missing": 0}
                elif run["last"] is not None:
                    run["missing"] += max(int((moment - run["last"]).total_seconds() // 3600) - 1, 0)
                run["last"] = moment
                run["values"].append(value)
            elif value is not None and run is not None:
                runs.append(run)
                run = None
            moment += timedelta(hours=1)
        if run is not None:
            runs.append(run)

        verdicts: list[dict[str, Any]] = []
        for run in runs:
            span = int((run["last"] - run["start"]).total_seconds() // 3600) + 1
            if span < CONTINUOUS_HOURS:
                continue
            values = run["values"]
            if run["missing"] > 0:
                cause = CAUSE_GAP
                conclusion = f"超限时段内缺测{run['missing']}小时，连续性无法确认，按数据中断处理"
            elif values[-1] > values[0]:
                cause = CAUSE_ACCEL
                conclusion = f"离层量由{values[0]:.0f}mm升至{values[-1]:.0f}mm且逐时完整，判定为真实离层加速"
            else:
                cause = CAUSE_HIGH
                conclusion = "离层量连续超限但趋势平稳，判定为持续高位"
            verdicts.append({
                "工作面": face,
                "开始": _hour_text(run["start"]),
                "结束": _hour_text(run["last"]),
                "连续小时": span,
                "实测小时": len(values),
                "缺测小时": run["missing"],
                "峰值": max(values),
                "原因": cause,
                "结论": conclusion,
                "处置": DISPOSAL[cause],
            })
        return verdicts

    # ---- 顶板日报 -------------------------------------------------

    def daily_report(self, date: str) -> dict[str, Any] | None:
        """顶板日报：按天汇总各工作面缺口与判定结论。

        日报从实时序列计算，补采回填后缺口统计与判定结论跟着一起变。
        """
        day = _parse_hour(date)
        if day is None:
            return None
        start = day.replace(hour=0)
        end = start + timedelta(hours=HOURS_PER_DAY - 1)
        faces: list[dict[str, Any]] = []
        for item in self.faces():
            face = item["工作面"]
            face_hours = self._face_hours(face)
            gaps = self._gaps(face_hours, start, end)
            verdicts = self._determinations(face, face_hours, start, end)
            reported = sum(1 for moment in face_hours if start <= moment <= end)
            faces.append({
                "工作面": face,
                "应到小时": HOURS_PER_DAY,
                "实到小时": reported,
                "缺测小时": HOURS_PER_DAY - reported,
                "缺口时段": gaps,
                "判定结论": verdicts,
            })
        summary = {
            "监测工作面": len(faces),
            "缺口总数": sum(len(face["缺口时段"]) for face in faces),
            "缺测小时总数": sum(face["缺测小时"] for face in faces),
            "判定结论数": sum(len(face["判定结论"]) for face in faces),
            "其中离层加速": sum(1 for face in faces for v in face["判定结论"] if v["原因"] == CAUSE_ACCEL),
            "其中数据中断": sum(1 for face in faces for v in face["判定结论"] if v["原因"] == CAUSE_GAP),
        }
        return {"日期": day.strftime("%Y-%m-%d"), "预警上限": WARN_LIMIT, "summary": summary, "faces": faces}
