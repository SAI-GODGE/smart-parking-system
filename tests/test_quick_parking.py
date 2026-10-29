"""TC group 7, 8: quick parking allocates only currently vacant slots."""

from datetime import datetime, timedelta

from models import BayStatus, Reservation, ReservationStatus
from services.booking import BookingError, create_reservation

from .conftest import (
    bay_ids,
    bay_status,
    create_facility,
    next_window,
)


def _quick_window(hours=4):
    now = datetime.now()
    return now, now + timedelta(hours=hours)


def test_quick_parking_page_shows_facility_availability(app, client):
    fid = create_facility(app, "QR Lot", bays=8)
    bays = bay_ids(app, fid)
    # Make the state deliberately mixed.
    from .conftest import set_bay_status, make_reservation

    set_bay_status(app, bays[0], BayStatus.MAINTENANCE)
    make_reservation(
        app, fid, bays[1], registration="MH-61 QQQQ 6161",
        status=ReservationStatus.CHECKED_IN, entry=datetime.now() - timedelta(minutes=20),
        start=datetime.now() - timedelta(hours=1), end=datetime.now() + timedelta(hours=1),
    )

    response = client.get(f"/parking/facility/{fid}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "QR Lot" in html
    assert "Select a Vacant Slot" in html
    assert 'data-stat="total"' in html
    assert 'data-stat="vacant"' in html
    assert 'data-stat="occupied"' in html
    assert 'data-stat="maintenance"' in html


def test_quick_parking_allocates_vacant_slot(app, client):
    fid = create_facility(app, "Quick Lot")
    bays = bay_ids(app, fid)
    start, end = _quick_window()

    res = create_reservation(
        facility_id=fid, bay_id=bays[0], vehicle_registration="MH-71 QUICK 7171",
        vehicle_type="car", start_time=start, end_time=end, mode="quick",
    )
    with app.app_context():
        from extensions import db

        row = db.session.get(Reservation, res.id)
        # Quick parking records the driver as already parked.
        assert row.status == ReservationStatus.CHECKED_IN
        assert row.entry_timestamp is not None
    assert bay_status(app, bays[0]) == BayStatus.OCCUPIED


def test_quick_parking_rejects_occupied_slot(app, client):
    fid = create_facility(app, "Occupied Lot")
    bays = bay_ids(app, fid)
    start, end = _quick_window()
    # Vehicle recorded as parked now.
    create_reservation(
        facility_id=fid, bay_id=bays[0], vehicle_registration="MH-72 OCCD 7272",
        vehicle_type="car", start_time=start, end_time=end, mode="quick",
    )

    try:
        create_reservation(
            facility_id=fid, bay_id=bays[0], vehicle_registration="MH-73 OCCD 7373",
            vehicle_type="car", start_time=start, end_time=end, mode="quick",
        )
        raised = False
    except BookingError as exc:
        raised = True
        assert "parked in it" in exc.user_message or "just booked" in exc.user_message
    assert raised, "occupied slot must not be allocated"


def test_quick_parking_rejects_reserved_slot(app, client):
    fid = create_facility(app, "Reserved Lot")
    bays = bay_ids(app, fid)
    start, end = _quick_window()
    create_reservation(
        facility_id=fid, bay_id=bays[0], vehicle_registration="MH-74 RSRV 7474",
        vehicle_type="car", start_time=start, end_time=end, mode="advance",
    )

    try:
        create_reservation(
            facility_id=fid, bay_id=bays[0], vehicle_registration="MH-75 RSRV 7575",
            vehicle_type="car", start_time=start, end_time=end, mode="quick",
        )
        raised = False
    except BookingError:
        raised = True
    assert raised, "reserved slot must not be allocated for quick parking"
    assert bay_status(app, bays[0]) == BayStatus.RESERVED


def test_quick_parking_never_allocates_maintenance_slot(app):
    fid = create_facility(app, "Maint Lot")
    bays = bay_ids(app, fid)
    from .conftest import set_bay_status

    set_bay_status(app, bays[0], BayStatus.MAINTENANCE)
    start, end = _quick_window()

    try:
        create_reservation(
            facility_id=fid, bay_id=bays[0], vehicle_registration="MH-76 MNTE 7676",
            vehicle_type="car", start_time=start, end_time=end, mode="quick",
        )
        raised = False
    except BookingError as exc:
        raised = True
        assert "maintenance" in exc.user_message
    assert raised
    assert bay_status(app, bays[0]) == BayStatus.MAINTENANCE


def test_advance_booking_never_allocates_maintenance_slot(app):
    fid = create_facility(app, "Maint Advance Lot")
    bays = bay_ids(app, fid)
    from .conftest import set_bay_status

    set_bay_status(app, bays[1], BayStatus.MAINTENANCE)
    start, end = next_window(offset_hours=5)

    try:
        create_reservation(
            facility_id=fid, bay_id=bays[1], vehicle_registration="MH-77 MNTE 7777",
            vehicle_type="car", start_time=start, end_time=end, mode="advance",
        )
        raised = False
    except BookingError as exc:
        raised = True
        assert "maintenance" in exc.user_message
    assert raised


def test_quick_reserve_http_flow(app, client):
    """Full HTTP flow through the QR page: select, confirm, see the ticket."""
    import re

    fid = create_facility(app, "HTTP Quick Lot")
    bays = bay_ids(app, fid)

    response = client.post(
        f"/parking/facility/{fid}/reserve",
        data={
            "bay_id": str(bays[2]),
            "vehicle_registration": "MH-78 HTTP 7878",
            "vehicle_type": "car",
        },
    )
    assert response.status_code == 302
    ticket_url = response.headers["Location"]
    assert ticket_url.startswith("/ticket/")

    html = client.get(ticket_url).get_data(as_text=True)
    assert "MH-78 HTTP 7878" in html
    assert "Directions" in html
    assert "Check Out" in html or "check out" in html.lower()
    assert bay_status(app, bays[2]) == BayStatus.OCCUPIED

    # Selecting no slot is handled gracefully.
    response = client.post(
        f"/parking/facility/{fid}/reserve",
        data={"bay_id": "", "vehicle_registration": "MH-79 HTTP 7979", "vehicle_type": "car"},
        follow_redirects=True,
    )
    assert "tap a free parking space" in response.get_data(as_text=True).lower()


def test_vehicle_type_compatibility_is_enforced(app):
    """A bike-only bay must not accept a car, in either mode."""
    from extensions import db
    from models import ParkingBay

    fid = create_facility(app, "Type Lot", bays=4)
    with app.app_context():
        bay = db.session.get(ParkingBay, bay_ids(app, fid)[3])
        bay.vehicle_type = "bike"
        db.session.commit()
        bay_id = bay.id

    start, end = _quick_window()
    try:
        create_reservation(
            facility_id=fid, bay_id=bay_id, vehicle_registration="MH-80 TYPE 8080",
            vehicle_type="car", start_time=start, end_time=end, mode="quick",
        )
        raised = False
    except BookingError as exc:
        raised = True
        assert "does not accept" in exc.user_message
    assert raised
