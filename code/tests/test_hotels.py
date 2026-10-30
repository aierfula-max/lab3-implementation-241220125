"""酒店入驻、审核与关键资料变更（REQ-003/004）。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from qiju.domain.enums import AuditStatus, BusinessStatus
from qiju.domain.errors import Conflict, PermissionDenied, ValidationError
from tests.factories import Org


def test_admin_creates_hotel_and_invitation(org: Org):
    hotel = org.app.auth.create_hotel(
        org.admin,
        name="新测试酒店",
        city="南京",
        address="新测试路 9 号",
        phone="02580000009",
        description="待审核",
    )
    assert hotel.audit_status is AuditStatus.PENDING
    assert hotel.business_status is BusinessStatus.SUSPENDED
    code = org.app.auth.issue_invitation(org.admin, hotel.id)
    assert code.hotel_id == hotel.id
    with pytest.raises(PermissionDenied):
        org.app.auth.create_hotel(
            org.manager_a, name="x", city="y", address="z", phone="02580000008"
        )


def test_manager_activates_and_submits_profile(org: Org):
    hotel = org.app.auth.create_hotel(
        org.admin,
        name="待激活酒店",
        city="南京",
        address="测试路 1 号",
        phone="02580000010",
    )
    code = org.app.auth.issue_invitation(org.admin, hotel.id)
    session = org.app.auth.activate_manager(
        code.code, "13900000088", "Manager@2026", "邀请码店长"
    )
    assert session.user.hotel_id == hotel.id
    updated = org.app.hotels.submit_profile(
        session,
        name="待激活酒店",
        city="南京",
        address="测试路 1 号",
        phone="02580000010",
        description="补充简介",
    )
    assert updated.audit_status is AuditStatus.PENDING
    assert updated.description == "补充简介"
    with pytest.raises(Conflict):
        org.app.auth.activate_manager(
            code.code, "13900000087", "Manager@2026", "重复激活"
        )


def test_first_audit_approve_makes_hotel_bookable(org: Org):
    hotel = org.app.auth.create_hotel(
        org.admin,
        name="审核酒店",
        city="南京",
        address="审核路 1 号",
        phone="02580000011",
    )
    with pytest.raises(ValidationError):
        org.app.hotels.audit_hotel(org.admin, hotel.id, approve=False, note="")
    approved = org.app.hotels.audit_hotel(org.admin, hotel.id, approve=True)
    assert approved.audit_status is AuditStatus.APPROVED
    assert approved.business_status is BusinessStatus.OPEN
    assert approved.is_bookable() is True
    with pytest.raises(PermissionDenied):
        org.app.hotels.audit_hotel(org.manager_a, hotel.id, approve=True)


def test_critical_change_keeps_old_profile_until_approved(org: Org):
    original_name = org.hotel_a.name
    changed = org.app.hotels.submit_profile(
        org.manager_a,
        name="测试酒店 A（改）",
        city=org.hotel_a.city,
        address=org.hotel_a.address,
        phone=org.hotel_a.phone,
    )
    assert changed.pending_profile
    assert changed.name == original_name, "审核期间对外仍展示旧名称"
    assert changed.is_bookable() is True
    assert org.app.hotels.get_hotel(org.hotel_a.id).name == original_name

    approved = org.app.hotels.audit_hotel(org.admin, org.hotel_a.id, approve=True)
    assert approved.name == "测试酒店 A（改）"
    assert approved.pending_profile == ""
    assert approved.is_bookable() is True


def test_reject_change_keeps_old_profile(org: Org):
    org.app.hotels.submit_profile(
        org.manager_a,
        name="不会生效的名字",
        city=org.hotel_a.city,
        address=org.hotel_a.address,
        phone=org.hotel_a.phone,
    )
    rejected = org.app.hotels.audit_hotel(
        org.admin, org.hotel_a.id, approve=False, note="资料不完整"
    )
    assert rejected.name == "测试酒店 A"
    assert rejected.pending_profile == ""
    assert rejected.is_bookable() is True


def test_suspend_business_stops_search(org: Org):
    suspended = org.app.hotels.set_business_status(org.manager_a, open_=False)
    assert suspended.business_status is BusinessStatus.SUSPENDED
    today = org.clock.now().date()
    results = org.app.booking.search(
        city="南京",
        check_in=today,
        check_out=today + timedelta(days=1),
        guests=1,
    )
    assert all(item.hotel.id != org.hotel_a.id for item in results)
    reopened = org.app.hotels.set_business_status(org.manager_a, open_=True)
    assert reopened.business_status is BusinessStatus.OPEN
