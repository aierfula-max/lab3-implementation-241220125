"""订单履约：确认、拒绝、取消、改单、入住、退房、退款标记。

状态机只负责“允不允许转”，真正的业务守卫在这里：

* 确认前重新核对库存（可能被店长改小、被停售）；
* 拒绝必须选四类原因之一，“其他”必须写说明；
* 顾客取消按 18:00 规则算扣费；
* 改单先占用新增间夜，全部成功后再释放减少的间夜；
* 提前退房只释放未住间夜，且必须店长确认。

每个方法都遵守同一个顺序：**取订单 → 校验数据范围 → 校验状态/角色 →
在事务里改库存、写退款、写日志 → 发站内信**。
"""

from __future__ import annotations

from datetime import date, datetime

from ..domain.cancellation import (
    cancel_quote,
    early_checkout_quote,
    no_show_quote,
    reject_quote,
)
from ..domain.entities import Order, OrderChange, RefundRecord, new_id
from ..domain.enums import (
    AuditAction,
    CancelReason,
    OrderStatus,
    RefundEvent,
    RefundStatus,
    RejectReason,
    Role,
)
from ..domain.errors import (
    Conflict,
    NotFound,
    PermissionDenied,
    StateConflict,
    ValidationError,
)
from ..domain.money import format_money
from ..domain.order_state import ensure_actor
from ..domain.pricing import build_nights, diff_of, total_of
from ..domain.validation import (
    date_range,
    validate_room_count,
    validate_stay,
)
from .base import BaseService, Session, resolve_order


