"""桌面端启动入口：``python run.py``。"""

from __future__ import annotations

import argparse
import sys

from qiju.application import build
from qiju.ui.app import DEFAULT_DB, App


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="栖居酒店在线预订系统（桌面版）")
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB),
        help=f"SQLite 数据库路径，默认 {DEFAULT_DB}",
    )
    parser.add_argument(
        "--no-seed",
        action="store_true",
        help="空库时不写入演示数据",
    )
    args = parser.parse_args(argv)
    services = build(args.db)
    app = App(services, db_path=args.db, seed=not args.no_seed)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
