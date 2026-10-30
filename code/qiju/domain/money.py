"""金额工具：全系统只用整数“分”（REQ-032/009）。

这条规则看起来啰嗦，但它是本项目里最便宜的正确性投资：
``0.1 + 0.2`` 的浮点误差一旦进入订单快照，退款对账就永远差一分钱。
所以这里只提供“分 -> 显示字符串”和“字符串 -> 分”两个方向，
任何业务代码都不允许出现 ``float``。
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

MAX_AMOUNT_CENTS = 99_999_999  # 999999.99 元，REQ-032 的边界用例


def yuan(cents: int) -> str:
    """把分格式化成两位小数的元，用于界面与日志。"""
    if not isinstance(cents, int):
        raise TypeError("金额必须是整数分")
    sign = "-" if cents < 0 else ""
    value = abs(cents)
    return f"{sign}{value // 100}.{value % 100:02d}"


def format_money(cents: int) -> str:
    """带人民币符号的展示格式。"""
    return f"¥{yuan(cents)}"


def parse_yuan(text: str) -> int:
    """把用户输入的元解析为分，拒绝负数与超过两位小数。

    用 ``Decimal`` 而不是 ``float``，并且显式乘 100 后取整，
    避免 ``19.99 * 100 == 1998.9999...`` 这类问题。
    """
    raw = text.strip().replace(",", "").replace("¥", "")
    if not raw:
        raise ValueError("金额不能为空")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"无法识别的金额：{text}") from exc
    if value < 0:
        raise ValueError("金额不能为负")
    if value.as_tuple().exponent < -2:
        raise ValueError("金额最多两位小数")
    cents = int(value * 100)
    if cents > MAX_AMOUNT_CENTS:
        raise ValueError("金额超出允许范围")
    return cents


def clamp_non_negative(cents: int) -> int:
    """退款计算中的兜底，避免出现负的应退金额。"""
    return max(0, cents)
