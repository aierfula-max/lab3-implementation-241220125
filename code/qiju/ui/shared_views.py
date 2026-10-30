"""店长与管理员共用：经营报表、操作日志、消息中心。"""

from __future__ import annotations

import tkinter as tk
from datetime import timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..domain.enums import AuditAction, Role
from ..domain.errors import DomainError
from ..domain.money import format_money
from . import theme
from .app import Page
from .customer_views import parse_date
from .widgets import Card, DataTable, StatCard, button, field_label, text_label, title


def percent(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


class ReportView(Page):
    title = "经营报表"
    subtitle = "可售间夜、计费间夜、已住间夜、出租率、平均房价与净成交"

    def build(self) -> None:
        today = self.services.ctx.clock.now().date()
        self.start = tk.StringVar(value=(today - timedelta(days=13)).isoformat())
        self.end = tk.StringVar(value=(today + timedelta(days=1)).isoformat())
        self.hotel = tk.StringVar(value="全部酒店")
        bar = tk.Frame(self, bg=theme.CANVAS)
        bar.pack(fill="x", pady=(0, 10))
        field_label(bar, "开始", bg=theme.CANVAS).pack(side="left")
        tk.Entry(bar, textvariable=self.start, width=12).pack(side="left", padx=(6, 10))
        field_label(bar, "结束（不含）", bg=theme.CANVAS).pack(side="left")
        tk.Entry(bar, textvariable=self.end, width=12).pack(side="left", padx=(6, 10))
        self.hotel_combo = None
        if self.app.session.user.role is Role.PLATFORM_ADMIN:
            self._hotels = self.services.hotels.list_hotels(self.app.session)
            ttk.Combobox(
                bar,
                textvariable=self.hotel,
                values=["全部酒店"] + [item.name for item in self._hotels],
                width=16,
                state="readonly",
            ).pack(side="left", padx=(0, 10))
        button(bar, "生成报表", self.refresh).pack(side="left")
        text_label(
            bar, "口径：REQ-018", fg=theme.MUTED, size=8
        ).pack(side="left", padx=12)

        self.stats = tk.Frame(self, bg=theme.CANVAS)
        self.stats.pack(fill="x", pady=(0, 12))
        for index in range(4):
            self.stats.columnconfigure(index, weight=1)
        self.cards: dict[str, StatCard] = {}
        specs = [
            ("sellable", "可售间夜", theme.PINE),
            ("sold", "计费间夜", theme.PINE),
            ("stayed", "已住间夜", theme.PINE),
            ("occupancy", "出租率", theme.BRASS),
            ("adr", "平均房价", theme.BRASS),
            ("revenue", "成交金额", theme.PINE_DARK),
            ("refund", "退款金额", theme.DANGER),
            ("net", "净成交金额", theme.OK),
        ]
        for index, (key, label, color) in enumerate(specs):
            card = StatCard(self.stats, label, "—", accent=color)
            card.grid(
                row=index // 4,
                column=index % 4,
                sticky="nsew",
                padx=(0 if index % 4 == 0 else 8, 0),
                pady=(0, 8),
            )
            self.cards[key] = card

        card = Card(self, padding=0)
        card.pack(fill="both", expand=True)
        self.table = DataTable(
            card.body,
            [
                ("day", "日期", 100, "w"),
                ("sellable", "可售间夜", 80, "center"),
                ("sold", "计费间夜", 80, "center"),
                ("stayed", "已住间夜", 80, "center"),
                ("occupancy", "出租率", 70, "center"),
                ("adr", "平均房价", 90, "e"),
                ("revenue", "成交金额", 100, "e"),
                ("refund", "退款", 90, "e"),
                ("created", "创建订单", 70, "center"),
                ("canceled", "取消", 60, "center"),
            ],
            height=12,
        )
        self.table.pack(fill="both", expand=True)

    def refresh(self) -> None:
        try:
            start = parse_date(self.start.get(), "开始日期")
            end = parse_date(self.end.get(), "结束日期")
        except ValueError as exc:
            messagebox.showerror("日期不合法", str(exc))
            return
        hotel_id = None
        if self.app.session.user.role is Role.PLATFORM_ADMIN:
            choice = self.hotel.get()
            if choice != "全部酒店":
                hotel_id = next(
                    (item.id for item in self._hotels if item.name == choice), None
                )
        try:
            summary = self.services.reports.summary(
                self.app.session, start=start, end=end, hotel_id=hotel_id
            )
        except (DomainError, ValueError) as exc:
            messagebox.showerror("生成失败", getattr(exc, "message", str(exc)))
            return
        self.cards["sellable"].set_value(str(summary.sellable_nights))
        self.cards["sold"].set_value(str(summary.sold_nights))
        self.cards["stayed"].set_value(str(summary.stayed_nights))
        self.cards["occupancy"].set_value(percent(summary.occupancy))
        self.cards["adr"].set_value(
            format_money(summary.adr_cents) if summary.adr_cents is not None else "—"
        )
        self.cards["revenue"].set_value(format_money(summary.revenue_cents))
        self.cards["refund"].set_value(format_money(summary.refund_cents))
        self.cards["net"].set_value(format_money(summary.net_cents))
        rows = [
            {
                "day": item.day.isoformat(),
                "sellable": item.sellable_nights,
                "sold": item.sold_nights,
                "stayed": item.stayed_nights,
                "occupancy": percent(item.occupancy),
                "adr": format_money(item.adr_cents) if item.adr_cents is not None else "—",
                "revenue": format_money(item.revenue_cents),
                "refund": format_money(item.refund_cents),
                "created": item.created_orders,
                "canceled": item.canceled_orders,
            }
            for item in summary.daily
        ]
        self.table.set_rows(rows)
        self.app.toast(
            f"报表已生成：{start} 至 {end}，取消率 {percent(summary.cancel_rate)}"
        )


class LogsView(Page):
    title = "操作日志"
    subtitle = "只追加、不修改；手机号脱敏；导出动作本身也会写一条日志"

    def build(self) -> None:
        bar = tk.Frame(self, bg=theme.CANVAS)
        bar.pack(fill="x", pady=(0, 10))
        self.action = tk.StringVar(value="全部")
        actions = ["全部"] + [item.value for item in AuditAction]
        ttk.Combobox(
            bar, textvariable=self.action, values=actions, width=20, state="readonly"
        ).pack(side="left")
        self.object_id = tk.StringVar()
        tk.Entry(bar, textvariable=self.object_id, width=24).pack(
            side="left", padx=8
        )
        button(bar, "查询", self.refresh, kind="ghost").pack(side="left")
        button(bar, "导出 CSV", self._export, kind="ghost").pack(side="left", padx=8)
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
                ("time", "时间", 135, "w"),
                ("role", "角色", 95, "w"),
                ("action", "动作", 140, "w"),
                ("object", "对象", 130, "w"),
                ("reason", "原因", 200, "w"),
                ("before", "改前", 110, "w"),
                ("after", "改后", 160, "w"),
            ],
            height=14,
        )
        self.table.pack(fill="both", expand=True)

    def refresh(self) -> None:
        from ..application.audit_service import LogFilter

        filters = LogFilter(
            action=None if self.action.get() == "全部" else self.action.get(),
            object_id=self.object_id.get().strip() or None,
        )
        try:
            logs = self.services.audit.query(self.app.session, filters)
        except DomainError as exc:
            messagebox.showerror("查询失败", exc.message)
            return
        rows = [
            {
                "time": item.created_at.strftime("%Y-%m-%d %H:%M:%S")
                if item.created_at
                else "",
                "role": item.actor_role,
                "action": item.action,
                "object": f"{item.object_type}:{item.object_id[:10]}",
                "reason": item.reason,
                "before": item.before_value,
                "after": item.after_value,
            }
            for item in logs
        ]
        self.table.set_rows(rows)
        self.hint.configure(text=f"最近 {len(rows)} 条")

    def _export(self) -> None:
        path = filedialog.asksaveasfilename(
            title="导出操作日志",
            defaultextension=".csv",
            initialfile="operation_logs.csv",
            filetypes=[("CSV 文件", "*.csv")],
        )
        if not path:
            return
        from ..application.audit_service import LogFilter

        try:
            count = self.services.audit.export_csv(
                self.app.session,
                Path(path),
                LogFilter(
                    action=None if self.action.get() == "全部" else self.action.get(),
                    object_id=self.object_id.get().strip() or None,
                ),
            )
        except DomainError as exc:
            messagebox.showerror("导出失败", exc.message)
            return
        self.refresh()
        self.app.toast(f"已导出 {count} 条日志到 {Path(path).name}")


