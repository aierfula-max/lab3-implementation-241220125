"""REQ-029：50 个并发抢最后一间，只能成功一个。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from qiju.application.booking_service import BookingRequest
from qiju.domain.entities import Guest, RoomType, new_id
from qiju.domain.errors import SoldOut
from tests.factories import Org
from tests.helpers import sold


def test_fifty_threads_one_room(org: Org):
    repos = org.app.ctx.repos
    last_room = RoomType(
        id=new_id(),
        hotel_id=org.hotel_a.id,
        name="最后一间",
        capacity=2,
        total_rooms=1,
        base_price_cents=30000,
    )
    repos.room_types.add(last_room)
    today = org.clock.now().date()
    org.app.inventory.set_day(
        org.manager_a,
        room_type_id=last_room.id,
        day=today + timedelta(days=1),
        total_rooms=1,
        price_cents=30000,
    )
    org.app.inventory.set_day(
        org.manager_a,
        room_type_id=last_room.id,
        day=today + timedelta(days=2),
        total_rooms=1,
        price_cents=30000,
    )

    def attempt(index: int) -> str:
        try:
            order = org.app.booking.create_order(
                org.customer,
                BookingRequest(
                    room_type_id=last_room.id,
                    check_in=today + timedelta(days=1),
                    check_out=today + timedelta(days=3),
                    room_count=1,
                    guests=[Guest("并发客", f"1360000{index:04d}")],
                    request_id=f"concurrent-{index}",
                ),
            )
            return f"ok:{order.order_no}"
        except SoldOut:
            return "sold-out"
        except Exception as exc:  # pragma: no cover - 失败时把异常类型带出来
            return f"error:{type(exc).__name__}:{exc}"

    with ThreadPoolExecutor(max_workers=50) as pool:
        results = list(pool.map(attempt, range(50)))
    successes = [item for item in results if item.startswith("ok:")]
    assert len(successes) == 1, results
    assert all(item == "sold-out" for item in results if not item.startswith("ok:"))
    assert sold(org, last_room.id, today + timedelta(days=1)) == 1
    assert sold(org, last_room.id, today + timedelta(days=2)) == 1
    assert len(org.app.orders.list_mine(org.customer)) == 1
