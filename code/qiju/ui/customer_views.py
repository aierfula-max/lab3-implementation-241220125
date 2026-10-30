"""顾客端：搜索、房型详情、下单、我的订单与改单/取消。"""

from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from tkinter import messagebox, ttk
from uuid import uuid4

from ..application.booking_service import BookingRequest, SearchResult
from ..domain.entities import Guest
from ..domain.enums import OrderStatus
from ..domain.errors import DomainError
from ..domain.money import format_money, parse_yuan
from . import theme
from .app import Page
from .widgets import Badge, Card, DataTable, button, field_label, text_label, title

STATUS_LABELS = {
    OrderStatus.PENDING: "待确认",
    OrderStatus.CONFIRMED: "已确认",
    OrderStatus.CHECKED_IN: "已入住",
    OrderStatus.COMPLETED: "已完成",
    OrderStatus.CANCELED: "已取消",
    OrderStatus.REJECTED: "已拒绝",
    OrderStatus.NO_SHOW: "未入住关闭",
}


def parse_date(text: str, field: str = "日期") -> date:
    try:
        return date.fromisoformat(text.strip())
    except ValueError as exc:
        raise ValueError(f"{field}格式应为 YYYY-MM-DD") from exc


class SearchView(Page):
    title = "搜索可订房型"
    subtitle = "按城市、日期、人数与价格筛选；总价为整段入住的每晚价格之和"

    def build(self) -> None:
        self._selected: SearchResult | None = None
        today = self.services.ctx.clock.now().date()
        self._default_in = today + timedelta(days=1)
        self._default_out = today + timedelta(days=3)
        self._build_filters()
        body = tk.Frame(self, bg=theme.CANVAS)
        body.pack(fill="both", expand=True, pady=(12, 0))
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        table_card = Card(body, padding=0)
        table_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.table = DataTable(
            table_card.body,
            [
                ("hotel", "酒店", 120, "w"),
                ("room", "房型", 90, "w"),
                ("bed", "床型", 145, "w"),
                ("area", "面积", 50, "center"),
                ("price", "每晚起", 80, "e"),
                ("total", "总价", 85, "e"),
                ("remaining", "剩余", 55, "center"),
            ],
            height=14,
            on_select=self._select,
            on_double=lambda _row: self._open_booking(),
        )
        self.table.pack(fill="both", expand=True)

        self.detail_card = Card(body, padding=0)
        self.detail_card.grid(row=0, column=1, sticky="nsew")
        self.detail = tk.Frame(self.detail_card.body, bg=theme.WHITE)
        self.detail.pack(fill="both", expand=True)
        self._render_empty()

    def _build_filters(self) -> None:
        card = Card(self, padding=14)
        card.pack(fill="x")
        row = tk.Frame(card.body, bg=theme.WHITE)
        row.pack(fill="x")
        self.city = tk.StringVar(value="南京")
        self.check_in = tk.StringVar(value=self._default_in.isoformat())
        self.check_out = tk.StringVar(value=self._default_out.isoformat())
        self.guests = tk.StringVar(value="2")
        self.price_min = tk.StringVar()
        self.price_max = tk.StringVar()
        self.sort = tk.StringVar(value="可订优先")

        def group(label: str, factory) -> None:
            box = tk.Frame(row, bg=theme.WHITE)
            box.pack(side="left", padx=(0, 16))
            field_label(box, label).pack(fill="x")
            factory(box).pack(fill="x", pady=(3, 0))

        group(
            "城市",
            lambda box: ttk.Combobox(
                box,
                textvariable=self.city,
                values=["全部", "南京", "苏州"],
                width=8,
                state="readonly",
            ),
        )
        group("入住", lambda box: tk.Entry(box, textvariable=self.check_in, width=12))
        group("退房", lambda box: tk.Entry(box, textvariable=self.check_out, width=12))
        group(
            "人数",
            lambda box: ttk.Spinbox(
                box, from_=1, to=6, textvariable=self.guests, width=5
            ),
        )
        group("最低总价", lambda box: tk.Entry(box, textvariable=self.price_min, width=9))
        group("最高总价", lambda box: tk.Entry(box, textvariable=self.price_max, width=9))
        group(
            "排序",
            lambda box: ttk.Combobox(
                box,
                textvariable=self.sort,
                values=["可订优先", "价格从低到高", "价格从高到低"],
                width=12,
                state="readonly",
            ),
        )
        button(row, "查询", self.refresh).pack(side="left", pady=(14, 0))
        button(row, "快速填明日", self._fill_tomorrow, kind="ghost").pack(
            side="left", padx=(8, 0), pady=(14, 0)
        )

    def _fill_tomorrow(self) -> None:
        today = self.services.ctx.clock.now().date()
        self.check_in.set((today + timedelta(days=1)).isoformat())
        self.check_out.set((today + timedelta(days=3)).isoformat())

    def refresh(self) -> None:
        try:
            check_in = parse_date(self.check_in.get(), "入住日期")
            check_out = parse_date(self.check_out.get(), "退房日期")
            low = parse_yuan(self.price_min.get()) if self.price_min.get().strip() else None
            high = parse_yuan(self.price_max.get()) if self.price_max.get().strip() else None
            guests = int(self.guests.get())
        except ValueError as exc:
            messagebox.showerror("条件不合法", str(exc))
            return
        sort_key = {
            "可订优先": "available",
            "价格从低到高": "price_asc",
            "价格从高到低": "price_desc",
        }.get(self.sort.get(), "available")
        try:
            results = self.services.booking.search(
                city=None if self.city.get() == "全部" else self.city.get(),
                check_in=check_in,
                check_out=check_out,
                guests=guests,
                price_min=low,
                price_max=high,
                sort=sort_key,
            )
        except DomainError as exc:
            messagebox.showerror("查询失败", exc.message)
            return
        self._results = results
        rows = [
            {
                "hotel": item.hotel.name,
                "room": item.room_type.name,
                "bed": item.room_type.bed_type,
                "area": f"{item.room_type.area_m2} ㎡",
                "price": format_money(item.price_cents),
                "total": format_money(item.total_cents),
                "remaining": f"{item.remaining} 间",
                "_result": item,
            }
            for item in results
        ]
        self.table.set_rows(rows)
        if rows:
            self.table.select_first()
        else:
            self._render_empty("该条件下没有可订房型，试试换日期或放宽价格")
        self.app.toast(f"共找到 {len(results)} 个可订房型")

    def _select(self, row: dict) -> None:
        self._selected = row["_result"]
        self._render_detail(self._selected)

    def _render_empty(self, message: str = "从左侧选择房型查看每晚价格") -> None:
        for child in self.detail.winfo_children():
            child.destroy()
        box = tk.Frame(self.detail, bg=theme.WHITE)
        box.pack(fill="both", expand=True, padx=22, pady=22)
        title(box, "房型详情").pack(fill="x")
        text_label(box, message, fg=theme.MUTED, size=9, wraplength=320).pack(
            fill="x", pady=(10, 0)
        )

    def _render_detail(self, result: SearchResult) -> None:
        for child in self.detail.winfo_children():
            child.destroy()
        box = tk.Frame(self.detail, bg=theme.WHITE)
        box.pack(fill="both", expand=True, padx=22, pady=20)
        title(box, result.room_type.name, size=16).pack(fill="x")
        text_label(
            box,
            f"{result.hotel.name} · {result.hotel.city} · 最多 {result.room_type.capacity} 人",
            fg=theme.MUTED,
            size=9,
        ).pack(fill="x", pady=(2, 10))
        info = tk.Frame(box, bg=theme.WHITE)
        info.pack(fill="x")
        for label, value in (
            ("床型", result.room_type.bed_type),
            ("面积", f"{result.room_type.area_m2} ㎡"),
            ("窗户", "有窗" if result.room_type.has_window else "无窗"),
            ("剩余", f"{result.remaining} 间"),
        ):
            cell = tk.Frame(info, bg=theme.WHITE)
            cell.pack(side="left", expand=True, fill="x")
            field_label(cell, label).pack(fill="x")
            text_label(cell, value, size=10).pack(fill="x")
        tk.Frame(box, bg=theme.LINE, height=1).pack(fill="x", pady=12)
        field_label(box, "每晚价格").pack(fill="x")
        for day, price in result.nights:
            line = tk.Frame(box, bg=theme.WHITE)
            line.pack(fill="x", pady=1)
            text_label(line, day.strftime("%m-%d %a"), fg=theme.MUTED, size=9).pack(
                side="left"
            )
            text_label(line, format_money(price), size=10).pack(side="right")
        total = tk.Frame(box, bg=theme.PINE_SOFT)
        total.pack(fill="x", pady=(10, 12))
        tk.Label(
            total,
            text=f"{len(result.nights)} 晚合计",
            bg=theme.PINE_SOFT,
            fg=theme.PINE_DARK,
            font=(self.app.family, -12),
        ).pack(side="left", padx=10, pady=8)
        tk.Label(
            total,
            text=format_money(result.total_cents),
            bg=theme.PINE_SOFT,
            fg=theme.PINE_DARK,
            font=(self.app.family, -19, "bold"),
        ).pack(side="right", padx=10)
        text_label(
            box,
            "价格与库存为查询时刻快照；提交订单时会在同一事务内再次校验并扣减。",
            fg=theme.MUTED,
            size=8,
            wraplength=320,
        ).pack(fill="x", pady=(0, 10))
        button(box, "立即预订", self._open_booking).pack(fill="x")

    def _open_booking(self) -> None:
        if self._selected is None:
            messagebox.showinfo("提示", "请先选择一个可订房型")
            return
        BookingDialog(self, self._selected, on_success=self._booked)

    def _booked(self, order_no: str) -> None:
        self.app.toast(f"预订成功，订单号 {order_no}", error=False)
        self.refresh()
        messagebox.showinfo(
            "预订成功",
            f"订单 {order_no} 已创建，状态为“待确认”。\n"
            "酒店确认前可在“我的订单”中免费取消。",
        )


