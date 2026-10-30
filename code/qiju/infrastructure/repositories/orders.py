"""订单聚合仓储。

订单、每晚明细、入住人、变更记录、退款记录在数据库里是五张表，但在
领域里是一个聚合。这个仓储负责“取订单时把明细一起装配好”，避免服务层
出现 ``order.nights`` 为空的半成品。

``save`` 用 ``version`` 做乐观锁：``UPDATE ... WHERE id=? AND version=?``
影响 0 行就抛 409。确认与超时任务并发时，这条语句是最后一道闸门。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from ...domain.clock import iso
from ...domain.entities import Order, OrderChange, OrderNight, RefundRecord
from ...domain.enums import OrderStatus, RefundStatus
from ...domain.errors import StateConflict
from ..db import Database
from ..mapping import (
    change_from_row,
    guest_from_row,
    night_from_row,
    order_from_row,
    refund_from_row,
)


class OrderRepository:
    """``orders`` 及其从属表。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------ 写
    def add(self, order: Order) -> None:
        """插入订单、每晚明细与入住人。调用方负责事务。"""
        conn = self.db.connection
        conn.execute(
            """
            INSERT INTO orders
                (id, order_no, user_id, hotel_id, room_type_id, check_in,
                 check_out, room_count, status, total_cents, request_id,
                 policy_version, version, created_at, confirm_deadline,
                 modified)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order.id,
                order.order_no,
                order.user_id,
                order.hotel_id,
                order.room_type_id,
                order.check_in.isoformat(),
                order.check_out.isoformat(),
                order.room_count,
                order.status.value,
                order.total_cents,
                order.request_id,
                order.policy_version,
                order.version,
                iso(order.created_at),
                iso(order.confirm_deadline),
                int(order.modified),
            ),
        )
        conn.executemany(
            """
            INSERT INTO order_nights
                (order_id, day, price_cents, room_count, subtotal_cents)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    order.id,
                    night.day.isoformat(),
                    night.price_cents,
                    night.room_count,
                    night.subtotal_cents,
                )
                for night in order.nights
            ],
        )
        conn.executemany(
            "INSERT INTO guests (id, order_id, name, phone) VALUES (?, ?, ?, ?)",
            [
                (f"{order.id}-{index}", order.id, guest.name, guest.phone)
                for index, guest in enumerate(order.guests)
            ],
        )

    def save(self, order: Order, expected_version: int | None = None) -> None:
        """整行更新并自增版本号。版本不匹配 → 409。"""
        expected = order.version if expected_version is None else expected_version
        cursor = self.db.execute(
            """
            UPDATE orders SET
                check_in = ?, check_out = ?, room_count = ?, status = ?,
                total_cents = ?, version = version + 1,
                confirm_deadline = ?, confirmed_at = ?,
                confirmed_by = ?, checked_in_at = ?, checked_in_by = ?,
                checked_out_at = ?, checked_out_by = ?, actual_check_out = ?,
                canceled_at = ?, cancel_reason = ?, rejected_at = ?,
                reject_reason = ?, reject_note = ?, modified = ?,
                early_checkout = ?
             WHERE id = ? AND version = ?
            """,
            (
                order.check_in.isoformat(),
                order.check_out.isoformat(),
                order.room_count,
                order.status.value,
                order.total_cents,
                iso(order.confirm_deadline),
                iso(order.confirmed_at),
                order.confirmed_by,
                iso(order.checked_in_at),
                order.checked_in_by,
                iso(order.checked_out_at),
                order.checked_out_by,
                order.actual_check_out.isoformat() if order.actual_check_out else None,
                iso(order.canceled_at),
                order.cancel_reason,
                iso(order.rejected_at),
                order.reject_reason,
                order.reject_note,
                int(order.modified),
                int(order.early_checkout),
                order.id,
                expected,
            ),
        )
        if cursor.rowcount != 1:
            raise StateConflict(
                "订单已被其他操作修改，请刷新后重试",
                detail={"order_id": order.id, "expected_version": expected},
            )
        order.version = expected + 1

    def replace_nights(self, order_id: str, nights: list[OrderNight]) -> None:
        """改单后重写每晚明细（旧明细不再保留）。"""
        conn = self.db.connection
        conn.execute("DELETE FROM order_nights WHERE order_id = ?", (order_id,))
        conn.executemany(
            """
            INSERT INTO order_nights
                (order_id, day, price_cents, room_count, subtotal_cents)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    order_id,
                    night.day.isoformat(),
                    night.price_cents,
                    night.room_count,
                    night.subtotal_cents,
                )
                for night in nights
            ],
        )

    def add_change(self, change: OrderChange) -> None:
        self.db.execute(
            """
            INSERT INTO order_changes
                (id, order_id, before_summary, after_summary, diff_cents,
                 operator_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                change.id,
                change.order_id,
                change.before_summary,
                change.after_summary,
                change.diff_cents,
                change.operator_id,
                iso(change.created_at),
            ),
        )

    def add_refund(self, refund: RefundRecord) -> None:
        self.db.execute(
            """
            INSERT INTO refund_records
                (id, refund_no, order_id, event_type, refundable_cents,
                 deducted_cents, status, created_at, marked_by, marked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                refund.id,
                refund.refund_no,
                refund.order_id,
                refund.event_type,
                refund.refundable_cents,
                refund.deducted_cents,
                refund.status.value,
                iso(refund.created_at),
                refund.marked_by,
                iso(refund.marked_at),
            ),
        )

    def mark_refunded(
        self, refund_id: str, operator_id: str, moment: datetime
    ) -> bool:
        cursor = self.db.execute(
            """
            UPDATE refund_records
               SET status = ?, marked_by = ?, marked_at = ?
             WHERE id = ? AND status = ?
            """,
            (
                RefundStatus.REFUNDED.value,
                operator_id,
                iso(moment),
                refund_id,
                RefundStatus.PENDING_OFFLINE.value,
            ),
        )
        return cursor.rowcount == 1

    # ------------------------------------------------------------------ 读
    def by_id(self, order_id: str) -> Order | None:
        row = self.db.query_one("SELECT * FROM orders WHERE id = ?", (order_id,))
        return self._hydrate(order_from_row(row)) if row else None

    def by_no(self, order_no: str) -> Order | None:
        row = self.db.query_one("SELECT * FROM orders WHERE order_no = ?", (order_no,))
        return self._hydrate(order_from_row(row)) if row else None

    def by_request(self, user_id: str, request_id: str) -> Order | None:
        row = self.db.query_one(
            "SELECT * FROM orders WHERE user_id = ? AND request_id = ?",
            (user_id, request_id),
        )
        return self._hydrate(order_from_row(row)) if row else None

    def duplicate_candidates(
        self,
        *,
        user_id: str,
        hotel_id: str,
        room_type_id: str,
        check_in: date,
        check_out: date,
        room_count: int,
        since: datetime,
    ) -> list[Order]:
        """2 分钟内内容相同的订单（REQ-024）。"""
        rows = self.db.query_all(
            """
            SELECT * FROM orders
             WHERE user_id = ? AND hotel_id = ? AND room_type_id = ?
               AND check_in = ? AND check_out = ? AND room_count = ?
               AND created_at >= ?
               AND status NOT IN (?, ?, ?)
             ORDER BY created_at DESC
            """,
            (
                user_id,
                hotel_id,
                room_type_id,
                check_in.isoformat(),
                check_out.isoformat(),
                room_count,
                iso(since),
                OrderStatus.CANCELED.value,
                OrderStatus.REJECTED.value,
                OrderStatus.NO_SHOW.value,
            ),
        )
        return [self._hydrate(order_from_row(row)) for row in rows]

    def refunds(self, order_id: str) -> list[RefundRecord]:
        rows = self.db.query_all(
            "SELECT * FROM refund_records WHERE order_id = ? ORDER BY created_at",
            (order_id,),
        )
        return [refund_from_row(row) for row in rows]

    def refund_by_event(self, order_id: str, event: str) -> RefundRecord | None:
        row = self.db.query_one(
            """
            SELECT * FROM refund_records WHERE order_id = ? AND event_type = ?
            """,
            (order_id, event),
        )
        return refund_from_row(row) if row else None

    def changes(self, order_id: str) -> list[OrderChange]:
        rows = self.db.query_all(
            "SELECT * FROM order_changes WHERE order_id = ? ORDER BY created_at",
            (order_id,),
        )
        return [change_from_row(row) for row in rows]

    def list_by_user(
        self,
        user_id: str,
        *,
        status: OrderStatus | None = None,
        keyword: str = "",
        limit: int = 200,
    ) -> list[Order]:
        sql = "SELECT * FROM orders WHERE user_id = ?"
        params: list[object] = [user_id]
        if status is not None:
            sql += " AND status = ?"
            params.append(status.value)
        if keyword:
            sql += " AND order_no LIKE ?"
            params.append(f"%{keyword}%")
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [self._hydrate(order_from_row(row)) for row in self.db.query_all(sql, tuple(params))]

    def list_by_hotel(
        self,
        hotel_id: str,
        *,
        status: OrderStatus | None = None,
        keyword: str = "",
        check_in_from: date | None = None,
        limit: int = 200,
    ) -> list[Order]:
        sql = "SELECT * FROM orders WHERE hotel_id = ?"
        params: list[object] = [hotel_id]
        if status is not None:
            sql += " AND status = ?"
            params.append(status.value)
        if keyword:
            sql += " AND (order_no LIKE ? OR id LIKE ?)"
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        if check_in_from is not None:
            sql += " AND check_in >= ?"
            params.append(check_in_from.isoformat())
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [self._hydrate(order_from_row(row)) for row in self.db.query_all(sql, tuple(params))]

    def list_pending_due(self, moment: datetime) -> list[Order]:
        """确认截止时间已到的待确认订单。

        截止时间是下单时的快照，所以管理员后来改确认时限，
        只影响之后创建的订单（REQ-010）。
        """
        rows = self.db.query_all(
            """
            SELECT * FROM orders
             WHERE status = ? AND confirm_deadline IS NOT NULL
               AND confirm_deadline <= ?
             ORDER BY created_at
            """,
            (OrderStatus.PENDING.value, iso(moment)),
        )
        return [self._hydrate(order_from_row(row)) for row in rows]

    def list_confirmed_before(self, day: date) -> list[Order]:
        """入住日已过、仍处于已确认的订单（未入住关闭候选）。"""
        rows = self.db.query_all(
            """
            SELECT * FROM orders
             WHERE status = ? AND check_in < ?
             ORDER BY check_in
            """,
            (OrderStatus.CONFIRMED.value, day.isoformat()),
        )
        return [self._hydrate(order_from_row(row)) for row in rows]

    def refunds_between(
        self, start: datetime, end: datetime, *, hotel_id: str | None = None
    ) -> list[RefundRecord]:
        """统计期内的退款记录（按记录创建时间归属）。"""
        sql = """
            SELECT r.* FROM refund_records r
              JOIN orders o ON o.id = r.order_id
             WHERE r.created_at >= ? AND r.created_at < ?
        """
        params: list[object] = [iso(start), iso(end)]
        if hotel_id is not None:
            sql += " AND o.hotel_id = ?"
            params.append(hotel_id)
        sql += " ORDER BY r.created_at"
        rows = self.db.query_all(sql, tuple(params))
        return [refund_from_row(row) for row in rows]

    def list_created_between(self, start: datetime, end: datetime) -> list[Order]:
        rows = self.db.query_all(
            """
            SELECT * FROM orders WHERE created_at >= ? AND created_at < ?
            ORDER BY created_at
            """,
            (iso(start), iso(end)),
        )
        return [self._hydrate(order_from_row(row)) for row in rows]

    def list_with_nights_between(self, start: date, end: date) -> list[Order]:
        """统计报表用：任一晚落在区间内的订单。"""
        rows = self.db.query_all(
            """
            SELECT DISTINCT o.* FROM orders o
              JOIN order_nights n ON n.order_id = o.id
             WHERE n.day >= ? AND n.day < ?
             ORDER BY o.created_at
            """,
            (start.isoformat(), end.isoformat()),
        )
        return [self._hydrate(order_from_row(row)) for row in rows]

    def list_all(self, *, limit: int = 500) -> list[Order]:
        rows = self.db.query_all(
            "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [self._hydrate(order_from_row(row)) for row in rows]

    # -------------------------------------------------------------- 内部
    def _hydrate(self, order: Order) -> Order:
        night_rows = self.db.query_all(
            "SELECT * FROM order_nights WHERE order_id = ? ORDER BY day",
            (order.id,),
        )
        guest_rows = self.db.query_all(
            "SELECT * FROM guests WHERE order_id = ? ORDER BY id",
            (order.id,),
        )
        order.nights = [night_from_row(row) for row in night_rows]
        order.guests = [guest_from_row(row) for row in guest_rows]
        return order


def recent_window(minutes: int) -> timedelta:
    """重复下单的判定窗口（REQ-024：2 分钟）。"""
    return timedelta(minutes=minutes)
