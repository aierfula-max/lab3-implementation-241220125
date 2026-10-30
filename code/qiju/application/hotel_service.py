"""酒店、房型、审核与确认时限（REQ-003/004/005/010）。

这里有一处实现比实验二的设计更细：**首次审核**与**上架后的关键资料变更
审核**不能共用同一个 ``audit_status``。如果变更审核时把酒店改回“待审核”，
``is_bookable()`` 会立刻变 False，已上架酒店就停单了，这与 REQ-003
“审核期间继续使用原资料对外展示并正常接单”冲突。所以酒店表多了一列
``pending_profile``：新资料先存这里，审核通过才覆盖旧值。
"""

from __future__ import annotations

import json
from datetime import date

from ..domain.entities import ConfirmPolicy, Hotel, RoomType, new_id
from ..domain.enums import AuditAction, AuditStatus, BusinessStatus, Role
from ..domain.errors import Conflict, NotFound, ValidationError
from ..domain.validation import (
    validate_contact_phone,
    validate_name,
    validate_timeout_minutes,
)
from .base import BaseService, Session


class HotelService(BaseService):
    """酒店资料、入驻审核、房型与确认时限。"""

    # ------------------------------------------------------------ 查询
    def get_hotel(self, hotel_id: str) -> Hotel | None:
        return self.repos.hotels.by_id(hotel_id)

    def list_hotels(self, session: Session) -> list[Hotel]:
        """管理员看全部；店长/前台只看本店。"""
        actor = self.require_active(session)
        if actor.role is Role.PLATFORM_ADMIN:
            return self.repos.hotels.list_all()
        if actor.hotel_id is None:
            return []
        hotel = self.repos.hotels.by_id(actor.hotel_id)
        return [hotel] if hotel else []

    def list_room_types(self, hotel_id: str) -> list[RoomType]:
        return self.repos.room_types.list_by_hotel(hotel_id)

    # ------------------------------------------------------------ 资料
    def submit_profile(
        self,
        session: Session,
        *,
        name: str,
        city: str,
        address: str,
        phone: str,
        description: str = "",
        checkin_time: str = "14:00",
        checkout_time: str = "12:00",
    ) -> Hotel:
        """店长填写/修改酒店资料。

        * 未通过首次审核：资料直接写入，状态置为待审核；
        * 已上架：名称/地址/电话属于关键资料，先存 ``pending_profile``，
          对外仍展示旧值，审核通过后切换。
        """
        actor = self.require_active(session)
        self.require_role(actor, Role.MANAGER)
        hotel = self.repos.hotels.by_id(actor.hotel_id or "")
        if hotel is None:
            raise NotFound("酒店不存在")
        data = {
            "name": validate_name(name, field="酒店名称"),
            "city": validate_name(city, field="城市"),
            "address": validate_name(address, field="地址"),
            "phone": validate_contact_phone(phone, field="联系电话"),
            "description": description.strip(),
            "checkin_time": checkin_time.strip() or "14:00",
            "checkout_time": checkout_time.strip() or "12:00",
        }
        critical_changed = any(
            data[key] != getattr(hotel, key) for key in ("name", "city", "address", "phone")
        )
        with self.db.transaction():
            if hotel.audit_status is AuditStatus.APPROVED and critical_changed:
                hotel.pending_profile = json.dumps(data, ensure_ascii=False)
                hotel.audit_note = "关键资料变更待审核，对外继续使用原资料"
            else:
                for key, value in data.items():
                    setattr(hotel, key, value)
                if hotel.audit_status is not AuditStatus.APPROVED:
                    hotel.audit_status = AuditStatus.PENDING
            self.repos.hotels.update(hotel)
            self.write_log(
                user=actor,
                action=AuditAction.HOTEL_UPDATE,
                object_type="Hotel",
                object_id=hotel.id,
                hotel_id=hotel.id,
                before=hotel.name,
                after=data["name"],
                reason="提交酒店资料" + ("（变更审核）" if hotel.pending_profile else ""),
            )
        return hotel

    def audit_hotel(
        self,
        session: Session,
        hotel_id: str,
        *,
        approve: bool,
        note: str = "",
    ) -> Hotel:
        """平台管理员审核。首次入驻与关键资料变更共用这个方法。"""
        actor = self.require_active(session)
        self.require_role(actor, Role.PLATFORM_ADMIN)
        hotel = self.repos.hotels.by_id(hotel_id)
        if hotel is None:
            raise NotFound("酒店不存在")
        if not approve and not note.strip():
            raise ValidationError("驳回必须填写原因")
        with self.db.transaction():
            if hotel.pending_profile:
                if approve:
                    for key, value in json.loads(hotel.pending_profile).items():
                        setattr(hotel, key, value)
                    hotel.audit_note = "关键资料变更审核通过"
                else:
                    hotel.audit_note = f"变更被驳回：{note.strip()}"
                hotel.pending_profile = ""
            else:
                hotel.audit_status = (
                    AuditStatus.APPROVED if approve else AuditStatus.REJECTED
                )
                hotel.audit_note = "" if approve else note.strip()
                if approve:
                    hotel.business_status = BusinessStatus.OPEN
            self.repos.hotels.update(hotel)
            self.write_log(
                user=actor,
                action=AuditAction.HOTEL_AUDIT,
                object_type="Hotel",
                object_id=hotel.id,
                hotel_id=hotel.id,
                before="待审核",
                after="通过" if approve else "驳回",
                reason=note.strip(),
            )
            manager = next(
                (
                    item
                    for item in self.repos.users.list_by_hotel(hotel.id)
                    if item.role is Role.MANAGER
                ),
                None,
            )
            if manager is not None:
                self.notify(
                    manager.id,
                    "入驻审核结果",
                    f"{hotel.name}：{'审核通过' if approve else '审核驳回'}"
                    + (f"（{note.strip()}）" if note.strip() else ""),
                )
        return hotel

    def set_business_status(self, session: Session, *, open_: bool) -> Hotel:
        """暂停/恢复营业。暂停只停新单，不自动取消已确认订单（REQ-004）。"""
        actor = self.require_active(session)
        self.require_role(actor, Role.MANAGER)
        hotel = self.repos.hotels.by_id(actor.hotel_id or "")
        if hotel is None:
            raise NotFound("酒店不存在")
        if hotel.audit_status is not AuditStatus.APPROVED:
            raise Conflict("酒店尚未通过审核")
        status = BusinessStatus.OPEN if open_ else BusinessStatus.SUSPENDED
        with self.db.transaction():
            hotel.business_status = status
            self.repos.hotels.update(hotel)
            self.write_log(
                user=actor,
                action=AuditAction.HOTEL_UPDATE,
                object_type="Hotel",
                object_id=hotel.id,
                hotel_id=hotel.id,
                before=f"营业状态 {status.value}",
                after=f"营业状态 {status.value}",
                reason="恢复营业" if open_ else "暂停营业",
            )
        return hotel

    # ------------------------------------------------------------ 房型
    def create_room_type(
        self,
        session: Session,
        *,
        name: str,
        capacity: int,
        total_rooms: int,
        base_price_cents: int,
        bed_type: str = "大床",
        area_m2: int = 25,
        has_window: bool = True,
    ) -> RoomType:
        actor = self.require_active(session)
        self.require_role(actor, Role.MANAGER)
        hotel = self.repos.hotels.by_id(actor.hotel_id or "")
        if hotel is None:
            raise NotFound("酒店不存在")
        if hotel.audit_status is not AuditStatus.APPROVED:
            raise Conflict("酒店通过审核后才能维护房型")
        self._validate_room_type(capacity, total_rooms, base_price_cents)
        name = validate_name(name, field="房型名称")
        existing = {item.name for item in self.repos.room_types.list_by_hotel(hotel.id)}
        if name in existing:
            raise Conflict("同一酒店内房型名称不能重复")
        room_type = RoomType(
            id=new_id(),
            hotel_id=hotel.id,
            name=name,
            capacity=capacity,
            total_rooms=total_rooms,
            base_price_cents=base_price_cents,
            bed_type=bed_type,
            area_m2=area_m2,
            has_window=has_window,
        )
        with self.db.transaction():
            self.repos.room_types.add(room_type)
            self.write_log(
                user=actor,
                action=AuditAction.ROOM_TYPE_CREATE,
                object_type="RoomType",
                object_id=room_type.id,
                hotel_id=hotel.id,
                after=f"{name}，{total_rooms} 间，{base_price_cents} 分",
                reason="新增房型",
            )
        return room_type

    def update_room_type(
        self,
        session: Session,
        room_type_id: str,
        *,
        name: str | None = None,
        capacity: int | None = None,
        total_rooms: int | None = None,
        base_price_cents: int | None = None,
        bed_type: str | None = None,
        area_m2: int | None = None,
        has_window: bool | None = None,
        on_sale: bool | None = None,
    ) -> RoomType:
        """修改房型。可售房间数不能低于未来已售出的最大间数（REQ-005）。"""
        actor = self.require_active(session)
        self.require_role(actor, Role.MANAGER)
        room_type = self.repos.room_types.by_id(room_type_id)
        if room_type is None or room_type.hotel_id != actor.hotel_id:
            raise NotFound("房型不存在")
        before = (
            f"{room_type.name}，{room_type.total_rooms} 间，"
            f"{room_type.base_price_cents} 分，上架={room_type.on_sale}"
        )
        target_total = room_type.total_rooms if total_rooms is None else total_rooms
        target_price = (
            room_type.base_price_cents
            if base_price_cents is None
            else base_price_cents
        )
        self._validate_room_type(
            room_type.capacity if capacity is None else capacity,
            target_total,
            target_price,
        )
        max_sold = self.repos.inventory.max_sold(room_type_id, date.today())
        if target_total < max_sold:
            raise Conflict(f"可售房间数不能低于未来已售出的 {max_sold} 间")
        with self.db.transaction():
            if name is not None and name != room_type.name:
                names = {
                    item.name
                    for item in self.repos.room_types.list_by_hotel(room_type.hotel_id)
                    if item.id != room_type.id
                }
                if name in names:
                    raise Conflict("同一酒店内房型名称不能重复")
                room_type.name = validate_name(name, field="房型名称")
            if capacity is not None:
                room_type.capacity = capacity
            if total_rooms is not None:
                room_type.total_rooms = total_rooms
            if base_price_cents is not None:
                room_type.base_price_cents = base_price_cents
            if bed_type is not None:
                room_type.bed_type = bed_type
            if area_m2 is not None:
                room_type.area_m2 = area_m2
            if has_window is not None:
                room_type.has_window = has_window
            if on_sale is not None:
                room_type.on_sale = on_sale
            self.repos.room_types.update(room_type)
            self.write_log(
                user=actor,
                action=AuditAction.ROOM_TYPE_UPDATE,
                object_type="RoomType",
                object_id=room_type.id,
                hotel_id=room_type.hotel_id,
                before=before,
                after=(
                    f"{room_type.name}，{room_type.total_rooms} 间，"
                    f"{room_type.base_price_cents} 分，上架={room_type.on_sale}"
                ),
                reason="修改房型",
            )
        return room_type

    @staticmethod
    def _validate_room_type(capacity: int, total_rooms: int, price_cents: int) -> None:
        if capacity < 1:
            raise ValidationError("最多入住人数必须大于等于 1")
        if total_rooms < 0:
            raise ValidationError("可售房间数不能为负")
        if price_cents <= 0:
            raise ValidationError("房型基准价必须大于 0")

    # ------------------------------------------------------------ 时限
    def get_policy(self, hotel_id: str) -> ConfirmPolicy:
        return self.repos.policies.get(hotel_id)

    def update_policy(self, session: Session, hotel_id: str, minutes: int) -> ConfirmPolicy:
        """确认时限只有平台管理员能改；店长只读（REQ-002/010）。"""
        actor = self.require_active(session)
        self.require_role(actor, Role.PLATFORM_ADMIN)
        minutes = validate_timeout_minutes(minutes)
        policy = ConfirmPolicy(
            hotel_id=hotel_id,
            timeout_minutes=minutes,
            updated_by=actor.id,
            updated_at=self.clock.now(),
        )
        with self.db.transaction():
            self.repos.policies.upsert(policy)
            self.write_log(
                user=actor,
                action=AuditAction.POLICY_UPDATE,
                object_type="ConfirmPolicy",
                object_id=hotel_id,
                hotel_id=hotel_id,
                after=f"{minutes} 分钟",
                reason="修改确认时限",
            )
        return policy
