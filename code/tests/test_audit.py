"""审计日志：字段、脱敏、事务回滚、导出与乐观锁。"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from qiju.application.audit_service import LogFilter
from qiju.application.base import mask_phone
from qiju.domain.enums import RejectReason
from qiju.domain.errors import PermissionDenied, StateConflict, ValidationError
from tests.factories import Org
from tests.helpers import book


def test_order_creation_writes_log_with_request_id(org: Org):
    order = book(org, org.customer, request_id="audit-key")
    logs = org.app.ctx.repos.logs.query(action="ORDER_CREATE")
    assert len(logs) == 1
    assert logs[0].object_id == order.id
    assert logs[0].request_id == "audit-key"
    assert logs[0].actor_id == org.customer.user.id
    assert logs[0].hotel_id == org.hotel_a.id


def test_log_masks_phone_in_reason(org: Org):
    order = book(org, org.customer)
    org.app.orders.reject(
        org.front_a,
        order.order_no,
        reason=RejectReason.OTHER,
        note="联系客人 13600000001 改期",
    )
    log = org.app.ctx.repos.logs.query(action="ORDER_REJECT")[0]
    assert "13600000001" not in log.reason
    assert "136****0001" in log.reason


def test_failed_operation_writes_no_log(org: Org):
    order = book(org, org.customer)
    before = len(org.app.ctx.repos.logs.all())
    with pytest.raises(ValidationError):
        org.app.orders.reject(
            org.front_a, order.order_no, reason=RejectReason.OTHER, note=""
        )
    assert len(org.app.ctx.repos.logs.all()) == before


def test_optimistic_lock_rejects_stale_write(org: Org):
    order = book(org, org.customer)
    repo = org.app.ctx.repos.orders
    first = repo.by_no(order.order_no)
    second = repo.by_no(order.order_no)
    repo.save(first)
    with pytest.raises(StateConflict):
        repo.save(second)


def test_manager_only_sees_own_hotel_logs(org: Org):
    book(org, org.customer)
    logs = org.app.audit.query(org.manager_a)
    assert logs
    assert all(log.hotel_id == org.hotel_a.id for log in logs)


def test_customer_cannot_read_logs(org: Org):
    with pytest.raises(PermissionDenied):
        org.app.audit.query(org.customer)


def test_export_csv_masks_and_writes_export_log(org: Org, tmp_path: Path):
    order = book(org, org.customer)
    org.app.orders.reject(
        org.front_a,
        order.order_no,
        reason=RejectReason.OTHER,
        note="电话 13600000001",
    )
    target = tmp_path / "logs.csv"
    count = org.app.audit.export_csv(org.manager_a, target)
    assert count > 0
    text = target.read_text(encoding="utf-8-sig")
    assert "13600000001" not in text
    assert "136****0001" in text
    with target.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0][0] == "日志ID"
    assert len(rows) == count + 1
    export_log = org.app.ctx.repos.logs.query(action="LOG_EXPORT")[0]
    assert "导出" in export_log.after_value


def test_log_filter_by_action(org: Org):
    order = book(org, org.customer)
    org.app.orders.reject(org.front_a, order.order_no, reason=RejectReason.SOLD_OUT)
    logs = org.app.audit.query(
        org.manager_a, LogFilter(action="ORDER_REJECT", object_id=order.id)
    )
    assert len(logs) == 1


def test_mask_phone_helper():
    assert mask_phone("张三 13600000001") == "张三 136****0001"
    assert mask_phone("订单 QJ1234") == "订单 QJ1234"
