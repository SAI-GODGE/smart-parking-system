"""Availability queries shared by pages, dashboards and the JSON API.

Nothing in here exposes vehicle registrations or personal data - only slot
status - so these helpers are safe to use on public pages.
"""

from datetime import datetime

from sqlalchemy import func

from extensions import db
from models import BayStatus, ParkingBay, ReservationStatus

from .booking import active_reservations_for_facility, overlaps, run_expiry


def facility_counts(facility_id):
    """Recorded status counts for one facility, computed from the database."""
    rows = (
        db.session.query(ParkingBay.status, func.count(ParkingBay.id))
        .filter(ParkingBay.facility_id == facility_id)
        .group_by(ParkingBay.status)
        .all()
    )
    counts = {status: 0 for status in BayStatus.ALL}
    for status, count in rows:
        counts[status] = count
    counts["total"] = sum(counts.values())
    return counts


def global_counts():
    """Recorded status counts across every bay in the system."""
    rows = (
        db.session.query(ParkingBay.status, func.count(ParkingBay.id))
        .group_by(ParkingBay.status)
        .all()
    )
    counts = {status: 0 for status in BayStatus.ALL}
    for status, count in rows:
        counts[status] = count
    counts["total"] = sum(counts.values())
    return counts


def _status_for_bay(bay, overlapping, now, window_mode):
    """Status of a bay plus whether it may be booked.

    Distinction between current occupancy and future reservations:
    - maintenance bays are never available;
    - an active reservation overlapping the requested window makes the bay
      unavailable (shown as occupied when a car is recorded as parked there,
      otherwise as reserved);
    - otherwise the bay is free for the window even if a car is parked there
      now but its reservation ends before the window starts.
    """
    if bay.status == BayStatus.MAINTENANCE:
        return BayStatus.MAINTENANCE, False

    if overlapping:
        if any(r.status == ReservationStatus.CHECKED_IN for r in overlapping):
            return BayStatus.OCCUPIED, False
        return BayStatus.RESERVED, False

    if window_mode:
        return BayStatus.VACANT, True

    # Current-status view (quick parking): trust recorded status.
    if bay.status == BayStatus.VACANT:
        return BayStatus.VACANT, True
    if bay.status == BayStatus.OCCUPIED:
        return BayStatus.OCCUPIED, False
    if bay.status == BayStatus.RESERVED:
        return BayStatus.RESERVED, False
    return bay.status, False


def bay_statuses(facility_id, start=None, end=None, needs_accessible=False, vehicle_type=None):
    """Return public status information for every bay of a facility.

    No vehicle registrations or user details are included.
    """
    now = datetime.now()
    run_expiry()

    bays = (
        ParkingBay.query.filter_by(facility_id=facility_id)
        .order_by(ParkingBay.floor, ParkingBay.zone, ParkingBay.slot_number)
        .all()
    )
    active = active_reservations_for_facility(facility_id)
    window_mode = start is not None and end is not None

    result = []
    for bay in bays:
        if window_mode:
            overlapping = [r for r in active.get(bay.id, []) if overlaps(r, start, end, now)]
        else:
            overlapping = [r for r in active.get(bay.id, []) if overlaps(r, now, now, now)]

        status, bookable = _status_for_bay(bay, overlapping, now, window_mode)

        if bookable:
            if vehicle_type and not bay.supports(vehicle_type):
                bookable = False
            if needs_accessible and not bay.is_accessible:
                bookable = False

        result.append(
            {
                "id": bay.id,
                "number": bay.slot_number,
                "label": bay.label,
                "floor": bay.floor,
                "zone": bay.zone,
                "status": status,
                "bookable": bool(bookable),
                "vehicle_type": bay.vehicle_type,
                "accessible": bay.is_accessible,
                "distance": bay.distance_from_gate,
            }
        )
    return result


def floors_and_zones(facility_id):
    """Distinct floors and zones configured for a facility."""
    floors = [
        row[0]
        for row in db.session.query(ParkingBay.floor)
        .filter(ParkingBay.facility_id == facility_id)
        .distinct()
        .order_by(ParkingBay.floor)
        .all()
    ]
    zones = [
        row[0]
        for row in db.session.query(ParkingBay.zone)
        .filter(ParkingBay.facility_id == facility_id)
        .distinct()
        .order_by(ParkingBay.zone)
        .all()
    ]
    return floors, zones
