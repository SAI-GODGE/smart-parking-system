# Smart Parking Management System

A full-stack web application for finding, reserving and managing parking
spaces in real time. Built with Flask and SQLite, it supports two booking
modes that share one booking engine and one database:

- **Mode A — Advance Booking**: pick a facility, choose a date/time window,
  see which spaces are free for that exact window, book one, then check in
  with the ticket when you arrive.
- **Mode B — QR-based Quick Parking**: scan a facility QR code (or open its
  link), see the live grid of spaces, tap a currently vacant one, and start
  parking immediately — the space is marked occupied right away.

Both modes use the same reservation lifecycle: **booked → checked in →
completed / cancelled / expired**, with bay status **vacant / reserved /
occupied / maintenance** kept in sync automatically.

## Features

- Live facility list with availability counts and hourly rates
- Date/time window selection with server-side validation (no past times,
  maximum advance days and maximum reservation length enforced)
- Live slot grid that only shows spaces free for the chosen window
- Ticket page with reservation code (`RS-…`), ticket code (`PK-…`),
  directions and check-in / checkout actions
- Quick parking on the QR page with instant allocation of a vacant space
- Ticket lookup and cancellation with ticket code + vehicle registration
- Public checkout form; checkout releases the space and records duration
  and (optionally) the parking fee
- Automatic expiry: unused advance bookings expire after the facility's
  hold period (default 30 minutes past arrival) and the space is released
- Operator dashboard: search by ticket, check-in, checkout, live totals
- Admin panel: manage facilities, slots (including maintenance closures),
  view reservations, change user roles, generate facility QR codes
- Slot recommendation score for drivers
- Role-based access control (driver / operator / admin), CSRF protection,
  hashed passwords, safe error pages

## Technology

| Layer    | Choice |
|----------|--------|
| Framework | Flask 3.0.3 |
| ORM / DB  | Flask-SQLAlchemy 3.1.1 + SQLite |
| Auth      | Flask-Login 0.6.3 (sessions) |
| Forms / CSRF | Flask-WTF 1.2.1, WTForms 3.1.2 |
| QR codes  | qrcode 7.4.2 + Pillow 10.4.0 |
| Tests     | pytest 8.2.2 |
| Config    | python-dotenv 1.0.1 |

## Installation

Requires Python 3.10+ (developed and tested on Python 3.12).

### Windows (PowerShell)

```powershell
cd "C:\Users\saipr\Downloads\MDM Project (Civil)"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Linux / macOS

```bash
cd path/to/project
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration (optional)

Copy `.env.example` to `.env` and adjust values if needed:

```bash
cp .env.example .env
```

| Variable | Default | Purpose |
|----------|---------|---------|
| `SECRET_KEY` | auto-generated into `instance/secret_key` | Signs sessions and CSRF tokens |
| `DATABASE_URL` | `instance/smart_parking.db` | Database connection string |
| `BASE_URL` | `http://127.0.0.1:5000` | Public base URL used inside QR codes |
| `FEE_CALCULATION_ENABLED` | `true` | Calculate/display fees at checkout |
| `RESERVATION_HOLD_MINUTES` | `30` | Grace period before an unused booking expires |
| `MAX_ADVANCE_DAYS` | `30` | How far ahead a booking may be made |

No secrets are hard-coded; `.env`, `instance/` and the virtual environment
are excluded by `.gitignore`.

## Database setup

The database is created automatically on first start, and sample data
(3 facilities, 80 spaces, demo accounts, demo reservations) is seeded when
the database is empty. To initialise it explicitly:

```powershell
flask --app app init-db
```

## Creating an administrator

There is no default admin password. Run once and type the password when
prompted:

```powershell
python create_admin.py
```

## Running the application

```powershell
python app.py
```

Then open <http://127.0.0.1:5000>.

### Demo accounts (seeded database)

| Role | Username | Password |
|------|----------|----------|
| Driver | `demo` | `demo1234` |
| Operator | `operator` | `operator1234` |
| Admin | — | created via `python create_admin.py` |

## QR codes

- Each facility has a public page at `/parking/facility/<id>` — this is the
  URL encoded in its QR code.
- QR codes (PNG) are downloadable and printable from **Admin → QR codes**
  (`/admin/qr`).
- **For scanning with a phone**, set `BASE_URL` in `.env` to the address the
  phone can reach, e.g. `BASE_URL=http://192.168.1.50:5000` (your machine's
  LAN IP). QR codes encode `BASE_URL` at generation time, so regenerate them
  after changing it.

## Running the tests

