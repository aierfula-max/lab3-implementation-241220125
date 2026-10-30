"""定时任务：超时取消、未入住关闭、每日对账（REQ-010/025/028）。

桌面版没有常驻调度进程，界面每 30 秒调一次 ``run``，启动时也会调一次。
这样既不引入 APScheduler 依赖，也方便测试：固定时钟往前拨 31 分钟，
再调一次 ``run``，就能看到订单被取消、库存被释放。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from ..domain.enums import OrderStatus
from ..domain.validation import date_range
from .base import BaseService, Session
from .order_service import OrderService


@dataclass(frozen=True, slots=True)
class ReconcileDiff:
    """订单间夜与库存已售数的不一致。"""

    room_type_id: str
    day: date
    expected_sold: int
    actual_sold: int

    @property
    def delta(self) -> int:
        return self.actual_sold - self.expected_sold


@dataclass(slots=True)
class SchedulerReport:
    """一次调度的结果，界面可以直接展示。"""

    timed_out: int = 0
    no_shows: int = 0
    diffs: list[ReconcileDiff] = field(default_factory=list)


class SchedulerService(BaseService):
    """系统任务。所有状态变更都走订单服务，保证日志与退款口径一致。"""

    def __init__(self, ctx, orders: OrderService) -> None:
        super().__init__(ctx)
        self.orders = orders

    def run(self, now: datetime | None = None) -> SchedulerReport:
        moment = now or self.clock.now()
        report = SchedulerReport()
        report.timed_out = self._timeouts(moment)
        report.no_shows = self._no_shows(moment)
        report.diffs = self._reconcile(moment.date())
        return report

    def _timeouts(self, moment: datetime) -> int:
        """取消确认截止时间已到的待确认订单。

        不在这里用 ``当前时刻 - 当前 policy`` 反推：那会让改配置影响存量订单。
        """
        count = 0
        for order in self.repos.orders.list_pending_due(moment):
            self.orders.timeout_cancel(order)
            count += 1
        return count

    def _no_shows(self, moment: datetime) -> int:
        """入住日 24:00 仍未入住 → 未入住关闭。"""
        count = 0
        for order in self.repos.orders.list_confirmed_before(moment.date()):
            self.orders.close_no_show(order)
            count += 1
        return count

    def _reconcile(self, today: date, *, days: int = 14) -> list[ReconcileDiff]:
        """核对未来两周“订单间夜”与“库存已售数”。

        只核对未来日期：过去日期可能因为正常退房、未入住关闭产生
        合理的口径差异，人工核对更有意义。
        """
        end = today + timedelta(days=days)
        active = {
            OrderStatus.PENDING,
            OrderStatus.CONFIRMED,
            OrderStatus.CHECKED_IN,
            OrderStatus.COMPLETED,
        }
        expected: dict[tuple[str, date], int] = {}
        for order in self.repos.orders.list_with_nights_between(today, end):
            if order.status not in active:
                continue
            for night in order.nights:
                # 提前退房释放掉的间夜不应再算作“应占用”
                if (
                    order.status is OrderStatus.COMPLETED
                    and order.actual_check_out is not None
                    and night.day >= order.actual_check_out
                ):
                    continue
                key = (order.room_type_id, night.day)
                expected[key] = expected.get(key, 0) + night.room_count
        diffs: list[ReconcileDiff] = []
        for (room_type_id, day), value in sorted(
            expected.items(), key=lambda item: (item[0][1], item[0][0])
        ):
            item = self.repos.inventory.get(room_type_id, day)
            actual = item.sold_rooms if item else 0
            if actual != value:
                diffs.append(
                    ReconcileDiff(
                        room_type_id=room_type_id,
                        day=day,
                        expected_sold=value,
                        actual_sold=actual,
                    )
                )
        return diffs

    def unread_notifications(self, session: Session) -> int:
        user = self.require_active(session)
        return self.repos.notifications.unread_count(user.id)

    def notifications(self, session: Session, limit: int = 30):
        user = self.require_active(session)
        return self.repos.notifications.list_by_user(user.id, limit=limit)

    def mark_notifications_read(self, session: Session) -> None:
        user = self.require_active(session)
        with self.db.transaction():
            self.repos.notifications.mark_all_read(user.id, self.clock.now())

    def days_until(self, day: date) -> int:
        """界面显示“还有几天入住”用。"""
        return (day - self.clock.now().date()).days

    def stay_range(self, start: date, days: int) -> list[date]:
        return date_range(start, start + timedelta(days=days))
