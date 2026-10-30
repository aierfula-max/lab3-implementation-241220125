"""商家端：订单工作台、房态价格、房型管理。"""

from __future__ import annotations

import tkinter as tk
from datetime import timedelta
from tkinter import messagebox, simpledialog, ttk

from ..domain.enums import OrderStatus, RefundStatus, RejectReason, Role
from ..domain.errors import DomainError
from ..domain.money import format_money, parse_yuan
from . import theme
from .app import Page
from .customer_views import STATUS_LABELS, parse_date
from .widgets import Badge, Card, DataTable, button, field_label, text_label, title


class WorkbenchView(Page):
    title = "订单工作台"
    subtitle = "确认、拒绝、入住、退房；每次操作都写操作日志并通知顾客"

    def build(self) -> None:
        self._order = None
        bar = tk.Frame(self, bg=theme.CANVAS)
        bar.pack(fill="x", pady=(0, 10))
        self.status = tk.StringVar(value="全部")
        ttk.Combobox(
            bar,
            textvariable=self.status,
            values=["全部"] + list(STATUS_LABELS.values()),
            width=12,
            state="readonly",
        ).pack(side="left")
        self.keyword = tk.StringVar()
        tk.Entry(bar, textvariable=self.keyword, width=20).pack(side="left", padx=8)
        button(bar, "筛选", self.refresh, kind="ghost").pack(side="left")
        button(bar, "执行定时任务", self.app.run_scheduler, kind="ghost").pack(
            side="left", padx=8
        )
        self.hint = tk.Label(
            bar,
            text="",
            bg=theme.CANVAS,
            fg=theme.MUTED,
            font=(self.app.family, -12),
        )
        self.hint.pack(side="right")

        body = tk.Frame(self, bg=theme.CANVAS)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)
        card = Card(body, padding=0)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.table = DataTable(
            card.body,
            [
                ("order_no", "订单号", 132, "w"),
                ("room", "房型", 85, "w"),
                ("stay", "入住 → 退房", 105, "w"),
                ("rooms", "间", 30, "center"),
                ("guest", "入住人", 60, "w"),
                ("total", "总价", 75, "e"),
                ("status", "状态", 92, "center"),
            ],
            height=14,
            on_select=self._select,
        )
        self.table.pack(fill="both", expand=True)
        self.detail_card = Card(body, padding=0)
        self.detail_card.grid(row=0, column=1, sticky="nsew")
        self.detail = tk.Frame(self.detail_card.body, bg=theme.WHITE)
        self.detail.pack(fill="both", expand=True)
        self._render_empty()

    def refresh(self) -> None:
        status = None
        for key, text in STATUS_LABELS.items():
            if text == self.status.get():
                status = key
        orders = self.services.orders.list_for_staff(
            self.app.session, status=status, keyword=self.keyword.get().strip()
        )
        rows = []
        for order in orders:
            room = self.services.ctx.repos.room_types.by_id(order.room_type_id)
            guest = order.guests[0].name if order.guests else "—"
            rows.append(
                {
                    "order_no": order.order_no,
                    "room": room.name if room else "—",
                    "stay": (
                        f"{order.check_in:%m-%d} → {order.check_out:%m-%d}"
                    ),
                    "rooms": order.room_count,
                    "guest": guest,
                    "total": format_money(order.total_cents),
                    "status": STATUS_LABELS.get(order.status, order.status.value),
                    "_order": order,
                }
            )
        self.table.set_rows(rows)
        self.hint.configure(text=f"共 {len(rows)} 张订单")
        if rows:
            self.table.select_first()
        else:
            self._render_empty("当前筛选条件下没有订单")

    def _select(self, row: dict) -> None:
        self._order = row["_order"]
        self._render_detail(self._order)

    def _render_empty(self, message: str = "选择左侧订单查看可执行操作") -> None:
        for child in self.detail.winfo_children():
            child.destroy()
        box = tk.Frame(self.detail, bg=theme.WHITE)
        box.pack(fill="both", expand=True, padx=20, pady=20)
        title(box, "订单详情").pack(fill="x")
        text_label(box, message, fg=theme.MUTED, size=9, wraplength=300).pack(
            fill="x", pady=(10, 0)
        )

    def _render_detail(self, order) -> None:
        for child in self.detail.winfo_children():
            child.destroy()
        box = tk.Frame(self.detail, bg=theme.WHITE)
        box.pack(fill="both", expand=True, padx=18, pady=16)
        head = tk.Frame(box, bg=theme.WHITE)
        head.pack(fill="x")
        title(head, order.order_no, size=12).pack(side="left")
        Badge(head, order.status.value).pack(side="right")
        room = self.services.ctx.repos.room_types.by_id(order.room_type_id)
        text_label(
            box,
            f"{room.name if room else '—'} · {order.room_count} 间 · "
            f"{order.check_in} → {order.check_out}",
            fg=theme.MUTED,
            size=9,
        ).pack(fill="x", pady=(4, 8))
        for label, value in (
            ("总价", format_money(order.total_cents)),
            ("入住人", "、".join(g.name for g in order.guests) or "—"),
            ("联系电话", "、".join(g.masked_phone for g in order.guests) or "—"),
            ("创建时间", order.created_at.strftime("%m-%d %H:%M") if order.created_at else "—"),
            (
                "确认截止",
                order.confirm_deadline.strftime("%m-%d %H:%M")
                if order.confirm_deadline
                else "—",
            ),
        ):
            line = tk.Frame(box, bg=theme.WHITE)
            line.pack(fill="x", pady=1)
            field_label(line, label, bg=theme.WHITE).pack(side="left")
            text_label(line, value, size=9).pack(side="right")
        if order.reject_reason:
            text_label(
                box,
                f"拒绝：{order.reject_reason} {order.reject_note}",
                fg=theme.DANGER,
                size=9,
                wraplength=300,
            ).pack(fill="x", pady=(4, 0))
        tk.Frame(box, bg=theme.LINE, height=1).pack(fill="x", pady=8)
        field_label(box, "每晚明细").pack(fill="x")
        for night in order.nights:
            line = tk.Frame(box, bg=theme.WHITE)
            line.pack(fill="x", pady=1)
            text_label(
                line, f"{night.day} × {night.room_count}", fg=theme.MUTED, size=9
            ).pack(side="left")
            text_label(line, format_money(night.subtotal_cents), size=9).pack(side="right")
        refunds = self.services.orders.refunds(self.app.session, order.order_no)
        if refunds:
            tk.Frame(box, bg=theme.LINE, height=1).pack(fill="x", pady=8)
            field_label(box, "退款记录").pack(fill="x")
            for refund in refunds:
                line = tk.Frame(box, bg=theme.WHITE)
                line.pack(fill="x", pady=2)
                text_label(
                    line,
                    f"{refund.event_type} 应退 {format_money(refund.refundable_cents)}",
                    fg=theme.MUTED,
                    size=8,
                ).pack(side="left")
                if refund.status is RefundStatus.PENDING_OFFLINE:
                    tk.Label(
                        line,
                        text="标记已退",
                        bg=theme.WHITE,
                        fg=theme.PINE,
                        font=(self.app.family, -11, "underline"),
                        cursor="hand2",
                    ).pack(side="right")
        actions = tk.Frame(box, bg=theme.WHITE)
        actions.pack(fill="x", side="bottom", pady=(12, 0))
        role = self.app.session.user.role
        if order.status is OrderStatus.PENDING:
            button(actions, "确认订单", self._confirm).pack(side="right")
            button(actions, "拒绝", self._reject, kind="danger").pack(
                side="right", padx=(0, 8)
            )
        elif order.status is OrderStatus.CONFIRMED:
            button(actions, "办理入住", self._check_in).pack(side="right")
            if role is Role.MANAGER:
                button(actions, "酒店取消", self._hotel_cancel, kind="danger").pack(
                    side="right", padx=(0, 8)
                )
        elif order.status is OrderStatus.CHECKED_IN:
            button(actions, "办理退房", self._check_out).pack(side="right")
        if refunds:
            button(actions, "处理退款", self._refunds, kind="ghost").pack(
                side="left"
            )

    def _confirm(self) -> None:
        if self._order is None:
            return
        try:
            self.services.orders.confirm(self.app.session, self._order.order_no)
        except DomainError as exc:
            messagebox.showerror("确认失败", exc.message)
            return
        self.app.toast(f"{self._order.order_no} 已确认")
        self.refresh()

    def _reject(self) -> None:
        if self._order is None:
            return
        RejectDialog(self, self._order, on_success=self.refresh)

    def _check_in(self) -> None:
        if self._order is None:
            return
        order = self._order
        today = self.services.ctx.clock.now().date()
        reason = ""
        if today < order.check_in:
            reason = simpledialog.askstring(
                "提前入住", "未到入住日，需店长放行。请填写原因：", parent=self
            ) or ""
            if not reason.strip():
                return
        try:
            self.services.orders.check_in(
                self.app.session, order.order_no, early_reason=reason
            )
        except DomainError as exc:
            messagebox.showerror("入住失败", exc.message)
            return
        self.app.toast("已办理入住")
        self.refresh()

    def _check_out(self) -> None:
        if self._order is None:
            return
        CheckoutDialog(self, self._order, on_success=self.refresh)

    def _hotel_cancel(self) -> None:
        if self._order is None:
            return
        note = simpledialog.askstring(
            "酒店取消",
            "仅用于酒店停业/无法接待，将全额退款。请填写原因：",
            parent=self,
        )
        if not note:
            return
        try:
            self.services.orders.cancel_by_hotel(
                self.app.session, self._order.order_no, note
            )
        except DomainError as exc:
            messagebox.showerror("取消失败", exc.message)
            return
        self.app.toast("已按酒店原因取消，全额可退")
        self.refresh()

    def _refunds(self) -> None:
        if self._order is None:
            return
        RefundDialog(self, self._order, on_success=self.refresh)


