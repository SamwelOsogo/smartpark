"""
database.py
-----------
Sets up and manages the SQLite database for SmartPark.

Design goal: the fee structure lives in the RateTier table, not in the
code. Management can add/edit/remove tiers (via the /admin/rates page
or directly in the DB) and the fee calculation logic will pick up the
change immediately -- satisfying the "change rates without a software
change" requirement.
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "smartpark.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS ParkingSlot (
    slot_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    bay_number   INTEGER NOT NULL UNIQUE,
    status       TEXT NOT NULL DEFAULT 'available'  -- 'available' | 'occupied'
);

CREATE TABLE IF NOT EXISTS Vehicle (
    vehicle_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    plate_number  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS ParkingSession (
    session_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id       INTEGER NOT NULL,
    slot_id          INTEGER NOT NULL,
    entry_time       TEXT NOT NULL,
    exit_time        TEXT,
    duration_minutes INTEGER,
    amount_payable   REAL,
    payment_method   TEXT,
    payment_status   TEXT NOT NULL DEFAULT 'pending', -- 'pending' | 'paid'
    FOREIGN KEY (vehicle_id) REFERENCES Vehicle(vehicle_id),
    FOREIGN KEY (slot_id) REFERENCES ParkingSlot(slot_id)
);

-- Dynamic rate table: tiers can be edited without touching code.
-- up_to_minutes = NULL means "no upper bound" (applies beyond the last tier)
CREATE TABLE IF NOT EXISTS RateTier (
    tier_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    label         TEXT NOT NULL,
    up_to_minutes INTEGER,      -- NULL = open-ended (final/overflow tier)
    fee_kshs      REAL NOT NULL,
    sort_order    INTEGER NOT NULL
);
"""

DEFAULT_TIERS = [
    ("Up to 30 minutes (free)", 30, 0, 1),
    ("Up to 2 hours", 120, 50, 2),
    ("Up to 4 hours", 240, 100, 3),
    ("Up to 6 hours", 360, 300, 4),
    ("Over 6 hours", None, 500, 5),
]


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(total_bays: int = 10):
    """Creates tables (if missing) and seeds slots + default rate tiers."""
    conn = get_connection()
    cur = conn.cursor()
    cur.executescript(SCHEMA)

    # Seed bays only if the table is empty
    cur.execute("SELECT COUNT(*) FROM ParkingSlot")
    if cur.fetchone()[0] == 0:
        cur.executemany(
            "INSERT INTO ParkingSlot (bay_number, status) VALUES (?, 'available')",
            [(i,) for i in range(1, total_bays + 1)],
        )

    # Seed rate tiers only if the table is empty
    cur.execute("SELECT COUNT(*) FROM RateTier")
    if cur.fetchone()[0] == 0:
        cur.executemany(
            "INSERT INTO RateTier (label, up_to_minutes, fee_kshs, sort_order) "
            "VALUES (?, ?, ?, ?)",
            DEFAULT_TIERS,
        )

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Database initialised at {DB_PATH}")
