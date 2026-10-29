"""Core booking engine shared by advance booking and quick parking.

Both modes use the same database, the same eligibility rules and the same
state transitions:

    booked  --check-in-->  checked_in  --checkout-->  completed
      |                        |
      +--cancel--> cancelled   +--(checkout releases the bay)

An unused advance reservation becomes expired after the facility's hold
period, and the bay is released at that moment.
"""

from datetime import datetime, timedelta
import re

from flask import current_app
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import (
    BayStatus,
    ParkingBay,
    ParkingFacility,
    ParkingTransaction,
    Reservation,
    ReservationStatus,
    VehicleType,
)
from sqlalchemy import func

from .locks import BOOKING_LOCK
from .tokens import new_reservation_code, new_ticket_code


class BookingError(Exception):
    """Raised for expected, user-facing booking problems."""

    def __init__(self, message):
        super().__init__(message)
        self.user_message = message


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def active_reservations_for_bay(bay_id):
    return (
        Reservation.query.filter(
            Reservation.bay_id == bay_id,
            Reservation.status.in_(ReservationStatus.ACTIVE),
        ).all()
    )


def active_reservations_for_facility(facility_id):
    """Map of bay_id -> list of active reservations for one facility."""
    rows = Reservation.query.filter(
        Reservation.facility_id == facility_id,
        Reservation.status.in_(ReservationStatus.ACTIVE),
    ).all()
    grouped = {}
    for res in rows:
        grouped.setdefault(res.bay_id, []).append(res)
    return grouped


def overlaps(reservation, start, end, now=None):
    """True when an active reservation conflicts with the window [start, end).

    A checked-in reservation that has passed its expected end time is treated
    as still occupying the bay until the driver checks out.
    """
    res_start = reservation.start_time
    res_end = reservation.end_time
    if reservation.status == ReservationStatus.CHECKED_IN and now and res_end < now:
        res_end = now
    return res_start < end and res_end > start


def validate_window(start_time, end_time):
    """Server-side validation of a reservation time window."""
    now = datetime.now()
    if start_time is None or end_time is None:
        raise BookingError("Please choose a valid date and time.")
    if end_time <= start_time:
        raise BookingError("The departure time must be after the arrival time.")
    if start_time < now:
        raise BookingError("The arrival time cannot be in the past. Please choose a future time.")
    max_days = current_app.config.get("MAX_ADVANCE_DAYS", 30)
    if start_time > now + timedelta(days=max_days):
        raise BookingError(
            f"Bookings can only be made up to {max_days} days ahead."
        )
    max_hours = current_app.config.get("MAX_RESERVATION_HOURS", 72)
    if (end_time - start_time).total_seconds() > max_hours * 3600:
        raise BookingError(f"A single reservation can be at most {max_hours} hours long.")


def validate_vehicle_details(vehicle_registration, vehicle_type):
    """Validate and normalise the vehicle information entered by the user."""
    reg = (vehicle_registration or "").strip()
    if not reg:
        raise BookingError("Please enter your vehicle registration number.")
    if len(reg) > 20:
        raise BookingError("The vehicle registration number is too long.")
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 -.")
    if any(ch not in allowed for ch in reg):
        raise BookingError(
            "The vehicle registration number may only contain letters, numbers, spaces, dots and dashes."
        )

    clean = re.sub(r"[\s\-.]+", "", reg.upper())
    letters = re.findall(r"[A-Z]", clean)
    digits = re.findall(r"[0-9]", clean)
    if len(clean) < 4 or len(letters) < 2 or len(digits) < 1:
        raise BookingError(
            "Please enter a valid vehicle registration number (e.g. MH 12 AB 1234 or DL 01 A 1234)."
        )

    # Standard format (state code + RTO + series + number) or BH series
    pattern_standard = r"^[A-Z]{2}[0-9]{1,2}[A-Z]{0,6}[0-9]{1,4}$"
    pattern_bh = r"^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$"
    pattern_general = r"^[A-Z]{2,4}[0-9]{1,4}[A-Z0-9]{0,6}$"

    if not (
        re.match(pattern_standard, clean)
        or re.match(pattern_bh, clean)
        or re.match(pattern_general, clean)
    ):
        raise BookingError(
            "Invalid vehicle registration number format. Please enter a valid number (e.g. MH 12 AB 1234)."
        )

    if vehicle_type not in VehicleType.BOOKABLE:
        raise BookingError("Please choose your vehicle type.")
    return reg.upper(), vehicle_type


