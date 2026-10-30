"""测试里反复用到的动作。"""

from __future__ import annotations

from datetime import date, timedelta

from qiju.application import Session
from qiju.application.booking_service import BookingRequest
from qiju.domain.entities import Guest, Order
from tests.factories import Org


def book(
    org: Org,
    session: Session,
    *,
    room_type_id: str | None = None,
    check_in: date | None = None,
    check_out: date | None = None,
    room_count: int = 1,
    guests: int = 1,
    request_id: str = "req-1",
    confirm_duplicate: bool = False,
    phone_suffix: str = "0001",
) -> Order:
    """默认订“明天入住、住 2 晚”的大床房。"""
    today = org.clock.now().date()
    return org.app.booking.create_order(
        session,
        BookingRequest(
            room_type_id=room_type_id or org.king.id,
            check_in=check_in or today + timedelta(days=1),
            check_out=check_out or today + timedelta(days=3),
            room_count=room_count,
            guests=[
                Guest(f"入住人{index}", f"136{phone_suffix}{index:04d}")
                for index in range(guests)
            ],
            request_id=request_id,
            confirm_duplicate=confirm_duplicate,
        ),
    )


def confirm(org: Org, order: Order) -> Order:
    return org.app.orders.confirm(org.front_a, order.order_no)


def sold(org: Org, room_type_id: str, day: date) -> int:
    item = org.app.ctx.repos.inventory.get(room_type_id, day)
    return item.sold_rooms if item else 0
