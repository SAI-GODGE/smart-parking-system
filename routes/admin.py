"""Protected administrator interface."""

from datetime import datetime

from flask import (
    Blueprint,
    Response,
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
    BayStatus,
    ParkingFacility,
    ParkingBay,
    Reservation,
    ReservationStatus,
    Role,
    User,
    VehicleType,
)
from services.availability import facility_counts, global_counts
from services.booking import (
    BookingError,
    cancel_reservation,
    checkout,
    check_in,
    run_expiry,
    _sync_bay_status,
)
from services.qr import facility_public_url, generate_qr_png

bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(f):
    from functools import wraps

    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@bp.route("/")
@admin_required
def dashboard():
    run_expiry()
    facilities = ParkingFacility.query.order_by(ParkingFacility.name).all()
    facility_rows = [
        {"facility": f, "counts": facility_counts(f.id)} for f in facilities
    ]
    active_count = Reservation.query.filter(
        Reservation.status.in_(ReservationStatus.ACTIVE)
    ).count()
    recent = Reservation.query.order_by(Reservation.created_at.desc()).limit(10).all()
    user_count = User.query.count()
    return render_template(
        "admin/dashboard.html",
        totals=global_counts(),
        facility_rows=facility_rows,
        active_count=active_count,
        recent=recent,
        user_count=user_count,
    )


# ---------------------------------------------------------------------------
# Facilities
# ---------------------------------------------------------------------------

def _facility_form_errors(form):
    errors = []
    name = (form.get("name") or "").strip()
    if not name:
        errors.append("Facility name is required.")
    elif len(name) > 120:
        errors.append("Facility name is too long.")
    existing = ParkingFacility.query.filter(ParkingFacility.name == name).first()
    if existing and str(existing.id) != (form.get("id") or ""):
        errors.append("A facility with that name already exists.")
    try:
        rate = float(form.get("hourly_rate") or 0)
        if rate < 0:
            errors.append("Hourly rate cannot be negative.")
    except ValueError:
        errors.append("Hourly rate must be a number.")
    try:
        duration = int(form.get("default_duration_hours") or 4)
        if not 1 <= duration <= 72:
            errors.append("Default duration must be between 1 and 72 hours.")
    except ValueError:
        errors.append("Default duration must be a whole number of hours.")
    try:
        hold = int(form.get("hold_minutes") or 0)
        if hold < 0:
            errors.append("Hold period cannot be negative.")
    except ValueError:
        errors.append("Hold period must be a whole number of minutes.")
    return errors


@bp.route("/facilities")
@admin_required
def facilities():
    rows = [
        {"facility": f, "counts": facility_counts(f.id)}
        for f in ParkingFacility.query.order_by(ParkingFacility.name).all()
    ]
    return render_template("admin/facilities.html", rows=rows)


@bp.route("/facilities/new", methods=["GET", "POST"])
@admin_required
def facility_new():
    if request.method == "POST":
        errors = _facility_form_errors(request.form)
        if errors:
            for message in errors:
                flash(message, "error")
            return render_template(
                "admin/facility_form.html",
                facility=None,
                form=request.form,
            )
        facility = ParkingFacility(
            name=request.form.get("name").strip(),
            location_description=(request.form.get("location_description") or "").strip(),
            address=(request.form.get("address") or "").strip(),
            parking_type=(request.form.get("parking_type") or "General parking").strip(),
            hourly_rate=float(request.form.get("hourly_rate") or 40),
            default_duration_hours=int(request.form.get("default_duration_hours") or 4),
            hold_minutes=int(request.form.get("hold_minutes") or 0),
            is_active=True,
        )
        db.session.add(facility)
        db.session.commit()
        flash("Facility created. Now add parking spaces to it.", "success")
        return redirect(url_for("admin.bays", facility_id=facility.id))
    return render_template("admin/facility_form.html", facility=None, form=None)


