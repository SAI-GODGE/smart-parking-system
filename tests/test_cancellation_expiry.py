"""TC group 14: cancellation and expiry follow the documented rules.

Documented rule: an advance reservation that is not checked in within the
hold period (default 30 minutes after the scheduled arrival time) expires
automatically and its bay is released.
"""

from datetime import datetime, timedelta

from extensions import db
from models import BayStatus, Reservation, ReservationStatus
from services.booking import (
    BookingError,
    cancel_reservation,
    create_reservation,
    run_expiry,
)

from .conftest import bay_ids, bay_status, create_facility, make_reservation, next_window


def test_cancelling_releases_the_bay(app):
    fid = create_facility(app, "Cancel Lot")
    bays = bay_ids(app, fid)
    start, end = next_window()
    res_id = make_reservation(
        app, fid, bays[0], registration="MH-20 CNCL 2020", start=start, end=end
    )
    assert bay_status(app, bays[0]) == BayStatus.RESERVED

    with app.app_context():
        res = db.session.get(Reservation, res_id)
        cancel_reservation(res, verify_registration=res.vehicle_registration)

    assert bay_status(app, bays[0]) == BayStatus.VACANT
    with app.app_context():
        assert db.session.get(Reservation, res_id).status == ReservationStatus.CANCELLED


def test_cancellation_requires_authorisation(app):
    """A stranger holding only the reservation id cannot cancel someone else's booking."""
    fid = create_facility(app, "Auth Cancel Lot")
    bays = bay_ids(app, fid)
    start, end = next_window()
    res_id = make_reservation(
        app, fid, bays[0], registration="MH-19 AUTH 1919", start=start, end=end
    )
    with app.app_context():
        res = db.session.get(Reservation, res_id)
        for kwargs in ({}, {"verify_registration": "MH-99 WRONG 9999"}):
            try:
                cancel_reservation(res, **kwargs)
                raised = False
            except BookingError as exc:
                raised = True
                assert "not allowed" in exc.user_message
            assert raised
    assert bay_status(app, bays[0]) == BayStatus.RESERVED


def test_cancelled_reservation_cannot_be_cancelled_again(app):
    fid = create_facility(app, "Cancel Twice Lot")
    bays = bay_ids(app, fid)
    start, end = next_window()
    res_id = make_reservation(
        app, fid, bays[0], registration="MH-21 CNCL 2121", start=start, end=end
    )
    with app.app_context():
        res = db.session.get(Reservation, res_id)
        cancel_reservation(res, verify_registration=res.vehicle_registration)
        try:
            cancel_reservation(res, verify_registration=res.vehicle_registration)
            raised = False
        except BookingError as exc:
            raised = True
            assert "active advance bookings" in exc.user_message
    assert raised


def test_cancelled_reservation_frees_slot_for_others(app):
    fid = create_facility(app, "Reuse Lot")
    bays = bay_ids(app, fid)
    start, end = next_window()
    res_id = make_reservation(
        app, fid, bays[0], registration="MH-22 REUS 2222", start=start, end=end
    )
    with app.app_context():
        res = db.session.get(Reservation, res_id)
        cancel_reservation(res, verify_registration=res.vehicle_registration)

    # Someone else can now book the same slot for the same window.
    res = create_reservation(
        facility_id=fid, bay_id=bays[0], vehicle_registration="MH-23 REUS 2323",
        vehicle_type="car", start_time=start, end_time=end, mode="advance",
    )
    assert res.id
    assert bay_status(app, bays[0]) == BayStatus.RESERVED


