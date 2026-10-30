"""SQLite 连接、建表与事务。

桌面版用 SQLite 而不是 PostgreSQL，是本实验里唯一一处“向下兼容”的取舍：
需求写的是行锁 + 事务，而 SQLite 只有一个写者。我的处理是
**一个连接 + 一把可重入锁 + ``BEGIN IMMEDIATE``**，让每个下单/取消在
进程内串行执行，语义上等价于“整库行锁”。它保证不超卖，但吞吐低，
所以报告的“不足”里明确写了：多节点部署必须换 PostgreSQL 并改回
``SELECT ... FOR UPDATE``。这里不想假装桌面版能扛 50 并发用户。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

SCHEMA = """
CREATE TABLE IF NOT EXISTS hotels (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    city            TEXT NOT NULL,
    address         TEXT NOT NULL,
    phone           TEXT NOT NULL,
    business_status TEXT NOT NULL,
    audit_status    TEXT NOT NULL,
    audit_note      TEXT NOT NULL DEFAULT '',
    description     TEXT NOT NULL DEFAULT '',
    pending_profile TEXT NOT NULL DEFAULT '',
    checkin_time    TEXT NOT NULL DEFAULT '14:00',
    checkout_time   TEXT NOT NULL DEFAULT '12:00',
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    phone         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    status        TEXT NOT NULL,
    hotel_id      TEXT REFERENCES hotels(id),
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invitation_codes (
    code       TEXT PRIMARY KEY,
    hotel_id   TEXT NOT NULL REFERENCES hotels(id),
    created_by TEXT NOT NULL REFERENCES users(id),
    expires_at TEXT NOT NULL,
    used_by    TEXT REFERENCES users(id),
    used_at    TEXT
);

CREATE TABLE IF NOT EXISTS room_types (
    id               TEXT PRIMARY KEY,
    hotel_id         TEXT NOT NULL REFERENCES hotels(id),
    name             TEXT NOT NULL,
    capacity         INTEGER NOT NULL CHECK (capacity >= 1),
    total_rooms      INTEGER NOT NULL CHECK (total_rooms >= 0),
    base_price_cents INTEGER NOT NULL CHECK (base_price_cents > 0),
    bed_type         TEXT NOT NULL,
    area_m2          INTEGER NOT NULL,
    has_window       INTEGER NOT NULL DEFAULT 1,
    on_sale          INTEGER NOT NULL DEFAULT 1,
    UNIQUE (hotel_id, name)
);

CREATE TABLE IF NOT EXISTS daily_inventory (
    room_type_id TEXT NOT NULL REFERENCES room_types(id),
    day          TEXT NOT NULL,
    total_rooms  INTEGER NOT NULL CHECK (total_rooms >= 0),
    sold_rooms   INTEGER NOT NULL DEFAULT 0 CHECK (sold_rooms >= 0),
    price_cents  INTEGER NOT NULL CHECK (price_cents > 0),
    stop_sale    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (room_type_id, day)
);

CREATE TABLE IF NOT EXISTS stop_sale_rules (
    id           TEXT PRIMARY KEY,
    room_type_id TEXT NOT NULL REFERENCES room_types(id),
    start_date   TEXT NOT NULL,
    end_date     TEXT NOT NULL,
    created_by   TEXT NOT NULL REFERENCES users(id),
    CHECK (end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS orders (
    id              TEXT PRIMARY KEY,
    order_no        TEXT NOT NULL UNIQUE,
    user_id         TEXT NOT NULL REFERENCES users(id),
    hotel_id        TEXT NOT NULL REFERENCES hotels(id),
    room_type_id    TEXT NOT NULL REFERENCES room_types(id),
    check_in        TEXT NOT NULL,
    check_out       TEXT NOT NULL,
    room_count      INTEGER NOT NULL CHECK (room_count >= 1),
    status          TEXT NOT NULL,
    total_cents     INTEGER NOT NULL CHECK (total_cents >= 0),
    request_id      TEXT NOT NULL,
    policy_version  TEXT NOT NULL DEFAULT 'policy_v1',
    version         INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    confirm_deadline TEXT,
    confirmed_at    TEXT,
    confirmed_by    TEXT,
    checked_in_at   TEXT,
    checked_in_by   TEXT,
    checked_out_at  TEXT,
    checked_out_by  TEXT,
    actual_check_out TEXT,
    canceled_at     TEXT,
    cancel_reason   TEXT NOT NULL DEFAULT '',
    rejected_at     TEXT,
    reject_reason   TEXT NOT NULL DEFAULT '',
    reject_note     TEXT NOT NULL DEFAULT '',
    modified        INTEGER NOT NULL DEFAULT 0,
    early_checkout  INTEGER NOT NULL DEFAULT 0,
    CHECK (check_out > check_in),
    UNIQUE (user_id, request_id)
);

CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_hotel ON orders(hotel_id, status);
CREATE INDEX IF NOT EXISTS idx_orders_checkin ON orders(check_in);

CREATE TABLE IF NOT EXISTS order_nights (
    order_id       TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    day            TEXT NOT NULL,
    price_cents    INTEGER NOT NULL,
    room_count     INTEGER NOT NULL,
    subtotal_cents INTEGER NOT NULL,
    PRIMARY KEY (order_id, day)
);

CREATE TABLE IF NOT EXISTS guests (
    id       TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    name     TEXT NOT NULL,
    phone    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_changes (
    id             TEXT PRIMARY KEY,
    order_id       TEXT NOT NULL REFERENCES orders(id),
    before_summary TEXT NOT NULL,
    after_summary  TEXT NOT NULL,
    diff_cents     INTEGER NOT NULL,
    operator_id    TEXT NOT NULL,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS refund_records (
    id               TEXT PRIMARY KEY,
    refund_no        TEXT NOT NULL UNIQUE,
    order_id         TEXT NOT NULL REFERENCES orders(id),
    event_type       TEXT NOT NULL,
    refundable_cents INTEGER NOT NULL,
    deducted_cents   INTEGER NOT NULL,
    status           TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    marked_by        TEXT,
    marked_at        TEXT,
    UNIQUE (order_id, event_type)
);

CREATE TABLE IF NOT EXISTS operation_logs (
    id           TEXT PRIMARY KEY,
    actor_id     TEXT,
    actor_role   TEXT NOT NULL,
    hotel_id     TEXT,
    action       TEXT NOT NULL,
    object_type  TEXT NOT NULL,
    object_id    TEXT NOT NULL,
    before_value TEXT NOT NULL DEFAULT '',
    after_value  TEXT NOT NULL DEFAULT '',
    reason       TEXT NOT NULL DEFAULT '',
    ip           TEXT NOT NULL DEFAULT '',
    request_id   TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_logs_time ON operation_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_logs_hotel ON operation_logs(hotel_id);

CREATE TABLE IF NOT EXISTS notifications (
    id         TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id),
    title      TEXT NOT NULL,
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read_at    TEXT
);

CREATE TABLE IF NOT EXISTS confirm_policies (
    hotel_id        TEXT PRIMARY KEY REFERENCES hotels(id),
    timeout_minutes INTEGER NOT NULL CHECK (timeout_minutes BETWEEN 15 AND 60),
    updated_by      TEXT,
    updated_at      TEXT
);
"""


class Database:
    """薄封装：建表、事务、查询。

    所有仓储共享一个 ``Database`` 实例。``transaction()`` 支持嵌套：
    只有最外层真正 ``BEGIN/COMMIT``，内层复用外层事务，保证“业务 + 日志”
    同事务提交（REQ-019/028）。
    """

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._conn = sqlite3.connect(
            self.path,
            check_same_thread=False,
            isolation_level=None,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._depth = 0
        with self._lock:
            self._conn.executescript(SCHEMA)

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """写事务。嵌套调用复用最外层事务。"""
        with self._lock:
            outermost = self._depth == 0
            if outermost:
                self._conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield self._conn
            except BaseException:
                self._depth -= 1
                if outermost:
                    self._conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if outermost:
                    self._conn.execute("COMMIT")

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def query_all(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def reset(self) -> None:
        """仅供测试：清空所有业务表。"""
        with self.transaction() as conn:
            for table in (
                "operation_logs",
                "notifications",
                "refund_records",
                "order_changes",
                "guests",
                "order_nights",
                "orders",
                "stop_sale_rules",
                "daily_inventory",
                "room_types",
                "invitation_codes",
                "confirm_policies",
                "users",
                "hotels",
            ):
                conn.execute(f"DELETE FROM {table}")