class MessagesView(Page):
    title = "消息中心"
    subtitle = "站内信模拟通知，不接短信与邮件；手机号在正文中已脱敏"

    def build(self) -> None:
        bar = tk.Frame(self, bg=theme.CANVAS)
        bar.pack(fill="x", pady=(0, 10))
        button(bar, "刷新", self.refresh, kind="ghost").pack(side="left")
        button(bar, "全部标为已读", self._read_all, kind="ghost").pack(
            side="left", padx=8
        )
        body = tk.Frame(self, bg=theme.CANVAS)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        card = Card(body, padding=0)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.table = DataTable(
            card.body,
            [
                ("time", "时间", 120, "w"),
                ("title", "标题", 150, "w"),
                ("read", "状态", 70, "center"),
            ],
            height=14,
            on_select=self._select,
        )
        self.table.pack(fill="both", expand=True)
        detail_card = Card(body, padding=0)
        detail_card.grid(row=0, column=1, sticky="nsew")
        self.detail = tk.Frame(detail_card.body, bg=theme.WHITE)
        self.detail.pack(fill="both", expand=True)
        self._render_empty()

    def refresh(self) -> None:
        messages = self.services.scheduler.notifications(self.app.session)
        self._messages = {item.id: item for item in messages}
        rows = [
            {
                "time": item.created_at.strftime("%m-%d %H:%M"),
                "title": item.title,
                "read": "已读" if item.read_at else "未读",
                "_id": item.id,
            }
            for item in messages
        ]
        self.table.set_rows(rows)
        if rows:
            self.table.select_first()
        else:
            self._render_empty("还没有消息")
        self.app.refresh_header()

    def _select(self, row: dict) -> None:
        message = self._messages.get(row["_id"])
        if message is None:
            return
        for child in self.detail.winfo_children():
            child.destroy()
        box = tk.Frame(self.detail, bg=theme.WHITE)
        box.pack(fill="both", expand=True, padx=20, pady=18)
        title(box, message.title, size=13).pack(fill="x")
        text_label(
            box,
            message.created_at.strftime("%Y-%m-%d %H:%M"),
            fg=theme.MUTED, size=8,
        ).pack(fill="x", pady=(2, 12))
        text_label(box, message.body, size=10, wraplength=380).pack(fill="x")

    def _render_empty(self, message: str = "选择左侧消息查看正文") -> None:
        for child in self.detail.winfo_children():
            child.destroy()
        box = tk.Frame(self.detail, bg=theme.WHITE)
        box.pack(fill="both", expand=True, padx=20, pady=18)
        title(box, "消息").pack(fill="x")
        text_label(box, message, fg=theme.MUTED, size=9, wraplength=340).pack(
            fill="x", pady=(10, 0)
        )

    def _read_all(self) -> None:
        self.services.scheduler.mark_notifications_read(self.app.session)
        self.refresh()
        self.app.toast("消息已全部标为已读")
