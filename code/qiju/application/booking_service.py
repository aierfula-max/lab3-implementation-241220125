"""查询与下单（REQ-007/008/009/024/029）。

这是整个系统最核心的一段代码。下单事务里做四件事，顺序不能换：

1. 幂等：``(user_id, request_id)`` 命中就直接返回原订单；
2. 重复内容检测：2 分钟内同房型同日期的单，要求顾客二次确认；
3. 逐晚 ``ensure`` + ``hold``，任一晚失败整单回滚；
4. 写订单、每晚明细、入住人、操作日志。

第 3 步的 ``hold`` 是带条件的 UPDATE，不是“先查后扣”。这是 REQ-029
唯一认可的做法，也是我在实现阶段改得最多的一处。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

from ..domain.entities import Guest, Hotel, Order, OrderNight, RoomType, new_id
from ..domain.enums import AuditAction, OrderStatus, Role
from ..domain.errors import (
    Conflict,
    DuplicateOrder,
    NotFound,
    SoldOut,
    StopSale,
    ValidationError,
)
from ..domain.pricing import build_nights, total_of
from ..domain.validation import (
    date_range,
    validate_capacity,
    validate_name,
    validate_phone,
    validate_price_range,
    validate_room_count,
    validate_stay,
)
from .base import BaseService, Session


@dataclass(frozen=True, slots=True)
class SearchResult:
    """一条可订房型结果。价格与库存都按“当前查询日期区间”计算。"""

    hotel: Hotel
    room_type: RoomType
    nights: list[tuple[date, int]]
    total_cents: int
    remaining: int
    stop_sale: bool = False
    price_cents: int = 0


@dataclass(slots=True)
class BookingRequest:
    """下单请求。``request_id`` 由客户端生成（REQ-024）。"""

    room_type_id: str
    check_in: date
    check_out: date
    room_count: int
    guests: list[Guest]
    request_id: str
    confirm_duplicate: bool = False


@dataclass(slots=True)
class Quote:
    """下单调价结果，界面在提交前展示。"""

    room_type: RoomType
    nights: list[OrderNight]
    total_cents: int
    nights_count: int


class BookingService(BaseService):
    """可订查询、报价与创建订单。"""

    # ------------------------------------------------------------ 查询
    def search(
        self,
        *,
        city: str | None = None,
        check_in: date,
        check_out: date,
        guests: int = 1,
        price_min: int | None = None,
        price_max: int | None = None,
        sort: str = "available",
    ) -> list[SearchResult]:
        """多条件可订查询。无需登录（REQ-007）。"""
        today = self.clock.now().date()
        validate_stay(check_in, check_out, today)
        if guests < 1:
            raise ValidationError("入住人数必须大于等于 1")
        low, high = validate_price_range(price_min, price_max)
        results: list[SearchResult] = []
        for hotel in self.repos.hotels.search(city or None):
            for room_type in self.repos.room_types.list_on_sale(hotel.id):
                if room_type.capacity < guests:
                    continue
                availability = self._availability(room_type, check_in, check_out)
                if availability is None:
                    continue
                nights, remaining = availability
                total = sum(price for _, price in nights)
                if not low <= total <= high:
                    continue
                results.append(
                    SearchResult(
                        hotel=hotel,
                        room_type=room_type,
                        nights=nights,
                        total_cents=total,
                        remaining=remaining,
                        price_cents=nights[0][1] if nights else 0,
                    )
                )
        if sort == "price_asc":
            results.sort(key=lambda item: item.total_cents)
        elif sort == "price_desc":
            results.sort(key=lambda item: -item.total_cents)
        else:
            results.sort(
                key=lambda item: (item.remaining == 0, item.total_cents)
            )
        return results

    def _availability(
        self, room_type: RoomType, check_in: date, check_out: date
    ) -> tuple[list[tuple[date, int]], int] | None:
        """返回 (每晚价格, 最少剩余)；停售或任一晚售罄则返回 None。

        停售结果不返回，而不是返回一条 ``stop_sale=True`` 的“不可订结果”：
        REQ-007 要求结果里每一天都可订，把不可订项混进列表会让界面
        不得不再过滤一次，容易漏。
        """
        existing = self.repos.inventory.list_range(room_type.id, check_in, check_out)
        nights: list[tuple[date, int]] = []
        remaining = 10**9
        for day in date_range(check_in, check_out):
            item = existing.get(day)
            if item is not None and item.stop_sale:
                return None
            price = item.price_cents if item else room_type.base_price_cents
            total_rooms = item.total_rooms if item else room_type.total_rooms
            sold = item.sold_rooms if item else 0
            remaining = min(remaining, max(0, total_rooms - sold))
            nights.append((day, price))
        if remaining <= 0:
            return None
        return nights, remaining

    def quote(
        self,
        *,
        room_type_id: str,
        check_in: date,
        check_out: date,
        room_count: int,
        guests: int = 1,
    ) -> Quote:
        """报价：不写库，只按当前价格算一遍。"""
        room_type = self.repos.room_types.by_id(room_type_id)
        if room_type is None:
            raise NotFound("房型不存在")
        validate_room_count(room_count)
        validate_capacity(room_type.capacity * room_count, guests)
        validate_stay(check_in, check_out, self.clock.now().date())
        existing = self.repos.inventory.list_range(room_type.id, check_in, check_out)
        prices: dict[date, int] = {}
        for day in date_range(check_in, check_out):
            item = existing.get(day)
            prices[day] = item.price_cents if item else room_type.base_price_cents
        nights = build_nights(date_range(check_in, check_out), prices, room_count)
        return Quote(
            room_type=room_type,
            nights=nights,
            total_cents=total_of(nights),
            nights_count=len(nights),
        )

    # ------------------------------------------------------------ 下单
    def create_order(self, session: Session, request: BookingRequest) -> Order:
        """提交预订。幂等、重复确认、逐晚扣减都在一个事务里。"""
        user = self.require_active(session)
        self.require_role(user, Role.CUSTOMER)
        if not request.request_id.strip():
            raise ValidationError("缺少 request_id")
        room_count = validate_room_count(request.room_count)
        if not request.guests:
            raise ValidationError("请填写入住人")
        for guest in request.guests:
            validate_name(guest.name, field="入住人姓名")
            validate_phone(guest.phone, field="入住人手机号")
        today = self.clock.now().date()
        validate_stay(request.check_in, request.check_out, today)
        room_type = self.repos.room_types.by_id(request.room_type_id)
        if room_type is None or not room_type.on_sale:
            raise NotFound("房型不存在或已下架")
        hotel = self.repos.hotels.by_id(room_type.hotel_id)
        if hotel is None or not hotel.is_bookable():
            raise Conflict("酒店暂停营业或未通过审核")
        validate_capacity(room_type.capacity * room_count, len(request.guests))

        # 幂等：同一 (user, request_id) 直接返回原订单
        existing = self.repos.orders.by_request(user.id, request.request_id)
        if existing is not None:
            return existing

        # 2 分钟内相同内容：要求二次确认（REQ-024）
        if not request.confirm_duplicate:
            since = self.clock.now() - timedelta(minutes=2)
            for candidate in self.repos.orders.duplicate_candidates(
                user_id=user.id,
                hotel_id=hotel.id,
                room_type_id=room_type.id,
                check_in=request.check_in,
                check_out=request.check_out,
                room_count=room_count,
                since=since,
            ):
                if self._same_guests(candidate.guests, request.guests):
                    raise DuplicateOrder(
                        "2 分钟内已有相同订单，请确认是否重复提交",
                        existing_order_no=candidate.order_no,
                    )

        policy = self.repos.policies.get(hotel.id)
        created_at = self.clock.now()
        confirm_deadline = created_at + timedelta(minutes=policy.timeout_minutes)
        with self.db.transaction():
            # 事务内再查一次幂等，挡住并发重放
            existing = self.repos.orders.by_request(user.id, request.request_id)
            if existing is not None:
                return existing
            prices: dict[date, int] = {}
            for day in date_range(request.check_in, request.check_out):
                self.repos.inventory.ensure(
                    room_type.id, day, room_type.total_rooms, room_type.base_price_cents
                )
                item = self.repos.inventory.get(room_type.id, day)
                assert item is not None
                if item.stop_sale:
                    raise StopSale(f"{day} 该房型已停售")
                if not self.repos.inventory.hold(room_type.id, day, room_count):
                    raise SoldOut(
                        f"{day} 库存不足，整单未创建",
                        detail={"date": day.isoformat()},
                    )
                prices[day] = item.price_cents
            nights = build_nights(
                date_range(request.check_in, request.check_out), prices, room_count
            )
            order = Order(
                id=new_id(),
                order_no=self._next_order_no(),
                user_id=user.id,
                hotel_id=hotel.id,
                room_type_id=room_type.id,
                check_in=request.check_in,
                check_out=request.check_out,
                room_count=room_count,
                status=OrderStatus.PENDING,
                total_cents=total_of(nights),
                request_id=request.request_id,
                created_at=created_at,
                confirm_deadline=confirm_deadline,
                nights=nights,
                guests=list(request.guests),
            )
            self.repos.orders.add(order)
            self.write_log(
                user=user,
                action=AuditAction.ORDER_CREATE,
                object_type="Order",
                object_id=order.id,
                hotel_id=hotel.id,
                after=(
                    f"{order.order_no}，{room_count} 间，{order.total_cents} 分，"
                    f"确认截止 {confirm_deadline.isoformat()}"
                ),
                request_id=request.request_id,
                moment=order.created_at,
            )
        return order

    @staticmethod
    def _same_guests(left: list[Guest], right: list[Guest]) -> bool:
        return {(g.name, g.phone) for g in left} == {(g.name, g.phone) for g in right}

    def _next_order_no(self) -> str:
        """订单号：QJ + 日期 + 6 位随机数，唯一性由数据库兜底。"""
        stamp = self.clock.now().strftime("%Y%m%d")
        for _ in range(20):
            candidate = f"QJ{stamp}{random.randint(0, 999999):06d}"
            if self.repos.orders.by_no(candidate) is None:
                return candidate
        raise Conflict("订单号生成失败，请重试")