@bp.route("/facilities/<int:facility_id>/edit", methods=["GET", "POST"])
@admin_required
def facility_edit(facility_id):
    facility = db.session.get(ParkingFacility, facility_id) or abort(404)
    if request.method == "POST":
        errors = _facility_form_errors(request.form)
        if errors:
            for message in errors:
                flash(message, "error")
            return render_template(
                "admin/facility_form.html", facility=facility, form=request.form
            )
        facility.name = request.form.get("name").strip()
        facility.location_description = (
            request.form.get("location_description") or ""
        ).strip()
        facility.address = (request.form.get("address") or "").strip()
        facility.parking_type = (
            request.form.get("parking_type") or "General parking"
        ).strip()
        facility.hourly_rate = float(request.form.get("hourly_rate") or 40)
        facility.default_duration_hours = int(
            request.form.get("default_duration_hours") or 4
        )
        facility.hold_minutes = int(request.form.get("hold_minutes") or 0)
        db.session.commit()
        flash("Facility updated.", "success")
        return redirect(url_for("admin.facilities"))
    return render_template(
        "admin/facility_form.html",
        facility=facility,
        form={
            "name": facility.name,
            "location_description": facility.location_description,
            "address": facility.address,
            "parking_type": facility.parking_type,
            "hourly_rate": facility.hourly_rate,
            "default_duration_hours": facility.default_duration_hours,
            "hold_minutes": facility.hold_minutes,
        },
    )


@bp.post("/facilities/<int:facility_id>/toggle")
@admin_required
def facility_toggle(facility_id):
    facility = db.session.get(ParkingFacility, facility_id) or abort(404)
    facility.is_active = not facility.is_active
    db.session.commit()
    state = "published" if facility.is_active else "hidden from drivers"
    flash(f"{facility.name} is now {state}.", "success")
    return redirect(url_for("admin.facilities"))


# ---------------------------------------------------------------------------
# Parking spaces
# ---------------------------------------------------------------------------

@bp.route("/facilities/<int:facility_id>/bays")
@admin_required
def bays(facility_id):
    facility = db.session.get(ParkingFacility, facility_id) or abort(404)
    rows = (
        ParkingBay.query.filter_by(facility_id=facility.id)
        .order_by(ParkingBay.floor, ParkingBay.zone, ParkingBay.slot_number)
        .all()
    )
    return render_template(
        "admin/bays.html", facility=facility, bays=rows, counts=facility_counts(facility.id)
    )


def _bay_form_errors(form, facility_id, bay=None):
    errors = []
    slot = (form.get("slot_number") or "").strip()
    if not slot:
        errors.append("Slot number is required.")
    elif len(slot) > 20:
        errors.append("Slot number is too long.")
    floor = 0
    try:
        floor = int(form.get("floor") or 0)
        if floor < 0 or floor > 50:
            errors.append("Floor must be between 0 and 50.")
    except ValueError:
        errors.append("Floor must be a whole number.")
    zone = (form.get("zone") or "").strip().upper()
    if not zone:
        errors.append("Zone is required.")
    if (form.get("vehicle_type") or "") not in VehicleType.ALL:
        errors.append("Please choose a valid vehicle type.")
    if (form.get("status") or "") not in BayStatus.ALL:
        errors.append("Please choose a valid status.")
    try:
        distance = int(form.get("distance_from_gate") or 0)
        if distance < 0 or distance > 10000:
            errors.append("Distance from the entrance must be between 0 and 10000.")
    except ValueError:
        errors.append("Distance from the entrance must be a whole number.")

    if slot and zone and not errors:
        query = ParkingBay.query.filter(
            ParkingBay.facility_id == facility_id,
            ParkingBay.floor == floor,
            db.func.upper(ParkingBay.zone) == zone,
            db.func.upper(ParkingBay.slot_number) == slot.upper(),
        )
        if bay is not None:
            query = query.filter(ParkingBay.id != bay.id)
        if query.first():
            errors.append(
                "That slot number already exists in this floor and zone."
            )
    return errors