class RejectDialog(tk.Toplevel):
    def __init__(self, view: WorkbenchView, order, *, on_success) -> None:
        super().__init__(view)
        self.view = view
        self.order = order
        self.on_success = on_success
        self.title(f"拒绝订单 {order.order_no}")
        self.geometry("420x320")
        self.configure(bg=theme.WHITE)
        self.transient(view.winfo_toplevel())
        self.grab_set()
        self.reason = tk.StringVar(value=RejectReason.SOLD_OUT.value)
        body = tk.Frame(self, bg=theme.WHITE)
        body.pack(fill="both", expand=True, padx=20, pady=16)
        title(body, "拒绝原因").pack(fill="x")
        ttk.Combobox(
            body,
            textvariable=self.reason,
            values=[item.value for item in RejectReason],
            state="readonly",
        ).pack(fill="x", pady=(8, 10))
        field_label(body, "说明（选择“其他”时必填）").pack(fill="x")
        self.note = tk.Text(body, height=5, relief="flat", highlightthickness=1,
                            highlightbackground=theme.LINE, highlightcolor=theme.PINE)
        self.note.pack(fill="x", pady=(4, 6))
        self.error = tk.Label(
            body, text="", bg=theme.WHITE, fg=theme.DANGER,
            font=(self.view.app.family, -12), anchor="w",
        )
        self.error.pack(fill="x")
        actions = tk.Frame(body, bg=theme.WHITE)
        actions.pack(fill="x", side="bottom")
        button(actions, "取消", self.destroy, kind="ghost").pack(side="right")
        button(actions, "确认拒绝", self._submit, kind="danger").pack(
            side="right", padx=(0, 8)
        )

    def _submit(self) -> None:
        try:
            reason = RejectReason(self.reason.get())
        except ValueError:
            self.error.configure(text="请选择拒绝原因")
            return
        try:
            self.view.services.orders.reject(
                self.view.app.session,
                self.order.order_no,
                reason=reason,
                note=self.note.get("1.0", "end").strip(),
            )
        except DomainError as exc:
            self.error.configure(text=exc.message)
            return
        self.destroy()
        self.on_success()
        self.view.app.toast("订单已拒绝，库存已释放")


