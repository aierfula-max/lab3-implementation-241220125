"""领域异常。

异常分层的目的不是“报错好看”，而是让上层能把“该给用户看什么”与
“该记什么日志”分开：``code`` 决定界面提示，``http_status`` 只用于
CLI/接口演示，桌面端不直接暴露 HTTP 概念。

错误码与实验二报告 2.2 节的 403/404/409 约定保持一致。
"""

from __future__ import annotations


class DomainError(Exception):
    """所有业务异常的基类。"""

    code = "DOMAIN_ERROR"
    http_status = 400

    def __init__(self, message: str, *, detail: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class ValidationError(DomainError):
    """参数或业务前置条件不成立。"""

    code = "VALIDATION_ERROR"
    http_status = 400


class Unauthenticated(DomainError):
    """未登录或会话失效。"""

    code = "UNAUTHENTICATED"
    http_status = 401


class PermissionDenied(DomainError):
    """越权写操作，返回 403 并记安全日志。"""

    code = "PERMISSION_DENIED"
    http_status = 403


class NotFound(DomainError):
    """资源不存在，或跨数据范围访问（统一 404，不泄露存在性）。"""

    code = "NOT_FOUND"
    http_status = 404


class Conflict(DomainError):
    """状态冲突、并发冲突、唯一约束冲突。"""

    code = "CONFLICT"
    http_status = 409


class SoldOut(Conflict):
    """任一晚库存不足，整单失败。"""

    code = "SOLD_OUT"


class StopSale(Conflict):
    """所选日期已停售。"""

    code = "STOP_SALE"


class DuplicateOrder(Conflict):
    """2 分钟内内容相同的订单，需要顾客二次确认。"""

    code = "DUPLICATE_ORDER"

    def __init__(self, message: str, *, existing_order_no: str) -> None:
        super().__init__(message, detail={"existing_order_no": existing_order_no})


class StateConflict(Conflict):
    """非法状态转换，或并发下状态已被他人改变。"""

    code = "STATE_CONFLICT"


class PaymentNotSupported(DomainError):
    """本期不接在线支付（REQ-014/033）。"""

    code = "PAYMENT_NOT_SUPPORTED"
    http_status = 400
