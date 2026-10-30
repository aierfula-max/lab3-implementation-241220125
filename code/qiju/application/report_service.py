"""经营统计报表（REQ-018）。

口径写在代码里，避免“同一个数在不同页面不一样”：

* 可售间夜 = 每日库存的可售间数之和，停售日计 0；没有库存记录的日期
  按房型可售数计；
* 计费间夜 = 已确认/已入住/已完成订单的入住间夜，加上未入住关闭订单的
  首晚、18:00 后取消订单的首晚；
* 已住间夜 = 实际办理入住的间夜；
* 成交金额 = 计费间夜按每晚明细单价 × 间数求和；
* 退款金额 = 退款记录“应退金额”之和；
* 取消率 = 已取消订单数 ÷ 统计期内创建的订单数。

报表只读，不修改任何历史数据。对账差异由调度器单独输出，不与报表混在
一起，否则财务口径会被“修正”污染。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from ..domain.cancellation import free_cancel_deadline
from ..domain.enums import CancelReason, OrderStatus, Role
from ..domain.errors import PermissionDenied
from ..domain.validation import date_range
from .base import BaseService, Session


@dataclass(frozen=True, slots=True)
class DailyMetric:
    """按日指标。出租率与平均房价用 ``None`` 表示分母为 0。"""

    day: date
    sellable_nights: int
    sold_nights: int
    stayed_nights: int
    revenue_cents: int
    refund_cents: int
    occupancy: float | None
    adr_cents: int | None
    created_orders: int
    canceled_orders: int


@dataclass(slots=True)
class ReportSummary:
    """统计期总览。"""

    start: date
    end: date
    sellable_nights: int = 0
    sold_nights: int = 0
    stayed_nights: int = 0
    revenue_cents: int = 0
    refund_cents: int = 0
    created_orders: int = 0
    canceled_orders: int = 0
    rejected_orders: int = 0
    no_show_orders: int = 0
    daily: list[DailyMetric] = field(default_factory=list)

    @property
    def net_cents(self) -> int:
        return self.revenue_cents - self.refund_cents

    @property
    def occupancy(self) -> float | None:
        if self.sellable_nights == 0:
            return None
        return self.sold_nights / self.sellable_nights

    @property
    def adr_cents(self) -> int | None:
        if self.sold_nights == 0:
            return None
        return round(self.revenue_cents / self.sold_nights)

    @property
    def cancel_rate(self) -> float | None:
        if self.created_orders == 0:
            return None
        return self.canceled_orders / self.created_orders

    @property
    def unfulfilled_rate(self) -> float | None:
        if self.created_orders == 0:
            return None
        return (self.canceled_orders + self.rejected_orders + self.no_show_orders) / (
            self.created_orders
        )


class ReportService(BaseService):
    """按日/按月汇总。店长看本店，管理员看全平台或指定酒店。"""

    def summary(
        self,
        session: Session,
        *,
        start: date,
        end: date,
        hotel_id: str | None = None,
    ) -> ReportSummary:
        actor = self.require_active(session)
        if end <= start:
            raise ValueError("结束日期必须晚于开始日期")
        if actor.role is Role.MANAGER:
            target_hotel = actor.hotel_id
        elif actor.role is Role.PLATFORM_ADMIN:
            target_hotel = hotel_id
        else:
            raise PermissionDenied("只有店长或平台管理员可以查看报表")

        daily = self._empty_daily(target_hotel, start, end)
        orders, refunds, created = self._load(target_hotel, start, end)
        today = self.clock.now().date()
        self._apply_orders(daily, orders, today)
        self._apply_refunds(daily, refunds, start)
        self._apply_created(daily, created, start)
        return self._assemble(start, end, daily, created)

    def _load(self, hotel_id, start, end):
        """一次取出三个口径需要的原始数据。"""
        moment = self.clock.now()
        tz = moment.tzinfo
        start_moment = datetime.combine(start, time.min, tzinfo=tz)
        end_moment = datetime.combine(end, time.min, tzinfo=tz)
        orders = self.repos.orders.list_with_nights_between(start, end)
        if hotel_id is not None:
            orders = [item for item in orders if item.hotel_id == hotel_id]
        refunds = self.repos.orders.refunds_between(
            start_moment, end_moment, hotel_id=hotel_id
        )
        created = self.repos.orders.list_created_between(start_moment, end_moment)
        if hotel_id is not None:
            created = [item for item in created if item.hotel_id == hotel_id]
        return orders, refunds, created

    def _empty_daily(self, hotel_id, start, end) -> dict[date, DailyMetric]:
        daily: dict[date, DailyMetric] = {}
        for day in date_range(start, end):
            daily[day] = DailyMetric(
                day=day,
                sellable_nights=self._sellable_nights(hotel_id, day),
                sold_nights=0,
                stayed_nights=0,
                revenue_cents=0,
                refund_cents=0,
                occupancy=None,
                adr_cents=None,
                created_orders=0,
                canceled_orders=0,
            )
        return daily

    @staticmethod
    def _apply_orders(daily, orders, today) -> None:
        for order in orders:
            billable = ReportService._billable_days(order, today)
            stayed = ReportService._stayed_days(order, today)
            for night in order.nights:
                if night.day not in daily:
                    continue
                metric = daily[night.day]
                if night.day in billable:
                    metric = _replace(
                        metric,
                        sold_nights=metric.sold_nights + night.room_count,
                        revenue_cents=metric.revenue_cents + night.subtotal_cents,
                    )
                if night.day in stayed:
                    metric = _replace(
                        metric, stayed_nights=metric.stayed_nights + night.room_count
                    )
                daily[night.day] = metric

    @staticmethod
    def _apply_refunds(daily, refunds, start) -> None:
        for refund in refunds:
            day = refund.created_at.date() if refund.created_at else start
            if day in daily:
                metric = daily[day]
                daily[day] = _replace(
                    metric, refund_cents=metric.refund_cents + refund.refundable_cents
                )

    @staticmethod
    def _apply_created(daily, created, start) -> None:
        for order in created:
            day = order.created_at.date() if order.created_at else start
            if day not in daily:
                continue
            metric = daily[day]
            daily[day] = _replace(
                metric,
                created_orders=metric.created_orders + 1,
                canceled_orders=metric.canceled_orders
                + int(order.status is OrderStatus.CANCELED),
            )

    @staticmethod
    def _assemble(start, end, daily, created) -> ReportSummary:
        summary = ReportSummary(start=start, end=end)
        for day in sorted(daily):
            metric = daily[day]
            summary.sellable_nights += metric.sellable_nights
            summary.sold_nights += metric.sold_nights
            summary.stayed_nights += metric.stayed_nights
            summary.revenue_cents += metric.revenue_cents
            summary.refund_cents += metric.refund_cents
            summary.created_orders += metric.created_orders
            summary.canceled_orders += metric.canceled_orders
            summary.daily.append(
                _replace(
                    metric,
                    occupancy=(
                        None
                        if metric.sellable_nights == 0
                        else metric.sold_nights / metric.sellable_nights
                    ),
                    adr_cents=(
                        None
                        if metric.sold_nights == 0
                        else round(metric.revenue_cents / metric.sold_nights)
                    ),
                )
            )
        summary.rejected_orders = sum(
            1 for item in created if item.status is OrderStatus.REJECTED
        )
        summary.no_show_orders = sum(
            1 for item in created if item.status is OrderStatus.NO_SHOW
        )
        return summary

    # ------------------------------------------------------------ 口径
    def _sellable_nights(self, hotel_id: str | None, day: date) -> int:
        if hotel_id is None:
            hotels = self.repos.hotels.list_all()
        else:
            hotel = self.repos.hotels.by_id(hotel_id)
            hotels = [hotel] if hotel else []
        total = 0
        for hotel in hotels:
            for room_type in self.repos.room_types.list_on_sale(hotel.id):
                item = self.repos.inventory.get(room_type.id, day)
                if item is None:
                    total += room_type.total_rooms
                elif not item.stop_sale:
                    total += item.total_rooms
        return total

    @staticmethod
    def _billable_days(order, today: date) -> set[date]:
        """返回计入“计费间夜”的日期集合。"""
        if order.status in (
            OrderStatus.CONFIRMED,
            OrderStatus.CHECKED_IN,
            OrderStatus.COMPLETED,
        ):
            days = set(order.stay_dates)
            if order.status is OrderStatus.COMPLETED and order.actual_check_out:
                days = {day for day in days if day < order.actual_check_out}
            return days
        if order.status is OrderStatus.NO_SHOW:
            return {order.check_in}
        if order.status is OrderStatus.CANCELED:
            customer_late = (
                order.cancel_reason == CancelReason.CUSTOMER.value
                and order.canceled_at is not None
                and order.canceled_at > free_cancel_deadline(order.check_in)
            )
            return {order.check_in} if customer_late else set()
        return set()

    @staticmethod
    def _stayed_days(order, today: date) -> set[date]:
        if order.status is OrderStatus.COMPLETED:
            end = order.actual_check_out or order.check_out
            return {day for day in order.stay_dates if day < end}
        if order.status is OrderStatus.CHECKED_IN:
            return {day for day in order.stay_dates if day < today}
        return set()


def _replace(metric: DailyMetric, **changes) -> DailyMetric:
    """``dataclasses.replace`` 的轻封装，保持调用处短一些。"""
    from dataclasses import replace

    return replace(metric, **changes)


def period_of_month(year: int, month: int) -> tuple[date, date]:
    """自然月区间，左闭右开。"""
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    return start, end


def last_n_days(today: date, days: int) -> tuple[date, date]:
    """最近 N 天（含今天），左闭右开。"""
    return today - timedelta(days=days - 1), today + timedelta(days=1)
