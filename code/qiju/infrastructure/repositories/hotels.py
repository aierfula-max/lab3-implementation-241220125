"""酒店、房型与确认时限仓储。"""

from __future__ import annotations

from datetime import date

from ...domain.clock import iso
from ...domain.entities import ConfirmPolicy, Hotel, RoomType, StopSaleRule
from ...domain.enums import AuditStatus, BusinessStatus
from ..db import Database
from ..mapping import hotel_from_row, policy_from_row, room_type_from_row


class HotelRepository:
    """``hotels`` 表。审核状态与营业状态分开更新。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, hotel: Hotel) -> None:
        self.db.execute(
            """
            INSERT INTO hotels
                (id, name, city, address, phone, business_status, audit_status,
                 audit_note, description, pending_profile, checkin_time,
                 checkout_time, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                hotel.id,
                hotel.name,
                hotel.city,
                hotel.address,
                hotel.phone,
                hotel.business_status.value,
                hotel.audit_status.value,
                hotel.audit_note,
                hotel.description,
                hotel.pending_profile,
                hotel.checkin_time,
                hotel.checkout_time,
                iso(hotel.created_at),
            ),
        )

    def by_id(self, hotel_id: str) -> Hotel | None:
        row = self.db.query_one("SELECT * FROM hotels WHERE id = ?", (hotel_id,))
        return hotel_from_row(row) if row else None

    def list_all(self) -> list[Hotel]:
        rows = self.db.query_all("SELECT * FROM hotels ORDER BY created_at")
        return [hotel_from_row(row) for row in rows]

    def list_by_audit(self, status: AuditStatus) -> list[Hotel]:
        rows = self.db.query_all(
            "SELECT * FROM hotels WHERE audit_status = ? ORDER BY created_at",
            (status.value,),
        )
        return [hotel_from_row(row) for row in rows]

    def update(self, hotel: Hotel) -> None:
        self.db.execute(
            """
            UPDATE hotels
               SET name = ?, city = ?, address = ?, phone = ?,
                   business_status = ?, audit_status = ?, audit_note = ?,
                   description = ?, pending_profile = ?, checkin_time = ?,
                   checkout_time = ?
             WHERE id = ?
            """,
            (
                hotel.name,
                hotel.city,
                hotel.address,
                hotel.phone,
                hotel.business_status.value,
                hotel.audit_status.value,
                hotel.audit_note,
                hotel.description,
                hotel.pending_profile,
                hotel.checkin_time,
                hotel.checkout_time,
                hotel.id,
            ),
        )

    def set_audit(self, hotel_id: str, status: AuditStatus, note: str) -> None:
        self.db.execute(
            "UPDATE hotels SET audit_status = ?, audit_note = ? WHERE id = ?",
            (status.value, note, hotel_id),
        )

    def set_business(self, hotel_id: str, status: BusinessStatus) -> None:
        self.db.execute(
            "UPDATE hotels SET business_status = ? WHERE id = ?",
            (status.value, hotel_id),
        )

    def search(self, city: str | None = None) -> list[Hotel]:
        if city:
            rows = self.db.query_all(
                """
                SELECT * FROM hotels
                 WHERE city = ? AND audit_status = ? AND business_status = ?
                 ORDER BY name
                """,
                (city, AuditStatus.APPROVED.value, BusinessStatus.OPEN.value),
            )
        else:
            rows = self.db.query_all(
                """
                SELECT * FROM hotels
                 WHERE audit_status = ? AND business_status = ?
                 ORDER BY name
                """,
                (AuditStatus.APPROVED.value, BusinessStatus.OPEN.value),
            )
        return [hotel_from_row(row) for row in rows]


