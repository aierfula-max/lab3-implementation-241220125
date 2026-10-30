"""操作日志查询与导出（REQ-019）。

导出有两个容易踩的点：

1. 店长只能导出本店日志，管理员才能导全平台；越权用 403，不是空结果；
2. 导出动作本身也要写一条日志，否则“谁把日志导走了”就查不到。

CSV 用 ``utf-8-sig``，是为了让 Excel 直接双击打开不乱码——这是很土但
很实际的一条经验，课程里不会讲，真交付时甲方一定会问。
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..domain.entities import OperationLog
from ..domain.enums import AuditAction, Role
from ..domain.errors import PermissionDenied
from .base import BaseService, Session


@dataclass(frozen=True, slots=True)
class LogFilter:
    """日志查询条件。"""

    action: str | None = None
    actor_id: str | None = None
    object_id: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    hotel_id: str | None = None


CSV_HEADER = [
    "日志ID",
    "时间",
    "操作人",
    "角色",
    "酒店范围",
    "动作",
    "对象类型",
    "对象ID",
    "改前值",
    "改后值",
    "原因",
    "IP",
    "请求号",
]


class AuditService(BaseService):
    """日志查询与导出。"""

    def query(self, session: Session, filters: LogFilter | None = None) -> list[OperationLog]:
        actor = self.require_active(session)
        condition = filters or LogFilter()
        if actor.role is Role.PLATFORM_ADMIN:
            hotel_id = condition.hotel_id
        elif actor.role is Role.MANAGER:
            hotel_id = actor.hotel_id  # 忽略前端传来的其他酒店
        else:
            raise PermissionDenied("只有店长或平台管理员可以查询操作日志")
        return self.repos.logs.query(
            hotel_id=hotel_id,
            actor_id=condition.actor_id,
            action=condition.action,
            object_id=condition.object_id,
            start=condition.start,
            end=condition.end,
        )

    def export_csv(
        self,
        session: Session,
        path: str | Path,
        filters: LogFilter | None = None,
    ) -> int:
        """导出为 CSV，返回条数；随后写一条“导出日志”的日志。"""
        actor = self.require_active(session)
        logs = self.query(session, filters)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(CSV_HEADER)
            for log in logs:
                writer.writerow(
                    [
                        log.id,
                        log.created_at.isoformat() if log.created_at else "",
                        log.actor_id or "system",
                        log.actor_role,
                        log.hotel_id or "全平台",
                        log.action,
                        log.object_type,
                        log.object_id,
                        log.before_value,
                        log.after_value,
                        log.reason,
                        log.ip,
                        log.request_id,
                    ]
                )
        with self.db.transaction():
            self.write_log(
                user=actor,
                action=AuditAction.LOG_EXPORT,
                object_type="OperationLog",
                object_id=str(target),
                hotel_id=actor.hotel_id if actor.role is Role.MANAGER else None,
                after=f"导出 {len(logs)} 条到 {target.name}",
                reason="日志导出",
            )
        return len(logs)
