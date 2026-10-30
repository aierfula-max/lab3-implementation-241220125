"""应用容器：把数据库、仓储、服务组装起来。

界面只依赖这个对象，不碰 sqlite3，也不自己 new 服务。这样测试里可以
用 ``build(":memory:", clock=FixedClock(...))`` 得到一套完全一样的环境。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.clock import Clock, SystemClock
from ..infrastructure.db import Database
from ..infrastructure.repositories import Repositories
from .audit_service import AuditService
from .auth_service import AuthService
from .base import ServiceContext, Session
from .booking_service import BookingService
from .hotel_service import HotelService
from .inventory_service import InventoryService
from .order_service import OrderService
from .report_service import ReportService
from .scheduler_service import SchedulerService


@dataclass(slots=True)
class Application:
    """一次进程内的全部应用服务。"""

    db: Database
    ctx: ServiceContext
    auth: AuthService
    hotels: HotelService
    inventory: InventoryService
    booking: BookingService
    orders: OrderService
    reports: ReportService
    scheduler: SchedulerService
    audit: AuditService

    def close(self) -> None:
        self.db.close()


def build(path: str = ":memory:", clock: Clock | None = None) -> Application:
    """按依赖顺序组装。"""
    db = Database(path)
    ctx = ServiceContext(
        db=db,
        repos=Repositories.create(db),
        clock=clock or SystemClock(),
    )
    orders = OrderService(ctx)
    return Application(
        db=db,
        ctx=ctx,
        auth=AuthService(ctx),
        hotels=HotelService(ctx),
        inventory=InventoryService(ctx),
        booking=BookingService(ctx),
        orders=orders,
        reports=ReportService(ctx),
        scheduler=SchedulerService(ctx, orders),
        audit=AuditService(ctx),
    )


__all__ = [
    "Application",
    "Session",
    "build",
]
