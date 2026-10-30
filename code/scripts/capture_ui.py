"""生成实验报告用的界面截图。

用法::

    DISPLAY=:0 python scripts/capture_ui.py ../report/figs

依赖 ImageMagick 的 ``import``（X11 窗口抓图）。这不是应用的一部分，
只是交付前的一次性脚本，放在仓库里是为了让截图可复现。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qiju.application import build  # noqa: E402
from qiju.ui.app import App  # noqa: E402


def shot(widget, target: Path) -> None:
    widget.update_idletasks()
    widget.update()
    time.sleep(0.25)
    subprocess.run(
        ["import", "-window", hex(widget.winfo_id()), str(target)],
        check=True,
    )
    print("saved", target)


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "../report/figs")
    out.mkdir(parents=True, exist_ok=True)
    db = Path(tempfile.mkdtemp()) / "demo.db"
    services = build(str(db))
    app = App(services, db_path=db, seed=True)
    app.geometry("1440x900+40+40")
    app.update()
    shot(app, out / "ui-01-login.png")

    app.login_as("13600000001", "Qiju@2026")
    app.update()
    search = app._pages["search"]
    shot(app, out / "ui-02-search.png")
    children = search.table.tree.get_children()
    if len(children) > 1:
        search.table.tree.selection_set(children[1])
        search.table.tree.focus(children[1])
        app.update()
    shot(app, out / "ui-03-room-detail.png")
    search._open_booking()
    app.update()
    dialog = app.grab_current()
    shot(dialog, out / "ui-04-booking-dialog.png")
    dialog.destroy()

    app.show("my_orders")
    app.update()
    shot(app, out / "ui-05-my-orders.png")

    app.logout()
    app.update()
    app.login_as("13700000001", "Front@2026")
    app.update()
    app.show("workbench")
    app.update()
    workbench = app._pages["workbench"]
    for iid, row in workbench.table._rows.items():
        if row["status"] == "待确认":
            workbench.table.tree.selection_set(iid)
            workbench.table.tree.focus(iid)
            break
    app.update()
    shot(app, out / "ui-06-workbench.png")

    app.logout()
    app.update()
    app.login_as("13900000001", "Manager@2026")
    app.update()
    app.show("calendar")
    app.update()
    calendar = app._pages["calendar"]
    for iid, row in calendar.table._rows.items():
        if row["stop"] == "停售":
            calendar.table.tree.selection_set(iid)
            calendar.table.tree.focus(iid)
            break
    app.update()
    shot(app, out / "ui-07-calendar.png")
    app.show("report")
    app.update()
    shot(app, out / "ui-08-report.png")

    app.logout()
    app.update()
    app.login_as("13800000000", "Admin@2026")
    app.update()
    app.show("hotels")
    app.update()
    shot(app, out / "ui-09-hotel-audit.png")
    app.show("logs")
    app.update()
    shot(app, out / "ui-10-logs.png")
    app.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
