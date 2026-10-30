"""仓储门面。

服务层只依赖这个对象，不直接依赖 SQLite。以后换 PostgreSQL 时，
改这里的组装即可，服务层不需要动。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..db import Database
from .hotels import (
    HotelRepository,
    PolicyRepository,
    RoomTypeRepository,
    StopSaleRepository,
)
from .inventory import InventoryRepository
from .logs import LogRepository, NotificationRepository
from .orders import OrderRepository
from .users import InvitationRepository, UserRepository


@dataclass(slots=True)
class Repositories:
    """所有仓储的集合。"""

    users: UserRepository
    invitations: InvitationRepository
    hotels: HotelRepository
    room_types: RoomTypeRepository
    stop_sales: StopSaleRepository
    inventory: InventoryRepository
    orders: OrderRepository
    logs: LogRepository
    notifications: NotificationRepository
    policies: PolicyRepository

    @classmethod
    def create(cls, db: Database) -> Repositories:
        return cls(
            users=UserRepository(db),
            invitations=InvitationRepository(db),
            hotels=HotelRepository(db),
            room_types=RoomTypeRepository(db),
            stop_sales=StopSaleRepository(db),
            inventory=InventoryRepository(db),
            orders=OrderRepository(db),
            logs=LogRepository(db),
            notifications=NotificationRepository(db),
            policies=PolicyRepository(db),
        )
