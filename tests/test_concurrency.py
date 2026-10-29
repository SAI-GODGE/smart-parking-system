"""TC group 9: two simultaneous requests cannot claim the same slot."""

from datetime import datetime, timedelta
from threading import Thread

from models import Reservation
from services.booking import BookingError, create_reservation

from .conftest import bay_ids, bay_status, create_facility


def test_two_simultaneous_quick_allocations_claim_one_slot(app):
    fid = create_facility(app, "Race Track Lot", bays=3)
    bays = bay_ids(app, fid)
    target = bays[0]

    now = datetime.now()
    results = []
    errors = []

    def attempt(index):
        try:
            with app.app_context():
                res = create_reservation(
                    facility_id=fid,
                    bay_id=target,
                    vehicle_registration=f"MH-90 RACE {index:04d}",
                    vehicle_type="car",
                    start_time=now,
                    end_time=now + timedelta(hours=2),
                    mode="quick",
                )
                results.append(res.id)
        except BookingError as exc:
            errors.append(exc.user_message)
        except Exception as exc:  # pragma: no cover - would be a real defect
            errors.append(f"UNEXPECTED: {type(exc).__name__}: {exc}")

    threads = [Thread(target=attempt, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(results) + len(errors) == 2, "both threads must complete"
    assert len(results) == 1, f"exactly one allocation must win, got {results} / {errors}"
    assert len(errors) == 1
    assert not any(str(e).startswith("UNEXPECTED") for e in errors), errors

    # Exactly one active reservation exists for that bay.
    with app.app_context():
        active = Reservation.query.filter(
            Reservation.bay_id == target,
            Reservation.status.in_(["booked", "checked_in"]),
        ).count()
    assert active == 1
    assert bay_status(app, target) == "occupied"


def test_sequential_second_allocation_fails(app):
    """The same race without threads: second request must be rejected."""
    fid = create_facility(app, "Sequential Lot", bays=2)
    bays = bay_ids(app, fid)
    now = datetime.now()

    create_reservation(
        facility_id=fid, bay_id=bays[0], vehicle_registration="MH-91 SEQE 9191",
        vehicle_type="car", start_time=now, end_time=now + timedelta(hours=1),
        mode="quick",
    )
    try:
        create_reservation(
            facility_id=fid, bay_id=bays[0], vehicle_registration="MH-92 SEQE 9292",
            vehicle_type="car", start_time=now, end_time=now + timedelta(hours=1),
            mode="quick",
        )
        raised = False
    except BookingError:
        raised = True
    assert raised
