"""可订查询与下单。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from qiju.application.booking_service import BookingRequest
from qiju.domain.entities import Guest
from qiju.domain.enums import OrderStatus
from qiju.domain.errors import (
    DuplicateOrder,
    SoldOut,
    StopSale,
    ValidationError,
)
from tests.factories import Org
from tests.helpers import book, sold


def test_create_order_occupies_each_night(org: Org):
    order = book(org, org.customer)
    assert order.status is OrderStatus.PENDING
    assert order.nights_count == 2
    assert order.total_cents == 60000
    for day in order.stay_dates:
        assert sold(org, org.king.id, day) == 1
    assert [night.price_cents for night in order.nights] == [30000, 30000]


def test_price_snapshot_survives_price_change(org: Org):
    today = org.clock.now().date()
    for day in (today + timedelta(days=1), today + timedelta(days=2)):
        org.app.inventory.set_day(
            org.manager_a,
            room_type_id=org.king.id,
            day=day,
            total_rooms=10,
            price_cents=35000,
        )
    order = book(org, org.customer)
    assert order.total_cents == 70000
    org.app.inventory.set_day(
        org.manager_a,
        room_type_id=org.king.id,
        day=today + timedelta(days=1),
        total_rooms=10,
        price_cents=99000,
    )
    reloaded = org.app.orders.get(org.customer, order.order_no)
    assert reloaded.total_cents == 70000
    assert reloaded.nights[0].price_cents == 35000


def test_sold_out_rolls_back_all_nights(org: Org):
    today = org.clock.now().date()
    org.app.inventory.set_day(
        org.manager_a,
        room_type_id=org.twin.id,
        day=today + timedelta(days=2),
        total_rooms=1,
        price_cents=20000,
    )
    with pytest.raises(SoldOut):
        book(org, org.customer, room_type_id=org.twin.id, room_count=2, request_id="x")
    assert sold(org, org.twin.id, today + timedelta(days=1)) == 0
    assert sold(org, org.twin.id, today + timedelta(days=2)) == 0
    assert org.app.orders.list_mine(org.customer) == []


def test_stop_sale_blocks_booking(org: Org):
    today = org.clock.now().date()
    org.app.inventory.set_stop_sale(
        org.manager_a,
        room_type_id=org.king.id,
        start=today + timedelta(days=1),
        end=today + timedelta(days=1),
    )
    with pytest.raises(StopSale):
        book(org, org.customer)
    assert sold(org, org.king.id, today + timedelta(days=1)) == 0


def test_idempotent_replay_returns_same_order(org: Org):
    first = book(org, org.customer, request_id="same-key")
    second = book(org, org.customer, request_id="same-key")
    assert first.id == second.id
    assert sold(org, org.king.id, first.check_in) == 1


def test_duplicate_content_needs_second_confirm(org: Org):
    first = book(org, org.customer, request_id="key-1")
    with pytest.raises(DuplicateOrder) as exc:
        book(org, org.customer, request_id="key-2")
    assert exc.value.detail["existing_order_no"] == first.order_no
    second = book(org, org.customer, request_id="key-3", confirm_duplicate=True)
    assert second.id != first.id
    assert sold(org, org.king.id, first.check_in) == 2


def test_capacity_is_checked_on_server(org: Org):
    with pytest.raises(ValidationError):
        book(org, org.customer, room_type_id=org.suite.id, room_count=1, guests=4)


def test_guest_phone_and_room_count_validation(org: Org):
    today = org.clock.now().date()
    with pytest.raises(ValidationError):
        org.app.booking.create_order(
            org.customer,
            BookingRequest(
                room_type_id=org.king.id,
                check_in=today + timedelta(days=1),
                check_out=today + timedelta(days=2),
                room_count=1,
                guests=[Guest("张三", "12345")],
                request_id="bad-phone",
            ),
        )
    with pytest.raises(ValidationError):
        book(org, org.customer, room_count=0, request_id="bad-count")


def test_past_date_and_long_stay_rejected(org: Org):
    today = org.clock.now().date()
    with pytest.raises(ValidationError):
        book(
            org,
            org.customer,
            check_in=today - timedelta(days=1),
            check_out=today + timedelta(days=1),
            request_id="past",
        )
    with pytest.raises(ValidationError):
        book(
            org,
            org.customer,
            check_in=today + timedelta(days=1),
            check_out=today + timedelta(days=40),
            request_id="long",
        )


def test_quote_matches_order_total(org: Org):
    today = org.clock.now().date()
    quote = org.app.booking.quote(
        room_type_id=org.king.id,
        check_in=today + timedelta(days=1),
        check_out=today + timedelta(days=3),
        room_count=2,
    )
    order = book(org, org.customer, room_count=2)
    assert quote.total_cents == order.total_cents == 120000


def test_search_filters_city_capacity_and_price(org: Org):
    today = org.clock.now().date()
    results = org.app.booking.search(
        city="南京",
        check_in=today + timedelta(days=1),
        check_out=today + timedelta(days=2),
        guests=2,
    )
    assert {item.hotel.name for item in results} == {"测试酒店 A"}
    assert {item.room_type.name for item in results} == {"大床房", "双床房", "套房"}
    cheap = org.app.booking.search(
        city="南京",
        check_in=today + timedelta(days=1),
        check_out=today + timedelta(days=2),
        guests=2,
        price_max=25000,
    )
    assert [item.room_type.name for item in cheap] == ["双床房"]


def test_search_hides_stop_sale_and_sold_out(org: Org):
    today = org.clock.now().date()
    org.app.inventory.set_stop_sale(
        org.manager_a,
        room_type_id=org.king.id,
        start=today + timedelta(days=1),
        end=today + timedelta(days=1),
    )
    org.app.inventory.set_day(
        org.manager_a,
        room_type_id=org.twin.id,
        day=today + timedelta(days=1),
        total_rooms=0,
        price_cents=20000,
    )
    results = org.app.booking.search(
        city="南京",
        check_in=today + timedelta(days=1),
        check_out=today + timedelta(days=2),
        guests=2,
    )
    assert [item.room_type.name for item in results] == ["套房"]


def test_search_does_not_require_login(org: Org):
    today = org.clock.now().date()
    results = org.app.booking.search(
        check_in=today + timedelta(days=1),
        check_out=today + timedelta(days=2),
    )
    assert len(results) == 4
    assert all(item.remaining > 0 for item in results)
