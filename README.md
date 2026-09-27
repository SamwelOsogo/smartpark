# SmartPark — Web-Based Parking Management System

**Multimedia University of Kenya — Data Structures & Algorithm, Task One**

A functional, web-based parking system built with Python (Flask) and SQLite.
Drivers can see live bay availability before entry; vehicles are recorded on
arrival; fees are calculated automatically on exit using a tiered rate table;
the barrier "opens" only after payment is confirmed.

## Running it

```bash
pip install -r requirements.txt
python database.py      # creates smartpark.db and seeds 10 bays + rate tiers
python app.py            # starts the web server
```

Open `http://127.0.0.1:5000/` in a browser.

- `/` — live display board (what drivers see before entry)
- `/entry` — record a vehicle arrival
- `/exit` — calculate amount payable and confirm payment
- `/admin` — audit log, total collected, current rate tiers

## 1. Terms of reference → Modules

| Client requirement | Module |
|---|---|
| Drivers see slot availability before entry | **Display Module** (`/`) |
| Records each vehicle on arrival | **Entry Module** (`/entry`) |
| Calculates time spent and amount to pay | **Fee Calculation Module** (inside Exit Module) |
| Barrier opens only on payment | **Payment & Exit Module** (`/exit`) |
| Auditable record of money collected | **Reporting Module** (`/admin`) |
| Rates can change without a software change | **Rate Configuration** (`RateTier` DB table) |

## 2. Algorithms

**Entry (`vehicle_entry`)**
1. Reject if the lot is full (no free bays) or the plate already has an
   active session.
2. Pop the lowest-numbered free bay from the min-heap.
3. Create/find the `Vehicle` row; insert a `ParkingSession` row with
   `entry_time = now` and no exit data yet.
4. Mark that bay `occupied`; cache the session in memory keyed by plate.

**Fee calculation (`calculate_fee`)**
Walks the `RateTier` table (ordered by `sort_order`) and returns the fee
for the first tier whose `up_to_minutes` is ≥ the parked duration. The
final tier has `up_to_minutes = NULL`, meaning "no upper bound" — it
catches everything over 6 hours. Because this reads from the database
instead of hard-coded numbers, **management can add, remove, or edit
tiers without changing any code.**

Default tiers (from the assignment brief):

| Duration | Fee |
|---|---|
| Up to 30 minutes | Free |
| Up to 2 hours | Ksh 50 |
| Up to 4 hours | Ksh 100 |
| Up to 6 hours | Ksh 300 |
| Over 6 hours | Ksh 500 |

**Exit (`vehicle_exit`)**
1. Look up the active session by plate number (O(1) hash-map lookup).
2. `duration = ceil((now − entry_time) in minutes)`.
3. `fee = calculate_fee(duration)`.
4. Simulate payment confirmation (placeholder for M-Pesa Daraja
   STK push / card gateway — in production this is where that API call
   would go). **The barrier only opens if this step succeeds.**
5. On success: write `exit_time`, `duration_minutes`, `amount_payable`,
   `payment_method`, and `payment_status='paid'` to `ParkingSession` —
   this row is the permanent audit record.
6. Push the bay number back onto the min-heap and mark it `available`
   in the database; remove the plate from the active-session cache.

## 3. Data structures used, and why

| Structure | Used for | Why |
|---|---|---|
| **Min-heap** (`heapq`) of free bay numbers | Bay allocation/release | Always yields the lowest free bay in O(log n); scanning a list for the lowest free bay would be O(n) on every single entry. |
| **Hash map** (`dict`), `plate_number → session` | Exit lookups | O(1) average lookup by plate number, instead of scanning every active session (O(n)). |
| **Relational tables** (SQLite) | Persistent storage of vehicles, sessions, slots, rates | Survives restarts, supports SQL aggregation for the audit/VAT report, and keeps the rate structure editable data rather than hard-coded constants. |

The heap and hash map are an in-memory index that is rebuilt from the
database on startup (`_load_state`), so the system stays fast during
normal operation but never loses data.

## 4. Database design (dynamic — no schema change needed for new rates)

```
ParkingSlot
- slot_id (PK)
- bay_number (unique)
- status            -- 'available' | 'occupied'

Vehicle
- vehicle_id (PK)
- plate_number (unique)

ParkingSession
- session_id (PK)
- vehicle_id (FK → Vehicle)
- slot_id (FK → ParkingSlot)
- entry_time
- exit_time
- duration_minutes
- amount_payable
- payment_method
- payment_status    -- 'pending' | 'paid'

RateTier
- tier_id (PK)
- label
- up_to_minutes      -- NULL = open-ended tier
- fee_kshs
- sort_order
```

`RateTier` is what makes the system "dynamic": management edits rows in
this table (via SQL or a future admin form) and `calculate_fee()` picks
up the new pricing immediately — no redeploy needed.

## 5. Scope

**In scope:** entry recording, live availability display, fee
calculation, payment confirmation, barrier-open simulation, audit
reporting.
**Out of scope (per assignment):** online pre-booking, valet
operations, third-party loyalty integration, automated number-plate
recognition/blacklisting.
