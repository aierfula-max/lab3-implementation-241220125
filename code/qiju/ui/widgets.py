"""可复用的小组件：卡片、状态标签、表格、空状态。

Tkinter 的原生控件偏“系统风”，这里统一包一层，页面代码就只需要关心
“放什么”，不用每个页面重复调 ``ttk.Style``。
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Iterable, Sequence
from tkinter import ttk

from . import theme


def px(size: int) -> int:
    """把设计稿字号换算成 Tk 的像素字号。

    Tk 在 X11/HiDPI 下对“正数=磅”的解释不稳定，同一份代码在 96 dpi 与
    192 dpi 上能差一倍；用负数（像素）最稳，截图和真机一致。
    """
    return -max(9, round(size * 1.35))


class Card(tk.Frame):
    """白底细边框卡片。"""

    def __init__(self, master: tk.Misc, padding: int = 16, **kwargs) -> None:
        super().__init__(
            master,
            bg=theme.WHITE,
            highlightbackground=theme.LINE,
            highlightthickness=1,
            bd=0,
            **kwargs,
        )
        self.body = tk.Frame(self, bg=theme.WHITE)
        self.body.pack(fill="both", expand=True, padx=padding, pady=padding)


def title(
    master: tk.Misc,
    text: str,
    size: int = 13,
    fg: str = theme.INK,
    bg: str = theme.WHITE,
) -> tk.Label:
    return tk.Label(
        master,
        text=text,
        bg=bg,
        fg=fg,
        font=(theme.pick_font(master), px(size), "bold"),
        anchor="w",
    )


def text_label(
    master: tk.Misc,
    text: str,
    *,
    size: int = 10,
    fg: str = theme.INK,
    bg: str = theme.WHITE,
    wraplength: int = 0,
) -> tk.Label:
    return tk.Label(
        master,
        text=text,
        bg=bg,
        fg=fg,
        font=(theme.pick_font(master), px(size)),
        anchor="w",
        justify="left",
        wraplength=wraplength,
    )


def button(
    master: tk.Misc,
    text: str,
    command: Callable[[], None],
    *,
    kind: str = "primary",
    width: int | None = None,
) -> ttk.Button:
    style = {
        "primary": "Primary.TButton",
        "ghost": "Ghost.TButton",
        "danger": "Danger.TButton",
    }.get(kind, "Ghost.TButton")
    return ttk.Button(master, text=text, command=command, style=style, width=width)


class Badge(tk.Label):
    """状态小标签。颜色按订单状态/退款状态映射。"""

    COLORS = {
        "PENDING": (theme.WARN, "#FBF1E3"),
        "CONFIRMED": (theme.PINE, theme.PINE_SOFT),
        "CHECKED_IN": ("#2C5F8A", "#E7EFF7"),
        "COMPLETED": (theme.OK, "#E7F2EC"),
        "CANCELED": (theme.MUTED, "#F0F0EE"),
        "REJECTED": (theme.DANGER, "#F8EAE8"),
        "NO_SHOW": ("#7A5A8C", "#F0EAF4"),
        "REFUNDED": (theme.OK, "#E7F2EC"),
        "PENDING_OFFLINE": (theme.WARN, "#FBF1E3"),
        "APPROVED": (theme.OK, "#E7F2EC"),
        "SUSPENDED": (theme.MUTED, "#F0F0EE"),
        "OPEN": (theme.OK, "#E7F2EC"),
    }
    LABELS = {
        "PENDING": "待确认",
        "CONFIRMED": "已确认",
        "CHECKED_IN": "已入住",
        "COMPLETED": "已完成",
        "CANCELED": "已取消",
        "REJECTED": "已拒绝",
        "NO_SHOW": "未入住关闭",
        "REFUNDED": "已退款",
        "PENDING_OFFLINE": "待线下退款",
        "APPROVED": "已通过",
        "SUSPENDED": "暂停营业",
        "OPEN": "营业中",
        "PENDING_AUDIT": "待审核",
        "REJECTED_AUDIT": "已驳回",
    }

    def __init__(self, master: tk.Misc, value: str, text: str | None = None) -> None:
        fg, bg = self.COLORS.get(value, (theme.MUTED, "#F0F0EE"))
        super().__init__(
            master,
            text=text or self.LABELS.get(value, value),
            bg=bg,
            fg=fg,
            font=(theme.pick_font(master), -12, "bold"),
            padx=8,
            pady=2,
        )


class DataTable(tk.Frame):
    """Treeview + 滚动条 + 行数据缓存。

    ``columns`` 是 ``(key, 标题, 宽度, 对齐)`` 的序列。行数据用 dict 存，
    选中后直接 ``selected()`` 拿回 dict，不需要再按 iid 反查业务对象。
    """

    def __init__(
        self,
        master: tk.Misc,
        columns: Sequence[tuple[str, str, int, str]],
        *,
        height: int = 12,
        on_select: Callable[[dict], None] | None = None,
        on_double: Callable[[dict], None] | None = None,
    ) -> None:
        super().__init__(master, bg=theme.WHITE)
        self._columns = list(columns)
        self._rows: dict[str, dict] = {}
        self._on_select = on_select
        keys = [item[0] for item in columns]
        self.tree = ttk.Treeview(
            self, columns=keys, show="headings", height=height, selectmode="browse"
        )
        for key, label, width, anchor in columns:
            self.tree.heading(key, text=label, anchor="w")
            self.tree.column(
                key, width=width, minwidth=width, anchor=anchor, stretch=True
            )
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=xscroll.set)
        scroll.pack(side="right", fill="y")
        xscroll.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.tag_configure("odd", background="#FBFAF6")
        self.tree.bind("<<TreeviewSelect>>", self._selected_event)
        if on_double is not None:
            self.tree.bind("<Double-1>", lambda _event: self._double_event())

    def set_rows(self, rows: Iterable[dict], *, clear_selection: bool = True) -> None:
        if clear_selection:
            for item in self.tree.selection():
                self.tree.selection_remove(item)
        self.tree.delete(*self.tree.get_children())
        self._rows.clear()
        for index, row in enumerate(rows):
            values = [row.get(key, "") for key, *_ in self._columns]
            iid = self.tree.insert(
                "",
                "end",
                values=values,
                tags=("odd",) if index % 2 else (),
            )
            self._rows[iid] = row

    def selected(self) -> dict | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self._rows.get(selection[0])

    def select_first(self) -> None:
        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children[0])
            self.tree.focus(children[0])

    def _selected_event(self, _event) -> None:
        row = self.selected()
        if row and self._on_select:
            self._on_select(row)

    def _double_event(self) -> None:
        row = self.selected()
        if row and self._on_double:
            self._on_double(row)


class StatCard(Card):
    """报表顶部的指标卡。"""

    def __init__(
        self,
        master: tk.Misc,
        label: str,
        value: str,
        hint: str = "",
        *,
        accent: str = theme.PINE,
    ) -> None:
        super().__init__(master, padding=14)
        self.value_label = tk.Label(
            self.body,
            text=value,
            bg=theme.WHITE,
            fg=accent,
            font=(theme.pick_font(master), -24, "bold"),
            anchor="w",
        )
        self.value_label.pack(fill="x")
        tk.Label(
            self.body,
            text=label,
            bg=theme.WHITE,
            fg=theme.INK,
            font=(theme.pick_font(master), -12),
            anchor="w",
        ).pack(fill="x", pady=(2, 0))
        if hint:
            tk.Label(
                self.body,
                text=hint,
                bg=theme.WHITE,
                fg=theme.MUTED,
                font=(theme.pick_font(master), -11),
                anchor="w",
            ).pack(fill="x")

    def set_value(self, value: str) -> None:
        self.value_label.configure(text=value)


def empty_state(master: tk.Misc, text: str = "暂无数据") -> tk.Label:
    return tk.Label(
        master,
        text=text,
        bg=theme.WHITE,
        fg=theme.MUTED,
        font=(theme.pick_font(master), -14),
        pady=28,
    )


def field_label(master: tk.Misc, text: str, bg: str = theme.WHITE) -> tk.Label:
    return tk.Label(
        master,
        text=text,
        bg=bg,
        fg=theme.MUTED,
        font=(theme.pick_font(master), -12),
        anchor="w",
    )


def divider(master: tk.Misc, bg: str = theme.LINE) -> tk.Frame:
    line = tk.Frame(master, bg=bg, height=1)
    line.pack(fill="x", pady=8)
    return line
