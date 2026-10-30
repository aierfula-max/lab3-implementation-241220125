"""每日库存、价格与停售（REQ-006/023）。

一个容易忽略的细节：没有库存记录的日期并不是“不可订”，而是按房型
可售数与基准价可订（REQ-006）。所以店长维护库存、下单扣减之前，都要先
``ensure`` 一行。这一行由 ``(room_type_id, day)`` 主键兜底，并发插入
只会成功一次。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from ..domain.entities import DailyInventory, StopSaleRule, new_id
from ..domain.enums import AuditAction, Role
from ..domain.errors import Conflict, NotFound, ValidationError
from ..domain.validation import date_range
from .base import BaseService, Session


@dataclass(frozen=True, slots=True)
class CalendarRow:
    """房态日历的一行。"""

    room_type_name: str
    room_type_id: str
    day: date
    total_rooms: int
    sold_rooms: int
    remaining: int
    price_cents: int
    stop_sale: bool


class InventoryService(BaseService):
    """店长维护库存/价格/停售；前台只读。"""

    def _room_type_for(self, actor_hotel_id: str | None, room_type_id: str):
        room_type = self.repos.room_types.by_id(room_type_id)
        if room_type is None or room_type.hotel_id != actor_hotel_id:
            raise NotFound("房型不存在")
        return room_type

    def calendar(
        self, session: Session, *, start: date, end: date
    ) -> list[CalendarRow]:
        """房态日历：覆盖区间内每一天，没有记录的按默认值展示。"""
        actor = self.require_active(session)
        if actor.hotel_id is None:
            return []
        if end <= start:
            raise ValidationError("结束日期必须晚于开始日期")
        rows: list[CalendarRow] = []
        for room_type in self.repos.room_types.list_by_hotel(actor.hotel_id):
            existing = self.repos.inventory.list_range(room_type.id, start, end)
            for day in date_range(start, end):
                item = existing.get(day)
                total = item.total_rooms if item else room_type.total_rooms
                sold = item.sold_rooms if item else 0
                price = item.price_cents if item else room_type.base_price_cents
                stop = item.stop_sale if item else False
                rows.append(
                    CalendarRow(
                        room_type_name=room_type.name,
                        room_type_id=room_type.id,
                        day=day,
                        total_rooms=total,
                        sold_rooms=sold,
                        remaining=max(0, total - sold) if not stop else 0,
                        price_cents=price,
                        stop_sale=stop,
                    )
                )
        return rows

    def set_day(
        self,
        session: Session,
        *,
        room_type_id: str,
        day: date,
        total_rooms: int,
        price_cents: int,
        stop_sale: bool = False,
    ) -> DailyInventory:
        """单日维护。过去日期只读；可售数不能低于已售数。"""
        actor = self.require_active(session)
        self.require_role(actor, Role.MANAGER)
        room_type = self._room_type_for(actor.hotel_id, room_type_id)
        if day < self.clock.now().date():
            raise ValidationError("过去的日期只读")
        if total_rooms < 0:
            raise ValidationError("可售间数不能为负")
        if price_cents <= 0:
            raise ValidationError("单价必须大于 0")
        self.repos.inventory.ensure(
            room_type.id, day, room_type.total_rooms, room_type.base_price_cents
        )
        current = self.repos.inventory.get(room_type.id, day)
        assert current is not None
        if total_rooms < current.sold_rooms:
            raise Conflict(f"可售间数不能低于该日已售出的 {current.sold_rooms} 间")
        with self.db.transaction():
            current.total_rooms = total_rooms
            current.price_cents = price_cents
            current.stop_sale = stop_sale
            self.repos.inventory.save(current)
            self.write_log(
                user=actor,
                action=AuditAction.INVENTORY_UPDATE,
                object_type="DailyInventory",
                object_id=f"{room_type.id}:{day.isoformat()}",
                hotel_id=room_type.hotel_id,
                before=f"{current.sold_rooms} 已售",
                after=f"{total_rooms} 间，{price_cents} 分，停售={stop_sale}",
                reason="维护每日库存",
            )
        return current

    def batch_set(
        self,
        session: Session,
        *,
        room_type_id: str,
        start: date,
        end: date,
        total_rooms: int | None = None,
        price_cents: int | None = None,
        stop_sale: bool | None = None,
    ) -> dict[str, list[date]]:
        """按日期段批量设置；停售日期默认跳过（REQ-006）。"""
        actor = self.require_active(session)
        self.require_role(actor, Role.MANAGER)
        room_type = self._room_type_for(actor.hotel_id, room_type_id)
        if end < start:
            raise ValidationError("结束日期必须晚于开始日期")
        today = self.clock.now().date()
        applied: list[date] = []
        skipped: list[date] = []
        with self.db.transaction():
            for day in date_range(start, end + timedelta(days=1)):
                if day < today:
                    skipped.append(day)
                    continue
                self.repos.inventory.ensure(
                    room_type.id,
                    day,
                    room_type.total_rooms,
                    room_type.base_price_cents,
                )
                item = self.repos.inventory.get(room_type.id, day)
                assert item is not None
                if item.stop_sale and stop_sale is None:
                    skipped.append(day)
                    continue
                if total_rooms is not None:
                    if total_rooms < item.sold_rooms:
                        raise Conflict(
                            f"{day} 可售间数不能低于已售出的 {item.sold_rooms} 间"
                        )
                    item.total_rooms = total_rooms
                if price_cents is not None:
                    if price_cents <= 0:
                        raise ValidationError("单价必须大于 0")
                    item.price_cents = price_cents
                if stop_sale is not None:
                    item.stop_sale = stop_sale
                self.repos.inventory.save(item)
                applied.append(day)
            self.write_log(
                user=actor,
                action=AuditAction.INVENTORY_UPDATE,
                object_type="DailyInventory",
                object_id=f"{room_type.id}:{start.isoformat()}~{end.isoformat()}",
                hotel_id=room_type.hotel_id,
                after=f"应用到 {len(applied)} 天，跳过 {len(skipped)} 天",
                reason="批量维护库存",
            )
        return {"applied": applied, "skipped": skipped}

    def set_stop_sale(
        self,
        session: Session,
        *,
        room_type_id: str,
        start: date,
        end: date,
        stop: bool = True,
    ) -> int:
        """按日期段停售/撤销。停售保留库存与价格，不取消已确认订单。"""
        actor = self.require_active(session)
        self.require_role(actor, Role.MANAGER)
        room_type = self._room_type_for(actor.hotel_id, room_type_id)
        if end < start:
            raise ValidationError("结束日期必须晚于开始日期")
        if start < self.clock.now().date():
            raise ValidationError("过去的日期只允许查看，不能新增停售")
        affected = 0
        with self.db.transaction():
            if stop:
                self.repos.stop_sales.add(
                    StopSaleRule(
                        id=new_id(),
                        room_type_id=room_type.id,
                        start_date=start,
                        end_date=end,
                        created_by=actor.id,
                    )
                )
            for day in date_range(start, end + timedelta(days=1)):
                self.repos.inventory.ensure(
                    room_type.id,
                    day,
                    room_type.total_rooms,
                    room_type.base_price_cents,
                )
                self.repos.inventory.set_stop_sale(room_type.id, day, stop)
                affected += 1
            self.write_log(
                user=actor,
                action=AuditAction.STOP_SALE,
                object_type="StopSaleRule",
                object_id=f"{room_type.id}:{start.isoformat()}~{end.isoformat()}",
                hotel_id=room_type.hotel_id,
                after=f"{'停售' if stop else '恢复'} {affected} 天",
                reason="按日期停售" if stop else "撤销停售",
            )
        return affected
