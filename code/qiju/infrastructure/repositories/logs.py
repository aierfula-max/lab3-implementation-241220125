"""操作日志与站内信仓储。

日志只提供 ``add`` 与 ``query``，没有 ``update``/``delete``——对应 REQ-019
“只允许追加”。真实部署里还要在数据库账号层面收回 UPDATE/DELETE 权限，
桌面版做不到，这一点写进报告不足里。
"""

from __future__ import annotations

from datetime import datetime

from ...domain.clock import iso
from ...domain.entities import Notification, OperationLog
from ..db import Database
from ..mapping import log_from_row, notification_from_row


class LogRepository:
    """``operation_logs`` 表。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, log: OperationLog) -> None:
        self.db.execute(
            """
            INSERT INTO operation_logs
                (id, actor_id, actor_role, hotel_id, action, object_type,
                 object_id, before_value, after_value, reason, ip, request_id,
                 created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                log.id,
                log.actor_id,
                log.actor_role,
                log.hotel_id,
                log.action,
                log.object_type,
                log.object_id,
                log.before_value,
                log.after_value,
                log.reason,
                log.ip,
                log.request_id,
                iso(log.created_at),
            ),
        )

    def query(
        self,
        *,
        hotel_id: str | None = None,
        actor_id: str | None = None,
        action: str | None = None,
        object_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> list[OperationLog]:
        sql = "SELECT * FROM operation_logs WHERE 1 = 1"
        params: list[object] = []
        if hotel_id is not None:
            sql += " AND hotel_id = ?"
            params.append(hotel_id)
        if actor_id:
            sql += " AND actor_id = ?"
            params.append(actor_id)
        if action:
            sql += " AND action = ?"
            params.append(action)
        if object_id:
            sql += " AND object_id = ?"
            params.append(object_id)
        if start is not None:
            sql += " AND created_at >= ?"
            params.append(iso(start))
        if end is not None:
            sql += " AND created_at < ?"
            params.append(iso(end))
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [log_from_row(row) for row in self.db.query_all(sql, tuple(params))]

    def all(self, limit: int = 5000) -> list[OperationLog]:
        rows = self.db.query_all(
            "SELECT * FROM operation_logs ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [log_from_row(row) for row in rows]


class NotificationRepository:
    """站内信（REQ-033：不接短信/邮件）。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, notification: Notification) -> None:
        self.db.execute(
            """
            INSERT INTO notifications
                (id, user_id, title, body, created_at, read_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                notification.id,
                notification.user_id,
                notification.title,
                notification.body,
                iso(notification.created_at),
                iso(notification.read_at),
            ),
        )

    def list_by_user(self, user_id: str, limit: int = 50) -> list[Notification]:
        rows = self.db.query_all(
            """
            SELECT * FROM notifications WHERE user_id = ?
             ORDER BY created_at DESC LIMIT ?
            """,
            (user_id, limit),
        )
        return [notification_from_row(row) for row in rows]

    def unread_count(self, user_id: str) -> int:
        row = self.db.query_one(
            "SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND read_at IS NULL",
            (user_id,),
        )
        return int(row["n"]) if row else 0

    def mark_all_read(self, user_id: str, moment: datetime) -> None:
        self.db.execute(
            "UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL",
            (iso(moment), user_id),
        )