def test_lapsed_reservation_expires_and_releases_bay(app):
    fid = create_facility(app, "Expiry Lot", hold_minutes=30)
    bays = bay_ids(app, fid)

    # Scheduled arrival was 45 minutes ago and nobody checked in.
    start = datetime.now() - timedelta(minutes=45)
    res_id = make_reservation(
        app, fid, bays[0], registration="MH-24 EXPR 2424",
        start=start, end=start + timedelta(hours=2),
    )
    assert bay_status(app, bays[0]) == BayStatus.RESERVED

    run_expiry()

    with app.app_context():
        res = db.session.get(Reservation, res_id)
        assert res.status == ReservationStatus.EXPIRED
    assert bay_status(app, bays[0]) == BayStatus.VACANT


def test_reservation_within_hold_period_is_not_expired(app):
    fid = create_facility(app, "Hold Lot", hold_minutes=30)
    bays = bay_ids(app, fid)

    # Scheduled arrival was 10 minutes ago - still within the hold period.
    start = datetime.now() - timedelta(minutes=10)
    res_id = make_reservation(
        app, fid, bays[0], registration="MH-25 HOLD 2525",
        start=start, end=start + timedelta(hours=2),
    )

    run_expiry()

    with app.app_context():
        res = db.session.get(Reservation, res_id)
        assert res.status == ReservationStatus.BOOKED
    assert bay_status(app, bays[0]) == BayStatus.RESERVED


def test_expired_reservation_cannot_check_in_or_be_cancelled(app):
    fid = create_facility(app, "Expired Action Lot", hold_minutes=30)
    bays = bay_ids(app, fid)
    start = datetime.now() - timedelta(hours=3)
    res_id = make_reservation(
        app, fid, bays[0], registration="MH-26 EXPR 2626",
        start=start, end=start + timedelta(hours=1),
    )
    run_expiry()

    with app.app_context():
        res = db.session.get(Reservation, res_id)
        assert res.status == ReservationStatus.EXPIRED
        for action in ("cancel", "checkin"):
            try:
                if action == "cancel":
                    cancel_reservation(
                        res, verify_registration=res.vehicle_registration
                    )
                else:
                    from services.booking import check_in

                    check_in(res)
                raised = False
            except BookingError:
                raised = True
            assert raised, f"{action} must be rejected for an expired reservation"


def test_expiry_frees_bay_for_a_new_advance_booking(app):
    fid = create_facility(app, "Expiry Reuse Lot", hold_minutes=15)
    bays = bay_ids(app, fid)
    start = datetime.now() - timedelta(hours=2)
    make_reservation(
        app, fid, bays[0], registration="MH-27 EXRE 2727",
        start=start, end=start + timedelta(hours=1),
    )
    run_expiry()
    assert bay_status(app, bays[0]) == BayStatus.VACANT

    new_start, new_end = next_window()
    res = create_reservation(
        facility_id=fid, bay_id=bays[0], vehicle_registration="MH-28 EXRE 2828",
        vehicle_type="car", start_time=new_start, end_time=new_end, mode="advance",
    )
    assert res.id


def test_checkout_of_completed_bay_with_future_reservation_becomes_reserved(app):
    """After checkout the bay returns to 'reserved' if a future booking exists."""
    fid = create_facility(app, "Handover Lot")
    bays = bay_ids(app, fid)

    # Car parked now (quick).
    now = datetime.now()
    parked = create_reservation(
        facility_id=fid, bay_id=bays[0], vehicle_registration="MH-29 PARK 2929",
        vehicle_type="car", start_time=now, end_time=now + timedelta(hours=1),
        mode="quick",
    )
    assert bay_status(app, bays[0]) == BayStatus.OCCUPIED

    # Note: quick parking prevents a second active reservation on the same bay,
    # so simulate a future booking by inserting one directly for the same bay
    # (window does not overlap the current one).
    tomorrow = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    make_reservation(
        app, fid, bays[0], registration="MH-30 FUTR 3030",
        start=tomorrow, end=tomorrow + timedelta(hours=2),
    )

    from services.booking import checkout

    checkout(parked.ticket_code, vehicle_registration="MH-29 PARK 2929")
    assert bay_status(app, bays[0]) == BayStatus.RESERVED
