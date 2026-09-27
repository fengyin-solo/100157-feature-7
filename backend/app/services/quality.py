"""数据质控业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

import re
from typing import Any

from app.store import store

MODULE = "quality"
REQUIRED_FIELDS = ["质控编号", "质控时段", "涉及站点"]
ENTRY_FIELDS = ["质控编号", "质控时段", "涉及站点", "质控规则", "检出疑误数", "质控人员", "质控日期", "质控状态"]
STATUS_ORDER = ["待执行", "执行中", "已完成", "已退回"]
ACTION_RULES = {"启动质控": "执行中", "确认完成": "已完成", "退回重做": "已退回"}
NEGATIVE_ACTIONS = []

# 疑误率判定口径：疑误率 = 检出疑误数 / 涉及站点数，
# 高于上限判偏高、低于下限判偏低，介于两者之间（含边界）判正常。
RATE_UPPER_LIMIT = 0.2
RATE_LOWER_LIMIT = 0.05
VERDICT_HIGH = "偏高"
VERDICT_LOW = "偏低"
VERDICT_NORMAL = "正常"
VERDICT_PENDING = "未判定"
VERDICTS = [VERDICT_HIGH, VERDICT_LOW, VERDICT_NORMAL, VERDICT_PENDING]


def _station_count(value: Any) -> int:
    """把「涉及站点」解析成站点数；纯数字直接取值，站点清单按分隔符计数，其余视为 0。"""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return max(int(value), 0)
    text = str(value).strip()
    if not text:
        return 0
    if text.isdigit():
        return int(text)
    parts = [part for part in re.split(r"[、,，;；\s]+", text) if part]
    if len(parts) > 1:
        return len(parts)
    return 0


def _error_count(value: Any) -> int:
    """把「检出疑误数」解析成非负整数，无法解析时按 0 处理。"""
    try:
        return max(int(float(str(value).strip())), 0)
    except (TypeError, ValueError):
        return 0


class QualityService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        verdict: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("质控编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if verdict:
            rows = [row for row in rows if (row.get("疑误率判定") or VERDICT_PENDING) == verdict]
        total = len(rows)
        summary = {name: 0 for name in VERDICTS}
        for row in rows:
            name = row.get("疑误率判定") or VERDICT_PENDING
            summary[name if name in summary else VERDICT_PENDING] += 1
        start = max(page - 1, 0) * size
        return rows[start:start + size], total, summary

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in ENTRY_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["疑误率"] = None
        entry["疑误率判定"] = VERDICT_PENDING
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
        if action == "启动质控":
            problem = self._compliance_problem(entry)
            if problem:
                return None, problem
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        if action == "启动质控":
            verdict, rate = self._judge(entry)
            return entry, f"质控任务已启动质控，疑误率 {rate:.1%}，判定为{verdict}"
        return entry, f"质控任务已{action}"

    def _compliance_problem(self, entry: dict[str, Any]) -> str | None:
        """启动质控前的合规检查：质控时段缺失、涉及站点数为零都不许直接判定。"""
        if not str(entry.get("质控时段") or "").strip():
            return "质控时段缺失，不满足判定条件，本次启动质控不予判定"
        if _station_count(entry.get("涉及站点")) <= 0:
            return "涉及站点数为零或无法解析，不满足判定条件，本次启动质控不予判定"
        return None

    def _judge(self, entry: dict[str, Any]) -> tuple[str, float]:
        """按疑误率给当前任务定档，并清掉同一时段其他任务上的旧判定，只留这一次结果。"""
        stations = _station_count(entry.get("涉及站点"))
        errors = _error_count(entry.get("检出疑误数"))
        rate = errors / stations
        if rate > RATE_UPPER_LIMIT:
            verdict = VERDICT_HIGH
        elif rate < RATE_LOWER_LIMIT:
            verdict = VERDICT_LOW
        else:
            verdict = VERDICT_NORMAL
        entry["疑误率"] = round(rate, 4)
        entry["疑误率判定"] = verdict
        entry["abnormal"] = verdict in (VERDICT_HIGH, VERDICT_LOW)
        period = str(entry.get("质控时段") or "").strip()
        for row in store.rows(MODULE):
            if row is entry:
                continue
            if str(row.get("质控时段") or "").strip() != period:
                continue
            row["疑误率"] = None
            row["疑误率判定"] = VERDICT_PENDING
            row["abnormal"] = False
        return verdict, rate
