"""时钟抽象。

业务规则里到处是“现在几点”——18:00 取消、30 分钟确认超时、
入住日 24:00 未入住。如果直接调 ``datetime.now()``，这些规则只能靠
真人熬夜等时间，没法写单元测试。所以统一走 ``Clock``：

* ``SystemClock`` 用酒店当地时区（Asia/Shanghai，REQ-032）；
* ``FixedClock`` 在测试里把时间钉在 17:59:59 / 18:00:00 / 18:00:01。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

HOTEL_TZ = ZoneInfo("Asia/Shanghai")


class Clock(Protocol):
    """只需要一个 ``now`` 方法。"""

    def now(self) -> datetime:
        """返回带时区的当前时间。"""


class SystemClock:
    """生产/演示用时钟。"""

    def now(self) -> datetime:
        return datetime.now(tz=HOTEL_TZ)


class FixedClock:
    """可手动推进的测试时钟。"""

    def __init__(self, moment: datetime) -> None:
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=HOTEL_TZ)
        self._moment = moment.astimezone(HOTEL_TZ)

    def now(self) -> datetime:
        return self._moment

    def set(self, moment: datetime) -> None:
        self._moment = moment.astimezone(HOTEL_TZ)

    def advance(self, **kwargs: float) -> None:
        self._moment = self._moment + timedelta(**kwargs)


def to_hotel_time(moment: datetime) -> datetime:
    """统一转成酒店时区；天真的时间按酒店时区解释。"""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=HOTEL_TZ)
    return moment.astimezone(HOTEL_TZ)


def parse_date(text: str) -> date:
    """解析 ``YYYY-MM-DD``。"""
    return datetime.strptime(text, "%Y-%m-%d").date()


def parse_datetime(text: str) -> datetime:
    """解析 ISO 时间并转成酒店时区。"""
    return to_hotel_time(datetime.fromisoformat(text))


def iso(moment: datetime | None) -> str | None:
    """落库用的 ISO 字符串；None 原样返回。"""
    return None if moment is None else to_hotel_time(moment).isoformat()


def utc_now_stamp() -> str:
    """给日志/导出用的 UTC 时间戳。"""
    return datetime.now(tz=UTC).isoformat()
