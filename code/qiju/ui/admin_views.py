"""平台端：酒店审核、全平台订单、确认时限。"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ..domain.enums import AuditStatus, BusinessStatus, OrderStatus
from ..domain.errors import DomainError
from ..domain.money import format_money
from . import theme
from .app import Page
from .customer_views import STATUS_LABELS
from .staff_views import RefundDialog
from .widgets import Badge, Card, DataTable, button, field_label, text_label, title


class HotelAuditView(Page):
    title = "酒店审核"
    subtitle = "首次入驻审核通过后才可上架；关键资料变更审核期间继续使用原资料"

    def build(self) -> None:
        bar = tk.Frame(self, bg=theme.CANVAS)
        bar.pack(fill="x", pady=(0, 10))
        button(bar, "录入酒店并签发邀请码", self._create_hotel).pack(side="left")
        button(bar, "刷新", self.refresh, kind="ghost").pack(side="left", padx=8)
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
                ("name", "酒店", 150, "w"),
                ("city", "城市", 70, "w"),
                ("audit", "审核", 80, "center"),
                ("business", "营业", 90, "center"),
                ("pending", "变更", 70, "center"),
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
        hotels = self.services.hotels.list_hotels(self.app.session)
        rows = []
        for hotel in hotels:
            rows.append(
                {
                    "name": hotel.name,
                    "city": hotel.city,
                    "audit": {
                        AuditStatus.PENDING: "待审核",
                        AuditStatus.APPROVED: "已通过",
                        AuditStatus.REJECTED: "已驳回",
                    }.get(hotel.audit_status, hotel.audit_status.value),
                    "business": "营业中"
                    if hotel.business_status is BusinessStatus.OPEN
                    else "停业",
                    "pending": "待审核" if hotel.pending_profile else "—",
                    "_hotel": hotel,
                }
            )
        self.table.set_rows(rows)
        if rows:
            self.table.select_first()

    def _select(self, row: dict) -> None:
        self._hotel = row["_hotel"]
        self._render(self._hotel)

    def _render_empty(self, message: str = "选择酒店查看资料与审核操作") -> None:
        for child in self.detail.winfo_children():
            child.destroy()
        box = tk.Frame(self.detail, bg=theme.WHITE)
        box.pack(fill="both", expand=True, padx=18, pady=18)
        title(box, "酒店资料").pack(fill="x")
        text_label(box, message, fg=theme.MUTED, size=9, wraplength=300).pack(
            fill="x", pady=(10, 0)
        )

    def _render(self, hotel) -> None:
        for child in self.detail.winfo_children():
            child.destroy()
        box = tk.Frame(self.detail, bg=theme.WHITE)
        box.pack(fill="both", expand=True, padx=18, pady=16)
        title(box, hotel.name, size=14).pack(fill="x")
        text_label(
            box,
            f"{hotel.city} · {hotel.address} · {hotel.phone}",
            fg=theme.MUTED, size=9, wraplength=300,
        ).pack(fill="x", pady=(2, 8))
        for label, value in (
            ("审核状态", hotel.audit_status.value),
            ("营业状态", hotel.business_status.value),
            ("入住/退房", f"{hotel.checkin_time} / {hotel.checkout_time}"),
            ("变更审核", "有，待处理" if hotel.pending_profile else "无"),
        ):
            line = tk.Frame(box, bg=theme.WHITE)
            line.pack(fill="x", pady=1)
            field_label(line, label, bg=theme.WHITE).pack(side="left")
            text_label(line, value, size=9).pack(side="right")
        if hotel.audit_note:
            text_label(
                box, hotel.audit_note, fg=theme.MUTED, size=8, wraplength=300
            ).pack(fill="x", pady=(4, 0))
        if hotel.pending_profile:
            text_label(
                box,
                "关键资料变更审核中：对外仍展示旧资料，审核通过后切换。",
                fg=theme.BRASS, size=8, wraplength=300,
            ).pack(fill="x", pady=(6, 0))
        text_label(
            box, hotel.description or "", fg=theme.MUTED, size=9, wraplength=300
        ).pack(fill="x", pady=(8, 0))
        actions = tk.Frame(box, bg=theme.WHITE)
        actions.pack(fill="x", side="bottom", pady=(12, 0))
        if hotel.audit_status is AuditStatus.PENDING or hotel.pending_profile:
            button(actions, "审核通过", self._approve).pack(side="right")
            button(actions, "驳回", self._reject, kind="danger").pack(
                side="right", padx=(0, 8)
            )
        button(actions, "签发邀请码", self._issue, kind="ghost").pack(side="left")

    def _approve(self) -> None:
        self._audit(True)

    def _reject(self) -> None:
        self._audit(False)

    def _audit(self, approve: bool) -> None:
        if not hasattr(self, "_hotel"):
            return
        note = ""
        if not approve:
            from tkinter import simpledialog

            note = simpledialog.askstring(
                "驳回原因", "请填写驳回原因（必填）：", parent=self
            ) or ""
            if not note.strip():
                return
        try:
            self.services.hotels.audit_hotel(
                self.app.session, self._hotel.id, approve=approve, note=note
            )
        except DomainError as exc:
            messagebox.showerror("审核失败", exc.message)
            return
        self.refresh()
        self.app.toast("审核通过" if approve else "已驳回")

    def _issue(self) -> None:
        if not hasattr(self, "_hotel"):
            return
        try:
            code = self.services.auth.issue_invitation(
                self.app.session, self._hotel.id
            )
        except DomainError as exc:
            messagebox.showerror("签发失败", exc.message)
            return
        messagebox.showinfo(
            "邀请码已签发",
            f"酒店：{self._hotel.name}\n邀请码：{code.code}\n"
            f"有效期至：{code.expires_at:%Y-%m-%d %H:%M}",
        )

    def _create_hotel(self) -> None:
        CreateHotelDialog(self, on_success=self.refresh)


class CreateHotelDialog(tk.Toplevel):
    def __init__(self, view: HotelAuditView, *, on_success) -> None:
        super().__init__(view)
        self.view = view
        self.on_success = on_success
        self.title("录入酒店")
        self.geometry("460x480")
        self.configure(bg=theme.WHITE)
        self.transient(view.winfo_toplevel())
        self.grab_set()
        self.vars = {
            key: tk.StringVar()
            for key in ("name", "city", "address", "phone", "description")
        }
        body = tk.Frame(self, bg=theme.WHITE)
        body.pack(fill="both", expand=True, padx=20, pady=16)
        title(body, "新酒店资料").pack(fill="x")
        text_label(
            body, "保存后状态为待审核，并自动签发一枚店长邀请码。",
            fg=theme.MUTED, size=8,
        ).pack(fill="x", pady=(2, 8))
        for label, key in (
            ("酒店名称", "name"),
            ("城市", "city"),
            ("地址", "address"),
            ("联系电话", "phone"),
            ("简介", "description"),
        ):
            field_label(body, label).pack(fill="x", pady=(6, 2))
            tk.Entry(body, textvariable=self.vars[key]).pack(fill="x", ipady=5)
        self.error = tk.Label(
            body, text="", bg=theme.WHITE, fg=theme.DANGER,
            font=(view.app.family, -12), anchor="w", wraplength=400,
        )
        self.error.pack(fill="x", pady=(6, 0))
        actions = tk.Frame(body, bg=theme.WHITE)
        actions.pack(fill="x", side="bottom")
        button(actions, "取消", self.destroy, kind="ghost").pack(side="right")
        button(actions, "保存并签发", self._submit).pack(side="right", padx=(0, 8))

    def _submit(self) -> None:
        try:
            hotel = self.view.services.auth.create_hotel(
                self.view.app.session,
                name=self.vars["name"].get(),
                city=self.vars["city"].get(),
                address=self.vars["address"].get(),
                phone=self.vars["phone"].get(),
                description=self.vars["description"].get(),
            )
            code = self.view.services.auth.issue_invitation(
                self.view.app.session, hotel.id
            )
        except (DomainError, ValueError) as exc:
            self.error.configure(text=getattr(exc, "message", str(exc)))
            return
        self.destroy()
        self.on_success()
        messagebox.showinfo(
            "已录入",
            f"{hotel.name} 已创建，状态待审核。\n店长邀请码：{code.code}",
        )


class AllOrdersView(Page):
    title = "全平台订单"
    subtitle = "平台管理员可强制取消，但必须填写原因；不能直接改金额、库存和价格"

    def build(self) -> None:
        bar = tk.Frame(self, bg=theme.CANVAS)
        bar.pack(fill="x", pady=(0, 10))
        self.status = tk.StringVar(value="全部")
        ttk.Combobox(
            bar, textvariable=self.status,
            values=["全部"] + list(STATUS_LABELS.values()),
            width=12, state="readonly",
        ).pack(side="left")
        self.keyword = tk.StringVar()
        tk.Entry(bar, textvariable=self.keyword, width=22).pack(side="left", padx=8)
        button(bar, "筛选", self.refresh, kind="ghost").pack(side="left")
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
                ("order_no", "订单号", 140, "w"),
                ("hotel", "酒店", 115, "w"),
                ("stay", "入住 → 退房", 110, "w"),
                ("total", "总价", 80, "e"),
                ("status", "状态", 80, "center"),
                ("created", "创建", 85, "w"),
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
        orders = self.services.orders.list_all(
            self.app.session, keyword=self.keyword.get().strip()
        )
        if status is not None:
            orders = [item for item in orders if item.status is status]
        rows = []
        for order in orders:
            hotel = self.services.hotels.get_hotel(order.hotel_id)
            rows.append(
                {
                    "order_no": order.order_no,
                    "hotel": hotel.name if hotel else "—",
                    "stay": (
                        f"{order.check_in:%m-%d} → {order.check_out:%m-%d}"
                    ),
                    "total": format_money(order.total_cents),
                    "status": STATUS_LABELS.get(order.status, order.status.value),
                    "created": order.created_at.strftime("%m-%d %H:%M")
                    if order.created_at
                    else "—",
                    "_order": order,
                }
            )
        self.table.set_rows(rows)
        if rows:
            self.table.select_first()
        else:
            self._render_empty("没有符合条件的订单")

    def _select(self, row: dict) -> None:
        self._order = row["_order"]
        self._render(self._order)

    def _render_empty(self, message: str = "选择订单查看详情") -> None:
        for child in self.detail.winfo_children():
            child.destroy()
        box = tk.Frame(self.detail, bg=theme.WHITE)
        box.pack(fill="both", expand=True, padx=18, pady=18)
        title(box, "订单详情").pack(fill="x")
        text_label(box, message, fg=theme.MUTED, size=9, wraplength=300).pack(
            fill="x", pady=(10, 0)
        )

    def _render(self, order) -> None:
        for child in self.detail.winfo_children():
            child.destroy()
        box = tk.Frame(self.detail, bg=theme.WHITE)
        box.pack(fill="both", expand=True, padx=18, pady=16)
        head = tk.Frame(box, bg=theme.WHITE)
        head.pack(fill="x")
        title(head, order.order_no, size=12).pack(side="left")
        Badge(head, order.status.value).pack(side="right")
        hotel = self.services.hotels.get_hotel(order.hotel_id)
        room = self.services.ctx.repos.room_types.by_id(order.room_type_id)
        text_label(
            box,
            f"{hotel.name if hotel else '—'} · {room.name if room else '—'} · "
            f"{order.check_in} → {order.check_out}",
            fg=theme.MUTED, size=9, wraplength=300,
        ).pack(fill="x", pady=(4, 8))
        for label, value in (
            ("总价", format_money(order.total_cents)),
            ("间数", f"{order.room_count} 间"),
            ("下单顾客", order.user_id[:8] + "…"),
            ("取消原因", order.cancel_reason or "—"),
        ):
            line = tk.Frame(box, bg=theme.WHITE)
            line.pack(fill="x", pady=1)
            field_label(line, label, bg=theme.WHITE).pack(side="left")
            text_label(line, value, size=9).pack(side="right")
        refunds = self.services.orders.refunds(self.app.session, order.order_no)
        if refunds:
            text_label(
                box,
                f"退款 {len(refunds)} 条，应退合计 "
                f"{format_money(sum(item.refundable_cents for item in refunds))}",
                fg=theme.MUTED, size=9,
            ).pack(fill="x", pady=(8, 0))
        actions = tk.Frame(box, bg=theme.WHITE)
        actions.pack(fill="x", side="bottom", pady=(12, 0))
        if order.status is OrderStatus.CONFIRMED:
            button(actions, "强制取消", self._force_cancel, kind="danger").pack(
                side="right"
            )
        if refunds:
            button(
                actions, "处理退款", lambda: RefundDialog(self, order, on_success=self.refresh),
                kind="ghost",
            ).pack(side="left")

    def _force_cancel(self) -> None:
        from tkinter import simpledialog

        reason = simpledialog.askstring(
            "强制取消",
            "必须填写原因（会记入日志，责任方为酒店/平台）：",
            parent=self,
        )
        if not reason or not reason.strip():
            return
        try:
            self.services.orders.force_cancel(
                self.app.session, self._order.order_no, reason
            )
        except DomainError as exc:
            messagebox.showerror("强制取消失败", exc.message)
            return
        self.refresh()
        self.app.toast("已强制取消并生成全额退款记录")


class PoliciesView(Page):
    title = "确认时限"
    subtitle = "默认 30 分钟，范围 15–60；只有平台管理员可改，店长只读"

    def build(self) -> None:
        bar = tk.Frame(self, bg=theme.CANVAS)
        bar.pack(fill="x", pady=(0, 10))
        field_label(bar, "确认时限（分钟）", bg=theme.CANVAS).pack(side="left")
        self.minutes = tk.StringVar(value="30")
        ttk.Spinbox(bar, from_=15, to=60, textvariable=self.minutes, width=6).pack(
            side="left", padx=(8, 8)
        )
        button(bar, "保存到选中酒店", self._save).pack(side="left")
        text_label(
            bar,
            "修改只影响之后创建的订单：订单创建时已把确认截止时间快照下来。",
            fg=theme.MUTED, size=8,
        ).pack(side="left", padx=14)
        card = Card(self, padding=0)
        card.pack(fill="both", expand=True)
        self.table = DataTable(
            card.body,
            [
                ("name", "酒店", 180, "w"),
                ("city", "城市", 100, "w"),
                ("audit", "审核", 100, "center"),
                ("timeout", "确认时限", 100, "center"),
            ],
            height=12,
            on_select=self._select,
        )
        self.table.pack(fill="both", expand=True)

    def refresh(self) -> None:
        rows = []
        for hotel in self.services.hotels.list_hotels(self.app.session):
            policy = self.services.hotels.get_policy(hotel.id)
            rows.append(
                {
                    "name": hotel.name,
                    "city": hotel.city,
                    "audit": "已通过" if hotel.audit_status.value == "APPROVED" else "待审核",
                    "timeout": f"{policy.timeout_minutes} 分钟",
                    "_hotel": hotel,
                    "_policy": policy,
                }
            )
        self.table.set_rows(rows)
        if rows:
            self.table.select_first()

    def _select(self, row: dict) -> None:
        self._row = row
        self.minutes.set(str(row["_policy"].timeout_minutes))

    def _save(self) -> None:
        row = self.table.selected()
        if not row:
            messagebox.showinfo("提示", "请先选择酒店")
            return
        try:
            self.services.hotels.update_policy(
                self.app.session, row["_hotel"].id, int(self.minutes.get())
            )
        except (DomainError, ValueError) as exc:
            messagebox.showerror("保存失败", getattr(exc, "message", str(exc)))
            return
        self.refresh()
        self.app.toast("确认时限已更新")
