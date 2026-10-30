"""统计口径：可售/计费/已住间夜、成交额、退款、取消率。"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from qiju.application.report_service import last_n_days, period_of_month
from qiju.domain.clock import HOTEL_TZ
from tests.factories import Org
from tests.helpers import book, confirm


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=HOTEL_TZ).replace(
        hour=hour, minute=minute
    )


def test_report_counts_three_kinds_of_nights(org: Org):
    today = date(2026, 10, 26)
    org.clock.set(at(today, 9))
    completed = book(
        org,
        org.customer,
        check_in=today + timedelta(days=1),
        check_out=today + timedelta(days=3),
        request_id="completed",
    )
    confirm(org, completed)
    org.clock.set(at(today + timedelta(days=1), 15))
    org.app.orders.check_in(org.front_a, completed.order_no)
    org.clock.set(at(today + timedelta(days=3), 10))
    org.app.orders.check_out(org.front_a, completed.order_no)

    org.clock.set(at(today + timedelta(days=1), 11))
    no_show = book(
        org,
        org.customer2,
        check_in=today + timedelta(days=2),
        check_out=today + timedelta(days=4),
        request_id="noshow",
    )
    confirm(org, no_show)
    org.clock.set(at(today + timedelta(days=3), 0, 20))
    org.app.scheduler.run()

    org.clock.set(at(today + timedelta(days=3), 9))
    canceled = book(
        org,
        org.customer,
        check_in=today + timedelta(days=4),
        check_out=today + timedelta(days=5),
        request_id="canceled",
    )
    org.app.orders.cancel_by_customer(org.customer, canceled.order_no)

    org.clock.set(at(today + timedelta(days=4), 10))
    summary = org.app.reports.summary(
        org.manager_a, start=today, end=today + timedelta(days=5)
    )
    # 3 个房型 × 5 天：大床 10 + 双床 2 + 套房 2 = 14/天
    assert summary.sellable_nights == 70
    assert summary.sold_nights == 3  # 2 晚已住 + no-show 首晚
    assert summary.stayed_nights == 2
    assert summary.revenue_cents == 90000
    assert summary.refund_cents == 60000  # no-show 退 30000 + 免费取消退 30000
    assert summary.net_cents == 30000
    assert summary.adr_cents == 30000
    assert abs(summary.occupancy - 3 / 70) < 1e-9
    assert summary.created_orders == 3
    assert summary.canceled_orders == 1
    assert abs(summary.cancel_rate - 1 / 3) < 1e-9


def test_report_is_scoped_to_hotel(org: Org):
    summary = org.app.reports.summary(
        org.manager_b, start=org.clock.now().date(), end=org.clock.now().date() + timedelta(days=2)
    )
    assert summary.sellable_nights == 10  # 5 间 × 2 天
    assert summary.revenue_cents == 0


def test_month_and_last_days_helpers():
    start, end = period_of_month(2026, 12)
    assert (start, end) == (date(2026, 12, 1), date(2027, 1, 1))
    start, end = last_n_days(date(2026, 10, 30), 7)
    assert (start, end) == (date(2026, 10, 24), date(2026, 10, 31))


def test_zero_denominator_is_none(org: Org):
    summary = org.app.reports.summary(
        org.manager_a, start=date(2027, 1, 1), end=date(2027, 1, 3)
    )
    assert summary.occupancy == 0
    assert summary.adr_cents is None
    assert summary.cancel_rate is None