@bp.route("/facilities/<int:facility_id>/bays/new", methods=["GET", "POST"])
@admin_required
def bay_new(facility_id):
    facility = db.session.get(ParkingFacility, facility_id) or abort(404)
    if request.method == "POST":
        errors = _bay_form_errors(request.form, facility.id)
        if errors:
            for message in errors:
                flash(message, "error")
            return render_template(
                "admin/bay_form.html",
                facility=facility,
                bay=None,
                form=request.form,
                vehicle_types=VehicleType.ALL,
                statuses=BayStatus.ALL,
            )
        bay = ParkingBay(
            facility_id=facility.id,
            slot_number=request.form.get("slot_number").strip(),
            floor=int(request.form.get("floor") or 0),
            zone=request.form.get("zone").strip().upper(),
            vehicle_type=request.form.get("vehicle_type"),
            status=request.form.get("status"),
            distance_from_gate=int(request.form.get("distance_from_gate") or 0),
            is_accessible=request.form.get("is_accessible") == "1",
        )
        db.session.add(bay)
        db.session.commit()
        flash(f"Slot {bay.label} added.", "success")
        return redirect(url_for("admin.bays", facility_id=facility.id))
    return render_template(
        "admin/bay_form.html",
        facility=facility,
        bay=None,
        form=None,
        vehicle_types=VehicleType.ALL,
        statuses=BayStatus.ALL,
    )


@bp.route("/bays/<int:bay_id>/edit", methods=["GET", "POST"])
@admin_required
def bay_edit(bay_id):
    bay = db.session.get(ParkingBay, bay_id) or abort(404)
    facility = bay.facility
    if request.method == "POST":
        errors = _bay_form_errors(request.form, facility.id, bay=bay)
        if errors:
            for message in errors:
                flash(message, "error")
            return render_template(
                "admin/bay_form.html",
                facility=facility,
                bay=bay,
                form=request.form,
                vehicle_types=VehicleType.ALL,
                statuses=BayStatus.ALL,
            )
        bay.slot_number = request.form.get("slot_number").strip()
        bay.floor = int(request.form.get("floor") or 0)
        bay.zone = request.form.get("zone").strip().upper()
        bay.vehicle_type = request.form.get("vehicle_type")
        bay.status = request.form.get("status")
        bay.distance_from_gate = int(request.form.get("distance_from_gate") or 0)
        bay.is_accessible = request.form.get("is_accessible") == "1"
        bay.updated_at = datetime.now()
        db.session.commit()
        flash(f"Slot {bay.label} updated.", "success")
        return redirect(url_for("admin.bays", facility_id=facility.id))
    return render_template(
        "admin/bay_form.html",
        facility=facility,
        bay=bay,
        form={
            "slot_number": bay.slot_number,
            "floor": bay.floor,
            "zone": bay.zone,
            "vehicle_type": bay.vehicle_type,
            "status": bay.status,
            "distance_from_gate": bay.distance_from_gate,
            "is_accessible": bay.is_accessible,
        },
        vehicle_types=VehicleType.ALL,
        statuses=BayStatus.ALL,
    )


@bp.post("/bays/<int:bay_id>/status")
@admin_required
def bay_status(bay_id):
    bay = db.session.get(ParkingBay, bay_id) or abort(404)
    target = request.form.get("target", "")
    if target == "maintenance":
        bay.status = BayStatus.MAINTENANCE
        flash(f"Slot {bay.label} is closed for maintenance.", "success")
    elif target == "service":
        _sync_bay_status(bay)
        flash(
            f"Slot {bay.label} returned to service "
            f"(now recorded as {bay.status_label.lower()}).",
            "success",
        )
    elif target in (BayStatus.VACANT, BayStatus.RESERVED, BayStatus.OCCUPIED):
        bay.status = target
        flash(f"Slot {bay.label} set to {bay.status_label.lower()}.", "success")
    else:
        flash("Unknown status change.", "error")
    bay.updated_at = datetime.now()
    db.session.commit()
    return redirect(request.referrer or url_for("admin.bays", facility_id=bay.facility_id))


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------

@bp.route("/reservations")
@admin_required
def reservations():
    status = request.args.get("status", "")
    query = Reservation.query
    if status in ReservationStatus.ALL:
        query = query.filter(Reservation.status == status)
    rows = query.order_by(Reservation.created_at.desc()).limit(200).all()
    return render_template(
        "admin/reservations.html",
        rows=rows,
        statuses=ReservationStatus.ALL,
        labels=ReservationStatus.LABELS,
        current_status=status,
    )


