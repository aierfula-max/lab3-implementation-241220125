"""库存、价格与停售维护。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from qiju.application.booking_service import BookingRequest
from qiju.domain.entities import Guest
from qiju.domain.errors import Conflict, NotFound, PermissionDenied, ValidationError
from tests.factories import Org
from tests.helpers import sold


def day(org: Org, offset: int):
    return org.clock.now().date() + timedelta(days=offset)


def test_set_day_updates_price_and_inventory(org: Org):
    item = org.app.inventory.set_day(
        org.manager_a,
        room_type_id=org.king.id,
        day=day(org, 1),
        total_rooms=8,
        price_cents=36000,
    )
    assert (item.total_rooms, item.price_cents) == (8, 36000)
    order = org.app.booking.quote(
        room_type_id=org.king.id,
        check_in=day(org, 1),
        check_out=day(org, 2),
        room_count=1,
    )
    assert order.total_cents == 36000


def test_cannot_set_below_sold(org: Org):
    order = org.app.booking.create_order(
        org.customer,
        BookingRequest(
            room_type_id=org.king.id,
            check_in=day(org, 1),
            check_out=day(org, 2),
            room_count=3,
            guests=[Guest("甲", "13600000001")],
            request_id="r",
        ),
    )
    assert sold(org, org.king.id, day(org, 1)) == 3
    with pytest.raises(Conflict):
        org.app.inventory.set_day(
            org.manager_a,
            room_type_id=org.king.id,
            day=day(org, 1),
            total_rooms=2,
            price_cents=30000,
        )
    assert order.room_count == 3


def test_batch_set_skips_stop_sale_days(org: Org):
    org.app.inventory.set_stop_sale(
        org.manager_a,
        room_type_id=org.king.id,
        start=day(org, 2),
        end=day(org, 2),
    )
    result = org.app.inventory.batch_set(
        org.manager_a,
        room_type_id=org.king.id,
        start=day(org, 1),
        end=day(org, 3),
        price_cents=31000,
    )
    assert result["applied"] == [day(org, 1), day(org, 3)]
    assert result["skipped"] == [day(org, 2)]
    assert org.app.ctx.repos.inventory.get(org.king.id, day(org, 2)).stop_sale is True


def test_stop_sale_and_restore(org: Org):
    affected = org.app.inventory.set_stop_sale(
        org.manager_a,
        room_type_id=org.king.id,
        start=day(org, 1),
        end=day(org, 2),
    )
    assert affected == 2
    item = org.app.ctx.repos.inventory.get(org.king.id, day(org, 1))
    assert item.stop_sale is True
    assert item.remaining == 0
    org.app.inventory.set_stop_sale(
        org.manager_a,
        room_type_id=org.king.id,
        start=day(org, 1),
        end=day(org, 2),
        stop=False,
    )
    assert org.app.ctx.repos.inventory.get(org.king.id, day(org, 1)).stop_sale is False


def test_past_date_is_read_only(org: Org):
    with pytest.raises(ValidationError):
        org.app.inventory.set_day(
            org.manager_a,
            room_type_id=org.king.id,
            day=day(org, -1),
            total_rooms=5,
            price_cents=30000,
        )


def test_front_desk_cannot_edit_inventory(org: Org):
    with pytest.raises(PermissionDenied):
        org.app.inventory.set_day(
            org.front_a,
            room_type_id=org.king.id,
            day=day(org, 1),
            total_rooms=5,
            price_cents=30000,
        )


def test_calendar_covers_every_day(org: Org):
    rows = org.app.inventory.calendar(org.manager_a, start=day(org, 1), end=day(org, 3))
    assert len(rows) == 3 * 2
    assert all(row.remaining > 0 for row in rows)


def test_room_type_total_cannot_drop_below_sold(org: Org):
    org.app.booking.create_order(
        org.customer,
        BookingRequest(
            room_type_id=org.king.id,
            check_in=day(org, 1),
            check_out=day(org, 2),
            room_count=4,
            guests=[Guest("甲", "13600000001")],
            request_id="r",
        ),
    )
    with pytest.raises(Conflict):
        org.app.hotels.update_room_type(
            org.manager_a, org.king.id, total_rooms=3
        )


def test_other_hotel_room_type_not_found(org: Org):
    with pytest.raises(NotFound):
        org.app.inventory.set_day(
            org.manager_b,
            room_type_id=org.king.id,
            day=day(org, 1),
            total_rooms=5,
            price_cents=30000,
        )
