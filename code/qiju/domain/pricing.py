"""定价与每晚明细（REQ-006/009/032）。

价格快照的原则：**订单总价是明细的和，明细是唯一真值**。
下单时把每一晚的单价、间数、小计写进 ``order_nights``，之后店长改价、
改房型基准价，都不会影响已创建的订单。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date

from .entities import OrderNight
from .errors import ValidationError


def build_nights(
    days: Iterable[date],
    price_by_day: Mapping[date, int],
    room_count: int,
) -> list[OrderNight]:
    """按日期顺序生成每晚明细。

    缺少某天的价格时直接报错，而不是悄悄取基准价：能走到这一步说明
    库存/价格装配已经出错，静默兜底会把错误藏进订单快照里。
    """
    if room_count < 1:
        raise ValidationError("间数必须大于等于 1")
    nights: list[OrderNight] = []
    for day in days:
        if day not in price_by_day:
            raise ValidationError(f"{day} 缺少价格")
        price = price_by_day[day]
        if price <= 0:
            raise ValidationError(f"{day} 的价格必须大于 0")
        nights.append(
            OrderNight(
                day=day,
                price_cents=price,
                room_count=room_count,
                subtotal_cents=price * room_count,
            )
        )
    return nights


def total_of(nights: Iterable[OrderNight]) -> int:
    """订单总价 = 每晚小计之和。"""
    return sum(item.subtotal_cents for item in nights)


def diff_of(old: Iterable[OrderNight], new: Iterable[OrderNight]) -> int:
    """改单差价：新总价 - 旧总价。"""
    return total_of(new) - total_of(old)


def release_amount(nights: Iterable[OrderNight], start: date) -> int:
    """释放 ``start`` 及之后（原退房日前）的未住间夜金额。

    用于提前退房：10/1 入住、10/4 退房，10/2 退房时只释放 10/2、10/3。
    """
    return sum(
        item.subtotal_cents for item in nights if item.day >= start
    )


def charge_first_night(nights: Iterable[OrderNight]) -> int:
    """首晚房费（18:00 后取消、未入住关闭的扣费口径）。"""
    for item in nights:
        return item.subtotal_cents
    return 0
