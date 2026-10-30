"""领域实体。

一张类图落到代码时最容易走样的是“关系”：类图里 ``Order 1 *-- 1..* OrderNight``
在代码里如果变成 ``Order.nights`` 里塞字典，聚合边界就没了。这里保留
实验二的 12 个实体，并用 ``slots`` 的 dataclass 明确字段，仓储层负责装配。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import uuid4

from .enums import (
    AuditStatus,
    BusinessStatus,
    OrderStatus,
    RefundStatus,
    Role,
    UserStatus,
)


def new_id() -> str:
    """业务主键用 UUID4 十六进制串，避免自增 ID 暴露数据量。"""
    return uuid4().hex


@dataclass(slots=True)
class User:
    """账号。手机号唯一；工作人员绑定 ``hotel_id``。"""

    id: str
    phone: str
    password_hash: str
    role: Role
    display_name: str
    status: UserStatus = UserStatus.ACTIVE
    hotel_id: str | None = None
    created_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.status is UserStatus.ACTIVE


@dataclass(slots=True)
class InvitationCode:
    """店长邀请码（REQ-001）。生成时绑定酒店，一次性使用。"""

    code: str
    hotel_id: str
    created_by: str
    expires_at: datetime
    used_by: str | None = None
    used_at: datetime | None = None

    def is_valid(self, now: datetime) -> bool:
        return self.used_by is None and now < self.expires_at


@dataclass(slots=True)
class Hotel:
    """酒店。审核状态与营业状态分开，因为“审核中仍可接单”只针对变更审核。"""

    id: str
    name: str
    city: str
    address: str
    phone: str
    business_status: BusinessStatus = BusinessStatus.SUSPENDED
    audit_status: AuditStatus = AuditStatus.PENDING
    audit_note: str = ""
    description: str = ""
    pending_profile: str = ""
    checkin_time: str = "14:00"
    checkout_time: str = "12:00"
    created_at: datetime | None = None

    def is_bookable(self) -> bool:
        """只有审核通过且营业中的酒店可被下单。"""
        return (
            self.audit_status is AuditStatus.APPROVED
            and self.business_status is BusinessStatus.OPEN
        )


@dataclass(slots=True)
class RoomType:
    """房型。同一酒店内名称唯一；下架不影响历史订单。"""

    id: str
    hotel_id: str
    name: str
    capacity: int
    total_rooms: int
    base_price_cents: int
    bed_type: str = "大床"
    area_m2: int = 25
    has_window: bool = True
    on_sale: bool = True

    def available_rooms(self, sold: int) -> int:
        """剩余可售间数，不允许为负。"""
        return max(0, self.total_rooms - sold)


@dataclass(slots=True)
class DailyInventory:
    """``(房型, 日期)`` 维度的库存与价格。"""

    room_type_id: str
    day: date
    total_rooms: int
    sold_rooms: int
    price_cents: int
    stop_sale: bool = False

    @property
    def remaining(self) -> int:
        if self.stop_sale:
            return 0
        return max(0, self.total_rooms - self.sold_rooms)


@dataclass(slots=True)
class StopSaleRule:
    """按日期段停售（REQ-023），保留原库存与价格。"""

    id: str
    room_type_id: str
    start_date: date
    end_date: date
    created_by: str

    def covers(self, day: date) -> bool:
        return self.start_date <= day <= self.end_date


@dataclass(slots=True)
class OrderNight:
    """订单每晚明细。总价必须由它求和，不能存第二份真值。"""

    day: date
    price_cents: int
    room_count: int
    subtotal_cents: int


@dataclass(slots=True)
class Guest:
    """入住人。只存姓名与手机号（REQ-034 待确认前不存证件）。"""

    name: str
    phone: str

    @property
    def masked_phone(self) -> str:
        """列表与日志用脱敏手机号（REQ-021）。"""
        if len(self.phone) < 7:
            return self.phone
        return f"{self.phone[:3]}****{self.phone[-4:]}"


@dataclass(slots=True)
class OrderChange:
    """改单记录。只追加，不覆盖历史。"""

    id: str
    order_id: str
    before_summary: str
    after_summary: str
    diff_cents: int
    operator_id: str
    created_at: datetime


@dataclass(slots=True)
class RefundRecord:
    """退款记录。本期只记账，不调用任何支付渠道。"""

    id: str
    refund_no: str
    order_id: str
    event_type: str
    refundable_cents: int
    deducted_cents: int
    status: RefundStatus = RefundStatus.PENDING_OFFLINE
    created_at: datetime | None = None
    marked_by: str | None = None
    marked_at: datetime | None = None


@dataclass(slots=True)
class OperationLog:
    """操作日志。字段与 REQ-019 的 13 项一一对应。"""

    id: str
    actor_id: str | None
    actor_role: str
    hotel_id: str | None
    action: str
    object_type: str
    object_id: str
    before_value: str = ""
    after_value: str = ""
    reason: str = ""
    ip: str = "127.0.0.1"
    request_id: str = ""
    created_at: datetime | None = None


@dataclass(slots=True)
class Notification:
    """站内信。本期不接短信/邮件（REQ-033）。"""

    id: str
    user_id: str
    title: str
    body: str
    created_at: datetime
    read_at: datetime | None = None


@dataclass(slots=True)
class ConfirmPolicy:
    """单店确认时限。默认 30 分钟，范围 15–60（REQ-010）。"""

    hotel_id: str
    timeout_minutes: int = 30
    updated_by: str | None = None
    updated_at: datetime | None = None


@dataclass(slots=True)
class Order:
    """订单聚合根。

    ``version`` 是乐观锁：确认与超时任务同时提交时，后提交者拿到 0 行更新，
    返回 409（REQ-010/017）。
    """

    id: str
    order_no: str
    user_id: str
    hotel_id: str
    room_type_id: str
    check_in: date
    check_out: date
    room_count: int
    status: OrderStatus
    total_cents: int
    request_id: str
    policy_version: str = "policy_v1"
    version: int = 0
    created_at: datetime | None = None
    confirm_deadline: datetime | None = None
    confirmed_at: datetime | None = None
    confirmed_by: str | None = None
    checked_in_at: datetime | None = None
    checked_in_by: str | None = None
    checked_out_at: datetime | None = None
    checked_out_by: str | None = None
    actual_check_out: date | None = None
    canceled_at: datetime | None = None
    cancel_reason: str = ""
    rejected_at: datetime | None = None
    reject_reason: str = ""
    reject_note: str = ""
    modified: bool = False
    early_checkout: bool = False
    nights: list[OrderNight] = field(default_factory=list)
    guests: list[Guest] = field(default_factory=list)

    @property
    def stay_dates(self) -> list[date]:
        """入住日含、退房日不含（REQ-032 左闭右开）。"""
        return [self.check_in.fromordinal(o) for o in range(
            self.check_in.toordinal(), self.check_out.toordinal()
        )]

    @property
    def nights_count(self) -> int:
        return (self.check_out - self.check_in).days

    def first_night(self) -> OrderNight | None:
        return self.nights[0] if self.nights else None

    def night(self, day: date) -> OrderNight | None:
        for item in self.nights:
            if item.day == day:
                return item
        return None

    def night_total(self) -> int:
        return sum(item.subtotal_cents for item in self.nights)
