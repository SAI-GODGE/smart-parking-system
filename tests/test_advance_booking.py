"""TC group 5, 6, 10: advance booking, time windows, duplicates."""

import re
from datetime import datetime, timedelta

from extensions import db
from models import BayStatus, ParkingBay, Reservation, ReservationStatus
from services.booking import BookingError, create_reservation

from .conftest import (
    bay_ids,
    bay_status,
    create_facility,
    create_user,
    make_reservation,
    next_window,
    reservation_by_id,
)


def _post_time_step(client, fid, start, end, vehicle="car", accessible="0"):
    hours = int((end - start).total_seconds() // 3600)
    return client.post(
        f"/book/{fid}",
        data={
            "date": start.strftime("%Y-%m-%d"),
            "time": start.strftime("%H:%M"),
            "duration": str(hours),
            "vehicle_type": vehicle,
            "needs_accessible": accessible,
        },
    )


def _post_confirm(client, fid, start, end, bay_id, reg, vehicle="car", accessible="0"):
    hours = int((end - start).total_seconds() // 3600)
    return client.post(
        f"/book/{fid}/confirm",
        data={
            "date": start.strftime("%Y-%m-%d"),
            "time": start.strftime("%H:%M"),
            "duration": str(hours),
            "vehicle_type": vehicle,
            "needs_accessible": accessible,
            "bay_id": str(bay_id),
            "vehicle_registration": reg,
        },
    )


def test_advance_booking_creates_valid_reservation(app, client):
    fid = create_facility(app, "Mall Parking")
    bays = bay_ids(app, fid)
    start, end = next_window()

    # Step 2 -> step 3
    response = _post_time_step(client, fid, start, end)
    assert response.status_code == 302
    slots_url = response.headers["Location"]
    assert "/slots" in slots_url

    page = client.get(slots_url)
    assert page.status_code == 200
    assert "bay-tile" in page.get_data(as_text=True)

    # Step 4 -> ticket
    response = _post_confirm(client, fid, start, end, bays[0], "MH-22 BOOK 2222")
    assert response.status_code == 302
    ticket_url = response.headers["Location"]
    assert ticket_url.startswith("/ticket/")

    with app.app_context():
        res = Reservation.query.filter_by(vehicle_registration="MH-22 BOOK 2222").one()
        assert res.status == "booked"
        assert res.bay_id == bays[0]
        assert res.reservation_code.startswith("RS-")
        assert res.ticket_code.startswith("PK-")
        assert res.start_time == start
        assert res.end_time == end
        # Slot status updated to reserved
        assert db.session.get(ParkingBay, bays[0]).status == BayStatus.RESERVED

    # The digital ticket shows all required information.
    html = client.get(ticket_url).get_data(as_text=True)
    assert "Mall Parking" in html
    assert "MH-22 BOOK 2222" in html
    assert "PK-" in html
    assert "RS-" in html
    assert "Directions" in html
    assert "check in" in html.lower()


def test_advance_booking_rejects_past_times(app, client):
    fid = create_facility(app, "Past Lot")
    past = datetime.now() - timedelta(hours=5)
    response = _post_time_step(client, fid, past, past + timedelta(hours=2))
    assert response.status_code == 200  # re-renders form
    assert "cannot be in the past" in response.get_data(as_text=True)


def test_advance_bookings_respect_time_windows(app):
    """Overlapping windows conflict; non-overlapping windows share the bay."""
    fid = create_facility(app, "Window Lot")
    bays = bay_ids(app, fid)
    bay = bays[0]
    base = (datetime.now() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)

    # Book 09:00 - 11:00
    create_reservation(
        facility_id=fid, bay_id=bay, vehicle_registration="MH-11 WIND 1111",
        vehicle_type="car", start_time=base, end_time=base + timedelta(hours=2),
        mode="advance",
    )

    # Overlapping window (10:00 - 12:00) must fail.
    try:
        create_reservation(
            facility_id=fid, bay_id=bay, vehicle_registration="MH-12 WIND 1212",
            vehicle_type="car", start_time=base + timedelta(hours=1),
            end_time=base + timedelta(hours=3), mode="advance",
        )
        raised = False
    except BookingError as exc:
        raised = True
        assert "just booked" in exc.user_message or "parked in it" in exc.user_message
    assert raised, "overlapping reservation should have been rejected"

    # Fully contained window (09:30 - 10:30) must also fail.
    try:
        create_reservation(
            facility_id=fid, bay_id=bay, vehicle_registration="MH-13 WIND 1313",
            vehicle_type="car", start_time=base + timedelta(minutes=30),
            end_time=base + timedelta(hours=1, minutes=30), mode="advance",
        )
        raised = False
    except BookingError:
        raised = True
    assert raised

    # Later non-overlapping window (12:00 - 14:00) succeeds on the same bay.
    res = create_reservation(
        facility_id=fid, bay_id=bay, vehicle_registration="MH-14 WIND 1414",
        vehicle_type="car", start_time=base + timedelta(hours=3),
        end_time=base + timedelta(hours=5), mode="advance",
    )
    assert res.id


def test_future_booking_allowed_on_currently_occupied_bay(app):
    """A bay that is occupied now can still be reserved for a later window."""
    fid = create_facility(app, "Busy Now Lot")
    bays = bay_ids(app, fid)
    bay = bays[0]

    now = datetime.now()
    # Car currently parked, expected to leave in 30 minutes.
    make_reservation(
        app, fid, bay, registration="MH-15 BUSY 1515",
        status=ReservationStatus.CHECKED_IN, mode="quick",
        start=now - timedelta(hours=1), end=now + timedelta(minutes=30),
        entry=now - timedelta(minutes=45),
    )
    assert bay_status(app, bay) == BayStatus.OCCUPIED

    # Booking tomorrow morning on the same bay is fine.
    tomorrow = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    res = create_reservation(
        facility_id=fid, bay_id=bay, vehicle_registration="MH-16 FUTR 1616",
        vehicle_type="car", start_time=tomorrow, end_time=tomorrow + timedelta(hours=2),
        mode="advance",
    )
    assert res.id
    # The bay stays occupied because a car is recorded there right now.
    assert bay_status(app, bay) == BayStatus.OCCUPIED


def test_duplicate_active_reservation_prevented_for_same_user(app):
    from models import User

    fid = create_facility(app, "Dup Lot")
    bays = bay_ids(app, fid)
    user_id = create_user(app, "dupdriver")
    user = db.session.get(User, user_id)

    start, end = next_window()
    create_reservation(
        facility_id=fid, bay_id=bays[0], vehicle_registration="MH-31 DUPP 3131",
        vehicle_type="car", start_time=start, end_time=end, mode="advance", user=user,
    )

    # Second active booking by the same user at overlapping time -> rejected.
    try:
        create_reservation(
            facility_id=fid, bay_id=bays[1], vehicle_registration="MH-32 DUPP 3232",
            vehicle_type="car", start_time=start, end_time=end, mode="advance", user=user,
        )
        raised = False
    except BookingError as exc:
        raised = True
        assert "already have an active parking booking" in exc.user_message
    assert raised


def test_duplicate_active_reservation_prevented_for_same_registration(app):
    fid = create_facility(app, "Dup Reg Lot")
    bays = bay_ids(app, fid)
    start, end = next_window()
    create_reservation(
        facility_id=fid, bay_id=bays[0], vehicle_registration="MH-41 DUPE 4141",
        vehicle_type="car", start_time=start, end_time=end, mode="advance",
    )
    # Same registration, different user (guest), overlapping time -> rejected.
    try:
        create_reservation(
            facility_id=fid, bay_id=bays[1], vehicle_registration="mh-41 dupe 4141",
            vehicle_type="car", start_time=start, end_time=end, mode="advance",
        )
        raised = False
    except BookingError as exc:
        raised = True
        assert "registration number already has an active booking" in exc.user_message
    assert raised


def test_slot_taken_during_confirmation_is_reported(app, client):
    """If the slot disappears between selection and confirmation, the user
    is sent back to an updated layout with a clear message."""
    fid = create_facility(app, "Race Lot")
    bays = bay_ids(app, fid)
    start, end = next_window()

    # Someone else claims the bay after the form was rendered.
    create_reservation(
        facility_id=fid, bay_id=bays[0], vehicle_registration="MH-51 RACE 5151",
        vehicle_type="car", start_time=start, end_time=end, mode="advance",
    )

    response = _post_confirm(client, fid, start, end, bays[0], "MH-52 RACE 5252")
    assert response.status_code == 302
    assert "/slots" in response.headers["Location"]

    follow = client.get(response.headers["Location"])
    html = follow.get_data(as_text=True)
    assert "just booked by someone else" in html or "not free for your time" in html


def test_vehicle_details_are_validated(app, client):
    fid = create_facility(app, "Validation Lot")
    bays = bay_ids(app, fid)
    start, end = next_window()

    response = _post_confirm(client, fid, start, end, bays[0], "")
    assert response.status_code == 302  # back to slots with an error
    follow = client.get(response.headers["Location"])
    assert "vehicle registration" in follow.get_data(as_text=True).lower()

    response = _post_confirm(
        client, fid, start, end, bays[0], "BAD;DROP TABLE--"
    )
    follow = client.get(response.headers["Location"])
    assert "may only contain letters" in follow.get_data(as_text=True)