class CheckoutDialog(tk.Toplevel):
    def __init__(self, view: WorkbenchView, order, *, on_success) -> None:
        super().__init__(view)
        self.view = view
        self.order = order
        self.on_success = on_success
        self.title(f"办理退房 {order.order_no}")
        self.geometry("400x260")
        self.configure(bg=theme.WHITE)
        self.transient(view.winfo_toplevel())
        self.grab_set()
        today = view.services.ctx.clock.now().date()
        self.actual = tk.StringVar(value=today.isoformat())
        body = tk.Frame(self, bg=theme.WHITE)
        body.pack(fill="both", expand=True, padx=20, pady=16)
        title(body, "退房日期").pack(fill="x")
        text_label(
            body,
            f"原定退房 {order.check_out}。提前退房只释放未住间夜，且需店长确认。",
            fg=theme.MUTED, size=8, wraplength=340,
        ).pack(fill="x", pady=(4, 10))
        tk.Entry(body, textvariable=self.actual).pack(fill="x", ipady=5)
        self.error = tk.Label(
            body, text="", bg=theme.WHITE, fg=theme.DANGER,
            font=(view.app.family, -12), anchor="w", wraplength=340,
        )
        self.error.pack(fill="x", pady=(8, 0))
        actions = tk.Frame(body, bg=theme.WHITE)
        actions.pack(fill="x", side="bottom")
        button(actions, "取消", self.destroy, kind="ghost").pack(side="right")
        button(actions, "确认退房", self._submit).pack(side="right", padx=(0, 8))

    def _submit(self) -> None:
        try:
            actual = parse_date(self.actual.get(), "退房日期")
            order, refund = self.view.services.orders.check_out(
                self.view.app.session, self.order.order_no, actual_check_out=actual
            )
        except DomainError as exc:
            self.error.configure(text=exc.message)
            return
        except ValueError as exc:
            self.error.configure(text=str(exc))
            return
        self.destroy()
        self.on_success()
        message = f"已退房，状态 {order.status.value}"
        if refund is not None:
            message += f"；未住间夜应退 {format_money(refund.refundable_cents)}"
        messagebox.showinfo("退房完成", message)