class BookingDialog(tk.Toplevel):
    """填写入住人并提交订单。"""

    def __init__(self, view: SearchView, result: SearchResult, *, on_success) -> None:
        super().__init__(view)
        self.view = view
        self.result = result
        self.on_success = on_success
        self.title("填写预订信息")
        self.geometry("460x640")
        self.configure(bg=theme.WHITE)
        self.transient(view.winfo_toplevel())
        self.grab_set()
        self.room_count = tk.StringVar(value="1")
        self.guests: list[tuple[tk.StringVar, tk.StringVar]] = []
        self._build()
        self._add_guest("", "")

    def _build(self) -> None:
        head = tk.Frame(self, bg=theme.PINE_DARK)
        head.pack(fill="x")
        tk.Label(
            head,
            text=self.result.room_type.name,
            bg=theme.PINE_DARK,
            fg=theme.WHITE,
            font=(self.view.app.family, -20, "bold"),
            anchor="w",
        ).pack(fill="x", padx=20, pady=(16, 2))
        tk.Label(
            head,
            text=(
                f"{self.result.hotel.name} · "
                f"{self.result.nights[0][0]} 至 {self.result.nights[-1][0]} 次日退房"
            ),
            bg=theme.PINE_DARK,
            fg="#C9DCD4",
            font=(self.view.app.family, -12),
            anchor="w",
        ).pack(fill="x", padx=20, pady=(0, 16))

        body = tk.Frame(self, bg=theme.WHITE)
        body.pack(fill="both", expand=True, padx=20, pady=14)
        row = tk.Frame(body, bg=theme.WHITE)
        row.pack(fill="x")
        field_label(row, "间数").pack(side="left")
        ttk.Spinbox(
            row, from_=1, to=max(1, self.result.remaining),
            textvariable=self.room_count, width=5, command=self._update_total,
        ).pack(side="left", padx=(8, 16))
        field_label(row, "最多入住").pack(side="left")
        text_label(
            row,
            f"{self.result.room_type.capacity} 人/间",
            size=9,
            fg=theme.MUTED,
        ).pack(side="left", padx=(8, 0))

        tk.Frame(body, bg=theme.LINE, height=1).pack(fill="x", pady=10)
        heading = tk.Frame(body, bg=theme.WHITE)
        heading.pack(fill="x")
        title(heading, "入住人", size=11).pack(side="left")
        button(heading, "添加", self._add_guest_row, kind="ghost").pack(side="right")
        header = tk.Frame(body, bg=theme.WHITE)
        header.pack(fill="x", pady=(6, 0))
        tk.Label(
            header,
            text="姓名",
            bg=theme.WHITE,
            fg=theme.MUTED,
            font=(self.view.app.family, -12),
            anchor="w",
        ).pack(side="left", fill="x", expand=True)
        tk.Label(
            header,
            text="手机号（11 位）",
            bg=theme.WHITE,
            fg=theme.MUTED,
            font=(self.view.app.family, -12),
            anchor="w",
            width=14,
        ).pack(side="left")
        tk.Label(
            header, text="", bg=theme.WHITE, width=4
        ).pack(side="left")
        self.guest_box = tk.Frame(body, bg=theme.WHITE)
        self.guest_box.pack(fill="x", pady=(2, 0))

        total = tk.Frame(body, bg=theme.PINE_SOFT)
        total.pack(fill="x", pady=12)
        self.total_label = tk.Label(
            total,
            text="",
            bg=theme.PINE_SOFT,
            fg=theme.PINE_DARK,
            font=(self.view.app.family, -18, "bold"),
            anchor="w",
        )
        self.total_label.pack(fill="x", padx=12, pady=8)
        self.error = tk.Label(
            body,
            text="",
            bg=theme.WHITE,
            fg=theme.DANGER,
            font=(self.view.app.family, -12),
            anchor="w",
            wraplength=400,
            justify="left",
        )
        self.error.pack(fill="x")
        text_label(
            body,
            "同一 request_id 重放返回原单；2 分钟内相同内容需二次确认。",
            fg=theme.MUTED,
            size=8,
            wraplength=380,
        ).pack(fill="x", pady=(4, 8))
        actions = tk.Frame(body, bg=theme.WHITE)
        actions.pack(fill="x", side="bottom")
        button(actions, "取消", self.destroy, kind="ghost").pack(side="right")
        button(actions, "提交预订", self._submit).pack(side="right", padx=(0, 8))
        self._update_total()

    def _add_guest(self, name: str, phone: str) -> None:
        row = tk.Frame(self.guest_box, bg=theme.WHITE)
        row.pack(fill="x", pady=3)
        name_var = tk.StringVar(value=name)
        phone_var = tk.StringVar(value=phone)
        name_entry = tk.Entry(row, textvariable=name_var, width=10)
        name_entry.pack(side="left", fill="x", expand=True, ipady=5)
        phone_entry = tk.Entry(row, textvariable=phone_var, width=14)
        phone_entry.pack(side="left", padx=6, ipady=5)
        remove = tk.Label(
            row,
            text="移除",
            bg=theme.WHITE,
            fg=theme.DANGER,
            font=(self.view.app.family, -11),
            cursor="hand2",
        )
        remove.pack(side="left")
        pair = (name_var, phone_var)
        self.guests.append(pair)
        remove.bind("<Button-1>", lambda _e, p=pair, r=row: self._remove_guest(p, r))

    def _add_guest_row(self) -> None:
        self._add_guest("", "")

    def _remove_guest(self, pair, row) -> None:
        if len(self.guests) <= 1:
            return
        self.guests.remove(pair)
        row.destroy()

    def _current_quote(self):
        rooms = int(self.room_count.get() or 1)
        return self.view.services.booking.quote(
            room_type_id=self.result.room_type.id,
            check_in=self.result.nights[0][0],
            check_out=self.result.nights[-1][0] + timedelta(days=1),
            room_count=rooms,
            guests=max(1, len(self.guests)),
        )

    def _update_total(self) -> None:
        try:
            quote = self._current_quote()
            self.total_label.configure(
                text=(
                    f"{quote.nights_count} 晚 × {quote.room_type.name}　"
                    f"合计 {format_money(quote.total_cents)}"
                )
            )
        except Exception:
            self.total_label.configure(text="—")

    def _submit(self, *, confirm_duplicate: bool = False) -> None:
        guests = []
        for name_var, phone_var in self.guests:
            name = name_var.get().strip()
            phone = phone_var.get().strip()
            if not name and not phone:
                continue
            guests.append(Guest(name=name, phone=phone))
        if not guests:
            self.error.configure(text="请至少填写一位入住人")
            return
        try:
            rooms = int(self.room_count.get())
            order = self.view.services.booking.create_order(
                self.view.app.session,
                BookingRequest(
                    room_type_id=self.result.room_type.id,
                    check_in=self.result.nights[0][0],
                    check_out=self.result.nights[-1][0] + timedelta(days=1),
                    room_count=rooms,
                    guests=guests,
                    request_id=uuid4().hex,
                    confirm_duplicate=confirm_duplicate,
                ),
            )
        except DomainError as exc:
            code = getattr(exc, "code", "")
            if code == "DUPLICATE_ORDER":
                existing = exc.detail.get("existing_order_no", "")
                if messagebox.askyesno(
                    "可能重复提交",
                    f"{exc.message}\n原订单：{existing}\n\n仍然创建一张新订单吗？",
                ):
                    self._submit(confirm_duplicate=True)
                return
            self.error.configure(text=exc.message)
            return
        except ValueError as exc:
            self.error.configure(text=str(exc))
            return
        self.destroy()
        self.on_success(order.order_no)


