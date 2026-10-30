"""订单履约：确认、拒绝、取消、入住、退房、退款、强制取消。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from qiju.domain.enums import OrderStatus, RefundStatus, RejectReason
from qiju.domain.errors import (
    Conflict,
    NotFound,
    PermissionDenied,
    StateConflict,
    ValidationError,
)
from tests.factories import Org
from tests.helpers import book, confirm, sold


def future(org: Org, days: int) -> date:
    return org.clock.now().date() + timedelta(days=days)


def test_confirm_records_operator_and_log(org: Org):
    order = book(org, org.customer)
    confirmed = confirm(org, order)
    assert confirmed.status is OrderStatus.CONFIRMED
    assert confirmed.confirmed_by == org.front_a.user.id
    actions = [log.action for log in org.app.ctx.repos.logs.all()]
    assert "ORDER_CONFIRM" in actions


def test_customer_cannot_confirm(org: Org):
    order = book(org, org.customer)
    with pytest.raises(PermissionDenied):
        org.app.orders.confirm(org.customer, order.order_no)


def test_confirm_rechecks_stock(org: Org):
    order = book(org, org.customer)
    org.app.inventory.set_stop_sale(
        org.manager_a,
        room_type_id=org.king.id,
        start=order.check_in,
        end=order.check_in,
    )
    with pytest.raises(StateConflict):
        org.app.orders.confirm(org.front_a, order.order_no)


def test_reject_other_requires_note_and_releases(org: Org):
    order = book(org, org.customer)
    with pytest.raises(ValidationError):
        org.app.orders.reject(
            org.front_a, order.order_no, reason=RejectReason.OTHER, note=" "
        )
    assert org.app.ctx.repos.logs.query(action="ORDER_REJECT") == []
    rejected = org.app.orders.reject(
        org.front_a, order.order_no, reason=RejectReason.SOLD_OUT
    )
    assert rejected.status is OrderStatus.REJECTED
    assert rejected.reject_reason == RejectReason.SOLD_OUT.value
    for day in order.stay_dates:
        assert sold(org, org.king.id, day) == 0
    refunds = org.app.orders.refunds(org.customer, order.order_no)
    assert len(refunds) == 1
    assert refunds[0].refundable_cents == order.total_cents


def test_customer_cancel_before_checkin_is_free(org: Org):
    order = book(org, org.customer)
    canceled, refund = org.app.orders.cancel_by_customer(org.customer, order.order_no)
    assert canceled.status is OrderStatus.CANCELED
    assert canceled.cancel_reason == "顾客取消"
    assert refund.refundable_cents == order.total_cents
    assert refund.deducted_cents == 0
    assert sold(org, org.king.id, order.check_in) == 0


def test_customer_cancel_after_1800_charges_first_night(org: Org):
    today = org.clock.now().date()
    order = book(
        org,
        org.customer,
        check_in=today,
        check_out=today + timedelta(days=2),
        request_id="today",
    )
    confirm(org, order)
    org.clock.set(
        __import__("datetime").datetime(
            2026, 10, 30, 18, 0, 1, tzinfo=org.clock.now().tzinfo
        )
    )
    _, refund = org.app.orders.cancel_by_customer(org.customer, order.order_no)
    assert refund.deducted_cents == 30000
    assert refund.refundable_cents == 30000


def test_customer_cannot_touch_other_order(org: Org):
    order = book(org, org.customer)
    with pytest.raises(NotFound):
        org.app.orders.cancel_by_customer(org.customer2, order.order_no)
    with pytest.raises(NotFound):
        org.app.orders.get(org.customer2, order.order_no)


def test_checked_in_cannot_cancel(org: Org):
    today = org.clock.now().date()
    order = book(org, org.customer, check_in=today, check_out=today + timedelta(days=2))
    confirm(org, order)
    org.app.orders.check_in(org.front_a, order.order_no)
    with pytest.raises(StateConflict):
        org.app.orders.cancel_by_customer(org.customer, order.order_no)


def test_early_check_in_needs_manager_and_reason(org: Org):
    order = book(org, org.customer)
    confirm(org, order)
    with pytest.raises(PermissionDenied):
        org.app.orders.check_in(org.front_a, order.order_no)
    with pytest.raises(ValidationError):
        org.app.orders.check_in(org.manager_a, order.order_no)
    checked = org.app.orders.check_in(
        org.manager_a, order.order_no, early_reason="客人提前到店"
    )
    assert checked.status is OrderStatus.CHECKED_IN


def test_early_checkout_releases_only_unused_nights(org: Org):
    today = org.clock.now().date()
    order = book(
        org,
        org.customer,
        check_in=today,
        check_out=today + timedelta(days=3),
        request_id="co",
    )
    confirm(org, order)
    org.app.orders.check_in(org.front_a, order.order_no)
    org.clock.set(
        __import__("datetime").datetime(
            2026, 10, 31, 10, 0, tzinfo=org.clock.now().tzinfo
        )
    )
    with pytest.raises(PermissionDenied):
        org.app.orders.check_out(org.front_a, order.order_no)
    done, refund = org.app.orders.check_out(org.manager_a, order.order_no)
    assert done.status is OrderStatus.COMPLETED
    assert done.early_checkout is True
    assert done.actual_check_out == today + timedelta(days=1)
    assert refund is not None and refund.refundable_cents == 60000
    assert sold(org, org.king.id, today) == 1
    assert sold(org, org.king.id, today + timedelta(days=1)) == 0
    assert sold(org, org.king.id, today + timedelta(days=2)) == 0


def test_normal_checkout_keeps_inventory(org: Org):
    today = org.clock.now().date()
    order = book(org, org.customer, check_in=today, check_out=today + timedelta(days=2))
    confirm(org, order)
    org.app.orders.check_in(org.front_a, order.order_no)
    org.clock.set(
        __import__("datetime").datetime(
            2026, 11, 1, 10, 0, tzinfo=org.clock.now().tzinfo
        )
    )
    done, refund = org.app.orders.check_out(org.front_a, order.order_no)
    assert done.status is OrderStatus.COMPLETED
    assert refund is None
    assert sold(org, org.king.id, today) == 1
    assert sold(org, org.king.id, today + timedelta(days=1)) == 1


def test_no_show_keeps_first_night(org: Org):
    start = future(org, 1)
    order = book(org, org.customer, check_in=start, check_out=start + timedelta(days=2))
    confirm(org, order)
    org.clock.set(
        __import__("datetime").datetime(
            2026, 11, 1, 0, 10, tzinfo=org.clock.now().tzinfo
        )
    )
    report = org.app.scheduler.run()
    assert report.no_shows == 1
    closed = org.app.orders.get(org.customer, order.order_no)
    assert closed.status is OrderStatus.NO_SHOW
    assert sold(org, org.king.id, start) == 1
    assert sold(org, org.king.id, start + timedelta(days=1)) == 0
    refunds = org.app.orders.refunds(org.customer, order.order_no)
    assert refunds[0].deducted_cents == 30000


def test_force_cancel_requires_admin_and_reason(org: Org):
    order = book(org, org.customer)
    confirm(org, order)
    with pytest.raises(PermissionDenied):
        org.app.orders.force_cancel(org.manager_a, order.order_no, "酒店问题")
    with pytest.raises(ValidationError):
        org.app.orders.force_cancel(org.admin, order.order_no, "  ")
    canceled, refund = org.app.orders.force_cancel(
        org.admin, order.order_no, "酒店无法接待"
    )
    assert canceled.status is OrderStatus.CANCELED
    assert refund.refundable_cents == order.total_cents
    log = org.app.ctx.repos.logs.query(action="ORDER_FORCE_CANCEL")[0]
    assert "酒店无法接待" in log.reason
    assert "责任方" in log.reason


def test_refund_can_only_be_marked_once(org: Org):
    order = book(org, org.customer)
    org.app.orders.reject(org.front_a, order.order_no, reason=RejectReason.SOLD_OUT)
    refund = org.app.orders.refunds(org.customer, order.order_no)[0]
    org.app.orders.mark_refund(org.manager_a, order.order_no, refund.id)
    assert org.app.orders.refunds(org.customer, order.order_no)[0].status is RefundStatus.REFUNDED
    with pytest.raises(Conflict):
        org.app.orders.mark_refund(org.manager_a, order.order_no, refund.id)


def test_terminal_state_cannot_transition(org: Org):
    order = book(org, org.customer)
    org.app.orders.cancel_by_customer(org.customer, order.order_no)
    with pytest.raises(StateConflict):
        org.app.orders.confirm(org.front_a, order.order_no)
