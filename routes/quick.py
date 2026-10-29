"""Mode B: QR-based quick parking.

The QR code printed at a facility entrance opens
/parking/facility/<facility_id> - this page. It shows the recorded
availability immediately and lets a driver claim a vacant slot with the
minimum possible information.
"""

from datetime import datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from extensions import db
from models import ParkingFacility, VehicleType
from services.availability import bay_statuses, facility_counts, floors_and_zones
from services.booking import BookingError, create_reservation, run_expiry

bp = Blueprint("quick", __name__)


def _get_facility_or_404(facility_id):
    facility = db.session.get(ParkingFacility, facility_id)
    if facility is None or not facility.is_active:
        abort(404)
    return facility


@bp.route("/park")
def choose():
    """Facility chooser for drivers who are already on site."""
    return redirect(url_for("main.facilities", mode="quick"))


@bp.route("/parking/facility/<int:facility_id>")
def parking_facility(facility_id):
    """The QR-code target: a mobile-friendly availability dashboard."""
    facility = _get_facility_or_404(facility_id)
    run_expiry()
    counts = facility_counts(facility.id)
    bays = bay_statuses(facility.id)
    floors, zones = floors_and_zones(facility.id)
    return render_template(
        "quick/parking.html",
        facility=facility,
        counts=counts,
        bays=bays,
        floors=floors,
        zones=zones,
        vehicle_types=[(v, VehicleType.LABELS[v]) for v in VehicleType.BOOKABLE],
        quick_hours=facility.default_duration_hours,
    )


@bp.route("/parking/facility/<int:facility_id>/reserve", methods=["POST"])
def reserve(facility_id):
    facility = _get_facility_or_404(facility_id)
    bay_id_raw = request.form.get("bay_id", "")
    registration = request.form.get("vehicle_registration", "")
    vehicle_type = request.form.get("vehicle_type", "")
    needs_accessible = request.form.get("needs_accessible") == "1"

    try:
        bay_id = int(bay_id_raw)
    except ValueError:
        bay_id = 0

    if bay_id <= 0:
        flash("Please tap a free parking space first.", "error")
        return redirect(url_for("quick.parking_facility", facility_id=facility.id))

    now = datetime.now()
    start = now
    end = now + timedelta(hours=facility.default_duration_hours or 4)

    try:
        reservation = create_reservation(
            facility_id=facility.id,
            bay_id=bay_id,
            vehicle_registration=registration,
            vehicle_type=vehicle_type,
            start_time=start,
            end_time=end,
            mode="quick",
            user=None,
            needs_accessible=needs_accessible,
        )
    except BookingError as exc:
        # Includes the "someone else just took it" case: send the driver
        # back to the freshly updated layout with a clear message.
        flash(exc.user_message, "error")
        return redirect(url_for("quick.parking_facility", facility_id=facility.id))

    flash("Your parking space is confirmed.", "success")
    return redirect(url_for("booking.ticket", ticket_code=reservation.ticket_code))
