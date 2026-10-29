"""Mode A: advance booking workflow, tickets, my bookings and lookup."""

from datetime import datetime, timedelta

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from extensions import db
from models import (
    ParkingFacility,
    Reservation,
    ReservationStatus,
    Role,
    VehicleType,
)
from services.availability import bay_statuses, facility_counts, floors_and_zones
from services.booking import (
    BookingError,
    cancel_reservation,
    create_reservation,
    directions_text,
    run_expiry,
    validate_vehicle_details,
    validate_window,
)
from services.recommendation import recommend_slot

bp = Blueprint("booking", __name__)

DURATION_CHOICES = [1, 2, 3, 4, 6, 8, 12, 24, 48, 72]

DURATION_LABELS = {
    1: "1 hour",
    2: "2 hours",
    3: "3 hours",
    4: "4 hours",
    6: "6 hours",
    8: "8 hours",
    12: "12 hours",
    24: "1 day",
    48: "2 days",
    72: "3 days",
}


def _get_facility_or_404(facility_id):
    facility = db.session.get(ParkingFacility, facility_id)
    if facility is None or not facility.is_active:
        abort(404)
    return facility


def _default_datetime():
    """Sensible default arrival: the next half hour from now."""
    now = datetime.now()
    minutes = 30 if now.minute < 30 else 60
    start = (now + timedelta(minutes=minutes)).replace(minute=0 if minutes == 60 else 30, second=0, microsecond=0)
    return start


def _parse_form_datetime():
    """Read arrival date/time and duration from form data."""
    date_raw = request.form.get("date", "")
    time_raw = request.form.get("time", "")
    duration_raw = request.form.get("duration", "")
    try:
        date_part = datetime.strptime(date_raw, "%Y-%m-%d").date()
        time_part = datetime.strptime(time_raw, "%H:%M").time()
    except ValueError:
        raise BookingError("Please choose a valid arrival date and time.")
    try:
        hours = int(duration_raw)
    except ValueError:
        raise BookingError("Please choose how long you will park.")
    if hours not in DURATION_CHOICES:
        raise BookingError("Please choose a valid parking duration.")
    start = datetime.combine(date_part, time_part)
    end = start + timedelta(hours=hours)
    return start, end, hours


def _slots_url(facility_id, start, end, vehicle_type, needs_accessible):
    from urllib.parse import urlencode

    query = urlencode(
        {
            "start": start.isoformat(timespec="seconds"),
            "end": end.isoformat(timespec="seconds"),
            "vehicle": vehicle_type,
            "accessible": "1" if needs_accessible else "0",
        }
    )
    return f"{url_for('booking.slots', facility_id=facility_id)}?{query}"


# ---------------------------------------------------------------------------
# Step 1 - choose a facility
# ---------------------------------------------------------------------------

@bp.route("/book")
def index():
    rows = []
    for facility in (
        ParkingFacility.query.filter_by(is_active=True).order_by(ParkingFacility.name).all()
    ):
        rows.append({"facility": facility, "counts": facility_counts(facility.id)})
    return render_template("facilities.html", rows=rows, mode="advance")


# ---------------------------------------------------------------------------
# Step 2 - choose date, time, duration and vehicle
# ---------------------------------------------------------------------------

@bp.route("/book/<int:facility_id>", methods=["GET", "POST"])
def time_step(facility_id):
    facility = _get_facility_or_404(facility_id)
    default_start = _default_datetime()

    if request.method == "POST":
        try:
            start, end, _hours = _parse_form_datetime()
            validate_window(start, end)
            vehicle_type = request.form.get("vehicle_type", "")
            if vehicle_type not in VehicleType.BOOKABLE:
                raise BookingError("Please choose your vehicle type.")
            needs_accessible = request.form.get("needs_accessible") == "1"
        except BookingError as exc:
            flash(exc.user_message, "error")
            return render_template(
                "booking/time_step.html",
                facility=facility,
                start=default_start,
                duration_choices=DURATION_CHOICES,
                duration_labels=DURATION_LABELS,
                vehicle_types=[(v, VehicleType.LABELS[v]) for v in VehicleType.BOOKABLE],
                selected={
                    "date": request.form.get("date", ""),
                    "time": request.form.get("time", ""),
                    "duration": request.form.get("duration", ""),
                    "vehicle_type": request.form.get("vehicle_type", ""),
                    "needs_accessible": request.form.get("needs_accessible") == "1",
                },
            )
        return redirect(
            _slots_url(facility.id, start, end, vehicle_type, needs_accessible)
        )

    return render_template(
        "booking/time_step.html",
        facility=facility,
        start=default_start,
        duration_choices=DURATION_CHOICES,
        duration_labels=DURATION_LABELS,
        vehicle_types=[(v, VehicleType.LABELS[v]) for v in VehicleType.BOOKABLE],
        selected=None,
    )


