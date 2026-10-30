"""调度任务：超时取消、未入住关闭、对账。"""

from __future__ import annotations

from datetime import timedelta

from qiju.domain.enums import OrderStatus, RejectReason
from tests.factories import Org
from tests.helpers import book, confirm, sold


def test_timeout_cancels_after_policy(org: Org):
    order = book(org, org.customer)
    org.clock.advance(minutes=29)
    assert org.app.scheduler.run().timed_out == 0
    assert org.app.orders.get(org.customer, order.order_no).status is OrderStatus.PENDING
    org.clock.advance(minutes=2)
    assert org.app.scheduler.run().timed_out == 1
    reloaded = org.app.orders.get(org.customer, order.order_no)
    assert reloaded.status is OrderStatus.CANCELED
    assert reloaded.cancel_reason == "超时未确认"
    assert sold(org, org.king.id, order.check_in) == 0
    refund = org.app.orders.refunds(org.customer, order.order_no)[0]
    assert refund.refundable_cents == order.total_cents


def test_policy_change_only_affects_new_orders(org: Org):
    old_order = book(org, org.customer, request_id="before-policy")  # 30 分钟
    org.app.hotels.update_policy(org.admin, org.hotel_a.id, 60)
    org.clock.advance(minutes=31)
    new_order = book(org, org.customer, request_id="after-policy")  # 60 分钟
    assert org.app.scheduler.run().timed_out == 1
    assert (
        org.app.orders.get(org.customer, old_order.order_no).status
        is OrderStatus.CANCELED
    )
    assert (
        org.app.orders.get(org.customer, new_order.order_no).status
        is OrderStatus.PENDING
    )


def test_no_show_job(org: Org):
    start = org.clock.now().date() + timedelta(days=1)
    order = book(org, org.customer, check_in=start, check_out=start + timedelta(days=2))
    confirm(org, order)
    org.clock.advance(days=2, hours=1)
    report = org.app.scheduler.run()
    assert report.no_shows == 1
    assert org.app.orders.get(org.customer, order.order_no).status is OrderStatus.NO_SHOW


def test_reconcile_detects_drift(org: Org):
    order = book(org, org.customer)
    assert org.app.scheduler.run().diffs == []
    # 手工多占一间，模拟“扣了库存但没有订单”的异常
    assert org.app.ctx.repos.inventory.hold(org.king.id, order.check_in, 1)
    diffs = org.app.scheduler.run().diffs
    assert len(diffs) == 1
    assert diffs[0].day == order.check_in
    assert diffs[0].delta == 1


def test_notifications_are_masked_and_can_be_read(org: Org):
    order = book(org, org.customer)
    org.app.orders.reject(org.front_a, order.order_no, reason=RejectReason.SOLD_OUT)
    assert org.app.scheduler.unread_notifications(org.customer) == 1
    message = org.app.scheduler.notifications(org.customer)[0]
    assert "13600000001" not in message.body
    org.app.scheduler.mark_notifications_read(org.customer)
    assert org.app.scheduler.unread_notifications(org.customer) == 0
