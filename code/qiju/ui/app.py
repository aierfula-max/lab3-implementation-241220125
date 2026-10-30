"""应用外壳：登录、侧边栏、页面路由、状态栏。

界面层只做三件事：调用服务、把结果排版、把异常翻译成中文提示。
所有业务判断都在服务层，所以这里的按钮是否可点只影响体验，不影响正确性。
"""

from __future__ import annotations

import contextlib
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, ttk

from ..application import Application, Session
from ..domain.clock import SystemClock
from ..domain.enums import Role
from ..infrastructure.seed import seed_demo
from . import theme

DEFAULT_DB = Path.home() / ".qiju" / "qiju.db"


class Page(tk.Frame):
    """页面基类。子类实现 ``build`` 与 ``refresh``。"""

    title = ""
    subtitle = ""

    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, bg=theme.CANVAS)
        self.app = app
        self.services = app.services
        self.build()

    def build(self) -> None:  # pragma: no cover - 由子类实现
        raise NotImplementedError

    def refresh(self) -> None:  # pragma: no cover - 由子类实现
        pass


class App(tk.Tk):
    """主窗口。"""

    def __init__(
        self,
        services: Application,
        *,
        db_path: str | Path = DEFAULT_DB,
        seed: bool = True,
    ) -> None:
        super().__init__()
        self.services = services
        self.db_path = Path(db_path)
        self.session: Session | None = None
        self._pages: dict[str, Page] = {}
        self._nav_buttons: dict[str, ttk.Button] = {}
        self._nav_specs: list[tuple[str, str, set[Role]]] = []
        self.title("栖居 · 酒店在线预订系统")
        self.geometry("1440x900")
        self.minsize(1200, 760)
        self.configure(bg=theme.CANVAS)
        self.family = theme.configure(self)
        with contextlib.suppress(tk.TclError):
            # 固定 1.0，保证在 2K/4K 屏与截图里字号、列宽一致
            self.tk.call("tk", "scaling", 1.0)
        if seed:
            seed_demo(services)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_login()
        self.after(400, self._tick)

    # ------------------------------------------------------------ 登录
    def _build_login(self) -> None:
        from .login_view import LoginView

        self._clear_root()
        self.login_view = LoginView(self, self)
        self.login_view.pack(fill="both", expand=True)

    def login(self, session: Session) -> None:
        """登录成功后构建主界面。"""
        self.session = session
        self._build_shell()
        self.run_scheduler(quiet=True)

    def logout(self) -> None:
        self.session = None
        self._pages.clear()
        self._nav_buttons.clear()
        self._build_login()

    def _clear_root(self) -> None:
        for child in self.winfo_children():
            child.destroy()

    # ------------------------------------------------------------ 外壳
    def _build_shell(self) -> None:
        assert self.session is not None
        self._clear_root()
        self.nav = tk.Frame(self, bg=theme.PINE_DARK, width=230)
        self.nav.pack(side="left", fill="y")
        self.nav.pack_propagate(False)
        brand = tk.Frame(self.nav, bg=theme.PINE_DARK)
        brand.pack(fill="x", pady=(22, 18), padx=18)
        tk.Label(
            brand,
            text="栖居 QIJU",
            bg=theme.PINE_DARK,
            fg=theme.WHITE,
            font=(self.family, -20, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            brand,
            text="酒店在线预订系统",
            bg=theme.PINE_DARK,
            fg="#BFD3CB",
            font=(self.family, -12),
            anchor="w",
        ).pack(fill="x", pady=(2, 0))

        self.nav_items = tk.Frame(self.nav, bg=theme.PINE_DARK)
        self.nav_items.pack(fill="both", expand=True)
        self._nav_specs = self._navigation_for(self.session.user.role)
        for key, label, _roles in self._nav_specs:
            btn = ttk.Button(
                self.nav_items,
                text=label,
                style="Sidebar.TButton",
                command=lambda k=key: self.show(k),
            )
            btn.pack(fill="x", padx=10, pady=1)
            self._nav_buttons[key] = btn

        bottom = tk.Frame(self.nav, bg=theme.PINE_DARK)
        bottom.pack(side="bottom", fill="x", padx=18, pady=18)
        tk.Label(
            bottom,
            text=self.session.user.display_name,
            bg=theme.PINE_DARK,
            fg=theme.WHITE,
            font=(self.family, -14, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            bottom,
            text=f"{self._role_label(self.session.user.role)} · {self.session.user.phone}",
            bg=theme.PINE_DARK,
            fg="#BFD3CB",
            font=(self.family, -11),
            anchor="w",
        ).pack(fill="x")
        ttk.Button(
            bottom,
            text="退出登录",
            style="Sidebar.TButton",
            command=self.logout,
        ).pack(fill="x", pady=(8, 0), padx=0)

        main = tk.Frame(self, bg=theme.CANVAS)
        main.pack(side="left", fill="both", expand=True)
        self.header = tk.Frame(
            main, bg=theme.WHITE, highlightbackground=theme.LINE, highlightthickness=0
        )
        self.header.pack(fill="x")
        header_inner = tk.Frame(self.header, bg=theme.WHITE)
        header_inner.pack(fill="x", padx=24, pady=16)
        self.page_title = tk.Label(
            header_inner,
            text="",
            bg=theme.WHITE,
            fg=theme.INK,
            font=(self.family, -23, "bold"),
            anchor="w",
        )
        self.page_title.pack(side="left")
        self.page_subtitle = tk.Label(
            header_inner,
            text="",
            bg=theme.WHITE,
            fg=theme.MUTED,
            font=(self.family, -12),
            anchor="w",
        )
        self.page_subtitle.pack(side="left", padx=(12, 0), pady=(6, 0))
        self.header_meta = tk.Label(
            header_inner,
            text="",
            bg=theme.WHITE,
            fg=theme.MUTED,
            font=(self.family, -12),
            anchor="e",
        )
        self.header_meta.pack(side="right")

        self.body = tk.Frame(main, bg=theme.CANVAS)
        self.body.pack(fill="both", expand=True, padx=22, pady=16)

        status = tk.Frame(main, bg=theme.CANVAS)
        status.pack(fill="x", padx=22, pady=(0, 10))
        self.status_label = tk.Label(
            status,
            text="",
            bg=theme.CANVAS,
            fg=theme.MUTED,
            font=(self.family, -12),
            anchor="w",
        )
        self.status_label.pack(side="left")
        self.clock_label = tk.Label(
            status,
            text="",
            bg=theme.CANVAS,
            fg=theme.MUTED,
            font=(self.family, -12),
            anchor="e",
        )
        self.clock_label.pack(side="right")

        pages = self._page_factories()
        self._factories = pages
        first = self._nav_specs[0][0]
        self.show(first)
        self._update_clock()

    @staticmethod
    def _role_label(role: Role) -> str:
        return {
            Role.CUSTOMER: "顾客",
            Role.FRONT_DESK: "前台",
            Role.MANAGER: "店长",
            Role.PLATFORM_ADMIN: "平台管理员",
        }.get(role, role.value)

    def _navigation_for(self, role: Role) -> list[tuple[str, str, set[Role]]]:
        all_roles = {Role.CUSTOMER, Role.FRONT_DESK, Role.MANAGER, Role.PLATFORM_ADMIN}
        specs = [
            ("search", "搜索房型", {Role.CUSTOMER}),
            ("my_orders", "我的订单", {Role.CUSTOMER}),
            ("workbench", "订单工作台", {Role.FRONT_DESK, Role.MANAGER}),
            ("calendar", "房态与价格", {Role.FRONT_DESK, Role.MANAGER}),
            ("room_types", "房型管理", {Role.MANAGER}),
            ("report", "经营报表", {Role.MANAGER, Role.PLATFORM_ADMIN}),
            ("hotels", "酒店审核", {Role.PLATFORM_ADMIN}),
            ("all_orders", "全平台订单", {Role.PLATFORM_ADMIN}),
            ("policies", "确认时限", {Role.PLATFORM_ADMIN}),
            ("logs", "操作日志", {Role.MANAGER, Role.PLATFORM_ADMIN}),
            ("messages", "消息中心", all_roles),
        ]
        return [item for item in specs if role in item[2]]

    def _page_factories(self) -> dict[str, Callable[[tk.Misc, App], Page]]:
        from .admin_views import AllOrdersView, HotelAuditView, PoliciesView
        from .customer_views import MyOrdersView, SearchView
        from .shared_views import LogsView, MessagesView, ReportView
        from .staff_views import CalendarView, RoomTypesView, WorkbenchView

        return {
            "search": SearchView,
            "my_orders": MyOrdersView,
            "workbench": WorkbenchView,
            "calendar": CalendarView,
            "room_types": RoomTypesView,
            "report": ReportView,
            "hotels": HotelAuditView,
            "all_orders": AllOrdersView,
            "policies": PoliciesView,
            "logs": LogsView,
            "messages": MessagesView,
        }

    def show(self, key: str) -> None:
        if key not in self._factories:
            return
        page = self._pages.get(key)
        if page is None:
            factory = self._factories[key]
            page = factory(self.body, self)
            page.pack(fill="both", expand=True)
            self._pages[key] = page
        for other in self._pages.values():
            if other is not page:
                other.pack_forget()
        page.pack(fill="both", expand=True)
        self.page_title.configure(text=page.title)
        self.page_subtitle.configure(text=page.subtitle)
        for name, button_widget in self._nav_buttons.items():
            button_widget.configure(
                style="SidebarActive.TButton" if name == key else "Sidebar.TButton"
            )
        self._current = key
        self.status_label.configure(text="")
        self.refresh_header()
        try:
            page.refresh()
        except Exception as exc:  # 界面层兜底，避免一个页面把整个应用卡死
            messagebox.showerror("加载失败", str(exc))

    # ------------------------------------------------------------ 杂项
    def toast(self, message: str, *, error: bool = False) -> None:
        self.status_label.configure(
            text=message, fg=theme.DANGER if error else theme.OK
        )
        self.after(6000, lambda: self.status_label.configure(text=""))

    def refresh_header(self) -> None:
        if self.session is None:
            return
        try:
            unread = self.services.scheduler.unread_notifications(self.session)
        except Exception:
            unread = 0
        self.header_meta.configure(text=f"未读 {unread}")

    def run_scheduler(self, *, quiet: bool = False) -> None:
        if self.session is None:
            return
        try:
            report = self.services.scheduler.run()
        except Exception as exc:
            if not quiet:
                messagebox.showerror("定时任务失败", str(exc))
            return
        if report.timed_out or report.no_shows or report.diffs:
            self.toast(
                f"定时任务：超时取消 {report.timed_out} 张，"
                f"未入住关闭 {report.no_shows} 张，对账差异 {len(report.diffs)} 条"
            )
        elif not quiet:
            self.toast("定时任务执行完毕，没有需要处理的订单")
        self.refresh_header()
        page = self._pages.get(getattr(self, "_current", ""))
        if page is not None:
            with contextlib.suppress(Exception):
                page.refresh()

    def _tick(self) -> None:
        self._update_clock()
        self.after(30000, self._tick)

    def _update_clock(self) -> None:
        now = SystemClock().now()
        self.clock_label.configure(
            text=f"酒店当地时间 {now.strftime('%Y-%m-%d %H:%M')}"
        )

    def _on_close(self) -> None:
        try:
            self.services.close()
        finally:
            self.destroy()

    # 供截图脚本使用
    def login_as(self, phone: str, password: str) -> None:
        session = self.services.auth.login(phone, password)
        self.login(session)