@bp.post("/reservations/<int:reservation_id>/action")
@admin_required
def reservation_action(reservation_id):
    reservation = db.session.get(Reservation, reservation_id) or abort(404)
    action = request.form.get("action", "")
    try:
        if action == "checkin":
            check_in(reservation)
            flash(f"{reservation.reservation_code}: checked in.", "success")
        elif action == "checkout":
            res, duration, fee = checkout(
                reservation.ticket_code, vehicle_registration=None, user=current_user
            )
            message = f"{res.reservation_code}: checked out after {duration} minutes."
            if fee is not None:
                message += f" Fee: Rs. {fee:.2f}"
            flash(message, "success")
        elif action == "cancel":
            cancel_reservation(reservation, actor=current_user)
            flash(f"{reservation.reservation_code}: cancelled and slot released.", "success")
        else:
            flash("Unknown action.", "error")
    except BookingError as exc:
        flash(exc.user_message, "error")
    return redirect(url_for("admin.reservations", status=request.args.get("status", "")))


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

@bp.route("/users")
@admin_required
def users():
    rows = User.query.order_by(User.created_at.desc()).all()
    return render_template(
        "admin/users.html", rows=rows, roles=Role.ALL, role_labels=Role.LABELS
    )


@bp.post("/users/<int:user_id>/role")
@admin_required
def user_role(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if user.id == current_user.id:
        flash("You cannot change your own role.", "error")
        return redirect(url_for("admin.users"))
    new_role = request.form.get("role", "")
    if new_role not in Role.ALL:
        flash("Unknown role.", "error")
        return redirect(url_for("admin.users"))
    if user.is_admin and new_role != Role.ADMIN:
        active_admins = User.query.filter(
            User.role == Role.ADMIN, User.account_status == "active"
        ).count()
        if active_admins <= 1:
            flash("There must be at least one active administrator.", "error")
            return redirect(url_for("admin.users"))
    user.role = new_role
    db.session.commit()
    flash(f"{user.username} is now a {Role.LABELS[new_role]}.", "success")
    return redirect(url_for("admin.users"))


@bp.post("/users/<int:user_id>/status")
@admin_required
def user_status(user_id):
    user = db.session.get(User, user_id) or abort(404)
    if user.id == current_user.id:
        flash("You cannot disable your own account.", "error")
        return redirect(url_for("admin.users"))
    target = request.form.get("status", "")
    if target not in ("active", "disabled"):
        flash("Unknown account status.", "error")
        return redirect(url_for("admin.users"))
    if target == "disabled" and user.is_admin:
        active_admins = User.query.filter(
            User.role == Role.ADMIN, User.account_status == "active"
        ).count()
        if active_admins <= 1:
            flash("There must be at least one active administrator.", "error")
            return redirect(url_for("admin.users"))
    user.account_status = target
    db.session.commit()
    flash(
        f"{user.username} is now {'active' if target == 'active' else 'disabled'}.",
        "success",
    )
    return redirect(url_for("admin.users"))


# ---------------------------------------------------------------------------
# QR codes
# ---------------------------------------------------------------------------

@bp.route("/qr")
@admin_required
def qr_codes():
    facilities = ParkingFacility.query.filter_by(is_active=True).order_by(
        ParkingFacility.name
    ).all()
    entries = [
        {
            "facility": f,
            "url": facility_public_url(f.id),
            "image_url": url_for("admin.qr_image", facility_id=f.id),
        }
        for f in facilities
    ]
    from flask import current_app

    return render_template(
        "admin/qr.html", entries=entries, base_url=current_app.config["BASE_URL"]
    )


@bp.route("/facility/<int:facility_id>/qr.png")
@admin_required
def qr_image(facility_id):
    facility = db.session.get(ParkingFacility, facility_id) or abort(404)
    png = generate_qr_png(facility_public_url(facility.id))
    headers = {}
    if request.args.get("download"):
        headers["Content-Disposition"] = (
            f'attachment; filename="qr-{facility.id}-{facility.name[:20]}.png"'
        )
    return Response(png, mimetype="image/png", headers=headers)