# ---------------------------------------------------------------------------
# Expiry
# ---------------------------------------------------------------------------

def _hold_minutes(facility):
    if facility.hold_minutes and facility.hold_minutes > 0:
        return facility.hold_minutes
    return current_app.config.get("RESERVATION_HOLD_MINUTES", 30)


def run_expiry():
    """Expire unused advance reservations and release their bays.

    Rule: an advance reservation that has not been checked in within the
    facility's hold period (default 30 minutes past the scheduled arrival
    time) expires automatically, and its bay becomes free again.
    """
    now = datetime.now()
    candidates = (
        Reservation.query.filter(Reservation.status == ReservationStatus.BOOKED)
        .options(db.joinedload(Reservation.facility))
        .all()
    )
    changed = False
    for res in candidates:
        hold = timedelta(minutes=_hold_minutes(res.facility))
        if now > res.start_time + hold:
            res.status = ReservationStatus.EXPIRED
            _sync_bay_status(res.bay)
            changed = True
    if changed:
        db.session.commit()


def _sync_bay_status(bay):
    """Recompute a bay's recorded status from its active reservations."""
    if bay is None or bay.status == BayStatus.MAINTENANCE:
        return
    occupied = (
        db.session.query(func.count(Reservation.id))
        .filter(
            Reservation.bay_id == bay.id,
            Reservation.status == ReservationStatus.CHECKED_IN,
        )
        .scalar()
        or 0
    )
    if occupied:
        bay.status = BayStatus.OCCUPIED
        return
    booked = (
        db.session.query(func.count(Reservation.id))
        .filter(
            Reservation.bay_id == bay.id,
            Reservation.status == ReservationStatus.BOOKED,
        )
        .scalar()
        or 0
    )
    bay.status = BayStatus.RESERVED if booked else BayStatus.VACANT


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------

def _check_eligibility(facility, bay, vehicle_type, start_time, end_time, needs_accessible):
    now = datetime.now()
    if bay is None or bay.facility_id != facility.id:
        raise BookingError("That parking space could not be found. Please choose another one.")
    if bay.status == BayStatus.MAINTENANCE:
        raise BookingError(
            f"Slot {bay.label} is closed for maintenance and cannot be booked."
        )
    if needs_accessible and not bay.is_accessible:
        raise BookingError(
            f"Slot {bay.label} is not an accessible space. Please choose another one."
        )
    if not bay.supports(vehicle_type):
        raise BookingError(
            f"Slot {bay.label} does not accept {VehicleType.LABELS.get(vehicle_type, vehicle_type).lower()}s."
        )
    for res in active_reservations_for_bay(bay.id):
        if overlaps(res, start_time, end_time, now):
            if res.status == ReservationStatus.CHECKED_IN and res.end_time <= end_time:
                raise BookingError(
                    f"Slot {bay.label} has a vehicle parked in it right now and is not free for your time."
                )
            raise BookingError(
                f"Slot {bay.label} was just booked by someone else for that time. Please pick another space."
            )


def _check_duplicate_active(db_session, facility, user, vehicle_registration, start_time, end_time):
    """Prevent the same driver holding two overlapping active bookings."""
    now = datetime.now()

    # Signed-in drivers may not hold two overlapping bookings themselves.
    if user is not None:
        own = Reservation.query.filter(
            Reservation.facility_id == facility.id,
            Reservation.user_id == user.id,
            Reservation.status.in_(ReservationStatus.ACTIVE),
        ).all()
        for res in own:
            if overlaps(res, start_time, end_time, now):
                raise BookingError(
                    "You already have an active parking booking at this facility for that time. "
                    "Please cancel it first or use your existing booking."
                )

    # The same vehicle registration may not hold two overlapping bookings.
    dup = Reservation.query.filter(
        Reservation.facility_id == facility.id,
        Reservation.status.in_(ReservationStatus.ACTIVE),
        func.upper(Reservation.vehicle_registration) == vehicle_registration.upper(),
    ).all()
    for res in dup:
        if overlaps(res, start_time, end_time, now):
            raise BookingError(
                "A vehicle with this registration number already has an active booking "
                "at this facility for that time."
            )


