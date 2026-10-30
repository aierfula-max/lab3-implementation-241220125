"""界面配色与 ttk 样式。

配色沿用实验二 UI 的墨绿 + 沙色，不另起一套。字号只留四档
（标题 20、小节 13、正文 10.5、辅助 9），避免每写一个页面就多一种字号。
"""

from __future__ import annotations

import contextlib
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

PINE = "#1E5A4E"
PINE_DARK = "#143F37"
PINE_SOFT = "#EAF2EE"
BRASS = "#C08A46"
INK = "#14231F"
MUTED = "#6F7B75"
PAPER = "#F7F3E9"
LINE = "#E4DDCF"
WHITE = "#FFFFFF"
DANGER = "#A6403A"
WARN = "#B4762C"
OK = "#2F7D5B"
CANVAS = "#F3F1EA"

_CJK_CANDIDATES = (
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "Microsoft YaHei",
    "PingFang SC",
    "WenQuanYi Micro Hei",
)


def pick_font(root: tk.Misc) -> str:
    """选一个系统里真的有中文字形的字体。"""
    families = set(tkfont.families(root))
    for name in _CJK_CANDIDATES:
        if name in families:
            return name
    return "TkDefaultFont"


def configure(root: tk.Tk) -> str:
    """注册 ttk 样式，返回选中的正文字体名。"""
    family = pick_font(root)
    root.option_add("*Font", (family, -14))
    style = ttk.Style(root)
    with contextlib.suppress(tk.TclError):
        style.theme_use("clam")

    style.configure(".", font=(family, -14), background=CANVAS, foreground=INK)
    style.configure("TFrame", background=CANVAS)
    style.configure("Card.TFrame", background=WHITE)
    style.configure("Sidebar.TFrame", background=PINE_DARK)
    style.configure("Header.TFrame", background=WHITE)

    style.configure(
        "TLabel", background=CANVAS, foreground=INK, font=(family, -14)
    )
    style.configure(
        "Card.TLabel", background=WHITE, foreground=INK, font=(family, -14)
    )
    style.configure(
        "Muted.TLabel", background=CANVAS, foreground=MUTED, font=(family, -12)
    )
    style.configure(
        "CardMuted.TLabel", background=WHITE, foreground=MUTED, font=(family, -12)
    )
    style.configure(
        "H1.TLabel",
        background=CANVAS,
        foreground=INK,
        font=(family, -27, "bold"),
    )
    style.configure(
        "H2.TLabel",
        background=WHITE,
        foreground=INK,
        font=(family, -18, "bold"),
    )
    style.configure(
        "SidebarBrand.TLabel",
        background=PINE_DARK,
        foreground=WHITE,
        font=(family, -20, "bold"),
    )
    style.configure(
        "SidebarMuted.TLabel",
        background=PINE_DARK,
        foreground="#BFD3CB",
        font=(family, -12),
    )

    style.configure(
        "Primary.TButton",
        background=PINE,
        foreground=WHITE,
        borderwidth=0,
        focusthickness=0,
        padding=(14, 7),
        font=(family, -14, "bold"),
    )
    style.map(
        "Primary.TButton",
        background=[("active", PINE_DARK), ("disabled", "#B9C9C2")],
        foreground=[("disabled", "#F2F2F2")],
    )
    style.configure(
        "Ghost.TButton",
        background=WHITE,
        foreground=PINE_DARK,
        borderwidth=1,
        bordercolor=LINE,
        padding=(12, 6),
        font=(family, -14),
    )
    style.map("Ghost.TButton", background=[("active", PINE_SOFT)])
    style.configure(
        "Danger.TButton",
        background=WHITE,
        foreground=DANGER,
        borderwidth=1,
        bordercolor="#E3C4C1",
        padding=(12, 6),
        font=(family, -14),
    )
    style.map("Danger.TButton", background=[("active", "#F8EAE8")])
    style.configure(
        "Sidebar.TButton",
        background=PINE_DARK,
        foreground="#D8E5DF",
        borderwidth=0,
        anchor="w",
        padding=(18, 9),
        font=(family, -14),
    )
    style.map(
        "Sidebar.TButton",
        background=[("active", PINE), ("pressed", PINE)],
        foreground=[("active", WHITE)],
    )
    style.configure(
        "SidebarActive.TButton",
        background=PINE,
        foreground=WHITE,
        borderwidth=0,
        anchor="w",
        padding=(18, 9),
        font=(family, -14, "bold"),
    )

    style.configure(
        "TEntry",
        fieldbackground=WHITE,
        bordercolor=LINE,
        lightcolor=LINE,
        darkcolor=LINE,
        padding=6,
    )
    style.configure(
        "TCombobox",
        fieldbackground=WHITE,
        bordercolor=LINE,
        lightcolor=LINE,
        darkcolor=LINE,
        padding=5,
    )
    style.configure(
        "Treeview",
        background=WHITE,
        fieldbackground=WHITE,
        foreground=INK,
        rowheight=30,
        borderwidth=0,
        font=(family, -14),
    )
    style.configure(
        "Treeview.Heading",
        background=PAPER,
        foreground=PINE_DARK,
        relief="flat",
        font=(family, -12, "bold"),
        padding=(8, 6),
    )
    style.map(
        "Treeview",
        background=[("selected", PINE_SOFT)],
        foreground=[("selected", PINE_DARK)],
    )
    style.map("Treeview.Heading", background=[("active", "#EFEADA")])
    style.configure(
        "TNotebook",
        background=CANVAS,
        borderwidth=0,
        tabmargins=(0, 4, 0, 0),
    )
    style.configure(
        "TNotebook.Tab",
        background=PAPER,
        foreground=MUTED,
        padding=(18, 8),
        font=(family, -14),
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", WHITE)],
        foreground=[("selected", PINE_DARK)],
    )
    style.configure("TSeparator", background=LINE)
    return family
