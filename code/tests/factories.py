"""测试用的最小组织：两家酒店、三个房型、五个账号。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

from qiju.application import Application, Session, build
from qiju.domain.clock import HOTEL_TZ, FixedClock
from qiju.domain.entities import Hotel, RoomType, User, new_id
from qiju.domain.enums import AuditStatus, BusinessStatus, Role
from qiju.infrastructure.security import hash_password

NOW = datetime(2026, 10, 30, 10, 0, tzinfo=HOTEL_TZ)
PASSWORD = "Test@2026"


@lru_cache(maxsize=8)
def _hash(password: str) -> str:
    return hash_password(password)


@dataclass(slots=True)
class Org:
    app: Application
    clock: FixedClock
    hotel_a: Hotel
    hotel_b: Hotel
    king: RoomType
    twin: RoomType
    suite: RoomType
    admin: Session
    manager_a: Session
    front_a: Session
    manager_b: Session
    customer: Session
    customer2: Session


def make_org() -> Org:
    clock = FixedClock(NOW)
    app = build(":memory:", clock)
    repos = app.ctx.repos
    hotel_a = Hotel(
        id=new_id(),
        name="测试酒店 A",
        city="南京",
        address="测试路 1 号",
        phone="02580000001",
        business_status=BusinessStatus.OPEN,
        audit_status=AuditStatus.APPROVED,
        created_at=NOW,
    )
    hotel_b = Hotel(
        id=new_id(),
        name="测试酒店 B",
        city="苏州",
        address="测试路 2 号",
        phone="05120000002",
        business_status=BusinessStatus.OPEN,
        audit_status=AuditStatus.APPROVED,
        created_at=NOW,
    )
    repos.hotels.add(hotel_a)
    repos.hotels.add(hotel_b)

    king = RoomType(
        id=new_id(),
        hotel_id=hotel_a.id,
        name="大床房",
        capacity=2,
        total_rooms=10,
        base_price_cents=30000,
    )
    twin = RoomType(
        id=new_id(),
        hotel_id=hotel_a.id,
        name="双床房",
        capacity=2,
        total_rooms=2,
        base_price_cents=20000,
    )
    suite = RoomType(
        id=new_id(),
        hotel_id=hotel_a.id,
        name="套房",
        capacity=3,
        total_rooms=2,
        base_price_cents=50000,
    )
    for room_type in (king, twin, suite):
        repos.room_types.add(room_type)
    repos.room_types.add(
        RoomType(
            id=new_id(),
            hotel_id=hotel_b.id,
            name="B 大床房",
            capacity=2,
            total_rooms=5,
            base_price_cents=26000,
        )
    )

    def user(phone: str, role: Role, name: str, hotel_id: str | None = None) -> User:
        item = User(
            id=new_id(),
            phone=phone,
            password_hash=_hash(PASSWORD),
            role=role,
            display_name=name,
            hotel_id=hotel_id,
            created_at=NOW,
        )
        repos.users.add(item)
        return item

    admin = user("13800000000", Role.PLATFORM_ADMIN, "管理员")
    manager_a = user("13900000001", Role.MANAGER, "店长 A", hotel_a.id)
    front_a = user("13700000001", Role.FRONT_DESK, "前台 A", hotel_a.id)
    manager_b = user("13900000002", Role.MANAGER, "店长 B", hotel_b.id)
    customer = user("13600000001", Role.CUSTOMER, "顾客一")
    customer2 = user("13600000002", Role.CUSTOMER, "顾客二")
    return Org(
        app=app,
        clock=clock,
        hotel_a=hotel_a,
        hotel_b=hotel_b,
        king=king,
        twin=twin,
        suite=suite,
        admin=Session(admin),
        manager_a=Session(manager_a),
        front_a=Session(front_a),
        manager_b=Session(manager_b),
        customer=Session(customer),
        customer2=Session(customer2),
    )


def reload(org: Org, session: Session) -> Session:
    """账号状态可能被改动，取最新快照。"""
    return Session(org.app.ctx.repos.users.by_id(session.user.id))
