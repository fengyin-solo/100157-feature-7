"""数据质控业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

import re
from typing import Any

from app.store import store

MODULE = "quality"
REQUIRED_FIELDS = ["质控编号", "质控时段", "涉及站点"]
STATUS_ORDER = ["待执行", "执行中", "已完成", "已退回"]
ACTION_RULES = {"启动质控": "执行中", "确认完成": "已完成", "退回重做": "已退回"}
NEGATIVE_ACTIONS = []

# 疑误率判定规则：疑误率 = 检出疑误数 / 涉及站点数，
# 高于上限判为偏高，低于下限判为偏低，区间内为正常。
RATE_UPPER_LIMIT = 0.5
RATE_LOWER_LIMIT = 0.05
VERDICT_HIGH = "偏高"
VERDICT_LOW = "偏低"
VERDICT_NORMAL = "正常"
VERDICT_PENDING = "未判定"
VERDICTS = [VERDICT_HIGH, VERDICT_LOW, VERDICT_NORMAL, VERDICT_PENDING]

_STATION_SPLIT = re.compile(r"[、,，;；\s]+")


def _station_count(value: Any) -> int:
    """涉及站点数：允许直接填数字，或填用顿号、逗号、分号、空白分隔的站点清单。"""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return max(int(value), 0)
    text = str(value).strip()
    if not text:
        return 0
    try:
        return max(int(float(text)), 0)
    except ValueError:
        return len([part for part in _STATION_SPLIT.split(text) if part])


def _error_count(value: Any) -> int:
    """检出疑误数：缺失或不是数字时按 0 条计。"""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return max(int(value), 0)
    text = str(value).strip()
    if not text:
        return 0
    try:
        return max(int(float(text)), 0)
    except ValueError:
        return 0


def _verdict_of(row: dict[str, Any]) -> str:
    return str(row.get("疑误率判定") or VERDICT_PENDING)


class QualityService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        period: str | None = None,
        station: str | None = None,
        verdict: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("质控编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if period:
            rows = [row for row in rows if period in str(row.get("质控时段", ""))]
        if station:
            rows = [row for row in rows if station in str(row.get("涉及站点", ""))]
        if verdict:
            rows = [row for row in rows if _verdict_of(row) == verdict]
        total = len(rows)
        summary = {
            VERDICT_HIGH: sum(1 for row in rows if _verdict_of(row) == VERDICT_HIGH),
            VERDICT_LOW: sum(1 for row in rows if _verdict_of(row) == VERDICT_LOW),
        }
        start = max(page - 1, 0) * size
        return rows[start:start + size], total, summary

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [
            field
            for field in REQUIRED_FIELDS
            if values.get(field) is None or not str(values.get(field)).strip()
        ]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        for field in ("质控规则", "检出疑误数", "质控人员", "质控日期", "质控状态"):
            if values.get(field) is not None:
                entry[field] = values.get(field)
        entry["疑误率"] = None
        entry["疑误率判定"] = VERDICT_PENDING
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"质控任务 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于数据质控可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        message = f"质控任务已{action}"
        if action == "启动质控":
            verdict, message = self._judge(entry)
            if verdict is None:
                return None, message
            message = f"质控任务已{action}，{message}"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, message

    def _judge(self, entry: dict[str, Any]) -> tuple[str | None, str]:
        """按涉及站点数与检出疑误数算疑误率并给出判定；不合规时不判定并说明原因。"""
        problems = []
        period = str(entry.get("质控时段") or "").strip()
        if not period:
            problems.append("质控时段缺失")
        stations = _station_count(entry.get("涉及站点"))
        if stations == 0:
            problems.append("涉及站点数为零")
        if problems:
            return None, f"不允许判定疑误率：{'、'.join(problems)}，请补正后重新启动质控"
        errors = _error_count(entry.get("检出疑误数"))
        rate = errors / stations
        if rate > RATE_UPPER_LIMIT:
            verdict = VERDICT_HIGH
        elif rate < RATE_LOWER_LIMIT:
            verdict = VERDICT_LOW
        else:
            verdict = VERDICT_NORMAL
        cleared = self._clear_same_period_results(entry, period)
        entry["疑误率"] = round(rate, 4)
        entry["疑误率判定"] = verdict
        message = f"检出疑误 {errors} 条、涉及站点 {stations} 个，疑误率 {rate:.2%}，判定{verdict}"
        if cleared:
            message += f"；同一时段 {period} 已清除其他 {cleared} 条判定结果，仅保留本次"
        return verdict, message

    def _clear_same_period_results(self, entry: dict[str, Any], period: str) -> int:
        """同一时段重复启动质控只留一次结果：清掉其他任务在同一时段的判定。"""
        cleared = 0
        for other in store.rows(MODULE):
            if other is entry:
                continue
            if str(other.get("质控时段") or "").strip() != period:
                continue
            if _verdict_of(other) == VERDICT_PENDING:
                continue
            other["疑误率"] = None
            other["疑误率判定"] = VERDICT_PENDING
            cleared += 1
        return cleared