class RefundDialog(tk.Toplevel):
    def __init__(self, view: WorkbenchView, order, *, on_success) -> None:
        super().__init__(view)
        self.view = view
        self.order = order
        self.on_success = on_success
        self.title(f"退款处理 {order.order_no}")
        self.geometry("480x340")
        self.configure(bg=theme.WHITE)
        self.transient(view.winfo_toplevel())
        self.grab_set()
        self.body = tk.Frame(self, bg=theme.WHITE)
        self.body.pack(fill="both", expand=True, padx=20, pady=16)
        self._render()

    def _render(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        title(self.body, "退款记录").pack(fill="x")
        text_label(
            self.body,
            "本期不接支付渠道，只记录应退金额与状态；线下退款后手动标记。",
            fg=theme.MUTED, size=8, wraplength=420,
        ).pack(fill="x", pady=(4, 10))
        refunds = self.view.services.orders.refunds(
            self.view.app.session, self.order.order_no
        )
        if not refunds:
            text_label(self.body, "没有退款记录", fg=theme.MUTED).pack(fill="x")
        for refund in refunds:
            row = tk.Frame(self.body, bg=theme.WHITE)
            row.pack(fill="x", pady=4)
            text_label(
                row,
                f"{refund.event_type} · 应退 {format_money(refund.refundable_cents)} "
                f"· 扣 {format_money(refund.deducted_cents)}",
                size=9,
            ).pack(side="left")
            Badge(row, refund.status.value).pack(side="right", padx=(8, 0))
            if refund.status is RefundStatus.PENDING_OFFLINE:
                button(
                    row,
                    "标记已退款",
                    lambda r=refund: self._mark(r.id),
                    kind="ghost",
                ).pack(side="right", padx=(8, 0))
        button(self.body, "关闭", self.destroy, kind="ghost").pack(
            side="bottom", anchor="e", pady=(10, 0)
        )

    def _mark(self, refund_id: str) -> None:
        try:
            self.view.services.orders.mark_refund(
                self.view.app.session, self.order.order_no, refund_id
            )
        except DomainError as exc:
            messagebox.showerror("标记失败", exc.message)
            return
        self.on_success()
        self._render()


class CalendarView(Page):
    title = "房态与价格"
    subtitle = "按房型 × 日期维护库存、价格与停售；停售保留原库存和价格"

    def build(self) -> None:
        self._row = None
        self.start = tk.StringVar(
            value=self.services.ctx.clock.now().date().isoformat()
        )
        self.days = tk.StringVar(value="14")
        bar = tk.Frame(self, bg=theme.CANVAS)
        bar.pack(fill="x", pady=(0, 10))
        field_label(bar, "起始日期", bg=theme.CANVAS).pack(side="left")
        tk.Entry(bar, textvariable=self.start, width=12).pack(side="left", padx=(6, 12))
        field_label(bar, "天数", bg=theme.CANVAS).pack(side="left")
        ttk.Spinbox(bar, from_=1, to=31, textvariable=self.days, width=5).pack(
            side="left", padx=(6, 12)
        )
        button(bar, "加载", self.refresh, kind="ghost").pack(side="left")
        if self.app.session.user.role is Role.MANAGER:
            button(bar, "批量设置", self._batch, kind="ghost").pack(
                side="left", padx=8
            )
        self.hint = tk.Label(
            bar, text="", bg=theme.CANVAS, fg=theme.MUTED,
            font=(self.app.family, -12),
        )
        self.hint.pack(side="right")

        body = tk.Frame(self, bg=theme.CANVAS)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        card = Card(body, padding=0)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.table = DataTable(
            card.body,
            [
                ("day", "日期", 100, "w"),
                ("room", "房型", 120, "w"),
                ("total", "可售", 60, "center"),
                ("sold", "已售", 60, "center"),
                ("remaining", "剩余", 60, "center"),
                ("price", "单价", 80, "e"),
                ("stop", "停售", 60, "center"),
            ],
            height=15,
            on_select=self._select,
        )
        self.table.pack(fill="both", expand=True)
        self.edit_card = Card(body, padding=0)
        self.edit_card.grid(row=0, column=1, sticky="nsew")
        self.edit = tk.Frame(self.edit_card.body, bg=theme.WHITE)
        self.edit.pack(fill="both", expand=True)
        self._render_empty()

    def refresh(self) -> None:
        try:
            start = parse_date(self.start.get(), "起始日期")
            days = int(self.days.get())
        except ValueError as exc:
            messagebox.showerror("条件不合法", str(exc))
            return
        rows = self.services.inventory.calendar(
            self.app.session, start=start, end=start + timedelta(days=days)
        )
        data = []
        for item in rows:
            data.append(
                {
                    "day": item.day.isoformat(),
                    "room": item.room_type_name,
                    "total": item.total_rooms,
                    "sold": item.sold_rooms,
                    "remaining": item.remaining,
                    "price": format_money(item.price_cents),
                    "stop": "停售" if item.stop_sale else "—",
                    "_row": item,
                }
            )
        self.table.set_rows(data)
        self.hint.configure(text=f"{len(rows)} 条房态记录")
        if data:
            self.table.select_first()
        else:
            self._render_empty("所选区间没有房态记录")

    def _select(self, row: dict) -> None:
        self._row = row["_row"]
        self._render_edit(self._row)

    def _render_empty(self, message: str = "选择左侧一行查看/编辑") -> None:
        for child in self.edit.winfo_children():
            child.destroy()
        box = tk.Frame(self.edit, bg=theme.WHITE)
        box.pack(fill="both", expand=True, padx=18, pady=18)
        title(box, "单日设置").pack(fill="x")
        text_label(box, message, fg=theme.MUTED, size=9, wraplength=220).pack(
            fill="x", pady=(10, 0)
        )

    def _render_edit(self, row) -> None:
        for child in self.edit.winfo_children():
            child.destroy()
        box = tk.Frame(self.edit, bg=theme.WHITE)
        box.pack(fill="both", expand=True, padx=18, pady=16)
        title(box, row.room_type_name, size=12).pack(fill="x")
        text_label(box, row.day.isoformat(), fg=theme.MUTED, size=9).pack(
            fill="x", pady=(2, 10)
        )
        text_label(
            box,
            f"已售 {row.sold_rooms} 间，剩余 {row.remaining} 间",
            fg=theme.MUTED, size=9,
        ).pack(fill="x")
        if self.app.session.user.role is not Role.MANAGER:
            text_label(
                box,
                "前台只读。价格、库存与停售由店长维护。",
                fg=theme.MUTED, size=9, wraplength=220,
            ).pack(fill="x", pady=(12, 0))
            return
        self.total_var = tk.StringVar(value=str(row.total_rooms))
        self.price_var = tk.StringVar(value=f"{row.price_cents / 100:.2f}")
        self.stop_var = tk.BooleanVar(value=row.stop_sale)
        for label, var in (("可售间数", self.total_var), ("单价（元）", self.price_var)):
            field_label(box, label).pack(fill="x", pady=(10, 2))
            tk.Entry(box, textvariable=var).pack(fill="x", ipady=5)
        ttk.Checkbutton(box, text="该日停售", variable=self.stop_var).pack(
            fill="x", pady=(10, 0)
        )
        self.error = tk.Label(
            box, text="", bg=theme.WHITE, fg=theme.DANGER,
            font=(self.app.family, -12), anchor="w", wraplength=220,
        )
        self.error.pack(fill="x", pady=(6, 0))
        button(box, "保存该日", self._save_day).pack(fill="x", pady=(10, 0))
        button(box, "停售所选日", self._toggle_stop, kind="danger").pack(
            fill="x", pady=(6, 0)
        )

    def _save_day(self) -> None:
        if self._row is None:
            return
        try:
            self.services.inventory.set_day(
                self.app.session,
                room_type_id=self._row.room_type_id,
                day=self._row.day,
                total_rooms=int(self.total_var.get()),
                price_cents=parse_yuan(self.price_var.get()),
                stop_sale=self.stop_var.get(),
            )
        except (DomainError, ValueError) as exc:
            self.error.configure(text=getattr(exc, "message", str(exc)))
            return
        self.refresh()

    def _toggle_stop(self) -> None:
        if self._row is None:
            return
        stop = not self._row.stop_sale
        try:
            self.services.inventory.set_stop_sale(
                self.app.session,
                room_type_id=self._row.room_type_id,
                start=self._row.day,
                end=self._row.day,
                stop=stop,
            )
        except DomainError as exc:
            self.error.configure(text=exc.message)
            return
        self.app.toast("已停售" if stop else "已恢复可订")
        self.refresh()

    def _batch(self) -> None:
        BatchInventoryDialog(self, on_success=self.refresh)


class BatchInventoryDialog(tk.Toplevel):
    def __init__(self, view: CalendarView, *, on_success) -> None:
        super().__init__(view)
        self.view = view
        self.on_success = on_success
        self.title("批量设置库存与价格")
        self.geometry("440x460")
        self.configure(bg=theme.WHITE)
        self.transient(view.winfo_toplevel())
        self.grab_set()
        today = view.services.ctx.clock.now().date()
        room_types = view.services.hotels.list_room_types(view.app.session.user.hotel_id)
        self.room = tk.StringVar(value=room_types[0].name if room_types else "")
        self.start = tk.StringVar(value=today.isoformat())
        self.end = tk.StringVar(value=(today + timedelta(days=6)).isoformat())
        self.total = tk.StringVar()
        self.price = tk.StringVar()
        self.stop = tk.StringVar(value="不改变")
        body = tk.Frame(self, bg=theme.WHITE)
        body.pack(fill="both", expand=True, padx=20, pady=16)
        title(body, "按日期段批量设置").pack(fill="x")
        text_label(
            body,
            "留空的字段不修改；已停售日期默认跳过。",
            fg=theme.MUTED, size=8,
        ).pack(fill="x", pady=(2, 8))
        field_label(body, "房型").pack(fill="x", pady=(6, 2))
        ttk.Combobox(
            body, textvariable=self.room,
            values=[item.name for item in room_types], state="readonly",
        ).pack(fill="x")
        for label, var in (
            ("开始日期", self.start),
            ("结束日期（含）", self.end),
            ("可售间数", self.total),
            ("单价（元）", self.price),
        ):
            field_label(body, label).pack(fill="x", pady=(8, 2))
            tk.Entry(body, textvariable=var).pack(fill="x", ipady=5)
        field_label(body, "停售").pack(fill="x", pady=(8, 2))
        ttk.Combobox(
            body, textvariable=self.stop,
            values=["不改变", "设为停售", "撤销停售"], state="readonly",
        ).pack(fill="x")
        self.error = tk.Label(
            body, text="", bg=theme.WHITE, fg=theme.DANGER,
            font=(view.app.family, -12), anchor="w", wraplength=380,
        )
        self.error.pack(fill="x", pady=(6, 0))
        actions = tk.Frame(body, bg=theme.WHITE)
        actions.pack(fill="x", side="bottom")
        button(actions, "取消", self.destroy, kind="ghost").pack(side="right")
        button(actions, "应用", self._submit).pack(side="right", padx=(0, 8))
        self._room_types = room_types

    def _submit(self) -> None:
        chosen = next((r for r in self._room_types if r.name == self.room.get()), None)
        if chosen is None:
            self.error.configure(text="请选择房型")
            return
        stop_value = {"不改变": None, "设为停售": True, "撤销停售": False}[self.stop.get()]
        try:
            result = self.view.services.inventory.batch_set(
                self.view.app.session,
                room_type_id=chosen.id,
                start=parse_date(self.start.get(), "开始日期"),
                end=parse_date(self.end.get(), "结束日期"),
                total_rooms=int(self.total.get()) if self.total.get().strip() else None,
                price_cents=parse_yuan(self.price.get()) if self.price.get().strip() else None,
                stop_sale=stop_value,
            )
        except (DomainError, ValueError) as exc:
            self.error.configure(text=getattr(exc, "message", str(exc)))
            return
        self.destroy()
        self.on_success()
        messagebox.showinfo(
            "批量设置完成",
            f"应用 {len(result['applied'])} 天，跳过 {len(result['skipped'])} 天"
            "（已停售或过去日期）。",
        )


class RoomTypesView(Page):
    title = "房型管理"
    subtitle = "可售间数不能低于未来已售出的最大间数；下架不影响历史订单"

    def build(self) -> None:
        bar = tk.Frame(self, bg=theme.CANVAS)
        bar.pack(fill="x", pady=(0, 10))
        button(bar, "新增房型", self._create).pack(side="left")
        button(bar, "编辑选中", self._edit, kind="ghost").pack(side="left", padx=8)
        button(bar, "上架 / 下架", self._toggle, kind="ghost").pack(side="left")
        self.hint = tk.Label(
            bar, text="", bg=theme.CANVAS, fg=theme.MUTED,
            font=(self.app.family, -12),
        )
        self.hint.pack(side="right")
        card = Card(self, padding=0)
        card.pack(fill="both", expand=True)
        self.table = DataTable(
            card.body,
            [
                ("name", "房型", 140, "w"),
                ("bed", "床型", 130, "w"),
                ("capacity", "可住", 50, "center"),
                ("total", "可售间数", 75, "center"),
                ("price", "基准价", 90, "e"),
                ("area", "面积", 60, "center"),
                ("window", "窗户", 60, "center"),
                ("onsale", "状态", 70, "center"),
            ],
            height=14,
            on_select=lambda row: setattr(self, "_row", row),
            on_double=lambda _row: self._edit(),
        )
        self.table.pack(fill="both", expand=True)

    def refresh(self) -> None:
        hotel_id = self.app.session.user.hotel_id
        room_types = self.services.hotels.list_room_types(hotel_id)
        rows = [
            {
                "name": item.name,
                "bed": item.bed_type,
                "capacity": f"{item.capacity} 人",
                "total": item.total_rooms,
                "price": format_money(item.base_price_cents),
                "area": f"{item.area_m2} ㎡",
                "window": "有窗" if item.has_window else "无窗",
                "onsale": "在售" if item.on_sale else "已下架",
                "_room": item,
            }
            for item in room_types
        ]
        self.table.set_rows(rows)
        self.hint.configure(text=f"共 {len(rows)} 个房型")

    def _selected(self):
        row = self.table.selected()
        return row["_room"] if row else None

    def _create(self) -> None:
        RoomTypeDialog(self, None, on_success=self.refresh)

    def _edit(self) -> None:
        room = self._selected()
        if room is None:
            messagebox.showinfo("提示", "请先选择一个房型")
            return
        RoomTypeDialog(self, room, on_success=self.refresh)

    def _toggle(self) -> None:
        room = self._selected()
        if room is None:
            return
        try:
            self.services.hotels.update_room_type(
                self.app.session, room.id, on_sale=not room.on_sale
            )
        except DomainError as exc:
            messagebox.showerror("操作失败", exc.message)
            return
        self.refresh()


class RoomTypeDialog(tk.Toplevel):
    def __init__(self, view: RoomTypesView, room, *, on_success) -> None:
        super().__init__(view)
        self.view = view
        self.room = room
        self.on_success = on_success
        self.title("编辑房型" if room else "新增房型")
        self.geometry("440x520")
        self.configure(bg=theme.WHITE)
        self.transient(view.winfo_toplevel())
        self.grab_set()
        self.vars = {
            "name": tk.StringVar(value=room.name if room else ""),
            "capacity": tk.StringVar(value=str(room.capacity) if room else "2"),
            "total": tk.StringVar(value=str(room.total_rooms) if room else "10"),
            "price": tk.StringVar(
                value=f"{room.base_price_cents / 100:.2f}" if room else "300.00"
            ),
            "bed": tk.StringVar(value=room.bed_type if room else "1.8 m 大床"),
            "area": tk.StringVar(value=str(room.area_m2) if room else "28"),
        }
        self.window = tk.BooleanVar(value=room.has_window if room else True)
        body = tk.Frame(self, bg=theme.WHITE)
        body.pack(fill="both", expand=True, padx=20, pady=16)
        title(body, "房型信息").pack(fill="x")
        for label, key in (
            ("房型名称", "name"),
            ("床型", "bed"),
            ("最多入住人数", "capacity"),
            ("可售房间数", "total"),
            ("基准价（元）", "price"),
            ("面积（㎡）", "area"),
        ):
            field_label(body, label).pack(fill="x", pady=(7, 2))
            tk.Entry(body, textvariable=self.vars[key]).pack(fill="x", ipady=5)
        ttk.Checkbutton(body, text="有窗", variable=self.window).pack(
            fill="x", pady=(10, 0)
        )
        self.error = tk.Label(
            body, text="", bg=theme.WHITE, fg=theme.DANGER,
            font=(view.app.family, -12), anchor="w", wraplength=380,
        )
        self.error.pack(fill="x", pady=(6, 0))
        actions = tk.Frame(body, bg=theme.WHITE)
        actions.pack(fill="x", side="bottom")
        button(actions, "取消", self.destroy, kind="ghost").pack(side="right")
        button(actions, "保存", self._submit).pack(side="right", padx=(0, 8))

    def _submit(self) -> None:
        try:
            payload = dict(
                name=self.vars["name"].get().strip(),
                capacity=int(self.vars["capacity"].get()),
                total_rooms=int(self.vars["total"].get()),
                base_price_cents=parse_yuan(self.vars["price"].get()),
                bed_type=self.vars["bed"].get().strip(),
                area_m2=int(self.vars["area"].get()),
                has_window=self.window.get(),
            )
            if self.room is None:
                self.view.services.hotels.create_room_type(
                    self.view.app.session, **payload
                )
            else:
                self.view.services.hotels.update_room_type(
                    self.view.app.session, self.room.id, **payload
                )
        except (DomainError, ValueError) as exc:
            self.error.configure(text=getattr(exc, "message", str(exc)))
            return
        self.destroy()
        self.on_success()
