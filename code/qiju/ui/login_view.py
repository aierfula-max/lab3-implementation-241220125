"""登录、注册与店长邀请码激活。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..domain.errors import DomainError
from . import theme
from .widgets import button, text_label, title

DEMO_ACCOUNTS = [
    ("顾客", "13600000001", "Qiju@2026"),
    ("前台", "13700000001", "Front@2026"),
    ("店长", "13900000001", "Manager@2026"),
    ("管理员", "13800000000", "Admin@2026"),
]


class LoginView(tk.Frame):
    """左侧品牌、右侧表单。演示账号一键填入，方便课堂展示。"""

    def __init__(self, master: tk.Misc, app) -> None:
        super().__init__(master, bg=theme.PAPER)
        self.app = app
        self._build_brand()
        self._build_form()

    # ------------------------------------------------------------ 左侧
    def _build_brand(self) -> None:
        panel = tk.Frame(self, bg=theme.PINE_DARK, width=440)
        panel.pack(side="left", fill="y")
        panel.pack_propagate(False)
        inner = tk.Frame(panel, bg=theme.PINE_DARK)
        inner.pack(fill="both", expand=True, padx=44, pady=52)
        tk.Label(
            inner,
            text="栖居 QIJU",
            bg=theme.PINE_DARK,
            fg=theme.WHITE,
            font=(self.app.family, -35, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            inner,
            text="面向中小连锁酒店的在线预订与房态管理系统",
            bg=theme.PINE_DARK,
            fg="#C9DCD4",
            font=(self.app.family, -15),
            anchor="w",
            wraplength=340,
            justify="left",
        ).pack(fill="x", pady=(8, 26))
        tk.Frame(inner, bg=theme.BRASS, height=2, width=64).pack(anchor="w")
        for head, body in (
            ("逐日库存", "按房型 × 日期维护库存与价格，停售保留原价"),
            ("状态机", "7 个订单状态，非法转换一律 409"),
            ("可追溯", "关键操作与业务同事务写日志，手机号脱敏"),
        ):
            block = tk.Frame(inner, bg=theme.PINE_DARK)
            block.pack(fill="x", pady=(18, 0))
            tk.Label(
                block,
                text=head,
                bg=theme.PINE_DARK,
                fg=theme.BRASS,
                font=(self.app.family, -14, "bold"),
                anchor="w",
            ).pack(fill="x")
            tk.Label(
                block,
                text=body,
                bg=theme.PINE_DARK,
                fg="#B9CCC4",
                font=(self.app.family, -12),
                anchor="w",
                wraplength=340,
                justify="left",
            ).pack(fill="x", pady=(2, 0))
        tk.Label(
            inner,
            text="241220125 王璟昊 · 软件工程实践 实验三",
            bg=theme.PINE_DARK,
            fg="#8FA9A0",
            font=(self.app.family, -11),
            anchor="w",
        ).pack(side="bottom", fill="x")

    # ------------------------------------------------------------ 右侧
    def _build_form(self) -> None:
        area = tk.Frame(self, bg=theme.PAPER)
        area.pack(side="left", fill="both", expand=True)
        wrapper = tk.Frame(area, bg=theme.PAPER)
        wrapper.place(relx=0.5, rely=0.46, anchor="center")
        title(wrapper, "欢迎回来", size=22, bg=theme.PAPER).pack(fill="x")
        text_label(
            wrapper,
            "登录后进入与角色对应的工作台",
            fg=theme.MUTED,
            bg=theme.PAPER,
            size=9,
        ).pack(fill="x", pady=(4, 16))

        notebook = ttk.Notebook(wrapper)
        notebook.pack(fill="both", expand=True)
        self.login_tab = tk.Frame(notebook, bg=theme.WHITE, padx=0, pady=0)
        self.register_tab = tk.Frame(notebook, bg=theme.WHITE)
        self.activate_tab = tk.Frame(notebook, bg=theme.WHITE)
        notebook.add(self.login_tab, text="  登录  ")
        notebook.add(self.register_tab, text="  注册  ")
        notebook.add(self.activate_tab, text="  店长激活  ")

        self._build_login_tab()
        self._build_register_tab()
        self._build_activate_tab()

    def _entry(self, master: tk.Misc, *, show: str | None = None) -> tk.Entry:
        entry = tk.Entry(
            master,
            font=(self.app.family, -15),
            bg=theme.WHITE,
            fg=theme.INK,
            insertbackground=theme.INK,
            relief="flat",
            highlightthickness=1,
            highlightbackground=theme.LINE,
            highlightcolor=theme.PINE,
        )
        if show:
            entry.configure(show=show)
        return entry

    def _form_row(self, master: tk.Misc, label: str, entry: tk.Entry) -> None:
        tk.Label(
            master,
            text=label,
            bg=theme.WHITE,
            fg=theme.MUTED,
            font=(self.app.family, -12),
            anchor="w",
        ).pack(fill="x", pady=(10, 3))
        entry.pack(fill="x", ipady=7)

    def _build_login_tab(self) -> None:
        tab = tk.Frame(self.login_tab, bg=theme.WHITE, padx=22, pady=18)
        tab.pack(fill="both", expand=True)
        self.login_phone = self._entry(tab)
        self.login_password = self._entry(tab, show="*")
        self._form_row(tab, "手机号", self.login_phone)
        self._form_row(tab, "密码", self.login_password)
        self.login_error = tk.Label(
            tab,
            text="",
            bg=theme.WHITE,
            fg=theme.DANGER,
            font=(self.app.family, -12),
            anchor="w",
            wraplength=340,
            justify="left",
        )
        self.login_error.pack(fill="x", pady=(8, 0))
        button(tab, "登录", self._do_login).pack(fill="x", pady=(10, 0))
        text_label(tab, "演示账号（点击填入）", fg=theme.MUTED, size=8).pack(
            fill="x", pady=(16, 6)
        )
        chips = tk.Frame(tab, bg=theme.WHITE)
        chips.pack(fill="x")
        for index, (label, phone, password) in enumerate(DEMO_ACCOUNTS):
            chip = tk.Label(
                chips,
                text=label,
                bg=theme.PINE_SOFT,
                fg=theme.PINE_DARK,
                font=(self.app.family, -12),
                padx=10,
                pady=4,
                cursor="hand2",
            )
            chip.grid(row=0, column=index, padx=(0, 6), sticky="w")
            chip.bind(
                "<Button-1>",
                lambda _event, p=phone, w=password: self._fill_login(p, w),
            )
        self.login_phone.focus_set()
        self.login_password.bind("<Return>", lambda _event: self._do_login())

    def _fill_login(self, phone: str, password: str) -> None:
        self.login_phone.delete(0, "end")
        self.login_phone.insert(0, phone)
        self.login_password.delete(0, "end")
        self.login_password.insert(0, password)

    def _do_login(self) -> None:
        try:
            session = self.app.services.auth.login(
                self.login_phone.get().strip(), self.login_password.get()
            )
        except DomainError as exc:
            self.login_error.configure(text=exc.message)
            return
        self.app.login(session)

    def _build_register_tab(self) -> None:
        tab = tk.Frame(self.register_tab, bg=theme.WHITE, padx=22, pady=18)
        tab.pack(fill="both", expand=True)
        self.reg_phone = self._entry(tab)
        self.reg_name = self._entry(tab)
        self.reg_password = self._entry(tab, show="*")
        self.reg_confirm = self._entry(tab, show="*")
        self._form_row(tab, "手机号", self.reg_phone)
        self._form_row(tab, "昵称", self.reg_name)
        self._form_row(tab, "密码（至少 8 位）", self.reg_password)
        self._form_row(tab, "确认密码", self.reg_confirm)
        self.reg_error = tk.Label(
            tab,
            text="",
            bg=theme.WHITE,
            fg=theme.DANGER,
            font=(self.app.family, -12),
            anchor="w",
            wraplength=340,
            justify="left",
        )
        self.reg_error.pack(fill="x", pady=(8, 0))
        button(tab, "注册并登录", self._do_register).pack(fill="x", pady=(10, 0))

    def _do_register(self) -> None:
        if self.reg_password.get() != self.reg_confirm.get():
            self.reg_error.configure(text="两次输入的密码不一致")
            return
        try:
            self.app.services.auth.register_customer(
                self.reg_phone.get().strip(),
                self.reg_password.get(),
                self.reg_name.get().strip(),
            )
            session = self.app.services.auth.login(
                self.reg_phone.get().strip(), self.reg_password.get()
            )
        except (DomainError, ValueError) as exc:
            self.reg_error.configure(text=getattr(exc, "message", str(exc)))
            return
        self.app.login(session)

    def _build_activate_tab(self) -> None:
        tab = tk.Frame(self.activate_tab, bg=theme.WHITE, padx=22, pady=18)
        tab.pack(fill="both", expand=True)
        self.act_code = self._entry(tab)
        self.act_phone = self._entry(tab)
        self.act_name = self._entry(tab)
        self.act_password = self._entry(tab, show="*")
        self._form_row(tab, "邀请码", self.act_code)
        self._form_row(tab, "手机号", self.act_phone)
        self._form_row(tab, "姓名", self.act_name)
        self._form_row(tab, "设置密码", self.act_password)
        text_label(
            tab,
            "演示邀请码：PENDING-INVITE（河西店）",
            fg=theme.MUTED,
            size=8,
        ).pack(fill="x", pady=(8, 0))
        self.act_error = tk.Label(
            tab,
            text="",
            bg=theme.WHITE,
            fg=theme.DANGER,
            font=(self.app.family, -12),
            anchor="w",
            wraplength=340,
            justify="left",
        )
        self.act_error.pack(fill="x", pady=(6, 0))
        button(tab, "激活并登录", self._do_activate).pack(fill="x", pady=(10, 0))

    def _do_activate(self) -> None:
        try:
            session = self.app.services.auth.activate_manager(
                self.act_code.get().strip(),
                self.act_phone.get().strip(),
                self.act_password.get(),
                self.act_name.get().strip(),
            )
        except (DomainError, ValueError) as exc:
            self.act_error.configure(text=getattr(exc, "message", str(exc)))
            return
        self.app.login(session)
