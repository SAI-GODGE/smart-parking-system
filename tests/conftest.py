"""Shared pytest fixtures for the Smart Parking Management System tests.

Every test runs against its own temporary SQLite file so tests never touch
the development database.
"""

from datetime import datetime, timedelta

import pytest

from app import create_app
from extensions import db
from models import (
    BayStatus,
    ParkingBay,
    ParkingFacility,
    Reservation,
    ReservationStatus,
    Role,
    User,
)


@pytest.fixture()
def app(tmp_path):
    db_file = tmp_path / "test.db"
    application = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SEED_ON_START": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_file.as_posix()}",
            "BASE_URL": "http://localhost",
            "RESERVATION_HOLD_MINUTES": 30,
            "MAX_ADVANCE_DAYS": 30,
        }
    )
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture(autouse=True)
def app_context(app):
    """Keep an application context open for the whole test so services and
    model helpers can be called directly."""
    with app.app_context():
        yield


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def create_facility(app, name="Test Parking", bays=6, **kwargs):
    """Create a facility with simple ground-floor bays and return its id."""
    with app.app_context():
        facility = ParkingFacility(
            name=name,
            location_description="Test location",
            address="1 Test Street",
            parking_type="Test parking",
            hourly_rate=kwargs.get("hourly_rate", 40.0),
            default_duration_hours=kwargs.get("default_duration_hours", 4),
            hold_minutes=kwargs.get("hold_minutes", 0),
            is_active=kwargs.get("is_active", True),
        )
        db.session.add(facility)
        db.session.flush()
        for i in range(1, bays + 1):
            db.session.add(
                ParkingBay(
                    facility_id=facility.id,
                    slot_number=f"{i:02d}",
                    floor=0,
                    zone="A",
                    vehicle_type=kwargs.get("vehicle_type", "any"),
                    status=BayStatus.VACANT,
                    distance_from_gate=i * 5,
                    is_accessible=(i == 1),
                )
            )
        db.session.commit()
        return facility.id


def bay_ids(app, facility_id):
    with app.app_context():
        rows = (
            ParkingBay.query.filter_by(facility_id=facility_id)
            .order_by(ParkingBay.id)
            .all()
        )
        return [b.id for b in rows]


def set_bay_status(app, bay_id, status):
    with app.app_context():
        bay = db.session.get(ParkingBay, bay_id)
        bay.status = status
        db.session.commit()


def create_user(app, username="alice", password="password123", role=Role.DRIVER):
    with app.app_context():
        user = User(username=username, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def login(client, username, password="password123"):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


def make_reservation(
    app,
    facility_id,
    bay_id,
    registration="MH-01 TEST 0001",
    vehicle_type="car",
    start=None,
    end=None,
    status=ReservationStatus.BOOKED,
    mode="advance",
    user_id=None,
    entry=None,
):
    """Insert a reservation row directly (for state-specific tests)."""
    from services.tokens import new_reservation_code, new_ticket_code

    start = start or (datetime.now() + timedelta(hours=2))
    end = end or (start + timedelta(hours=2))
    with app.app_context():
        res = Reservation(
            reservation_code=new_reservation_code(),
            ticket_code=new_ticket_code(),
            facility_id=facility_id,
            bay_id=bay_id,
            user_id=user_id,
            vehicle_registration=registration,
            vehicle_type=vehicle_type,
            mode=mode,
            status=status,
            start_time=start,
            end_time=end,
            entry_timestamp=entry,
        )
        db.session.add(res)
        bay = db.session.get(ParkingBay, bay_id)
        if status == ReservationStatus.CHECKED_IN:
            bay.status = BayStatus.OCCUPIED
        elif status == ReservationStatus.BOOKED and bay.status == BayStatus.VACANT:
            bay.status = BayStatus.RESERVED
        db.session.commit()
        return res.id


def reservation_by_id(app, reservation_id):
    with app.app_context():
        res = db.session.get(Reservation, reservation_id)
        db.session.refresh(res)
        return {
            "id": res.id,
            "status": res.status,
            "ticket": res.ticket_code,
            "code": res.reservation_code,
            "bay_id": res.bay_id,
            "registration": res.vehicle_registration,
            "entry": res.entry_timestamp,
            "exit": res.exit_timestamp,
        }


def bay_status(app, bay_id):
    with app.app_context():
        return db.session.get(ParkingBay, bay_id).status


def next_window(offset_hours=3, duration_hours=2):
    start = (datetime.now() + timedelta(hours=offset_hours)).replace(
        second=0, microsecond=0
    )
    return start, start + timedelta(hours=duration_hours)