class OrderService(BaseService):
    """订单生命周期。"""

    # ------------------------------------------------------------ 查询
    def list_mine(
        self,
        session: Session,
        *,
        status: OrderStatus | None = None,
        keyword: str = "",
    ) -> list[Order]:
        user = self.require_active(session)
        self.require_role(user, Role.CUSTOMER)
        return self.repos.orders.list_by_user(user.id, status=status, keyword=keyword)

    def list_for_staff(
        self,
        session: Session,
        *,
        status: OrderStatus | None = None,
        keyword: str = "",
    ) -> list[Order]:
        user = self.require_active(session)
        self.require_role(user, Role.FRONT_DESK, Role.MANAGER)
        if user.hotel_id is None:
            return []
        return self.repos.orders.list_by_hotel(
            user.hotel_id, status=status, keyword=keyword
        )

    def list_all(self, session: Session, *, keyword: str = "") -> list[Order]:
        user = self.require_active(session)
        self.require_role(user, Role.PLATFORM_ADMIN)
        orders = self.repos.orders.list_all()
        if keyword:
            orders = [item for item in orders if keyword in item.order_no]
        return orders

    def get(self, session: Session, order_no: str) -> Order:
        user = self.require_active(session)
        return resolve_order(self.repos, user, order_no)

    def refunds(self, session: Session, order_no: str) -> list[RefundRecord]:
        user = self.require_active(session)
        order = resolve_order(self.repos, user, order_no)
        return self.repos.orders.refunds(order.id)

    def changes(self, session: Session, order_no: str) -> list[OrderChange]:
        user = self.require_active(session)
        order = resolve_order(self.repos, user, order_no)
        return self.repos.orders.changes(order.id)

    # ------------------------------------------------------------ 确认
    def confirm(self, session: Session, order_no: str) -> Order:
        """前台/店长确认订单；确认前再次校验库存。"""
        actor = self.require_active(session)
        order = resolve_order(self.repos, actor, order_no)
        self.require_staff(actor, order.hotel_id)
        ensure_actor(order.status, OrderStatus.CONFIRMED, actor.role)
        self._assert_stock_confirmable(order)
        with self.db.transaction():
            order.status = OrderStatus.CONFIRMED
            order.confirmed_at = self.clock.now()
            order.confirmed_by = actor.id
            self.repos.orders.save(order, expected_version=order.version)
            self.write_log(
                user=actor,
                action=AuditAction.ORDER_CONFIRM,
                object_type="Order",
                object_id=order.id,
                hotel_id=order.hotel_id,
                before=OrderStatus.PENDING.value,
                after=OrderStatus.CONFIRMED.value,
            )
            self._notify_customer(
                order, "订单已确认", f"订单 {order.order_no} 已确认，请按时到店。"
            )
        return order

    def _assert_stock_confirmable(self, order: Order) -> None:
        for day in order.stay_dates:
            item = self.repos.inventory.get(order.room_type_id, day)
            if item is None:
                raise StateConflict(f"{day} 库存记录缺失，只能拒绝该订单")
            if item.stop_sale:
                raise StateConflict(f"{day} 已停售，不能确认，只能拒绝")
            if item.sold_rooms > item.total_rooms:
                raise StateConflict(f"{day} 库存不足，不能确认，只能拒绝")

    # ------------------------------------------------------------ 拒绝
    def reject(
        self,
        session: Session,
        order_no: str,
        *,
        reason: RejectReason,
        note: str = "",
    ) -> Order:
        """拒绝待确认订单，释放全部库存并全额退款。"""
        actor = self.require_active(session)
        order = resolve_order(self.repos, actor, order_no)
        self.require_staff(actor, order.hotel_id)
        ensure_actor(order.status, OrderStatus.REJECTED, actor.role)
        if reason is RejectReason.OTHER and not note.strip():
            raise ValidationError("选择“其他”时必须填写说明")
        quote = reject_quote(order)
        with self.db.transaction():
            self._release_days(order, order.stay_dates)
            order.status = OrderStatus.REJECTED
            order.rejected_at = self.clock.now()
            order.reject_reason = reason.value
            order.reject_note = note.strip()
            self.repos.orders.save(order, expected_version=order.version)
            self._record_refund(
                order, quote.event.value, quote.refundable_cents, 0, order.rejected_at
            )
            self.write_log(
                user=actor,
                action=AuditAction.ORDER_REJECT,
                object_type="Order",
                object_id=order.id,
                hotel_id=order.hotel_id,
                before=OrderStatus.PENDING.value,
                after=OrderStatus.REJECTED.value,
                reason=f"{reason.value}：{note.strip()}".strip("："),
            )
            self._notify_customer(
                order,
                "订单被拒绝",
                f"订单 {order.order_no} 被拒绝，原因：{reason.value}。"
                f"应退 {format_money(quote.refundable_cents)}。",
            )
        return order

    # ------------------------------------------------------------ 取消
    def cancel_by_customer(
        self, session: Session, order_no: str
    ) -> tuple[Order, RefundRecord]:
        """顾客取消。18:00 前免费，18:00 后收首晚。"""
        actor = self.require_active(session)
        order = resolve_order(self.repos, actor, order_no)
        self.require_role(actor, Role.CUSTOMER)
        if order.user_id != actor.id:
            raise NotFound("订单不存在")
        ensure_actor(order.status, OrderStatus.CANCELED, actor.role)
        quote = cancel_quote(order, self.clock.now(), CancelReason.CUSTOMER)
        with self.db.transaction():
            self._release_days(order, order.stay_dates)
            order.status = OrderStatus.CANCELED
            order.canceled_at = self.clock.now()
            order.cancel_reason = CancelReason.CUSTOMER.value
            self.repos.orders.save(order, expected_version=order.version)
            refund = self._record_refund(
                order, quote.event.value, quote.refundable_cents, quote.deducted_cents
            )
            self.write_log(
                user=actor,
                action=AuditAction.ORDER_CANCEL,
                object_type="Order",
                object_id=order.id,
                hotel_id=order.hotel_id,
                before=OrderStatus.PENDING.value,
                after=OrderStatus.CANCELED.value,
                reason=f"{quote.note}，扣费 {quote.deducted_cents} 分",
            )
            self._notify_hotel(
                order, "顾客取消订单", f"订单 {order.order_no} 已被顾客取消。"
            )
            self._notify_customer(
                order,
                "取消成功",
                f"订单 {order.order_no} 已取消，{quote.note}，"
                f"应退 {format_money(quote.refundable_cents)}。",
            )
        return order, refund

    def cancel_by_hotel(
        self, session: Session, order_no: str, reason_note: str = ""
    ) -> tuple[Order, RefundRecord]:
        """酒店逐单取消（停业/无法接待），全额可退（REQ-004/026）。"""
        actor = self.require_active(session)
        order = resolve_order(self.repos, actor, order_no)
        self.require_manager(actor, order.hotel_id)
        if order.status is OrderStatus.PENDING:
            raise StateConflict("待确认订单请使用拒绝")
        ensure_actor(order.status, OrderStatus.CANCELED, actor.role)
        quote = cancel_quote(order, self.clock.now(), CancelReason.HOTEL_CLOSED)
        with self.db.transaction():
            before = order.status.value
            self._release_days(order, order.stay_dates)
            order.status = OrderStatus.CANCELED
            order.canceled_at = self.clock.now()
            order.cancel_reason = CancelReason.HOTEL_CLOSED.value
            self.repos.orders.save(order, expected_version=order.version)
            refund = self._record_refund(
                order, RefundEvent.HOTEL_CLOSED.value, quote.refundable_cents, 0
            )
            self.write_log(
                user=actor,
                action=AuditAction.ORDER_CANCEL,
                object_type="Order",
                object_id=order.id,
                hotel_id=order.hotel_id,
                before=before,
                after=OrderStatus.CANCELED.value,
                reason=reason_note.strip() or "酒店停业取消",
            )
            self._notify_customer(
                order,
                "酒店取消订单",
                f"订单 {order.order_no} 因酒店原因取消，"
                f"全额可退 {format_money(quote.refundable_cents)}。",
            )
        return order, refund

    def force_cancel(
        self, session: Session, order_no: str, reason: str
    ) -> tuple[Order, RefundRecord]:
        """平台强制取消。必须写原因；已入住订单不走这里（REQ-026）。"""
        actor = self.require_active(session)
        self.require_role(actor, Role.PLATFORM_ADMIN)
        order = resolve_order(self.repos, actor, order_no)
        if not reason.strip():
            raise ValidationError("强制取消必须填写原因")
        if order.status is OrderStatus.CHECKED_IN:
            raise Conflict("已入住订单不适用强制取消，请转线下处理")
        ensure_actor(order.status, OrderStatus.CANCELED, actor.role)
        quote = cancel_quote(order, self.clock.now(), CancelReason.ADMIN_FORCE)
        with self.db.transaction():
            before = order.status.value
            self._release_days(order, order.stay_dates)
            order.status = OrderStatus.CANCELED
            order.canceled_at = self.clock.now()
            order.cancel_reason = CancelReason.ADMIN_FORCE.value
            self.repos.orders.save(order, expected_version=order.version)
            refund = self._record_refund(
                order, RefundEvent.ADMIN_FORCE.value, quote.refundable_cents, 0
            )
            self.write_log(
                user=actor,
                action=AuditAction.ORDER_FORCE_CANCEL,
                object_type="Order",
                object_id=order.id,
                hotel_id=order.hotel_id,
                before=before,
                after=OrderStatus.CANCELED.value,
                reason=f"责任方：酒店/平台。{reason.strip()}",
            )
            self._notify_customer(
                order,
                "订单被平台取消",
                f"订单 {order.order_no} 已被平台取消，原因：{reason.strip()}。",
            )
        return order, refund

    # ------------------------------------------------------------ 改单
    def modify(
        self,
        session: Session,
        order_no: str,
        *,
        check_in: date,
        check_out: date,
        room_count: int,
    ) -> tuple[Order, int]:
        """改单一次：先占新增间夜，全部成功后再释放减少的间夜。"""
        actor = self.require_active(session)
        order = resolve_order(self.repos, actor, order_no)
        self.require_role(actor, Role.CUSTOMER)
        if order.user_id != actor.id:
            raise NotFound("订单不存在")
        if order.status is not OrderStatus.CONFIRMED:
            raise StateConflict("只有已确认且未入住的订单可以修改")
        if order.modified:
            raise StateConflict("每张订单只能修改一次")
        if self.clock.now().date() >= order.check_in:
            raise StateConflict("入住当天不能改单")
        validate_stay(check_in, check_out, self.clock.now().date())
        validate_room_count(room_count)
        room_type = self.repos.room_types.by_id(order.room_type_id)
        if room_type is None:
            raise NotFound("房型不存在")
        old_count = {night.day: night.room_count for night in order.nights}
        new_count = {
            day: room_count for day in date_range(check_in, check_out)
        }
        with self.db.transaction():
            # 1) 先占用所有正向差额
            for day, count in new_count.items():
                delta = count - old_count.get(day, 0)
                if delta <= 0:
                    continue
                self.repos.inventory.ensure(
                    room_type.id, day, room_type.total_rooms, room_type.base_price_cents
                )
                item = self.repos.inventory.get(room_type.id, day)
                if item is not None and item.stop_sale:
                    raise Conflict(f"{day} 已停售，无法改单")
                if not self.repos.inventory.hold(room_type.id, day, delta):
                    raise Conflict(f"{day} 库存不足，原订单保持不变")
            # 2) 正向全部成功后再释放负向差额
            for day, count in old_count.items():
                delta = new_count.get(day, 0) - count
                if delta < 0:
                    self.repos.inventory.release(room_type.id, day, -delta)
            # 3) 按新日期的价格快照重算
            prices: dict[date, int] = {}
            for day in date_range(check_in, check_out):
                item = self.repos.inventory.get(room_type.id, day)
                assert item is not None
                prices[day] = item.price_cents
            new_nights = build_nights(date_range(check_in, check_out), prices, room_count)
            diff = diff_of(order.nights, new_nights)
            before = (
                f"{order.check_in}~{order.check_out}，{order.room_count} 间，"
                f"{order.total_cents} 分"
            )
            order.check_in = check_in
            order.check_out = check_out
            order.room_count = room_count
            order.nights = new_nights
            order.total_cents = total_of(new_nights)
            order.modified = True
            self.repos.orders.save(order, expected_version=order.version)
            self.repos.orders.replace_nights(order.id, new_nights)
            self.repos.orders.add_change(
                OrderChange(
                    id=new_id(),
                    order_id=order.id,
                    before_summary=before,
                    after_summary=(
                        f"{check_in}~{check_out}，{room_count} 间，"
                        f"{order.total_cents} 分"
                    ),
                    diff_cents=diff,
                    operator_id=actor.id,
                    created_at=self.clock.now(),
                )
            )
            if diff < 0:
                self._record_refund(
                    order, RefundEvent.MODIFY.value, -diff, 0
                )
            self.write_log(
                user=actor,
                action=AuditAction.ORDER_MODIFY,
                object_type="Order",
                object_id=order.id,
                hotel_id=order.hotel_id,
                before=before,
                after=(
                    f"{check_in}~{check_out}，{room_count} 间，"
                    f"{order.total_cents} 分"
                ),
                reason=f"改单差价 {diff} 分" + ("（线下补收）" if diff > 0 else ""),
            )
            self._notify_hotel(
                order,
                "顾客修改订单",
                f"订单 {order.order_no} 已改期/改间数，差价 {diff / 100:.2f} 元。",
            )
        return order, diff

    # ------------------------------------------------------------ 入住
    def check_in(
        self, session: Session, order_no: str, *, early_reason: str = ""
    ) -> Order:
        """办理入住。提前到店需店长放行并填写原因（REQ-015）。"""
        actor = self.require_active(session)
        order = resolve_order(self.repos, actor, order_no)
        self.require_staff(actor, order.hotel_id)
        ensure_actor(order.status, OrderStatus.CHECKED_IN, actor.role)
        today = self.clock.now().date()
        if today < order.check_in:
            if actor.role is not Role.MANAGER:
                raise PermissionDenied("提前入住需要店长放行")
            if not early_reason.strip():
                raise ValidationError("提前入住必须填写原因")
        if today >= order.check_out:
            raise Conflict("已过退房日，请先处理未入住/异常订单")
        with self.db.transaction():
            order.status = OrderStatus.CHECKED_IN
            order.checked_in_at = self.clock.now()
            order.checked_in_by = actor.id
            self.repos.orders.save(order, expected_version=order.version)
            self.write_log(
                user=actor,
                action=AuditAction.ORDER_CHECK_IN,
                object_type="Order",
                object_id=order.id,
                hotel_id=order.hotel_id,
                before=OrderStatus.CONFIRMED.value,
                after=OrderStatus.CHECKED_IN.value,
                reason=early_reason.strip(),
            )
        return order

    def check_out(
        self, session: Session, order_no: str, *, actual_check_out: date | None = None
    ) -> tuple[Order, RefundRecord | None]:
        """办理退房。提前退房需店长确认，并释放未住间夜。"""
        actor = self.require_active(session)
        order = resolve_order(self.repos, actor, order_no)
        self.require_staff(actor, order.hotel_id)
        ensure_actor(order.status, OrderStatus.COMPLETED, actor.role)
        moment = self.clock.now()
        actual = actual_check_out or moment.date()
        refund: RefundRecord | None = None
        early = actual < order.check_out
        if early and actor.role is not Role.MANAGER:
            raise PermissionDenied("提前退房需要店长确认")
        if actual <= order.check_in:
            raise ValidationError("退房日期必须晚于入住日期")
        with self.db.transaction():
            if early:
                quote = early_checkout_quote(order, actual)
                self._release_days_after(order, actual)
                order.early_checkout = True
                order.actual_check_out = actual
                refund = self._record_refund(
                    order, quote.event.value, quote.refundable_cents, 0
                )
            else:
                order.actual_check_out = actual
            order.status = OrderStatus.COMPLETED
            order.checked_out_at = moment
            order.checked_out_by = actor.id
            self.repos.orders.save(order, expected_version=order.version)
            self.write_log(
                user=actor,
                action=AuditAction.ORDER_CHECK_OUT,
                object_type="Order",
                object_id=order.id,
                hotel_id=order.hotel_id,
                before=OrderStatus.CHECKED_IN.value,
                after=OrderStatus.COMPLETED.value,
                reason="提前退房" if early else "正常退房",
            )
            if early and refund is not None:
                self._notify_customer(
                    order,
                    "提前退房完成",
                    f"订单 {order.order_no} 提前退房，未住间夜应退 "
                    f"{format_money(refund.refundable_cents)}。",
                )
        return order, refund

    # ------------------------------------------------------------ 退款
    def mark_refund(self, session: Session, order_no: str, refund_id: str) -> None:
        """店长标记本店退款为“已退款”；管理员可标记全平台。"""
        actor = self.require_active(session)
        order = resolve_order(self.repos, actor, order_no)
        if actor.role is Role.MANAGER:
            self.require_manager(actor, order.hotel_id)
        elif actor.role is not Role.PLATFORM_ADMIN:
            raise PermissionDenied("只有店长或平台管理员可以标记退款")
        refund = next(
            (item for item in self.repos.orders.refunds(order.id) if item.id == refund_id),
            None,
        )
        if refund is None:
            raise NotFound("退款记录不存在")
        with self.db.transaction():
            if not self.repos.orders.mark_refunded(refund_id, actor.id, self.clock.now()):
                raise Conflict("退款记录已处理")
            self.write_log(
                user=actor,
                action=AuditAction.REFUND_MARK,
                object_type="RefundRecord",
                object_id=refund_id,
                hotel_id=order.hotel_id,
                before=RefundStatus.PENDING_OFFLINE.value,
                after=RefundStatus.REFUNDED.value,
                reason=f"订单 {order.order_no}，应退 {refund.refundable_cents} 分",
            )

    # ------------------------------------------------------------ 系统任务
    def timeout_cancel(self, order: Order) -> None:
        """超时未确认，由调度器自动取消并释放全部库存（REQ-010）。"""
        ensure_actor(order.status, OrderStatus.CANCELED, Role.SYSTEM)
        quote = cancel_quote(order, self.clock.now(), CancelReason.TIMEOUT)
        moment = self.clock.now()
        with self.db.transaction():
            self._release_days(order, order.stay_dates)
            order.status = OrderStatus.CANCELED
            order.canceled_at = moment
            order.cancel_reason = CancelReason.TIMEOUT.value
            self.repos.orders.save(order, expected_version=order.version)
            self._record_refund(
                order, quote.event.value, quote.refundable_cents, 0, moment
            )
            self.write_log(
                user=None,
                actor_role=Role.SYSTEM.value,
                action=AuditAction.ORDER_CANCEL,
                object_type="Order",
                object_id=order.id,
                hotel_id=order.hotel_id,
                before=OrderStatus.PENDING.value,
                after=OrderStatus.CANCELED.value,
                reason="超时未确认，系统自动取消",
                moment=moment,
            )
            self._notify_customer(
                order,
                "订单超时取消",
                f"订单 {order.order_no} 超时未确认，已自动取消并释放库存。",
            )

    def close_no_show(self, order: Order) -> None:
        """未入住关闭（由调度器调用）。首晚照收，释放之后日期。"""
        ensure_actor(order.status, OrderStatus.NO_SHOW, Role.SYSTEM)
        quote = no_show_quote(order)
        moment = self.clock.now()
        with self.db.transaction():
            release_days = order.stay_dates[1:]
            self._release_days(order, release_days)
            order.status = OrderStatus.NO_SHOW
            order.canceled_at = moment
            order.cancel_reason = "未入住关闭"
            self.repos.orders.save(order, expected_version=order.version)
            self._record_refund(
                order, quote.event.value, quote.refundable_cents, quote.deducted_cents, moment
            )
            self.write_log(
                user=None,
                actor_role=Role.SYSTEM.value,
                action=AuditAction.ORDER_NO_SHOW,
                object_type="Order",
                object_id=order.id,
                hotel_id=order.hotel_id,
                before=OrderStatus.CONFIRMED.value,
                after=OrderStatus.NO_SHOW.value,
                reason=quote.note,
                moment=moment,
            )
            self._notify_customer(
                order,
                "订单未入住关闭",
                f"订单 {order.order_no} 因未入住已关闭，{quote.note}。",
            )

    # ------------------------------------------------------------ 内部
    def _release_days(self, order: Order, days: list[date]) -> None:
        for day in days:
            if not self.repos.inventory.release(order.room_type_id, day, order.room_count):
                raise StateConflict(f"{day} 库存释放失败，请联系管理员对账")

    def _release_days_after(self, order: Order, start: date) -> None:
        days = [day for day in order.stay_dates if day >= start]
        self._release_days(order, days)

    def _record_refund(
        self,
        order: Order,
        event: str,
        refundable_cents: int,
        deducted_cents: int,
        moment: datetime | None = None,
    ) -> RefundRecord:
        """写退款记录；同一订单同一事件只写一条（幂等）。"""
        existing = self.repos.orders.refund_by_event(order.id, event)
        if existing is not None:
            return existing
        refund = RefundRecord(
            id=new_id(),
            refund_no=f"RF{order.order_no[-10:]}{event[:2]}{new_id()[:4].upper()}",
            order_id=order.id,
            event_type=event,
            refundable_cents=max(0, refundable_cents),
            deducted_cents=max(0, deducted_cents),
            created_at=moment or self.clock.now(),
        )
        self.repos.orders.add_refund(refund)
        return refund

    def _notify_customer(self, order: Order, title: str, body: str) -> None:
        self.notify(order.user_id, title, body)

    def _notify_hotel(self, order: Order, title: str, body: str) -> None:
        for user in self.repos.users.list_by_hotel(order.hotel_id):
            if user.role in (Role.MANAGER, Role.FRONT_DESK):
                self.notify(user.id, title, body)
