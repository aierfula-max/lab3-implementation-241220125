"""领域纯函数：金额、定价、状态机、取消口径、输入校验。"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from qiju.domain.cancellation import (
    cancel_quote,
    early_checkout_quote,
    free_cancel_deadline,
    no_show_quote,
)
from qiju.domain.clock import HOTEL_TZ
from qiju.domain.entities import Order, OrderNight
from qiju.domain.enums import CancelReason, OrderStatus, Role
from qiju.domain.errors import StateConflict, ValidationError
from qiju.domain.money import format_money, parse_yuan, yuan
from qiju.domain.order_state import (
    allowed_actions,
    allowed_targets,
    ensure_actor,
    find_transition,
)
from qiju.domain.pricing import build_nights, diff_of, release_amount, total_of
from qiju.domain.validation import (
    validate_capacity,
    validate_phone,
    validate_price_range,
    validate_stay,
    validate_timeout_minutes,
)

TODAY = date(2026, 10, 30)


def make_order(*, total: int = 90000, status: OrderStatus = OrderStatus.CONFIRMED) -> Order:
    nights = [
        OrderNight(day=TODAY, price_cents=30000, room_count=1, subtotal_cents=30000),
        OrderNight(
            day=TODAY.replace(day=31), price_cents=30000, room_count=1, subtotal_cents=30000
        ),
        OrderNight(day=date(2026, 11, 1), price_cents=30000, room_count=1, subtotal_cents=30000),
    ]
    return Order(
        id="o1",
        order_no="QJ1",
        user_id="u1",
        hotel_id="h1",
        room_type_id="r1",
        check_in=TODAY,
        check_out=date(2026, 11, 2),
        room_count=1,
        status=status,
        total_cents=total,
        request_id="r",
        nights=nights,
    )


# ------------------------------------------------------------------ 金额
def test_money_round_trip():
    assert yuan(32800) == "328.00"
    assert format_money(1) == "¥0.01"
    assert parse_yuan("328.00") == 32800
    assert parse_yuan("0.1") == 10
    assert parse_yuan("¥1,299.90") == 129990


def test_money_rejects_float_like_input():
    with pytest.raises(ValueError):
        parse_yuan("19.999")
    with pytest.raises(ValueError):
        parse_yuan("-1")
    with pytest.raises(ValueError):
        parse_yuan("abc")


def test_money_no_float_drift():
    total = parse_yuan("0.1") + parse_yuan("0.2")
    assert total == 30
    assert yuan(total) == "0.30"


# ------------------------------------------------------------------ 定价
def test_build_nights_and_total():
    days = [TODAY, date(2026, 10, 31)]
    prices = {TODAY: 30000, date(2026, 10, 31): 38000}
    nights = build_nights(days, prices, 2)
    assert [item.subtotal_cents for item in nights] == [60000, 76000]
    assert total_of(nights) == 136000
    cheaper = build_nights(
        days, {TODAY: 30000, date(2026, 10, 31): 30000}, 2
    )
    assert diff_of(nights, cheaper) == -16000


def test_build_nights_rejects_missing_price():
    with pytest.raises(ValidationError):
        build_nights([TODAY], {}, 1)


def test_release_amount_only_unused_nights():
    order = make_order()
    assert release_amount(order.nights, date(2026, 10, 31)) == 60000


# ------------------------------------------------------------------ 状态机
def test_seven_states_and_seven_transitions():
    from qiju.domain.order_state import TRANSITIONS

    assert len(OrderStatus) == 7
    # REQ-017 表 3 逐行数下来是 7 条；“8 条”是实验二的口误，
    # 多算的一条是把顾客取消与超时取消当成两种转换，它们目标状态相同。
    assert len(TRANSITIONS) == 7
    assert allowed_targets(OrderStatus.COMPLETED) == []


def test_forbidden_transition_raises_409():
    with pytest.raises(StateConflict):
        find_transition(OrderStatus.COMPLETED, OrderStatus.CANCELED)
    with pytest.raises(StateConflict):
        find_transition(OrderStatus.PENDING, OrderStatus.CHECKED_IN)


def test_role_must_match_transition():
    assert ensure_actor(
        OrderStatus.PENDING, OrderStatus.CONFIRMED, Role.FRONT_DESK
    ).action == "confirm"
    with pytest.raises(StateConflict):
        ensure_actor(OrderStatus.PENDING, OrderStatus.CONFIRMED, Role.CUSTOMER)


def test_allowed_actions_by_role():
    assert "confirm" in allowed_actions(OrderStatus.PENDING, Role.FRONT_DESK)
    assert allowed_actions(OrderStatus.PENDING, Role.CUSTOMER) == ["cancel"]


# ------------------------------------------------------------------ 取消
def test_free_cancel_boundary_1759_1800_1801():
    order = make_order()
    before = datetime(2026, 10, 30, 17, 59, 59, tzinfo=HOTEL_TZ)
    exactly = datetime(2026, 10, 30, 18, 0, 0, tzinfo=HOTEL_TZ)
    after = datetime(2026, 10, 30, 18, 0, 1, tzinfo=HOTEL_TZ)
    assert cancel_quote(order, before, CancelReason.CUSTOMER).deducted_cents == 0
    assert cancel_quote(order, exactly, CancelReason.CUSTOMER).deducted_cents == 0
    late = cancel_quote(order, after, CancelReason.CUSTOMER)
    assert late.deducted_cents == 30000
    assert late.refundable_cents == 60000


def test_cancel_before_check_in_day_is_free():
    order = make_order()
    previous = datetime(2026, 10, 29, 23, 0, tzinfo=HOTEL_TZ)
    assert cancel_quote(order, previous, CancelReason.CUSTOMER).deducted_cents == 0


def test_no_show_and_early_checkout():
    order = make_order()
    quote = no_show_quote(order)
    assert (quote.deducted_cents, quote.refundable_cents) == (30000, 60000)
    early = early_checkout_quote(order, date(2026, 10, 31))
    assert early.refundable_cents == 60000
    normal = early_checkout_quote(order, date(2026, 11, 2))
    assert normal.refundable_cents == 0


def test_free_cancel_deadline_is_checkin_1800():
    deadline = free_cancel_deadline(TODAY)
    assert deadline.hour == 18 and deadline.minute == 0


# ------------------------------------------------------------------ 校验
def test_validate_phone():
    assert validate_phone("13600000001") == "13600000001"
    for bad in ("12345", "12600000001", "1360000000a"):
        with pytest.raises(ValidationError):
            validate_phone(bad)


def test_validate_stay_edges():
    assert validate_stay(TODAY, date(2026, 11, 1), TODAY) == 2
    with pytest.raises(ValidationError):
        validate_stay(TODAY, TODAY, TODAY)
    with pytest.raises(ValidationError):
        validate_stay(TODAY - date.resolution, date(2026, 11, 1), TODAY)
    with pytest.raises(ValidationError):
        validate_stay(TODAY, TODAY.replace(year=2026, month=12, day=1), TODAY)


def test_validate_price_range_swaps():
    assert validate_price_range(500, 100) == (100, 500)
    assert validate_price_range(None, None) == (0, 10**9)
    with pytest.raises(ValidationError):
        validate_price_range(-1, 10)


def test_validate_capacity_and_timeout():
    with pytest.raises(ValidationError):
        validate_capacity(2, 3)
    assert validate_capacity(2, 2) is None
    with pytest.raises(ValidationError):
        validate_timeout_minutes(10)
    assert validate_timeout_minutes(15) == 15
