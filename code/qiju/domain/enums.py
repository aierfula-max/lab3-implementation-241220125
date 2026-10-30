"""领域枚举。

对应实验二类图中的枚举类型（报告表 2-3）。所有枚举都继承 ``str``，
这样写进 SQLite 时就是可读的字符串，排查数据问题时不需要再查码表。
"""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """带 ``str`` 语义的枚举基类，便于直接落库与序列化。"""

    def __str__(self) -> str:  # pragma: no cover - 仅影响打印
        return str(self.value)


class Role(StrEnum):
    """账号角色（REQ-001/002）。"""

    CUSTOMER = "CUSTOMER"
    FRONT_DESK = "FRONT_DESK"
    MANAGER = "MANAGER"
    PLATFORM_ADMIN = "PLATFORM_ADMIN"
    SYSTEM = "SYSTEM"


class UserStatus(StrEnum):
    """账号状态。停用后已有会话立即失效。"""

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class AuditStatus(StrEnum):
    """酒店入驻审核状态（REQ-003）。"""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class BusinessStatus(StrEnum):
    """酒店营业状态（REQ-004）。暂停营业只停止接单。"""

    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"


class OrderStatus(StrEnum):
    """订单 7 状态（REQ-017 表 3）。"""

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    NO_SHOW = "NO_SHOW"

    @property
    def is_terminal(self) -> bool:
        """终态不可再迁移。"""
        return self in {
            OrderStatus.COMPLETED,
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
            OrderStatus.NO_SHOW,
        }


class RefundStatus(StrEnum):
    """退款状态。本期只记账，不接支付渠道（REQ-012/033）。"""

    PENDING_OFFLINE = "PENDING_OFFLINE"
    REFUNDED = "REFUNDED"


class RejectReason(StrEnum):
    """拒绝原因，只允许四选一（REQ-011）。"""

    SOLD_OUT = "无房"
    EQUIPMENT = "设备故障"
    PRICE_ERROR = "价格错误"
    OTHER = "其他"


class CancelReason(StrEnum):
    """取消原因。不同原因对应不同退款责任方。"""

    CUSTOMER = "顾客取消"
    TIMEOUT = "超时未确认"
    HOTEL_CLOSED = "酒店停业"
    ADMIN_FORCE = "平台强制取消"
    EARLY_CHECKOUT = "提前退房"
    MODIFY = "改单差额"


class RefundEvent(StrEnum):
    """退款事件的幂等键（REQ-028：同一事件只生成一条）。"""

    CANCEL = "CANCEL"
    REJECT = "REJECT"
    NO_SHOW = "NO_SHOW"
    EARLY_CHECKOUT = "EARLY_CHECKOUT"
    MODIFY = "MODIFY"
    ADMIN_FORCE = "ADMIN_FORCE"
    HOTEL_CLOSED = "HOTEL_CLOSED"


class AuditAction(StrEnum):
    """写操作日志的动作名（REQ-019）。"""

    LOGIN = "LOGIN"
    USER_CREATE = "USER_CREATE"
    HOTEL_SUBMIT = "HOTEL_SUBMIT"
    HOTEL_AUDIT = "HOTEL_AUDIT"
    HOTEL_UPDATE = "HOTEL_UPDATE"
    ROOM_TYPE_CREATE = "ROOM_TYPE_CREATE"
    ROOM_TYPE_UPDATE = "ROOM_TYPE_UPDATE"
    INVENTORY_UPDATE = "INVENTORY_UPDATE"
    STOP_SALE = "STOP_SALE"
    ORDER_CREATE = "ORDER_CREATE"
    ORDER_CONFIRM = "ORDER_CONFIRM"
    ORDER_REJECT = "ORDER_REJECT"
    ORDER_CANCEL = "ORDER_CANCEL"
    ORDER_MODIFY = "ORDER_MODIFY"
    ORDER_CHECK_IN = "ORDER_CHECK_IN"
    ORDER_CHECK_OUT = "ORDER_CHECK_OUT"
    ORDER_NO_SHOW = "ORDER_NO_SHOW"
    ORDER_FORCE_CANCEL = "ORDER_FORCE_CANCEL"
    REFUND_MARK = "REFUND_MARK"
    POLICY_UPDATE = "POLICY_UPDATE"
    LOG_EXPORT = "LOG_EXPORT"
