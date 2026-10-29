"""Parking operator workspace.

Operators can see recorded availability, find a ticket, confirm arrival
(check-in) and process checkout for drivers who need assistance.
"""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from extensions import db
from models import ParkingFacility, Reservation, ReservationStatus
from services.availability import facility_counts, global_counts
from services.booking import BookingError, checkout, check_in, run_expiry

bp = Blueprint("operator", __name__, url_prefix="/operator")


def operator_required(f):
    from functools import wraps

    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_operator:
            abort(403)
        return f(*args, **kwargs)

    return wrapper


@bp.route("/")
@operator_required
def dashboard():
    run_expiry()
    facilities = ParkingFacility.query.filter_by(is_active=True).order_by(
        ParkingFacility.name
    ).all()
    facility_rows = [
        {"facility": f, "counts": facility_counts(f.id)} for f in facilities
    ]
    active = (
        Reservation.query.filter(Reservation.status.in_(ReservationStatus.ACTIVE))
        .order_by(Reservation.start_time)
        .all()
    )
    recent = (
        Reservation.query.order_by(Reservation.created_at.desc()).limit(8).all()
    )
    search_result = None
    search_ticket = request.values.get("q", "").strip()
    if search_ticket:
        search_result = Reservation.query.filter(
            db.func.upper(Reservation.ticket_code) == search_ticket.upper()
        ).first()

    return render_template(
        "operator/dashboard.html",
        facility_rows=facility_rows,
        totals=global_counts(),
        active=active,
        recent=recent,
        search_result=search_result,
        search_ticket=search_ticket,
    )


@bp.post("/checkin/<int:reservation_id>")
@operator_required
def checkin(reservation_id):
    reservation = db.session.get(Reservation, reservation_id)
    if reservation is None:
        abort(404)
    try:
        check_in(reservation)
    except BookingError as exc:
        flash(exc.user_message, "error")
    else:
        flash(
            f"{reservation.bay_label}: vehicle recorded as parked.",
            "success",
        )
    return redirect(url_for("operator.dashboard"))


@bp.post("/checkout/<int:reservation_id>")
@operator_required
def process_checkout(reservation_id):
    reservation = db.session.get(Reservation, reservation_id)
    if reservation is None:
        abort(404)
    try:
        res, duration, fee = checkout(
            reservation.ticket_code, vehicle_registration=None, user=current_user
        )
    except BookingError as exc:
        flash(exc.user_message, "error")
    else:
        message = f"Checked out {res.bay_label} after {duration} minutes."
        if fee is not None:
            message += f" Fee: Rs. {fee:.2f}"
        flash(message, "success")
    return redirect(url_for("operator.dashboard"))
