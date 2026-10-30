"""演示数据。

数据分两段：先用一个“十天前”的固定时钟跑出历史订单（已完成、未入住、
取消），再把时钟调回现在，生成今天工作台上能操作的订单。这样界面截图和
报表都不是空表，也不需要手工改数据库。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from ..application import Application, Session
from ..application.booking_service import BookingRequest
from ..domain.clock import FixedClock, SystemClock
from ..domain.entities import (
    ConfirmPolicy,
    Guest,
    Hotel,
    RoomType,
    User,
    new_id,
)
from ..domain.enums import AuditStatus, BusinessStatus, Role
from ..domain.validation import date_range
from ..infrastructure.security import hash_password

DEMO_PASSWORD = "Qiju@2026"


def seed_demo(app: Application, *, now: datetime | None = None) -> dict[str, str]:
    """写入一套可演示的数据；重复调用会直接返回已有账号。"""
    if app.ctx.repos.users.by_phone("13800000000") is not None:
        return {"admin": "13800000000", "note": "already seeded"}

    moment = now or SystemClock().now()
    history_clock = FixedClock(moment - timedelta(days=10))
    original_clock = app.ctx.clock
    app.ctx.clock = history_clock

    hotels = _seed_org(app, moment)
    _seed_inventory(app, moment)
    _seed_history(app, hotels, moment)
    app.ctx.clock = original_clock
    _seed_today(app, hotels, moment)
    return {
        "admin": "13800000000",
        "manager": "13900000001",
        "front_desk": "13700000001",
        "customer": "13600000001",
        "password": DEMO_PASSWORD,
        "invitation": "PENDING-INVITE",
    }


def _seed_org(app: Application, moment: datetime) -> dict[str, Hotel]:
    repos = app.ctx.repos
    hotels = {
        "fzm": Hotel(
            id=new_id(),
            name="栖居·夫子庙店",
            city="南京",
            address="秦淮区贡院街 18 号",
            phone="02586661234",
            business_status=BusinessStatus.OPEN,
            audit_status=AuditStatus.APPROVED,
            description="临秦淮河，步行 5 分钟到夫子庙；2024 年翻新。",
            created_at=moment - timedelta(days=400),
        ),
        "xjkw": Hotel(
            id=new_id(),
            name="栖居·新街口店",
            city="南京",
            address="鼓楼区中山路 100 号",
            phone="02586665678",
            business_status=BusinessStatus.OPEN,
            audit_status=AuditStatus.APPROVED,
            description="地铁 1/2 号线新街口站上盖，适合商务出行。",
            created_at=moment - timedelta(days=300),
        ),
        "hxz": Hotel(
            id=new_id(),
            name="栖居·河西店",
            city="南京",
            address="建邺区江东中路 300 号",
            phone="02586669012",
            business_status=BusinessStatus.SUSPENDED,
            audit_status=AuditStatus.PENDING,
            description="奥体中心旁，新店待审核。",
            created_at=moment - timedelta(days=5),
        ),
    }
    for hotel in hotels.values():
        repos.hotels.add(hotel)

    def add_user(phone, role, name, hotel_id=None, password=DEMO_PASSWORD):
        user = User(
            id=new_id(),
            phone=phone,
            password_hash=hash_password(password),
            role=role,
            display_name=name,
            hotel_id=hotel_id,
            created_at=moment - timedelta(days=200),
        )
        repos.users.add(user)
        return user

    add_user("13800000000", Role.PLATFORM_ADMIN, "平台管理员", password="Admin@2026")
    add_user("13900000001", Role.MANAGER, "陈栖", hotels["fzm"].id, "Manager@2026")
    add_user("13900000002", Role.MANAGER, "许南", hotels["xjkw"].id, "Manager@2026")
    add_user("13700000001", Role.FRONT_DESK, "小林", hotels["fzm"].id, "Front@2026")
    add_user("13600000001", Role.CUSTOMER, "林小满")
    add_user("13600000002", Role.CUSTOMER, "周予安")
    add_user("13600000003", Role.CUSTOMER, "苏澜")

    room_types = {
        "fzm-king": RoomType(
            id=new_id(),
            hotel_id=hotels["fzm"].id,
            name="河景大床房",
            capacity=2,
            total_rooms=12,
            base_price_cents=32800,
            bed_type="1.8 m 大床",
            area_m2=28,
        ),
        "fzm-twin": RoomType(
            id=new_id(),
            hotel_id=hotels["fzm"].id,
            name="庭院双床房",
            capacity=2,
            total_rooms=10,
            base_price_cents=29800,
            bed_type="1.2 m 双床",
            area_m2=26,
        ),
        "fzm-suite": RoomType(
            id=new_id(),
            hotel_id=hotels["fzm"].id,
            name="秦淮套房",
            capacity=3,
            total_rooms=4,
            base_price_cents=68800,
            bed_type="2.0 m 大床 + 沙发床",
            area_m2=52,
        ),
        "xjk-king": RoomType(
            id=new_id(),
            hotel_id=hotels["xjkw"].id,
            name="城景大床房",
            capacity=2,
            total_rooms=20,
            base_price_cents=36800,
            bed_type="1.8 m 大床",
            area_m2=30,
        ),
        "xjk-twin": RoomType(
            id=new_id(),
            hotel_id=hotels["xjkw"].id,
            name="商务双床房",
            capacity=2,
            total_rooms=16,
            base_price_cents=33800,
            bed_type="1.35 m 双床",
            area_m2=32,
        ),
        "hxz-king": RoomType(
            id=new_id(),
            hotel_id=hotels["hxz"].id,
            name="奥体大床房",
            capacity=2,
            total_rooms=18,
            base_price_cents=31800,
            bed_type="1.8 m 大床",
            area_m2=29,
        ),
    }
    for room_type in room_types.values():
        repos.room_types.add(room_type)
    app.ctx.repos.policies.upsert(
        ConfirmPolicy(hotel_id=hotels["fzm"].id, timeout_minutes=30)
    )
    app.ctx.repos.policies.upsert(
        ConfirmPolicy(hotel_id=hotels["xjkw"].id, timeout_minutes=45)
    )
    _seed_invitation(app, hotels["hxz"].id, moment)
    return hotels


def _seed_invitation(app: Application, hotel_id: str, moment: datetime) -> None:
    from ..domain.entities import InvitationCode

    app.ctx.repos.invitations.add(
        InvitationCode(
            code="PENDING-INVITE",
            hotel_id=hotel_id,
            created_by=app.ctx.repos.users.by_phone("13800000000").id,
            expires_at=moment + timedelta(days=30),
        )
    )


def _seed_inventory(app: Application, moment: datetime) -> None:
    """未来 45 天与过去 14 天的库存；周末加价，另设两天停售。"""
    today = moment.date()
    hotels = app.ctx.repos.hotels.list_all()
    room_types = []
    for hotel in hotels[:2]:
        room_types.extend(app.ctx.repos.room_types.list_by_hotel(hotel.id))
    for room_type in room_types:
        for day in date_range(today - timedelta(days=14), today + timedelta(days=45)):
            weekend = day.weekday() >= 5
            price = room_type.base_price_cents + (8000 if weekend else 0)
            item = app.ctx.repos.inventory.get(room_type.id, day)
            if item is None:
                from ..domain.entities import DailyInventory

                app.ctx.repos.inventory.save(
                    DailyInventory(
                        room_type_id=room_type.id,
                        day=day,
                        total_rooms=room_type.total_rooms,
                        sold_rooms=0,
                        price_cents=price,
                        stop_sale=False,
                    )
                )
    stop_day = today + timedelta(days=5)
    for room_type in room_types[:2]:
        app.ctx.repos.inventory.set_stop_sale(room_type.id, stop_day, True)


def _seed_history(app: Application, hotels: dict[str, Hotel], moment: datetime) -> None:
    """用固定时钟跑出历史订单：已完成、提前退房、迟到取消、未入住。"""
    clock: FixedClock = app.ctx.clock  # type: ignore[assignment]
    tz = moment.tzinfo
    fzm = hotels["fzm"]
    manager = Session(app.ctx.repos.users.by_phone("13900000001"))
    front = Session(app.ctx.repos.users.by_phone("13700000001"))
    customer = Session(app.ctx.repos.users.by_phone("13600000001"))
    customer2 = Session(app.ctx.repos.users.by_phone("13600000002"))
    room_type = app.ctx.repos.room_types.list_by_hotel(fzm.id)[0]
    base_day = moment.date()

    def at(day: date, hour: int, minute: int = 0) -> datetime:
        return datetime.combine(day, time(hour, minute), tzinfo=tz)

    # 1) 已完成：10 天前入住，住 3 晚，正常退房
    clock.set(at(base_day - timedelta(days=10), 10))
    order = app.booking.create_order(
        customer,
        BookingRequest(
            room_type_id=room_type.id,
            check_in=base_day - timedelta(days=9),
            check_out=base_day - timedelta(days=6),
            room_count=1,
            guests=[Guest("林小满", "13600000001")],
            request_id="seed-completed-1",
        ),
    )
    clock.set(at(base_day - timedelta(days=9), 14, 20))
    app.orders.confirm(front, order.order_no)
    app.orders.check_in(front, order.order_no)
    clock.set(at(base_day - timedelta(days=6), 10, 10))
    app.orders.check_out(front, order.order_no)

    # 2) 提前退房：原定 4 晚，住 2 晚后退房，退掉后 2 晚
    clock.set(at(base_day - timedelta(days=8), 9))
    order = app.booking.create_order(
        customer2,
        BookingRequest(
            room_type_id=room_type.id,
            check_in=base_day - timedelta(days=7),
            check_out=base_day - timedelta(days=3),
            room_count=1,
            guests=[Guest("周予安", "13600000002")],
            request_id="seed-early-2",
        ),
    )
    clock.set(at(base_day - timedelta(days=7), 15))
    app.orders.confirm(front, order.order_no)
    app.orders.check_in(front, order.order_no)
    clock.set(at(base_day - timedelta(days=5), 10))
    app.orders.check_out(manager, order.order_no)

    # 3) 18:00 后取消：首晚扣费
    clock.set(at(base_day - timedelta(days=4), 9))
    order = app.booking.create_order(
        customer,
        BookingRequest(
            room_type_id=room_type.id,
            check_in=base_day - timedelta(days=4),
            check_out=base_day - timedelta(days=2),
            room_count=1,
            guests=[Guest("林小满", "13600000001")],
            request_id="seed-late-cancel-3",
        ),
    )
    app.orders.confirm(front, order.order_no)
    clock.set(at(base_day - timedelta(days=4), 19, 20))
    app.orders.cancel_by_customer(customer, order.order_no)

    # 4) 未入住关闭：入住日次日凌晨由调度器关闭
    clock.set(at(base_day - timedelta(days=4), 11))
    order = app.booking.create_order(
        customer2,
        BookingRequest(
            room_type_id=room_type.id,
            check_in=base_day - timedelta(days=3),
            check_out=base_day - timedelta(days=1),
            room_count=1,
            guests=[Guest("周予安", "13600000002")],
            request_id="seed-noshow-4",
        ),
    )
    app.orders.confirm(front, order.order_no)
    clock.set(at(base_day - timedelta(days=2), 0, 20))
    app.scheduler.run()


def _seed_today(app: Application, hotels: dict[str, Hotel], moment: datetime) -> None:
    """今天的订单：待确认、已确认、已入住各一张，方便截图。"""
    fzm = hotels["fzm"]
    customer = Session(app.ctx.repos.users.by_phone("13600000001"))
    customer2 = Session(app.ctx.repos.users.by_phone("13600000002"))
    customer3 = Session(app.ctx.repos.users.by_phone("13600000003"))
    front = Session(app.ctx.repos.users.by_phone("13700000001"))
    room_types = app.ctx.repos.room_types.list_by_hotel(fzm.id)
    today = moment.date()

    pending = app.booking.create_order(
        customer2,
        BookingRequest(
            room_type_id=room_types[0].id,
            check_in=today + timedelta(days=1),
            check_out=today + timedelta(days=3),
            room_count=2,
            guests=[Guest("周予安", "13600000002"), Guest("周予宁", "13600000009")],
            request_id="seed-today-pending",
        ),
    )
    confirmed = app.booking.create_order(
        customer3,
        BookingRequest(
            room_type_id=room_types[1].id,
            check_in=today,
            check_out=today + timedelta(days=2),
            room_count=1,
            guests=[Guest("苏澜", "13600000003")],
            request_id="seed-today-confirmed",
        ),
    )
    app.orders.confirm(front, confirmed.order_no)
    # 在住订单要“昨天入住”，临时把时钟拨回昨天上午
    saved_clock = app.ctx.clock
    app.ctx.clock = FixedClock(
        datetime.combine(today - timedelta(days=1), time(9), tzinfo=moment.tzinfo)
    )
    inhouse = app.booking.create_order(
        customer,
        BookingRequest(
            room_type_id=room_types[2].id,
            check_in=today - timedelta(days=1),
            check_out=today + timedelta(days=1),
            room_count=1,
            guests=[Guest("林小满", "13600000001")],
            request_id="seed-today-inhouse",
        ),
    )
    app.orders.confirm(front, inhouse.order_no)
    app.orders.check_in(front, inhouse.order_no)
    app.ctx.clock = saved_clock
    # 留一张待确认给工作台
    return {"pending": pending.order_no, "order_no": confirmed.order_no}
