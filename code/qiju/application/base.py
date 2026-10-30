"""服务层公共设施：会话、权限、日志。

权限判断集中在这里，业务方法只写“谁能做”。这样做的原因很实际：
REQ-002 要求“功能权限 + 数据范围”同时校验，如果每个方法各写一遍，
迟早会漏掉一处；而漏掉的那一处往往就是越权漏洞。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from ..domain.clock import Clock
from ..domain.entities import Notification, OperationLog, Order, User, new_id
from ..domain.enums import AuditAction, Role
from ..domain.errors import NotFound, PermissionDenied, Unauthenticated
from ..infrastructure.db import Database
from ..infrastructure.repositories import Repositories

PHONE_IN_TEXT = re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)")


def mask_phone(text: str) -> str:
    """把任意文本中的手机号脱敏（REQ-021）。"""
    return PHONE_IN_TEXT.sub(r"\1****\2", text)


@dataclass(frozen=True, slots=True)
class Session:
    """登录会话。只保存用户快照，业务方法每次从库里取最新状态。"""

    user: User


@dataclass(slots=True)
class ServiceContext:
    """服务依赖。"""

    db: Database
    repos: Repositories
    clock: Clock


class BaseService:
    """所有应用服务的基类。"""

    def __init__(self, ctx: ServiceContext) -> None:
        self.ctx = ctx
        self.db = ctx.db
        self.repos = ctx.repos

    @property
    def clock(self) -> Clock:
        """始终读容器里的时钟，测试替换时钟后所有服务立即生效。"""
        return self.ctx.clock

    # ------------------------------------------------------------ 会话
    def require_active(self, session: Session) -> User:
        """每次操作都重新读用户，停用账号的旧会话立即失效。"""
        user = self.repos.users.by_id(session.user.id)
        if user is None:
            raise Unauthenticated("会话已失效，请重新登录")
        if not user.is_active:
            raise Unauthenticated("账号已停用")
        return user

    def require_role(self, user: User, *roles: Role) -> None:
        if user.role not in roles:
            raise PermissionDenied("当前角色无权执行该操作")

    def require_staff(self, user: User, hotel_id: str) -> None:
        """前台/店长只能操作本店数据；店长不能越店。"""
        self.require_role(user, Role.FRONT_DESK, Role.MANAGER)
        if user.hotel_id != hotel_id:
            # 统一 404，不泄露其他酒店的数据是否存在（REQ-002）
            raise NotFound("资源不存在")

    def require_manager(self, user: User, hotel_id: str) -> None:
        self.require_role(user, Role.MANAGER)
        if user.hotel_id != hotel_id:
            raise NotFound("资源不存在")

    # ------------------------------------------------------------ 日志
    def write_log(
        self,
        *,
        user: User | None,
        action: AuditAction,
        object_type: str,
        object_id: str,
        hotel_id: str | None = None,
        before: str = "",
        after: str = "",
        reason: str = "",
        request_id: str = "",
        moment: datetime | None = None,
        actor_role: str | None = None,
    ) -> None:
        """写一条操作日志。调用方负责把它放在业务事务里。"""
        log = OperationLog(
            id=new_id(),
            actor_id=user.id if user else None,
            actor_role=actor_role or (user.role.value if user else Role.SYSTEM.value),
            hotel_id=hotel_id if hotel_id is not None else (user.hotel_id if user else None),
            action=action.value,
            object_type=object_type,
            object_id=object_id,
            before_value=mask_phone(before),
            after_value=mask_phone(after),
            reason=mask_phone(reason),
            request_id=request_id,
            created_at=moment or self.clock.now(),
        )
        self.repos.logs.add(log)

    def notify(self, user_id: str, title: str, body: str, moment: datetime | None = None) -> None:
        """站内信。"""
        self.repos.notifications.add(
            Notification(
                id=new_id(),
                user_id=user_id,
                title=title,
                body=mask_phone(body),
                created_at=moment or self.clock.now(),
            )
        )


def resolve_order(
    repos: Repositories, user: User, order_no: str
) -> Order:
    """按数据范围取订单；越权与不存在都返回 404。"""
    order = repos.orders.by_no(order_no)
    if order is None:
        raise NotFound("订单不存在")
    if user.role is Role.CUSTOMER:
        if order.user_id != user.id:
            raise NotFound("订单不存在")
    elif user.role in (Role.FRONT_DESK, Role.MANAGER):
        if order.hotel_id != user.hotel_id:
            raise NotFound("订单不存在")
    elif user.role is not Role.PLATFORM_ADMIN:
        raise NotFound("订单不存在")
    return order
