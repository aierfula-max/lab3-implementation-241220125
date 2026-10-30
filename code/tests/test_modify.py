"""改单：重叠日期不重复占用，失败时原单不变。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from qiju.domain.errors import Conflict, NotFound, StateConflict
from tests.factories import Org
from tests.helpers import book, confirm, sold


def test_extend_dates_and_rooms(org: Org):
    order = book(org, org.customer)
    confirm(org, order)
    today = org.clock.now().date()
    changed, diff = org.app.orders.modify(
        org.customer,
        order.order_no,
        check_in=today + timedelta(days=1),
        check_out=today + timedelta(days=4),
        room_count=2,
    )
    assert changed.room_count == 2
    assert changed.nights_count == 3
    assert diff == 120000
    for offset in (1, 2, 3):
        assert sold(org, org.king.id, today + timedelta(days=offset)) == 2
    assert changed.modified is True


def test_overlap_is_not_double_held(org: Org):
    order = book(org, org.customer)
    confirm(org, order)
    today = org.clock.now().date()
    org.app.orders.modify(
        org.customer,
        order.order_no,
        check_in=today + timedelta(days=2),
        check_out=today + timedelta(days=4),
        room_count=1,
    )
    assert sold(org, org.king.id, today + timedelta(days=1)) == 0
    assert sold(org, org.king.id, today + timedelta(days=2)) == 1
    assert sold(org, org.king.id, today + timedelta(days=3)) == 1


def test_modify_failure_keeps_original(org: Org):
    order = book(org, org.customer, room_type_id=org.twin.id)
    confirm(org, order)
    today = org.clock.now().date()
    org.app.inventory.set_day(
        org.manager_a,
        room_type_id=org.twin.id,
        day=today + timedelta(days=3),
        total_rooms=0,
        price_cents=20000,
    )
    with pytest.raises(Conflict):
        org.app.orders.modify(
            org.customer,
            order.order_no,
            check_in=today + timedelta(days=1),
            check_out=today + timedelta(days=4),
            room_count=1,
        )
    reloaded = org.app.orders.get(org.customer, order.order_no)
    assert reloaded.check_out == today + timedelta(days=3)
    assert reloaded.modified is False
    assert sold(org, org.twin.id, today + timedelta(days=3)) == 0


def test_only_one_modify(org: Org):
    order = book(org, org.customer)
    confirm(org, order)
    today = org.clock.now().date()
    org.app.orders.modify(
        org.customer,
        order.order_no,
        check_in=today + timedelta(days=1),
        check_out=today + timedelta(days=2),
        room_count=1,
    )
    with pytest.raises(StateConflict):
        org.app.orders.modify(
            org.customer,
            order.order_no,
            check_in=today + timedelta(days=1),
            check_out=today + timedelta(days=3),
            room_count=1,
        )


def test_modify_before_confirm_rejected(org: Org):
    order = book(org, org.customer)
    today = org.clock.now().date()
    with pytest.raises(StateConflict):
        org.app.orders.modify(
            org.customer,
            order.order_no,
            check_in=today + timedelta(days=1),
            check_out=today + timedelta(days=2),
            room_count=1,
        )


def test_modify_shorter_creates_refund_and_change(org: Org):
    order = book(org, org.customer)
    confirm(org, order)
    today = org.clock.now().date()
    changed, diff = org.app.orders.modify(
        org.customer,
        order.order_no,
        check_in=today + timedelta(days=1),
        check_out=today + timedelta(days=2),
        room_count=1,
    )
    assert diff == -30000
    assert changed.total_cents == 30000
    refunds = org.app.orders.refunds(org.customer, order.order_no)
    assert refunds[0].refundable_cents == 30000
    changes = org.app.orders.changes(org.customer, order.order_no)
    assert changes[0].diff_cents == -30000


def test_modify_other_customer_not_found(org: Org):
    order = book(org, org.customer)
    confirm(org, order)
    today = org.clock.now().date()
    with pytest.raises(NotFound):
        org.app.orders.modify(
            org.customer2,
            order.order_no,
            check_in=today + timedelta(days=1),
            check_out=today + timedelta(days=2),
            room_count=1,
        )
