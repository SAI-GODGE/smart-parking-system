"""Public pages: home, facility lists, how-it-works, availability API."""

from datetime import datetime

from flask import Blueprint, jsonify, render_template, request

from extensions import db
from models import BayStatus, ParkingFacility, ReservationStatus, VehicleType
from services.availability import bay_statuses, facility_counts
from services.booking import BookingError, validate_window

bp = Blueprint("main", __name__)


def _facility_rows():
    facilities = (
        ParkingFacility.query.filter_by(is_active=True)
        .order_by(ParkingFacility.name)
        .all()
    )
    return [
        {"facility": facility, "counts": facility_counts(facility.id)}
        for facility in facilities
    ]


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/facilities")
def facilities():
    mode = request.args.get("mode", "view")
    if mode not in ("advance", "quick", "view"):
        mode = "view"
    return render_template("facilities.html", rows=_facility_rows(), mode=mode)


@bp.route("/how-it-works")
def how_it_works():
    return render_template("how_it_works.html")


@bp.route("/api/facilities/<int:facility_id>/availability")
def availability_api(facility_id):
    facility = db.session.get(ParkingFacility, facility_id)
    if facility is None or not facility.is_active:
        return jsonify({"error": "Facility not found."}), 404

    start = end = None
    start_raw = request.args.get("start")
    end_raw = request.args.get("end")
    if start_raw and end_raw:
        try:
            start = datetime.fromisoformat(start_raw)
            end = datetime.fromisoformat(end_raw)
        except ValueError:
            return jsonify({"error": "Invalid date/time values."}), 400
        try:
            validate_window(start, end)
        except BookingError as exc:
            return jsonify({"error": exc.user_message}), 400

    needs_accessible = request.args.get("accessible") in ("1", "true", "yes")
    vehicle_type = request.args.get("vehicle_type") or None
    if vehicle_type not in VehicleType.BOOKABLE:
        vehicle_type = None

    bays = bay_statuses(
        facility_id,
        start=start,
        end=end,
        needs_accessible=needs_accessible,
        vehicle_type=vehicle_type,
    )
    counts = facility_counts(facility_id)
    free_count = sum(1 for b in bays if b["bookable"])

    return jsonify(
        {
            "facility_id": facility.id,
            "counts": counts,
            "free_count": free_count,
            "window": {
                "start": start.isoformat() if start else None,
                "end": end.isoformat() if end else None,
            },
            "bays": bays,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
    )


@bp.app_context_processor
def inject_globals():
    return {
        "BayStatus": BayStatus,
        "ReservationStatus": ReservationStatus,
        "VehicleType": VehicleType,
        "now_dt": datetime.now(),
    }
