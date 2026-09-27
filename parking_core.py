"""
parking_core.py
----------------
Core algorithm and data structures for SmartPark.

DATA STRUCTURES USED (and why):

1. Min-heap (heapq) of free bay numbers.
   - Reason: entry always needs "the lowest-numbered free bay" and exit
     needs to return a bay to the pool. A min-heap gives O(log n) for
     both allocate and release, and always yields the smallest free bay
     at the top -- better than scanning a list (O(n)) for every entry.

2. Dictionary (hash map) of plate_number -> active session info.
   - Reason: exit lookups happen by plate number. A hash map gives O(1)
     average lookup instead of scanning all active sessions.

3. SQLite tables as the persistent store (see database.py).
   - The heap and dict above are an in-memory cache/index rebuilt from
     the database on startup, so the system survives restarts and keeps
     an auditable, queryable history (ParkingSession rows) for
     reconciliation and VAT reporting.
"""

import heapq
import math
from datetime import datetime

from database import get_connection


class ParkingCore:
    def __init__(self):
        self._free_bays = []       # min-heap of available bay_numbers
        self._bay_id_map = {}      # bay_number -> slot_id
        self._active = {}          # plate_number -> session dict (cache)
        self._load_state()

    # ---------- state loading ----------

    def _load_state(self):
        conn = get_connection()
        cur = conn.cursor()

        cur.execute("SELECT slot_id, bay_number, status FROM ParkingSlot")
        rows = cur.fetchall()
        self._bay_id_map = {r["bay_number"]: r["slot_id"] for r in rows}
        self._free_bays = [r["bay_number"] for r in rows if r["status"] == "available"]
        heapq.heapify(self._free_bays)

        cur.execute(
            """SELECT ps.session_id, v.plate_number, ps.slot_id, ps.entry_time,
                      pl.bay_number
               FROM ParkingSession ps
               JOIN Vehicle v ON v.vehicle_id = ps.vehicle_id
               JOIN ParkingSlot pl ON pl.slot_id = ps.slot_id
               WHERE ps.payment_status = 'pending' AND ps.exit_time IS NULL"""
        )
        for r in cur.fetchall():
            self._active[r["plate_number"]] = {
                "session_id": r["session_id"],
                "bay_number": r["bay_number"],
                "entry_time": r["entry_time"],
            }
        conn.close()

    # ---------- public status ----------

    def total_bays(self):
        return len(self._bay_id_map)

    def available_count(self):
        return len(self._free_bays)

    def occupied_bays(self):
        """Returns list of dicts for the live display board."""
        return sorted(
            [
                {"plate": plate, "bay": info["bay_number"], "entry_time": info["entry_time"]}
                for plate, info in self._active.items()
            ],
            key=lambda x: x["bay"],
        )

    def rate_tiers(self):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT label, up_to_minutes, fee_kshs FROM RateTier ORDER BY sort_order")
        tiers = [dict(r) for r in cur.fetchall()]
        conn.close()
        return tiers

    # ---------- ALGORITHM: vehicle entry ----------

    def vehicle_entry(self, plate_number: str):
        """
        Entry algorithm:
          1. Reject if lot full (heap empty).
          2. Reject if this plate already has an active session.
          3. Pop lowest bay number from the min-heap.
          4. Create/find the Vehicle row.
          5. Insert a ParkingSession row (entry_time = now, exit fields NULL).
          6. Mark the bay 'occupied' in ParkingSlot.
          7. Cache the session in the in-memory dict for O(1) exit lookup.
        """
        plate_number = plate_number.strip().upper()
        if not plate_number:
            return {"ok": False, "error": "Plate number is required."}

        if plate_number in self._active:
            return {"ok": False, "error": f"{plate_number} already has an active session."}

        if not self._free_bays:
            return {"ok": False, "error": "Parking lot is full. No bays available."}

        bay_number = heapq.heappop(self._free_bays)
        slot_id = self._bay_id_map[bay_number]
        entry_time = datetime.now().isoformat(timespec="seconds")

        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO Vehicle (plate_number) VALUES (?) "
            "ON CONFLICT(plate_number) DO NOTHING",
            (plate_number,),
        )
        cur.execute("SELECT vehicle_id FROM Vehicle WHERE plate_number = ?", (plate_number,))
        vehicle_id = cur.fetchone()["vehicle_id"]

        cur.execute(
            "INSERT INTO ParkingSession (vehicle_id, slot_id, entry_time, payment_status) "
            "VALUES (?, ?, ?, 'pending')",
            (vehicle_id, slot_id, entry_time),
        )
        session_id = cur.lastrowid
        cur.execute("UPDATE ParkingSlot SET status = 'occupied' WHERE slot_id = ?", (slot_id,))
        conn.commit()
        conn.close()

        self._active[plate_number] = {
            "session_id": session_id,
            "bay_number": bay_number,
            "entry_time": entry_time,
        }

        return {
            "ok": True,
            "plate": plate_number,
            "bay": bay_number,
            "entry_time": entry_time,
            "slots_remaining": self.available_count(),
        }

    # ---------- ALGORITHM: fee calculation ----------

    def calculate_fee(self, duration_minutes: int):
        """
        Walks the RateTier table (ordered by sort_order) and returns the
        fee for the first tier whose up_to_minutes >= duration.
        A NULL up_to_minutes tier is the open-ended overflow tier.
        """
        tiers = self.rate_tiers()
        for tier in tiers:
            if tier["up_to_minutes"] is None or duration_minutes <= tier["up_to_minutes"]:
                return tier["fee_kshs"], tier["label"]
        # Fallback (should not happen if a final NULL tier exists)
        return tiers[-1]["fee_kshs"], tiers[-1]["label"]

    # ---------- ALGORITHM: vehicle exit ----------

    def quote_exit(self, plate_number: str):
        """Computes (without committing) the amount payable for a plate."""
        plate_number = plate_number.strip().upper()
        session = self._active.get(plate_number)
        if not session:
            return {"ok": False, "error": f"No active session found for {plate_number}."}

        entry_time = datetime.fromisoformat(session["entry_time"])
        duration_minutes = math.ceil((datetime.now() - entry_time).total_seconds() / 60)
        fee, tier_label = self.calculate_fee(duration_minutes)

        return {
            "ok": True,
            "plate": plate_number,
            "bay": session["bay_number"],
            "duration_minutes": duration_minutes,
            "fee": fee,
            "tier_label": tier_label,
        }

    def vehicle_exit(self, plate_number: str, payment_method: str):
        """
        Exit algorithm:
          1. Look up active session by plate (O(1) via dict).
          2. duration = now - entry_time; round up to the minute.
          3. fee = calculate_fee(duration)  [see RateTier walk above]
          4. Simulate payment confirmation (would call M-Pesa/card gateway
             in production -- barrier opens ONLY if this returns True).
          5. On success: write exit_time, duration, amount, payment_method,
             payment_status='paid' to ParkingSession (the audit trail).
          6. Return the bay to the min-heap and mark ParkingSlot 'available'.
          7. Remove the plate from the in-memory active-session cache.
        """
        quote = self.quote_exit(plate_number)
        if not quote["ok"]:
            return quote

        payment_confirmed = self._confirm_payment(quote["fee"], payment_method)
        if not payment_confirmed:
            return {"ok": False, "error": "Payment failed or was not confirmed. Barrier remains closed."}

        plate_number = quote["plate"]
        session = self._active[plate_number]
        exit_time = datetime.now().isoformat(timespec="seconds")
        slot_id = self._bay_id_map[session["bay_number"]]

        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """UPDATE ParkingSession
               SET exit_time = ?, duration_minutes = ?, amount_payable = ?,
                   payment_method = ?, payment_status = 'paid'
               WHERE session_id = ?""",
            (exit_time, quote["duration_minutes"], quote["fee"], payment_method, session["session_id"]),
        )
        cur.execute("UPDATE ParkingSlot SET status = 'available' WHERE slot_id = ?", (slot_id,))
        conn.commit()
        conn.close()

        heapq.heappush(self._free_bays, session["bay_number"])
        del self._active[plate_number]

        quote["exit_time"] = exit_time
        quote["payment_method"] = payment_method
        quote["slots_remaining"] = self.available_count()
        return quote

    def _confirm_payment(self, amount, method):
        """
        Placeholder for a real M-Pesa Daraja STK push / card gateway call.
        Always succeeds in this demo so the barrier-open flow can be shown.
        """
        return True

    # ---------- reporting ----------

    def audit_log(self, limit=100):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """SELECT v.plate_number, pl.bay_number, ps.entry_time, ps.exit_time,
                      ps.duration_minutes, ps.amount_payable, ps.payment_method
               FROM ParkingSession ps
               JOIN Vehicle v ON v.vehicle_id = ps.vehicle_id
               JOIN ParkingSlot pl ON pl.slot_id = ps.slot_id
               WHERE ps.payment_status = 'paid'
               ORDER BY ps.exit_time DESC
               LIMIT ?""",
            (limit,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT COALESCE(SUM(amount_payable), 0) AS total FROM ParkingSession WHERE payment_status='paid'")
        total = cur.fetchone()["total"]
        conn.close()
        return rows, total