class RoomTypeRepository:
    """``room_types`` 表。同一酒店内名称唯一。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, room_type: RoomType) -> None:
        self.db.execute(
            """
            INSERT INTO room_types
                (id, hotel_id, name, capacity, total_rooms, base_price_cents,
                 bed_type, area_m2, has_window, on_sale)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                room_type.id,
                room_type.hotel_id,
                room_type.name,
                room_type.capacity,
                room_type.total_rooms,
                room_type.base_price_cents,
                room_type.bed_type,
                room_type.area_m2,
                int(room_type.has_window),
                int(room_type.on_sale),
            ),
        )

    def by_id(self, room_type_id: str) -> RoomType | None:
        row = self.db.query_one(
            "SELECT * FROM room_types WHERE id = ?", (room_type_id,)
        )
        return room_type_from_row(row) if row else None

    def list_by_hotel(self, hotel_id: str) -> list[RoomType]:
        rows = self.db.query_all(
            "SELECT * FROM room_types WHERE hotel_id = ? ORDER BY name", (hotel_id,)
        )
        return [room_type_from_row(row) for row in rows]

    def list_on_sale(self, hotel_id: str) -> list[RoomType]:
        rows = self.db.query_all(
            """
            SELECT * FROM room_types
             WHERE hotel_id = ? AND on_sale = 1
             ORDER BY base_price_cents
            """,
            (hotel_id,),
        )
        return [room_type_from_row(row) for row in rows]

    def update(self, room_type: RoomType) -> None:
        self.db.execute(
            """
            UPDATE room_types
               SET name = ?, capacity = ?, total_rooms = ?, base_price_cents = ?,
                   bed_type = ?, area_m2 = ?, has_window = ?, on_sale = ?
             WHERE id = ?
            """,
            (
                room_type.name,
                room_type.capacity,
                room_type.total_rooms,
                room_type.base_price_cents,
                room_type.bed_type,
                room_type.area_m2,
                int(room_type.has_window),
                int(room_type.on_sale),
                room_type.id,
            ),
        )


class StopSaleRepository:
    """停售规则。停售保留库存与价格，只影响可订性。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, rule: StopSaleRule) -> None:
        self.db.execute(
            """
            INSERT INTO stop_sale_rules
                (id, room_type_id, start_date, end_date, created_by)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                rule.id,
                rule.room_type_id,
                rule.start_date.isoformat(),
                rule.end_date.isoformat(),
                rule.created_by,
            ),
        )

    def covers(self, room_type_id: str, day: date) -> bool:
        row = self.db.query_one(
            """
            SELECT 1 FROM stop_sale_rules
             WHERE room_type_id = ? AND start_date <= ? AND end_date >= ?
             LIMIT 1
            """,
            (room_type_id, day.isoformat(), day.isoformat()),
        )
        return row is not None

    def list_by_room_type(self, room_type_id: str) -> list[StopSaleRule]:
        rows = self.db.query_all(
            "SELECT * FROM stop_sale_rules WHERE room_type_id = ? ORDER BY start_date",
            (room_type_id,),
        )
        return [
            StopSaleRule(
                id=row["id"],
                room_type_id=row["room_type_id"],
                start_date=date.fromisoformat(row["start_date"]),
                end_date=date.fromisoformat(row["end_date"]),
                created_by=row["created_by"],
            )
            for row in rows
        ]


class PolicyRepository:
    """单店确认时限（REQ-010）。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, hotel_id: str) -> ConfirmPolicy:
        row = self.db.query_one(
            "SELECT * FROM confirm_policies WHERE hotel_id = ?", (hotel_id,)
        )
        if row is None:
            return ConfirmPolicy(hotel_id=hotel_id)
        return policy_from_row(row)

    def upsert(self, policy: ConfirmPolicy) -> None:
        self.db.execute(
            """
            INSERT INTO confirm_policies
                (hotel_id, timeout_minutes, updated_by, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(hotel_id) DO UPDATE SET
                timeout_minutes = excluded.timeout_minutes,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at
            """,
            (
                policy.hotel_id,
                policy.timeout_minutes,
                policy.updated_by,
                iso(policy.updated_at),
            ),
        )