def _check_booking_limits(user, vehicle_registration):
    """Enforce maximum of 3 active bookings per user or vehicle registration."""
    if user is not None and getattr(user, "is_authenticated", False):
        if not getattr(user, "is_admin", False):
            user_active_count = Reservation.query.filter(
                Reservation.user_id == user.id,
                Reservation.status.in_(ReservationStatus.ACTIVE),
            ).count()
            if user_active_count >= 3:
                raise BookingError(
                    "Booking limit reached: You can have at most 3 active slot reservations at a time."
                )

    reg_active_count = Reservation.query.filter(
        func.upper(Reservation.vehicle_registration) == vehicle_registration.upper(),
        Reservation.status.in_(ReservationStatus.ACTIVE),
    ).count()
    if reg_active_count >= 3:
        raise BookingError(
            "Booking limit reached: This vehicle already has 3 active slot reservations at a time."
        )


def create_reservation(
    *,
    facility_id,
    bay_id,
    vehicle_registration,
    vehicle_type,
    start_time,
    end_time,
    mode,
    user=None,
    needs_accessible=False,
):
    """Create a reservation after re-checking availability on the backend.

    The availability check and the database write happen inside one lock and
    one transaction, so two simultaneous requests can never allocate the same
    bay for overlapping periods.
    """
    reg, vtype = validate_vehicle_details(vehicle_registration, vehicle_type)

    with BOOKING_LOCK:
        run_expiry()
        facility = db.session.get(ParkingFacility, facility_id)
        if facility is None or not facility.is_active:
            raise BookingError("That parking facility is not available.")
        bay = db.session.get(ParkingBay, bay_id)
        _check_eligibility(facility, bay, vtype, start_time, end_time, needs_accessible)
        _check_duplicate_active(db.session, facility, user, reg, start_time, end_time)
        _check_booking_limits(user, reg)

        res = Reservation(
            reservation_code=new_reservation_code(),
            ticket_code=new_ticket_code(),
            facility_id=facility.id,
            bay_id=bay.id,
            user_id=user.id if user else None,
            vehicle_registration=reg,
            vehicle_type=vtype,
            mode=mode,
            status=ReservationStatus.BOOKED,
            start_time=start_time,
            end_time=end_time,
        )

        if mode == "quick":
            res.status = ReservationStatus.CHECKED_IN
            res.entry_timestamp = datetime.now()

        db.session.add(res)

        # Update the recorded slot status.
        if bay.status != BayStatus.MAINTENANCE:
            if res.status == ReservationStatus.CHECKED_IN:
                bay.status = BayStatus.OCCUPIED
            elif bay.status == BayStatus.VACANT:
                bay.status = BayStatus.RESERVED
        bay.updated_at = datetime.now()

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            raise BookingError(
                "That parking space was taken at the last moment. Please choose another one."
            )
        db.session.refresh(res)
        return res


# ---------------------------------------------------------------------------
# Check-in
# ---------------------------------------------------------------------------

def check_in(reservation):
    """Record that the driver has arrived at an advance booking."""
    with BOOKING_LOCK:
        run_expiry()
        res = db.session.get(Reservation, reservation.id)
        if res is None:
            raise BookingError("Booking not found.")
        if res.status == ReservationStatus.CHECKED_IN:
            raise BookingError("This booking is already checked in.")
        if res.status != ReservationStatus.BOOKED:
            raise BookingError(
                f"This booking is {res.status_label.lower()} and cannot be checked in."
            )
        bay = res.bay
        if bay.status == BayStatus.MAINTENANCE:
            raise BookingError(
                f"Slot {bay.label} is closed for maintenance. Please contact the parking operator."
            )
        other = (
            Reservation.query.filter(
                Reservation.bay_id == bay.id,
                Reservation.status == ReservationStatus.CHECKED_IN,
                Reservation.id != res.id,
            ).first()
        )
        if other:
            raise BookingError(
                f"Slot {bay.label} already has a vehicle parked in it. Please contact the operator."
            )
        res.status = ReservationStatus.CHECKED_IN
        res.entry_timestamp = datetime.now()
        bay.status = BayStatus.OCCUPIED
        bay.updated_at = datetime.now()
        db.session.commit()
        db.session.refresh(res)
        return res


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------

