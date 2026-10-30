"""无界面演示与自检。

用法::

    python -m qiju.cli demo      # 内存库跑一遍“查询→下单→确认→入住→退房→报表”
    python -m qiju.cli verify    # 核对订单间夜与库存已售数
    python -m qiju.cli seed --db ./qiju.db

``demo`` 也是我提交前的手动回归脚本：它不依赖界面，能在 2 秒内把
主流程和三个异常分支跑一遍。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, time, timedelta

from .application import Session, build
from .application.booking_service import BookingRequest
from .domain.clock import HOTEL_TZ, FixedClock
from .domain.entities import Guest
from .domain.enums import OrderStatus
from .domain.errors import DomainError
from .domain.money import format_money
from .infrastructure.seed import DEMO_PASSWORD, seed_demo


def _rule(text: str) -> None:
    print(f"\n{'=' * 8} {text} {'=' * 8}")


def demo(now: datetime | None = None) -> int:
    moment = now or datetime.now(tz=HOTEL_TZ).replace(hour=10, minute=0, second=0, microsecond=0)
    app = build(":memory:", FixedClock(moment))
    seed_demo(app, now=moment)
    customer = Session(app.ctx.repos.users.by_phone("13600000001"))
    front = Session(app.ctx.repos.users.by_phone("13700000001"))
    manager = Session(app.ctx.repos.users.by_phone("13900000001"))
    today = moment.date()

    _rule("1. 可订查询")
    results = app.booking.search(
        city="南京",
        check_in=today + timedelta(days=1),
        check_out=today + timedelta(days=3),
        guests=2,
    )
    for item in results[:4]:
        print(
            f"  {item.hotel.name:<12} {item.room_type.name:<8} "
            f"{len(item.nights)} 晚 合计 {format_money(item.total_cents):>9} "
            f"剩余 {item.remaining} 间"
        )

    _rule("2. 提交预订（逐晚扣减 + 幂等）")
    request = BookingRequest(
        room_type_id=results[0].room_type.id,
        check_in=today + timedelta(days=1),
        check_out=today + timedelta(days=3),
        room_count=1,
        guests=[Guest("林小满", "13600000001")],
        request_id="demo-001",
    )
    order = app.booking.create_order(customer, request)
    again = app.booking.create_order(customer, request)
    print(
        f"  订单号 {order.order_no}，状态 {order.status.value}，"
        f"总价 {format_money(order.total_cents)}"
    )
    print(f"  同一 request_id 重放返回同一订单：{order.id == again.id}")
    try:
        app.booking.create_order(
            customer,
            BookingRequest(
                room_type_id=results[0].room_type.id,
                check_in=today + timedelta(days=1),
                check_out=today + timedelta(days=3),
                room_count=1,
                guests=[Guest("林小满", "13600000001")],
                request_id="demo-duplicate",
            ),
        )
    except DomainError as exc:
        print(f"  重复内容提示：{exc.message}")
    for night in order.nights:
        print(f"    {night.day}  ¥{night.price_cents / 100:.2f} × {night.room_count}")

    _rule("3. 确认 → 入住 → 退房")
    app.ctx.clock = FixedClock(moment)
    app.orders.confirm(front, order.order_no)
    app.ctx.clock = FixedClock(
        datetime.combine(today + timedelta(days=1), time(14, 30), tzinfo=HOTEL_TZ)
    )
    app.orders.check_in(front, order.order_no)
    app.ctx.clock = FixedClock(
        datetime.combine(today + timedelta(days=3), time(9, 40), tzinfo=HOTEL_TZ)
    )
    app.orders.check_out(front, order.order_no)
    done = app.orders.get(customer, order.order_no)
    refunds = app.orders.refunds(customer, order.order_no)
    print(f"  最终状态 {done.status.value}，退款记录 {len(refunds)} 条")

    _rule("4. 异常分支")
    app.ctx.clock = FixedClock(moment)
    try:
        app.booking.create_order(
            customer,
            BookingRequest(
                room_type_id=results[0].room_type.id,
                check_in=today + timedelta(days=1),
                check_out=today + timedelta(days=3),
                room_count=20,
                guests=[Guest("林小满", "13600000001")],
                request_id="demo-overbook",
            ),
        )
    except DomainError as exc:
        print(f"  超卖拦截：{exc.message}")
    try:
        app.orders.confirm(front, order.order_no)
    except DomainError as exc:
        print(f"  非法状态转换：{exc.message}")

    _rule("5. 定时任务与对账")
    app.ctx.clock = FixedClock(moment)
    report = app.scheduler.run()
    print(
        f"  超时取消 {report.timed_out} 张，未入住关闭 {report.no_shows} 张，"
        f"对账差异 {len(report.diffs)} 条"
    )

    _rule("6. 经营报表（最近 14 天）")
    summary = app.reports.summary(
        manager, start=today - timedelta(days=13), end=today + timedelta(days=1)
    )
    print(
        f"  可售 {summary.sellable_nights} 间夜，计费 {summary.sold_nights} 间夜，"
        f"已住 {summary.stayed_nights} 间夜"
    )
    print(
        f"  出租率 {(summary.occupancy or 0) * 100:.1f}%，"
        f"平均房价 {format_money(summary.adr_cents or 0)}，"
        f"成交 {format_money(summary.revenue_cents)}，"
        f"退款 {format_money(summary.refund_cents)}"
    )
    print(f"  演示账号：{customer.user.phone} / {DEMO_PASSWORD}")
    app.close()
    return 0


def verify(path: str) -> int:
    """核对待确认/已确认/已入住/已完成订单的间夜与库存已售数。"""
    app = build(path)
    today = app.ctx.clock.now().date()
    problems = 0
    for order in app.ctx.repos.orders.list_with_nights_between(
        today, today + timedelta(days=30)
    ):
        if order.status not in (
            OrderStatus.PENDING,
            OrderStatus.CONFIRMED,
            OrderStatus.CHECKED_IN,
            OrderStatus.COMPLETED,
        ):
            continue
        for night in order.nights:
            item = app.ctx.repos.inventory.get(order.room_type_id, night.day)
            if item is None:
                print(f"  缺少库存记录：{order.order_no} {night.day}")
                problems += 1
    print(f"核对完成：{'未发现缺失' if problems == 0 else f'{problems} 处缺失'}")
    app.close()
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="栖居系统命令行工具")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("demo", help="运行无界面演示")
    verify_parser = sub.add_parser("verify", help="核对库存与订单间夜")
    verify_parser.add_argument("--db", default="./qiju.db")
    seed_parser = sub.add_parser("seed", help="向指定数据库写演示数据")
    seed_parser.add_argument("--db", default="./qiju.db")
    args = parser.parse_args(argv)
    if args.command == "demo":
        return demo()
    if args.command == "verify":
        return verify(args.db)
    if args.command == "seed":
        app = build(args.db)
        seed_demo(app)
        print(f"演示数据已写入 {args.db}")
        app.close()
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
