"""TC group 11, 12, 13: ticket validation and checkout."""

from datetime import datetime, timedelta

from extensions import db
from models import BayStatus, ParkingTransaction, Reservation, ReservationStatus, User
from services.booking import BookingError, checkout, create_reservation

from .conftest import bay_ids, bay_status, create_facility, make_reservation, next_window


def _parked_reservation(app, fid, bay, registration="MH-10 PARK 0101"):
    now = datetime.now()
    return create_reservation(
        facility_id=fid, bay_id=bay, vehicle_registration=registration,
        vehicle_type="car", start_time=now, end_time=now + timedelta(hours=3),
        mode="quick",
    )


def test_invalid_ticket_is_rejected(app, client):
    response = client.post(
        "/checkout",
        data={"ticket_code": "PK-0000000000000000", "vehicle_registration": "MH-1 AAA 1111"},
        follow_redirects=True,
    )
    assert "No parking ticket matches that code" in response.get_data(as_text=True)


def test_checkout_requires_matching_registration(app):
    fid = create_facility(app, "Reg Match Lot")
    bays = bay_ids(app, fid)
    res = _parked_reservation(app, fid, bays[0])

    try:
        checkout(res.ticket_code, vehicle_registration="MH-9 WRONG 9999")
        raised = False
    except BookingError as exc:
        raised = True
        assert "does not match" in exc.user_message
    assert raised

    # The reservation is untouched.
    assert bay_status(app, bays[0]) == BayStatus.OCCUPIED


def test_valid_checkout_releases_slot_and_records_exit(app):
    fid = create_facility(app, "Checkout Lot")
    bays = bay_ids(app, fid)
    res = _parked_reservation(app, fid, bays[0], registration="MH-12 EXITX 1212")
    assert bay_status(app, bays[0]) == BayStatus.OCCUPIED

    checked_out, duration, fee = checkout(res.ticket_code, vehicle_registration="MH-12 EXITX 1212")
    assert checked_out.status == ReservationStatus.COMPLETED
    assert checked_out.exit_timestamp is not None
    assert checked_out.entry_timestamp is not None
    assert duration >= 0
    assert fee is not None and fee > 0

    # Slot released and fee recorded - all in the same transaction.
    assert bay_status(app, bays[0]) == BayStatus.VACANT
    with app.app_context():
        assert ParkingTransaction.query.filter_by(reservation_id=checked_out.id).count() == 1


def test_completed_ticket_cannot_be_checked_out_twice(app):
    fid = create_facility(app, "Double Checkout Lot")
    bays = bay_ids(app, fid)
    res = _parked_reservation(app, fid, bays[0], registration="MH-13 TWIC 1313")

    checkout(res.ticket_code, vehicle_registration="MH-13 TWIC 1313")
    try:
        checkout(res.ticket_code, vehicle_registration="MH-13 TWIC 1313")
        raised = False
    except BookingError as exc:
        raised = True
        assert "already checked out" in exc.user_message
    assert raised


def test_unchecked_in_reservation_cannot_check_out(app):
    fid = create_facility(app, "No Show Lot")
    bays = bay_ids(app, fid)
    start, end = next_window()
    res = make_reservation(
        app, fid, bays[0], registration="MH-14 NSHO 1414", start=start, end=end
    )
    with app.app_context():
        ticket = db.session.get(Reservation, res).ticket_code

    try:
        checkout(ticket, vehicle_registration="MH-14 NSHO 1414")
        raised = False
    except BookingError as exc:
        raised = True
        assert "has not been checked in" in exc.user_message
    assert raised
    assert bay_status(app, bays[0]) == BayStatus.RESERVED


def test_checkout_http_flow(app, client):
    fid = create_facility(app, "HTTP Checkout Lot")
    bays = bay_ids(app, fid)
    res = _parked_reservation(app, fid, bays[1], registration="MH-15 HTTP 1515")

    response = client.post(
        "/checkout",
        data={"ticket_code": res.ticket_code, "vehicle_registration": "mh-15 http 1515"},
    )
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "checkout complete" in html
    assert "released" in html
    assert "Rs." in html  # fee shown (fee calculation enabled)

    # Second attempt reports the previous checkout.
    response = client.post(
        "/checkout",
        data={"ticket_code": res.ticket_code, "vehicle_registration": "mh-15 http 1515"},
        follow_redirects=True,
    )
    assert "already checked out" in response.get_data(as_text=True)


def test_checkout_works_for_signed_in_owner_without_typing_registration(app, client):
    from .conftest import create_user, login

    fid = create_facility(app, "Owner Checkout Lot")
    bays = bay_ids(app, fid)
    user_id = create_user(app, "checkoutowner")
    user = db.session.get(User, user_id)
    now = datetime.now()
    res = create_reservation(
        facility_id=fid, bay_id=bays[0], vehicle_registration="MH-16 OWNE 1616",
        vehicle_type="car", start_time=now, end_time=now + timedelta(hours=2),
        mode="quick", user=user,
    )
    login(client, "checkoutowner")

    response = client.post(
        "/checkout", data={"ticket_code": res.ticket_code, "vehicle_registration": ""}
    )
    assert response.status_code == 200
    assert "checkout complete" in response.get_data(as_text=True)


def test_fee_calculation_uses_facility_rate(app):
    fid = create_facility(app, "Fee Lot", hourly_rate=60.0)
    bays = bay_ids(app, fid)
    res = _parked_reservation(app, fid, bays[0], registration="MH-17 FEEA 1717")

    _, _, fee = checkout(res.ticket_code, vehicle_registration="MH-17 FEEA 1717")
    assert fee is not None
    assert fee % 60 == 0  # whole hours at Rs. 60
    assert fee >= 60