```powershell
.\.venv\Scripts\pytest.exe tests -q     # Windows PowerShell
```

```bash
pytest tests -q                          # Linux / macOS (venv active)
```

Every test runs against its own temporary SQLite file, so the development
database is never touched. The suite covers:

| Area | Tests |
|------|-------|
| App startup, config, seed idempotency | `test_app_startup.py` |
| Registration, login, roles, disabled accounts | `test_auth_roles.py` |
| Advance booking, time windows, duplicates | `test_advance_booking.py` |
| Quick parking (vacant-only allocation) | `test_quick_parking.py` |
| Ticket validation and checkout | `test_checkout.py` |
| Cancellation and expiry rules | `test_cancellation_expiry.py` |
| Dashboard counts and privacy of registrations | `test_dashboard_privacy.py` |
| QR routing/generation, recommendation score | `test_qr_recommendation.py` |
| Operator and admin HTTP workflows | `test_operator_admin.py` |
| CSRF, safe errors, auth redirects, hashing, SQL-injection style inputs | `test_security.py` |
| Concurrent booking race (threads) | `test_concurrency.py` |

**Actual result (this machine): `76 passed in 44.67s`.**

## Project structure

```
app.py                 Application factory + CLI (init-db) + dev server
config.py              Config / TestConfig, .env loading, secret key
extensions.py          db, login_manager, csrf instances
create_admin.py        Interactive first-run admin creation
models/                SQLAlchemy models (User, ParkingFacility, ParkingBay,
                       Reservation, ParkingTransaction) + status constants
services/              booking engine, availability, recommendation, QR,
                       seeding, tokens, concurrency lock
routes/                main, auth, booking, quick, checkout, operator, admin
templates/             Jinja2 templates (one folder per blueprint)
static/                CSS and JavaScript (bay grid, live polling, forms)
tests/                 pytest suite
instance/              SQLite database + generated secret key (not in git)
```

## Database schema (summary)

- **users** — username, password hash, email, role (driver/operator/admin),
  account status
- **parking_facilities** — name, address, type, hourly rate, default
  duration, hold minutes, active flag
- **parking_bays** — facility, floor, zone, slot number (unique per
  facility), vehicle type, accessible flag, distance from gate, status
- **reservations** — reservation code, ticket code, facility, bay, user
  (nullable for guests), vehicle registration/type, mode, status, time
  window, entry/exit timestamps
- **parking_transactions** — one row per checkout: duration, hourly rate,
  amount (display only — no payment gateway is integrated)

Key rules:

- A bay is identified by *(facility, floor, zone, slot number)*.
- A reservation overlaps another when the windows intersect; a checked-in
  car that outstays its expected end keeps the bay until checkout.
- Bay status is recomputed from its active reservations after every state
  change (maintenance is sticky until reopened by an operator).
- Expiry: `now > start_time + hold` on a non-checked-in booking ⇒ expired.

## Recommendation score

Eligible candidates (correct vehicle type, not in maintenance, accessible if
needed, bookable) are scored — **lower is better**:

```
score = 0.5 × normalized_distance + 0.3 × normalized_floor + 0.2 × vehicle_match
```

- `vehicle_match` = 0 for an exact vehicle-type bay, 0.25 for an "any" bay,
  +1.0 penalty for a bay on a non-preferred floor.
- The lowest score wins; ties keep the closest bay.

## Security

- Passwords hashed with Werkzeug (`scrypt`/`pbkdf2`)
- CSRF protection on every state-changing form (Flask-WTF)
- Role checks on all operator/admin routes; drivers get a clean 403 page
- Login `next=` redirects only to local paths (no open redirects)
- Public pages and the availability API expose only slot status — never
  vehicle registrations (registrations appear only on tickets, the owner's
  own bookings, and staff views)
- Ticket code + matching registration required for guest checkout/cancel
- Custom 403/404/500 pages; no tracebacks or raw errors are rendered
- Booking allocation is serialised with a process-wide lock so two
  requests can never take the same space

## Limitations

- SQLite and a single process — the concurrency lock is in-process only;
  a multi-worker deployment would need a shared lock or stronger isolation
- Fees are calculated and displayed only; no payment gateway is integrated
- QR codes are for facility pages, not per-reservation tickets
- Email/SMS notifications are out of scope
- Use a production WSGI server (e.g. gunicorn/waitress) for deployment
  instead of the Flask development server

## Reference

Project objectives, architecture and requirements follow the provided
reference report `Smart_Parking_Management_System_Project_Report_after_humannize.pdf`.