class MyOrdersView(Page):
    title = "我的订单"
    subtitle = "查看每晚明细、退款与改单记录；已确认且未入住的订单可改一次"

    def build(self) -> None:
        self._order = None
        filters = tk.Frame(self, bg=theme.CANVAS)
        filters.pack(fill="x", pady=(0, 10))
        self.status = tk.StringVar(value="全部")
        ttk.Combobox(
            filters,
            textvariable=self.status,
            values=["全部"] + list(STATUS_LABELS.values()),
            width=12,
            state="readonly",
        ).pack(side="left")
        self.keyword = tk.StringVar()
        tk.Entry(filters, textvariable=self.keyword, width=22).pack(
            side="left", padx=8
        )
        button(filters, "筛选", self.refresh, kind="ghost").pack(side="left")
        button(filters, "刷新", self.refresh, kind="ghost").pack(side="left", padx=8)

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
                ("hotel", "酒店", 110, "w"),
                ("room", "房型", 85, "w"),
                ("stay", "入住 / 退房", 115, "w"),
                ("total", "总价", 80, "e"),
                ("status", "状态", 80, "center"),
            ],
            height=13,
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
        label = self.status.get()
        for key, text in STATUS_LABELS.items():
            if text == label:
                status = key
        orders = self.services.orders.list_mine(
            self.app.session, status=status, keyword=self.keyword.get().strip()
        )
        rows = []
        for order in orders:
            hotel = self.services.hotels.get_hotel(order.hotel_id)
            room = self.services.ctx.repos.room_types.by_id(order.room_type_id)
            rows.append(
                {
                    "order_no": order.order_no,
                    "hotel": hotel.name if hotel else "—",
                    "room": room.name if room else "—",
                    "stay": (
                        f"{order.check_in:%m-%d} → {order.check_out:%m-%d}"
                    ),
                    "total": format_money(order.total_cents),
                    "status": STATUS_LABELS.get(order.status, order.status.value),
                    "_order": order,
                }
            )
        self.table.set_rows(rows)
        if not rows:
            self._render_empty("还没有订单，去“搜索房型”订一间吧")
        else:
            self.table.select_first()

    def _select(self, row: dict) -> None:
        self._order = row["_order"]
        self._render_detail(self._order)

    def _render_empty(self, message: str = "选择左侧订单查看详情") -> None:
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
        hotel = self.services.hotels.get_hotel(order.hotel_id)
        room = self.services.ctx.repos.room_types.by_id(order.room_type_id)
        text_label(
            box,
            f"{hotel.name if hotel else '—'} · {room.name if room else '—'} · "
            f"{order.room_count} 间",
            fg=theme.MUTED,
            size=9,
        ).pack(fill="x", pady=(4, 8))
        for label, value in (
            ("入住", str(order.check_in)),
            ("退房", str(order.check_out)),
            ("总价", format_money(order.total_cents)),
            (
                "确认截止",
                order.confirm_deadline.strftime("%m-%d %H:%M")
                if order.confirm_deadline
                else "—",
            ),
            ("改单", "已改一次" if order.modified else "未改单"),
        ):
            line = tk.Frame(box, bg=theme.WHITE)
            line.pack(fill="x", pady=1)
            field_label(line, label, bg=theme.WHITE).pack(side="left")
            text_label(line, value, size=9).pack(side="right")
        if order.reject_reason:
            text_label(
                box,
                f"拒绝原因：{order.reject_reason} {order.reject_note}",
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
                line.pack(fill="x", pady=1)
                text_label(
                    line,
                    f"{refund.event_type} · 扣 {format_money(refund.deducted_cents)}",
                    fg=theme.MUTED,
                    size=8,
                ).pack(side="left")
                text_label(line, format_money(refund.refundable_cents), size=9).pack(side="right")
        changes = self.services.orders.changes(self.app.session, order.order_no)
        if changes:
            text_label(
                box,
                f"改单差价 {format_money(changes[-1].diff_cents)}",
                fg=theme.MUTED,
                size=8,
            ).pack(fill="x", pady=(6, 0))
        actions = tk.Frame(box, bg=theme.WHITE)
        actions.pack(fill="x", side="bottom", pady=(12, 0))
        if order.status is OrderStatus.PENDING or order.status is OrderStatus.CONFIRMED:
            button(actions, "取消订单", self._cancel, kind="danger").pack(side="right")
        if order.status is OrderStatus.CONFIRMED and not order.modified:
            button(actions, "修改订单", self._modify, kind="ghost").pack(
                side="right", padx=(0, 8)
            )

    def _cancel(self) -> None:
        if self._order is None:
            return
        if not messagebox.askyesno(
            "确认取消",
            f"确定取消订单 {self._order.order_no} 吗？\n"
            "入住当天 18:00 前免费，18:00 后收取首晚房费。",
        ):
            return
        try:
            _, refund = self.services.orders.cancel_by_customer(
                self.app.session, self._order.order_no
            )
        except DomainError as exc:
            messagebox.showerror("取消失败", exc.message)
            return
        self.refresh()
        messagebox.showinfo(
            "已取消",
            f"订单已取消。\n应退 {format_money(refund.refundable_cents)}，"
            f"扣费 {format_money(refund.deducted_cents)}。",
        )

    def _modify(self) -> None:
        if self._order is None:
            return
        ModifyDialog(self, self._order, on_success=self.refresh)


class ModifyDialog(tk.Toplevel):
    """改期/改间数。"""

    def __init__(self, view: MyOrdersView, order, *, on_success) -> None:
        super().__init__(view)
        self.view = view
        self.order = order
        self.on_success = on_success
        self.title(f"修改订单 {order.order_no}")
        self.geometry("420x360")
        self.configure(bg=theme.WHITE)
        self.transient(view.winfo_toplevel())
        self.grab_set()
        self.check_in = tk.StringVar(value=order.check_in.isoformat())
        self.check_out = tk.StringVar(value=order.check_out.isoformat())
        self.room_count = tk.StringVar(value=str(order.room_count))
        body = tk.Frame(self, bg=theme.WHITE)
        body.pack(fill="both", expand=True, padx=22, pady=18)
        title(body, "修改入住日期与间数").pack(fill="x")
        text_label(
            body,
            "每张订单只能修改一次；新增间夜先占用，全部成功后才释放减少的间夜。",
            fg=theme.MUTED,
            size=8,
            wraplength=360,
        ).pack(fill="x", pady=(4, 12))
        for label, var in (("入住日期", self.check_in), ("退房日期", self.check_out)):
            field_label(body, label).pack(fill="x", pady=(6, 2))
            tk.Entry(body, textvariable=var).pack(fill="x", ipady=5)
        field_label(body, "间数").pack(fill="x", pady=(10, 2))
        ttk.Spinbox(body, from_=1, to=10, textvariable=self.room_count).pack(fill="x")
        self.error = tk.Label(
            body, text="", bg=theme.WHITE, fg=theme.DANGER,
            font=(self.view.app.family, -12), anchor="w", wraplength=360,
            justify="left",
        )
        self.error.pack(fill="x", pady=(8, 0))
        actions = tk.Frame(body, bg=theme.WHITE)
        actions.pack(fill="x", side="bottom")
        button(actions, "取消", self.destroy, kind="ghost").pack(side="right")
        button(actions, "提交修改", self._submit).pack(side="right", padx=(0, 8))

    def _submit(self) -> None:
        try:
            changed, diff = self.view.services.orders.modify(
                self.view.app.session,
                self.order.order_no,
                check_in=parse_date(self.check_in.get(), "入住日期"),
                check_out=parse_date(self.check_out.get(), "退房日期"),
                room_count=int(self.room_count.get()),
            )
        except DomainError as exc:
            self.error.configure(text=exc.message)
            return
        except ValueError as exc:
            self.error.configure(text=str(exc))
            return
        self.destroy()
        self.on_success()
        messagebox.showinfo(
            "修改成功",
            f"新总价 {format_money(changed.total_cents)}，差价 {format_money(diff)}。",
        )
