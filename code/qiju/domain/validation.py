"""输入校验。

校验放在领域层而不是界面层，原因是“绕过查询页直接调下单接口”也要被拦
（REQ-008 的异常分支）。界面只负责把提示显示在哪里，不负责判断合不合法。
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from .errors import ValidationError

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
MAX_NIGHTS = 30
MAX_ROOM_COUNT = 20


def validate_phone(phone: str, *, field: str = "手机号") -> str:
    """中国大陆手机号：1 开头，第二位 3–9，共 11 位。"""
    value = (phone or "").strip()
    if not PHONE_RE.match(value):
        raise ValidationError(f"{field}格式不正确，应为 11 位手机号")
    return value


def validate_name(name: str, *, field: str = "姓名") -> str:
    """姓名只做长度与空白校验，不限制字符集。"""
    value = (name or "").strip()
    if not value:
        raise ValidationError(f"{field}不能为空")
    if len(value) > 20:
        raise ValidationError(f"{field}不能超过 20 个字符")
    return value


def validate_stay(
    check_in: date,
    check_out: date,
    today: date,
    *,
    max_nights: int = MAX_NIGHTS,
) -> int:
    """校验日期区间并返回晚数。入住日含、退房日不含。"""
    if check_out <= check_in:
        raise ValidationError("退房日期必须晚于入住日期")
    if check_in < today:
        raise ValidationError("入住日期不能早于今天")
    nights = (check_out - check_in).days
    if nights > max_nights:
        raise ValidationError(f"入住晚数不能超过 {max_nights} 晚")
    return nights


def validate_room_count(count: int) -> int:
    """间数 1–20，超过 20 间请走团队预订（本期不做）。"""
    if count < 1:
        raise ValidationError("间数必须大于等于 1")
    if count > MAX_ROOM_COUNT:
        raise ValidationError(f"单笔订单最多 {MAX_ROOM_COUNT} 间")
    return count


def validate_capacity(capacity: int, guests: int) -> None:
    """入住人数不能超过房型上限。"""
    if guests < 1:
        raise ValidationError("入住人数必须大于等于 1")
    if guests > capacity:
        raise ValidationError(f"该房型最多入住 {capacity} 人")


def validate_price_range(low: int | None, high: int | None) -> tuple[int, int]:
    """价格区间上下限颠倒时自动交换并提示（REQ-007）。"""
    lo = 0 if low is None else low
    hi = 10**9 if high is None else high
    if lo < 0 or hi < 0:
        raise ValidationError("价格区间不能为负")
    if lo > hi:
        return hi, lo
    return lo, hi


def date_range(start: date, end: date) -> list[date]:
    """左闭右开的日期列表。"""
    return [start + timedelta(days=offset) for offset in range((end - start).days)]


def validate_timeout_minutes(minutes: int) -> int:
    """确认时限只允许 15–60 分钟（REQ-010）。"""
    if not 15 <= minutes <= 60:
        raise ValidationError("确认时限必须在 15–60 分钟之间")
    return minutes