# ---------------------------------------------------------------------------
# Step 3 - pick a slot
# ---------------------------------------------------------------------------

@bp.route("/book/<int:facility_id>/slots")
def slots(facility_id):
    facility = _get_facility_or_404(facility_id)
    try:
        start = datetime.fromisoformat(request.args.get("start", ""))
        end = datetime.fromisoformat(request.args.get("end", ""))
        validate_window(start, end)
    except (ValueError, BookingError) as exc:
        message = (
            exc.user_message
            if isinstance(exc, BookingError)
            else "That booking time is no longer valid. Please start again."
        )
        flash(message, "error")
        return redirect(url_for("booking.time_step", facility_id=facility.id))

    vehicle_type = request.args.get("vehicle", "")
    if vehicle_type not in VehicleType.BOOKABLE:
        flash("Please choose your vehicle type.", "error")
        return redirect(url_for("booking.time_step", facility_id=facility.id))
    needs_accessible = request.args.get("accessible") == "1"

    bays = bay_statuses(
        facility.id,
        start=start,
        end=end,
        needs_accessible=needs_accessible,
        vehicle_type=vehicle_type,
    )
    bookable = [b for b in bays if b["bookable"]]
    recommendation, score, reason = recommend_slot(bookable, vehicle_type=vehicle_type)
    floors, zones = floors_and_zones(facility.id)
    hold = facility.hold_minutes_effective
    from flask import current_app

    hold = hold if hold is not None else current_app.config["RESERVATION_HOLD_MINUTES"]

    return render_template(
        "booking/slots.html",
        facility=facility,
        start=start,
        end=end,
        vehicle_type=vehicle_type,
        needs_accessible=needs_accessible,
        bays=bays,
        free_count=len(bookable),
        recommendation=recommendation,
        recommendation_reason=reason,
        floors=floors,
        zones=zones,
        duration_labels=DURATION_LABELS,
        hold_minutes=hold,
        duration_hours=int((end - start).total_seconds() // 3600),
    )


# ---------------------------------------------------------------------------
# Step 4 - confirm booking
# ---------------------------------------------------------------------------

@bp.route("/book/<int:facility_id>/confirm", methods=["POST"])
def confirm(facility_id):
    facility = _get_facility_or_404(facility_id)
    try:
        start, end, _hours = _parse_form_datetime()
        validate_window(start, end)
        bay_id = int(request.form.get("bay_id") or 0)
    except (BookingError, ValueError) as exc:
        message = (
            exc.user_message
            if isinstance(exc, BookingError)
            else "Please choose a parking space first."
        )
        flash(message, "error")
        return redirect(url_for("booking.time_step", facility_id=facility.id))

    vehicle_type = request.form.get("vehicle_type", "")
    needs_accessible = request.form.get("needs_accessible") == "1"
    registration = request.form.get("vehicle_registration", "")
    slots_url = _slots_url(facility.id, start, end, vehicle_type, needs_accessible)

    if not current_user.is_authenticated:
        # Guests may book too; they manage the booking with the ticket code.
        pass

    try:
        reservation = create_reservation(
            facility_id=facility.id,
            bay_id=bay_id,
            vehicle_registration=registration,
            vehicle_type=vehicle_type,
            start_time=start,
            end_time=end,
            mode="advance",
            user=current_user if current_user.is_authenticated else None,
            needs_accessible=needs_accessible,
        )
    except BookingError as exc:
        flash(exc.user_message, "error")
        return redirect(slots_url)

    flash("Your parking space is reserved.", "success")
    return redirect(url_for("booking.ticket", ticket_code=reservation.ticket_code))


# ---------------------------------------------------------------------------
# Digital ticket
# ---------------------------------------------------------------------------

@bp.route("/ticket/<ticket_code>")
def ticket(ticket_code):
    code = (ticket_code or "").strip().upper()
    reservation = Reservation.query.filter(
        db.func.upper(Reservation.ticket_code) == code
    ).first()
    if reservation is None:
        abort(404)
    is_owner = current_user.is_authenticated and reservation.user_id == current_user.id
    is_staff = current_user.is_authenticated and current_user.is_operator
    return render_template(
        "booking/ticket.html",
        reservation=reservation,
        directions=directions_text(reservation),
        can_cancel=(reservation.status == ReservationStatus.BOOKED and (is_owner or is_staff)),
        guest_cancel=False,
        can_checkout=(reservation.status == ReservationStatus.CHECKED_IN),
        verified=False,
    )


@bp.post("/ticket/<ticket_code>/check-in")
def ticket_check_in(ticket_code):
    """Record the driver's arrival (holder of the ticket code)."""
    code = (ticket_code or "").strip().upper()
    reservation = Reservation.query.filter(
        db.func.upper(Reservation.ticket_code) == code
    ).first()
    if reservation is None:
        abort(404)
    from services.booking import check_in

    try:
        check_in(reservation)
    except BookingError as exc:
        flash(exc.user_message, "error")
    else:
        flash("You are checked in. Please park in your assigned space.", "success")
    return redirect(url_for("booking.ticket", ticket_code=code))


# ---------------------------------------------------------------------------
# My bookings (signed-in drivers)
# ---------------------------------------------------------------------------

@bp.route("/my-bookings")
@login_required
def my_bookings():
    run_expiry()
    reservations = (
        Reservation.query.filter(Reservation.user_id == current_user.id)
        .order_by(Reservation.created_at.desc())
        .all()
    )
    upcoming = [
        r
        for r in reservations
        if r.status in (ReservationStatus.BOOKED, ReservationStatus.CHECKED_IN)
    ]
    past = [
        r
        for r in reservations
        if r.status
        in (ReservationStatus.COMPLETED, ReservationStatus.CANCELLED, ReservationStatus.EXPIRED)
    ]
    return render_template(
        "booking/my_bookings.html", upcoming=upcoming, past=past
    )


@bp.route("/my-bookings/<int:reservation_id>/cancel", methods=["POST"])
@login_required
def cancel_my_booking(reservation_id):
    reservation = db.session.get(Reservation, reservation_id)
    if reservation is None or reservation.user_id != current_user.id:
        abort(403)
    try:
        cancel_reservation(reservation, actor=current_user)
    except BookingError as exc:
        flash(exc.user_message, "error")
    else:
        flash("Your booking has been cancelled and the space is free again.", "success")
    return redirect(url_for("booking.my_bookings"))


# ---------------------------------------------------------------------------
# Guest lookup with ticket code
# ---------------------------------------------------------------------------

@bp.route("/lookup", methods=["GET", "POST"])
def lookup():
    if request.method == "POST":
        code = (request.form.get("ticket_code") or "").strip().upper()
        reg = (request.form.get("vehicle_registration") or "").strip().upper()
        reservation = Reservation.query.filter(
            db.func.upper(Reservation.ticket_code) == code
        ).first()
        if reservation is None:
            flash(
                "No parking ticket matches that code. Please check and try again.",
                "error",
            )
        elif reservation.vehicle_registration.upper() != reg:
            flash(
                "The vehicle registration does not match this ticket. "
                "Please check and try again.",
                "error",
            )
        else:
            is_owner = (
                current_user.is_authenticated
                and reservation.user_id == current_user.id
            )
            is_staff = current_user.is_authenticated and current_user.is_operator
            return render_template(
                "booking/ticket.html",
                reservation=reservation,
                directions=directions_text(reservation),
                can_cancel=(
                    reservation.status == ReservationStatus.BOOKED
                    and (is_owner or is_staff)
                ),
                guest_cancel=(reservation.status == ReservationStatus.BOOKED),
                can_checkout=(reservation.status == ReservationStatus.CHECKED_IN),
                verified=True,
            )
    return render_template("booking/lookup.html")


@bp.route("/lookup/cancel", methods=["POST"])
def lookup_cancel():
    code = (request.form.get("ticket_code") or "").strip().upper()
    reg = (request.form.get("vehicle_registration") or "").strip().upper()
    reservation = Reservation.query.filter(
        db.func.upper(Reservation.ticket_code) == code
    ).first()
    if reservation is None or reservation.vehicle_registration.upper() != reg:
        flash("We could not verify that booking. Please check your details.", "error")
        return redirect(url_for("booking.lookup"))
    try:
        cancel_reservation(
            reservation,
            actor=current_user if current_user.is_authenticated else None,
            verify_registration=reg,
        )
    except BookingError as exc:
        flash(exc.user_message, "error")
        return redirect(url_for("booking.lookup"))
    flash("The booking has been cancelled and the space is free again.", "success")
    return redirect(url_for("booking.lookup"))
