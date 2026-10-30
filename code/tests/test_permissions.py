"""权限与数据范围（REQ-002/021）。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from qiju.domain.enums import Role, UserStatus
from qiju.domain.errors import (
    NotFound,
    PermissionDenied,
    Unauthenticated,
    ValidationError,
)
from tests.factories import Org
from tests.helpers import book, confirm


def test_manager_cannot_see_other_hotel_order(org: Org):
    order = book(org, org.customer)
    with pytest.raises(NotFound):
        org.app.orders.get(org.manager_b, order.order_no)
    with pytest.raises(NotFound):
        org.app.orders.confirm(org.manager_b, order.order_no)


def test_customer_scope_is_own_orders_only(org: Org):
    order = book(org, org.customer)
    with pytest.raises(NotFound):
        org.app.orders.get(org.customer2, order.order_no)
    assert org.app.orders.list_mine(org.customer2) == []


def test_customer_cannot_use_staff_views(org: Org):
    with pytest.raises(PermissionDenied):
        org.app.orders.list_for_staff(org.customer)
    today = org.clock.now().date()
    with pytest.raises(PermissionDenied):
        org.app.reports.summary(
            org.customer, start=today, end=today + timedelta(days=2)
        )


def test_manager_cannot_change_policy_but_admin_can(org: Org):
    with pytest.raises(PermissionDenied):
        org.app.hotels.update_policy(org.manager_a, org.hotel_a.id, 15)
    policy = org.app.hotels.update_policy(org.admin, org.hotel_a.id, 15)
    assert policy.timeout_minutes == 15
    with pytest.raises(ValidationError):
        org.app.hotels.update_policy(org.admin, org.hotel_a.id, 10)


def test_admin_cannot_edit_inventory(org: Org):
    with pytest.raises(PermissionDenied):
        org.app.inventory.set_day(
            org.admin,
            room_type_id=org.king.id,
            day=org.clock.now().date() + timedelta(days=1),
            total_rooms=5,
            price_cents=30000,
        )


def test_front_desk_cannot_force_cancel(org: Org):
    order = book(org, org.customer)
    confirm(org, order)
    with pytest.raises(PermissionDenied):
        org.app.orders.force_cancel(org.front_a, order.order_no, "x")


def test_disabled_account_session_invalid(org: Org):
    org.app.ctx.repos.users.set_status(org.customer.user.id, UserStatus.DISABLED)
    with pytest.raises(Unauthenticated):
        org.app.orders.list_mine(org.customer)
    with pytest.raises(Unauthenticated):
        book(org, org.customer, request_id="disabled")


def test_manager_can_create_front_desk_but_not_for_other_hotel(org: Org):
    user = org.app.auth.create_front_desk(
        org.manager_a, "13700000009", "Front@2026", "新前台"
    )
    assert user.hotel_id == org.hotel_a.id and user.role is Role.FRONT_DESK
    with pytest.raises(NotFound):
        org.app.auth.disable_user(org.manager_b, user.id)


def test_login_failure_message_does_not_leak(org: Org):
    with pytest.raises(ValidationError) as exc:
        org.app.auth.login("13600000001", "wrong-password")
    assert "手机号或密码错误" in str(exc.value)
    with pytest.raises(ValidationError) as exc2:
        org.app.auth.login("13600009999", "whatever")
    assert "手机号或密码错误" in str(exc2.value)


def test_login_returns_session_and_writes_log(org: Org):
    session = org.app.auth.login("13600000001", "Test@2026")
    assert session.user.role is Role.CUSTOMER
    assert org.app.ctx.repos.logs.query(action="LOGIN", actor_id=session.user.id)
