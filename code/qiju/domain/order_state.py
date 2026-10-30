"""订单状态机（REQ-017）。

实验二的状态图里有 7 个状态、8 条允许转换和 5 类禁止转换。这里把图直接
落成一张表：服务层只负责“守卫是否成立”，能不能转、谁能转、要不要写原因，
全部由这张表回答。这样做的直接好处是——想加一条“已完成→已取消”时，
必须先改表，改表就会撞上 REQ-017 的单测。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .enums import OrderStatus, Role
from .errors import StateConflict


class InventoryEffect(Enum):
    """状态转换对库存的影响，供服务层与报告共用。"""

    NONE = "不变"
    RELEASE_ALL = "释放全部日期"
    RELEASE_AFTER_FIRST = "释放入住日之后"
    RELEASE_UNUSED = "释放未住间夜"


@dataclass(frozen=True, slots=True)
class Transition:
    """一条允许的状态转换。"""

    source: OrderStatus
    target: OrderStatus
    action: str
    actors: frozenset[Role]
    reason_required: bool = False
    inventory: InventoryEffect = InventoryEffect.NONE


_STAFF = frozenset({Role.FRONT_DESK, Role.MANAGER})
_CUSTOMER = frozenset({Role.CUSTOMER})
_SYSTEM = frozenset({Role.SYSTEM})
_ADMIN = frozenset({Role.PLATFORM_ADMIN})
_STAFF_ADMIN = _STAFF | _ADMIN
_CANCEL_ACTORS = _CUSTOMER | _STAFF | _ADMIN | _SYSTEM

TRANSITIONS: tuple[Transition, ...] = (
    Transition(
        OrderStatus.PENDING, OrderStatus.CONFIRMED, "confirm", _STAFF
    ),
    Transition(
        OrderStatus.PENDING,
        OrderStatus.REJECTED,
        "reject",
        _STAFF,
        reason_required=True,
        inventory=InventoryEffect.RELEASE_ALL,
    ),
    Transition(
        OrderStatus.PENDING,
        OrderStatus.CANCELED,
        "cancel",
        _CUSTOMER | _SYSTEM,
        inventory=InventoryEffect.RELEASE_ALL,
    ),
    Transition(
        OrderStatus.CONFIRMED,
        OrderStatus.CHECKED_IN,
        "check_in",
        _STAFF,
    ),
    Transition(
        OrderStatus.CONFIRMED,
        OrderStatus.CANCELED,
        "cancel",
        _CANCEL_ACTORS,
        inventory=InventoryEffect.RELEASE_ALL,
    ),
    Transition(
        OrderStatus.CONFIRMED,
        OrderStatus.NO_SHOW,
        "no_show",
        _SYSTEM,
        reason_required=True,
        inventory=InventoryEffect.RELEASE_AFTER_FIRST,
    ),
    Transition(
        OrderStatus.CHECKED_IN,
        OrderStatus.COMPLETED,
        "check_out",
        _STAFF,
        inventory=InventoryEffect.RELEASE_UNUSED,
    ),
)


def find_transition(source: OrderStatus, target: OrderStatus) -> Transition:
    """取出转换定义；不存在则抛 409。"""
    for item in TRANSITIONS:
        if item.source is source and item.target is target:
            return item
    raise StateConflict(
        f"不允许的状态转换：{source.value} → {target.value}",
        detail={"source": source.value, "target": target.value},
    )


def allowed_targets(source: OrderStatus) -> list[OrderStatus]:
    """当前状态下所有允许的下一状态。"""
    return [item.target for item in TRANSITIONS if item.source is source]


def allowed_actions(source: OrderStatus, role: Role) -> list[str]:
    """界面按角色渲染按钮时用，避免把不可点的按钮画上去再报错。"""
    return [
        item.action
        for item in TRANSITIONS
        if item.source is source and role in item.actors
    ]


def ensure_actor(source: OrderStatus, target: OrderStatus, role: Role) -> Transition:
    """校验角色是否有权发起该转换。"""
    item = find_transition(source, target)
    if role not in item.actors:
        raise StateConflict(
            f"角色 {role.value} 不能执行 {item.action}",
            detail={"action": item.action, "role": role.value},
        )
    return item
