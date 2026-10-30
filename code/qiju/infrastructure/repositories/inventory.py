"""每日库存仓储。

库存扣减是本项目最需要小心的一张表。这里只提供两个“原子动作”：

* ``hold``：``sold_rooms + n``，带 ``sold_rooms + n <= total_rooms`` 与
  ``stop_sale = 0`` 的条件，更新 0 行即售罄；
* ``release``：``sold_rooms - n``，带 ``sold_rooms >= n`` 的条件，防止释放
  超过已售数量。

条件写在 ``WHERE`` 里而不是先查后改，是避免“先查后扣”的唯一办法。
在 SQLite 的单写者模型下这已经足够；换成 PostgreSQL 时把这两条改成
``UPDATE ... WHERE`` 同样成立，不需要改业务代码。
"""

from __future__ import annotations

from datetime import date, timedelta

from ...domain.entities import DailyInventory
from ..db import Database
from ..mapping import inventory_from_row


class InventoryRepository:
    """``daily_inventory`` 表。"""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, room_type_id: str, day: date) -> DailyInventory | None:
        row = self.db.query_one(
            """
            SELECT * FROM daily_inventory
             WHERE room_type_id = ? AND day = ?
            """,
            (room_type_id, day.isoformat()),
        )
        return inventory_from_row(row) if row else None

    def list_range(
        self, room_type_id: str, start: date, end: date
    ) -> dict[date, DailyInventory]:
        rows = self.db.query_all(
            """
            SELECT * FROM daily_inventory
             WHERE room_type_id = ? AND day >= ? AND day < ?
             ORDER BY day
            """,
            (room_type_id, start.isoformat(), end.isoformat()),
        )
        return {inventory_from_row(row).day: inventory_from_row(row) for row in rows}

    def list_by_hotel(
        self,
        hotel_id: str,
        start: date,
        end: date,
    ) -> list[DailyInventory]:
        """房态日历用：一次取某酒店全部房型在区间内的记录。"""
        rows = self.db.query_all(
            """
            SELECT i.* FROM daily_inventory i
              JOIN room_types r ON r.id = i.room_type_id
             WHERE r.hotel_id = ? AND i.day >= ? AND i.day < ?
             ORDER BY r.name, i.day
            """,
            (hotel_id, start.isoformat(), end.isoformat()),
        )
        return [inventory_from_row(row) for row in rows]

    def ensure(
        self, room_type_id: str, day: date, total_rooms: int, price_cents: int
    ) -> None:
        """无记录的日期按房型可售数与基准价生成记录（REQ-006）。

        ``INSERT OR IGNORE`` 保证并发首次预订同一天时只有一条记录。
        """
        self.db.execute(
            """
            INSERT OR IGNORE INTO daily_inventory
                (room_type_id, day, total_rooms, sold_rooms, price_cents, stop_sale)
            VALUES (?, ?, ?, 0, ?, 0)
            """,
            (room_type_id, day.isoformat(), total_rooms, price_cents),
        )

    def hold(self, room_type_id: str, day: date, count: int) -> bool:
        """原子占用；返回 False 表示库存不足或已停售。"""
        cursor = self.db.execute(
            """
            UPDATE daily_inventory
               SET sold_rooms = sold_rooms + ?
             WHERE room_type_id = ? AND day = ?
               AND stop_sale = 0
               AND sold_rooms + ? <= total_rooms
            """,
            (count, room_type_id, day.isoformat(), count),
        )
        return cursor.rowcount == 1

    def release(self, room_type_id: str, day: date, count: int) -> bool:
        """原子释放；返回 False 表示释放数超过已售数。"""
        cursor = self.db.execute(
            """
            UPDATE daily_inventory
               SET sold_rooms = sold_rooms - ?
             WHERE room_type_id = ? AND day = ?
               AND sold_rooms >= ?
            """,
            (count, room_type_id, day.isoformat(), count),
        )
        return cursor.rowcount == 1

    def save(self, inventory: DailyInventory) -> None:
        """店长维护库存/价格/停售时整行写入。"""
        self.db.execute(
            """
            INSERT INTO daily_inventory
                (room_type_id, day, total_rooms, sold_rooms, price_cents, stop_sale)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(room_type_id, day) DO UPDATE SET
                total_rooms = excluded.total_rooms,
                sold_rooms = excluded.sold_rooms,
                price_cents = excluded.price_cents,
                stop_sale   = excluded.stop_sale
            """,
            (
                inventory.room_type_id,
                inventory.day.isoformat(),
                inventory.total_rooms,
                inventory.sold_rooms,
                inventory.price_cents,
                int(inventory.stop_sale),
            ),
        )

    def set_stop_sale(self, room_type_id: str, day: date, stop: bool) -> None:
        self.db.execute(
            """
            UPDATE daily_inventory SET stop_sale = ?
             WHERE room_type_id = ? AND day = ?
            """,
            (int(stop), room_type_id, day.isoformat()),
        )

    def max_sold(self, room_type_id: str, start: date | None = None) -> int:
        """未来日期已售出的最大间数，用于校验“可售数不能低于已售”。"""
        if start is None:
            start = date.today()
        row = self.db.query_one(
            """
            SELECT MAX(sold_rooms) AS value FROM daily_inventory
             WHERE room_type_id = ? AND day >= ?
            """,
            (room_type_id, start.isoformat()),
        )
        return int(row["value"] or 0) if row else 0

    def sold_in_range(self, room_type_id: str, start: date, end: date) -> int:
        """区间内已售间夜（用于核对与报表）。"""
        row = self.db.query_one(
            """
            SELECT COALESCE(SUM(sold_rooms), 0) AS value
              FROM daily_inventory
             WHERE room_type_id = ? AND day >= ? AND day < ?
            """,
            (room_type_id, start.isoformat(), end.isoformat()),
        )
        return int(row["value"]) if row else 0

    @staticmethod
    def dates(start: date, end: date) -> list[date]:
        return [start + timedelta(days=i) for i in range((end - start).days)]
