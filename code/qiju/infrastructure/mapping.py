"""sqlite3.Row 与领域对象的转换。

单独放一个文件，是为了让“SQL 里存什么格式”只在这里出现一次。
否则日期在 A 仓储是字符串、在 B 仓储是 date，迟早会出错。
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

from ..domain.clock import parse_date, parse_datetime
from ..domain.entities import (
    ConfirmPolicy,
    DailyInventory,
    Guest,
    Hotel,
    InvitationCode,
    Notification,
    OperationLog,
    Order,
    OrderChange,
    OrderNight,
    RefundRecord,
    RoomType,
    User,
)
from ..domain.enums import (
    AuditStatus,
    BusinessStatus,
    OrderStatus,
    RefundStatus,
    Role,
    UserStatus,
)


def dt(value: str | None) -> datetime | None:
    return None if value is None else parse_datetime(value)


def d(value: str) -> date:
    return parse_date(value)


def user_from_row(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        phone=row["phone"],
        password_hash=row["password_hash"],
        role=Role(row["role"]),
        display_name=row["display_name"],
        status=UserStatus(row["status"]),
        hotel_id=row["hotel_id"],
        created_at=dt(row["created_at"]),
    )


def hotel_from_row(row: sqlite3.Row) -> Hotel:
    return Hotel(
        id=row["id"],
        name=row["name"],
        city=row["city"],
        address=row["address"],
        phone=row["phone"],
        business_status=BusinessStatus(row["business_status"]),
        audit_status=AuditStatus(row["audit_status"]),
        audit_note=row["audit_note"],
        description=row["description"],
        pending_profile=row["pending_profile"],
        checkin_time=row["checkin_time"],
        checkout_time=row["checkout_time"],
        created_at=dt(row["created_at"]),
    )


def room_type_from_row(row: sqlite3.Row) -> RoomType:
    return RoomType(
        id=row["id"],
        hotel_id=row["hotel_id"],
        name=row["name"],
        capacity=row["capacity"],
        total_rooms=row["total_rooms"],
        base_price_cents=row["base_price_cents"],
        bed_type=row["bed_type"],
        area_m2=row["area_m2"],
        has_window=bool(row["has_window"]),
        on_sale=bool(row["on_sale"]),
    )


def inventory_from_row(row: sqlite3.Row) -> DailyInventory:
    return DailyInventory(
        room_type_id=row["room_type_id"],
        day=d(row["day"]),
        total_rooms=row["total_rooms"],
        sold_rooms=row["sold_rooms"],
        price_cents=row["price_cents"],
        stop_sale=bool(row["stop_sale"]),
    )


def invitation_from_row(row: sqlite3.Row) -> InvitationCode:
    return InvitationCode(
        code=row["code"],
        hotel_id=row["hotel_id"],
        created_by=row["created_by"],
        expires_at=parse_datetime(row["expires_at"]),
        used_by=row["used_by"],
        used_at=dt(row["used_at"]),
    )


def order_from_row(row: sqlite3.Row) -> Order:
    return Order(
        id=row["id"],
        order_no=row["order_no"],
        user_id=row["user_id"],
        hotel_id=row["hotel_id"],
        room_type_id=row["room_type_id"],
        check_in=d(row["check_in"]),
        check_out=d(row["check_out"]),
        room_count=row["room_count"],
        status=OrderStatus(row["status"]),
        total_cents=row["total_cents"],
        request_id=row["request_id"],
        policy_version=row["policy_version"],
        version=row["version"],
        created_at=dt(row["created_at"]),
        confirm_deadline=dt(row["confirm_deadline"]),
        confirmed_at=dt(row["confirmed_at"]),
        confirmed_by=row["confirmed_by"],
        checked_in_at=dt(row["checked_in_at"]),
        checked_in_by=row["checked_in_by"],
        checked_out_at=dt(row["checked_out_at"]),
        checked_out_by=row["checked_out_by"],
        actual_check_out=d(row["actual_check_out"]) if row["actual_check_out"] else None,
        canceled_at=dt(row["canceled_at"]),
        cancel_reason=row["cancel_reason"],
        rejected_at=dt(row["rejected_at"]),
        reject_reason=row["reject_reason"],
        reject_note=row["reject_note"],
        modified=bool(row["modified"]),
        early_checkout=bool(row["early_checkout"]),
    )


def night_from_row(row: sqlite3.Row) -> OrderNight:
    return OrderNight(
        day=d(row["day"]),
        price_cents=row["price_cents"],
        room_count=row["room_count"],
        subtotal_cents=row["subtotal_cents"],
    )


def guest_from_row(row: sqlite3.Row) -> Guest:
    return Guest(name=row["name"], phone=row["phone"])


def change_from_row(row: sqlite3.Row) -> OrderChange:
    return OrderChange(
        id=row["id"],
        order_id=row["order_id"],
        before_summary=row["before_summary"],
        after_summary=row["after_summary"],
        diff_cents=row["diff_cents"],
        operator_id=row["operator_id"],
        created_at=parse_datetime(row["created_at"]),
    )


def refund_from_row(row: sqlite3.Row) -> RefundRecord:
    return RefundRecord(
        id=row["id"],
        refund_no=row["refund_no"],
        order_id=row["order_id"],
        event_type=row["event_type"],
        refundable_cents=row["refundable_cents"],
        deducted_cents=row["deducted_cents"],
        status=RefundStatus(row["status"]),
        created_at=dt(row["created_at"]),
        marked_by=row["marked_by"],
        marked_at=dt(row["marked_at"]),
    )


def log_from_row(row: sqlite3.Row) -> OperationLog:
    return OperationLog(
        id=row["id"],
        actor_id=row["actor_id"],
        actor_role=row["actor_role"],
        hotel_id=row["hotel_id"],
        action=row["action"],
        object_type=row["object_type"],
        object_id=row["object_id"],
        before_value=row["before_value"],
        after_value=row["after_value"],
        reason=row["reason"],
        ip=row["ip"],
        request_id=row["request_id"],
        created_at=dt(row["created_at"]),
    )


def notification_from_row(row: sqlite3.Row) -> Notification:
    return Notification(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        body=row["body"],
        created_at=parse_datetime(row["created_at"]),
        read_at=dt(row["read_at"]),
    )


def policy_from_row(row: sqlite3.Row) -> ConfirmPolicy:
    return ConfirmPolicy(
        hotel_id=row["hotel_id"],
        timeout_minutes=row["timeout_minutes"],
        updated_by=row["updated_by"],
        updated_at=dt(row["updated_at"]),
    )
