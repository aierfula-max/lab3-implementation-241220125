"""账号与邀请码仓储。"""

from __future__ import annotations

from datetime import datetime

from ...domain.clock import iso
from ...domain.entities import InvitationCode, User
from ...domain.enums import UserStatus
from ..db import Database
from ..mapping import invitation_from_row, user_from_row


class UserRepository:
    """``users`` 表。手机号唯一，由数据库兜底。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, user: User) -> None:
        self.db.execute(
            """
            INSERT INTO users
                (id, phone, password_hash, role, display_name, status, hotel_id,
                 created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user.id,
                user.phone,
                user.password_hash,
                user.role.value,
                user.display_name,
                user.status.value,
                user.hotel_id,
                iso(user.created_at),
            ),
        )

    def by_phone(self, phone: str) -> User | None:
        row = self.db.query_one("SELECT * FROM users WHERE phone = ?", (phone,))
        return user_from_row(row) if row else None

    def by_id(self, user_id: str) -> User | None:
        row = self.db.query_one("SELECT * FROM users WHERE id = ?", (user_id,))
        return user_from_row(row) if row else None

    def list_by_hotel(self, hotel_id: str) -> list[User]:
        rows = self.db.query_all(
            "SELECT * FROM users WHERE hotel_id = ? ORDER BY created_at",
            (hotel_id,),
        )
        return [user_from_row(row) for row in rows]

    def set_status(self, user_id: str, status: UserStatus) -> None:
        self.db.execute(
            "UPDATE users SET status = ? WHERE id = ?", (status.value, user_id)
        )


class InvitationRepository:
    """邀请码。一次性使用，过期时间写入库。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, code: InvitationCode) -> None:
        self.db.execute(
            """
            INSERT INTO invitation_codes
                (code, hotel_id, created_by, expires_at, used_by, used_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                code.code,
                code.hotel_id,
                code.created_by,
                iso(code.expires_at),
                code.used_by,
                iso(code.used_at),
            ),
        )

    def by_code(self, code: str) -> InvitationCode | None:
        row = self.db.query_one(
            "SELECT * FROM invitation_codes WHERE code = ?", (code,)
        )
        return invitation_from_row(row) if row else None

    def mark_used(self, code: str, user_id: str, moment: datetime) -> None:
        self.db.execute(
            """
            UPDATE invitation_codes
               SET used_by = ?, used_at = ?
             WHERE code = ? AND used_by IS NULL
            """,
            (user_id, iso(moment), code),
        )