def _fee_for(facility, duration_minutes):
    rate = float(facility.hourly_rate or 0.0)
    hours = max(1, -(-duration_minutes // 60))  # ceil
    return rate, round(hours * rate, 2)


def checkout(ticket_code, vehicle_registration=None, user=None):
    """Validate a ticket, record the exit and release the bay.

    The reservation update, the exit timestamp and the bay release are all
    written in a single database transaction.
    """
    code = (ticket_code or "").strip().upper()
    if not code:
        raise BookingError("Please enter your ticket code.")

    with BOOKING_LOCK:
        run_expiry()
        res = Reservation.query.filter(func.upper(Reservation.ticket_code) == code).first()
        if res is None:
            raise BookingError("No parking ticket matches that code. Please check and try again.")

        entered_reg = (vehicle_registration or "").strip().upper()
        if entered_reg:
            if entered_reg != res.vehicle_registration.upper():
                raise BookingError("The vehicle registration does not match this ticket.")
        else:
            # Without a registration, only the booking owner or a staff
            # member may complete the checkout.
            allowed = user is not None and (
                user.is_operator or user.id == res.user_id
            )
            if not allowed:
                raise BookingError("Please enter your vehicle registration number.")

        if res.status == ReservationStatus.COMPLETED:
            when = res.exit_timestamp.strftime("%d %b %Y, %H:%M") if res.exit_timestamp else ""
            raise BookingError(f"This ticket was already checked out on {when}.")
        if res.status == ReservationStatus.CANCELLED:
            raise BookingError("This reservation was cancelled and cannot be checked out.")
        if res.status == ReservationStatus.EXPIRED:
            raise BookingError("This reservation expired and cannot be checked out.")
        if res.status == ReservationStatus.BOOKED:
            raise BookingError(
                "This reservation has not been checked in yet, so there is nothing to check out."
            )

        now = datetime.now()
        entry = res.entry_timestamp or res.start_time
        duration_minutes = max(0, int((now - entry).total_seconds() // 60))

        facility = res.facility
        fee_amount = None
        rate = None
        if current_app.config.get("FEE_CALCULATION_ENABLED", False):
            rate, fee_amount = _fee_for(facility, duration_minutes)

        res.status = ReservationStatus.COMPLETED
        res.exit_timestamp = now
        res.end_time = now if now > res.end_time else res.end_time

        _sync_bay_status(res.bay)
        res.bay.updated_at = now

        if fee_amount is not None:
            db.session.add(
                ParkingTransaction(
                    reservation_id=res.id,
                    duration_minutes=duration_minutes,
                    rate_per_hour=rate,
                    amount=fee_amount,
                    status="calculated",
                )
            )
        db.session.commit()
        db.session.refresh(res)
        return res, duration_minutes, fee_amount


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------

def cancel_reservation(reservation, *, actor=None, verify_registration=None):
    """Cancel an eligible reservation and release its bay.

    Eligibility: only reservations that are still 'booked' (not checked in,
    not completed/cancelled/expired) may be cancelled. Only the owner, a
    staff member, or someone holding the ticket code plus matching vehicle
    registration may cancel.
    """
    with BOOKING_LOCK:
        run_expiry()
        res = db.session.get(Reservation, reservation.id)
        if res is None:
            raise BookingError("Booking not found.")

        is_owner = actor is not None and res.user_id == actor.id
        is_staff = actor is not None and actor.is_operator
        verified_guest = False
        if verify_registration is not None:
            verified_guest = (
                verify_registration.strip().upper() == res.vehicle_registration.upper()
            )
        if not (is_owner or is_staff or verified_guest):
            raise BookingError("You are not allowed to cancel this booking.")

        if res.status == ReservationStatus.CHECKED_IN:
            raise BookingError(
                "This vehicle has already checked in. Please use checkout instead."
            )
        if res.status != ReservationStatus.BOOKED:
            raise BookingError(
                f"Only active advance bookings can be cancelled. This one is {res.status_label.lower()}."
            )

        res.status = ReservationStatus.CANCELLED
        _sync_bay_status(res.bay)
        res.bay.updated_at = datetime.now()
        db.session.commit()
        db.session.refresh(res)
        return res


# ---------------------------------------------------------------------------
# Helpers for display
# ---------------------------------------------------------------------------

def directions_text(reservation):
    """Simple parking directions for the assigned bay."""
    bay = reservation.bay
    facility = reservation.facility
    floor_name = "Ground floor" if bay.floor == 0 else f"Floor {bay.floor}"
    parts = [
        f"Enter {facility.name}.",
        f"Go to {floor_name}, Zone {bay.zone}.",
        f"Park in slot {bay.slot_number}.",
    ]
    if bay.is_accessible:
        parts.append("This is an accessible parking space.")
    return " ".join(parts)
