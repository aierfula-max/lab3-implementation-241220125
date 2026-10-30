"""取消、未入住与提前退房的退款口径（REQ-012/016/025）。

这块规则最容易被“想当然”写错，所以单独成模块，并且只用纯函数：
输入订单、当前时间、原因，输出 ``扣费 / 应退``。服务层拿到结果后只负责
释放库存、写退款记录，不再自己算钱。

三条口径先写在这里，避免以后改代码时忘了当初为什么这么定：

1. 顾客取消：入住当天 18:00:00 及之前免费；18:00:01 起收首晚房费。
   早于入住日的取消一律免费。
2. 未入住关闭：首晚照收，其余晚全额可退；库存只释放入住日之后。
3. 提前退房：按实际入住晚数结算，释放退房日当晚起至原退房日前一晚。
   10/1 入住、10/4 退房、10/2 退房 → 释放 10/2、10/3，10/1 照收。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from .clock import HOTEL_TZ, to_hotel_time
from .entities import Order
from .enums import CancelReason, RefundEvent
from .errors import StateConflict
from .pricing import charge_first_night, release_amount


@dataclass(frozen=True, slots=True)
class RefundQuote:
    """一次退款事件的计算结果。"""

    event: RefundEvent
    deducted_cents: int
    refundable_cents: int
    note: str


def free_cancel_deadline(check_in: date) -> datetime:
    """入住日 18:00:00（酒店当地时区）。"""
    return datetime.combine(check_in, time(18, 0, 0), tzinfo=HOTEL_TZ)


def cancel_quote(order: Order, now: datetime, reason: CancelReason) -> RefundQuote:
    """计算取消订单的扣费与应退金额。"""
    moment = to_hotel_time(now)
    total = order.total_cents
    if reason is CancelReason.CUSTOMER:
        if moment.date() > order.check_in:
            raise StateConflict("已过入住日，不能按顾客取消处理")
        if moment <= free_cancel_deadline(order.check_in):
            return RefundQuote(RefundEvent.CANCEL, 0, total, "18:00 前免费取消")
        deduction = charge_first_night(order.nights)
        return RefundQuote(
            RefundEvent.CANCEL,
            deduction,
            max(0, total - deduction),
            "18:00 后取消，收取首晚房费",
        )
    if reason is CancelReason.TIMEOUT:
        return RefundQuote(RefundEvent.CANCEL, 0, total, "超时未确认，全额可退")
    if reason is CancelReason.HOTEL_CLOSED:
        return RefundQuote(
            RefundEvent.HOTEL_CLOSED, 0, total, "酒店停业取消，全额可退"
        )
    if reason is CancelReason.ADMIN_FORCE:
        return RefundQuote(
            RefundEvent.ADMIN_FORCE, 0, total, "平台强制取消，全额可退"
        )
    return RefundQuote(RefundEvent.CANCEL, 0, total, "取消")


def reject_quote(order: Order) -> RefundQuote:
    """酒店拒绝订单：全额可退（REQ-011）。"""
    return RefundQuote(RefundEvent.REJECT, 0, order.total_cents, "酒店拒绝，全额可退")


def no_show_quote(order: Order) -> RefundQuote:
    """未入住关闭：首晚照收，其余可退（REQ-025）。"""
    deduction = charge_first_night(order.nights)
    return RefundQuote(
        RefundEvent.NO_SHOW,
        deduction,
        max(0, order.total_cents - deduction),
        "未入住，首晚房费不退",
    )


def early_checkout_quote(order: Order, actual_check_out: date) -> RefundQuote:
    """提前退房：只退未住的间夜（REQ-016）。"""
    if actual_check_out <= order.check_in:
        raise StateConflict("退房日必须晚于入住日")
    if actual_check_out >= order.check_out:
        return RefundQuote(RefundEvent.EARLY_CHECKOUT, 0, 0, "正常退房，不释放库存")
    refundable = release_amount(order.nights, actual_check_out)
    return RefundQuote(
        RefundEvent.EARLY_CHECKOUT,
        0,
        refundable,
        f"提前退房，释放 {actual_check_out} 起未住间夜",
    )
