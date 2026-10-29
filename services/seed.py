"""Sample data so the application is usable immediately after setup.

Sample data is only written when the database contains no parking
facilities, so it is never duplicated on application startup.
"""

import random
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from extensions import db
from models import (
    BayStatus,
    ParkingBay,
    ParkingFacility,
    Reservation,
    ReservationStatus,
    Role,
    User,
    VehicleType,
)
from services.tokens import new_reservation_code, new_ticket_code

FACILITY_SPECS = [
    {
        "name": "City Central Mall Parking",
        "location_description": "MG Road, opposite the City Central Mall",
        "address": "MG Road, Chhatrapati Sambhajinagar, Maharashtra 431001",
        "parking_type": "Covered multi-level mall parking",
        "hourly_rate": 40.0,
        "default_duration_hours": 4,
        "floors": {0: ["A", "B"], 1: ["C", "D"]},
        "bays_per_zone": 8,
    },
    {
        "name": "Railway Station Multi-Level Parking",
        "location_description": "Beside the main railway station entrance",
        "address": "Station Road, Chhatrapati Sambhajinagar, Maharashtra 431001",
        "parking_type": "Open multi-storey long-stay parking",
        "hourly_rate": 30.0,
        "default_duration_hours": 8,
        "floors": {0: ["A"], 1: ["B"], 2: ["C"]},
        "bays_per_zone": 10,
    },
    {
        "name": "Hospital Main Gate Parking",
        "location_description": "Near the casualty gate of the civil hospital",
        "address": "Central Avenue, Chhatrapati Sambhajinagar, Maharashtra 431001",
        "parking_type": "Ground-level visitor parking with accessible bays",
        "hourly_rate": 25.0,
        "default_duration_hours": 4,
        "floors": {0: ["A", "B"]},
        "bays_per_zone": 9,
    },
]

DEMO_USERS = [
    ("demo", "demo1234", Role.DRIVER, "demo@example.com"),
    ("operator", "operator1234", Role.OPERATOR, "operator@example.com"),
]


def _vehicle_mix(index, rnd):
    """Deterministic mix of bay vehicle types."""
    if index % 9 == 4:
        return VehicleType.BIKE
    if index % 13 == 7:
        return VehicleType.EV
    if index % 11 == 6:
        return VehicleType.VAN
    if index % 5 == 2:
        return VehicleType.CAR
    return VehicleType.ANY


def _status_mix(index, rnd):
    if index % 23 == 11:
        return BayStatus.MAINTENANCE
    if index % 5 == 3:
        return BayStatus.OCCUPIED
    if index % 7 == 5:
        return BayStatus.RESERVED
    return BayStatus.VACANT


def seed_if_empty():
    """Create sample facilities, bays and demo accounts when the DB is empty."""
    if ParkingFacility.query.first() is not None:
        return False
    seed()
    return True


def seed():
    rnd = random.Random(20261028)
    now = datetime.now()

    users = {}
    for username, password, role, email in DEMO_USERS:
        user = User(
            username=username,
            email=email,
            role=role,
            password_hash=generate_password_hash(password),
        )
        db.session.add(user)
        users[username] = user
    db.session.flush()

    sequence = 100
    for spec in FACILITY_SPECS:
        facility = ParkingFacility(
            name=spec["name"],
            location_description=spec["location_description"],
            address=spec["address"],
            parking_type=spec["parking_type"],
            hourly_rate=spec["hourly_rate"],
            default_duration_hours=spec["default_duration_hours"],
            is_active=True,
        )
        db.session.add(facility)
        db.session.flush()

        index = 0
        for floor, zones in spec["floors"].items():
            for zone in zones:
                for n in range(1, spec["bays_per_zone"] + 1):
                    index += 1
                    sequence += 1
                    status = _status_mix(index, rnd)
                    bay = ParkingBay(
                        facility_id=facility.id,
                        slot_number=f"{n:02d}",
                        floor=floor,
                        zone=zone,
                        vehicle_type=_vehicle_mix(index, rnd),
                        status=BayStatus.VACANT,
                        distance_from_gate=10 + floor * 15 + n * 4 + rnd.randint(0, 5),
                        is_accessible=(floor == 0 and n <= 2),
                    )
                    if status == BayStatus.MAINTENANCE:
                        bay.status = BayStatus.MAINTENANCE
                    db.session.add(bay)
                    db.session.flush()

                    if status == BayStatus.OCCUPIED:
                        _add_demo_reservation(
                            facility, bay, users["operator"], sequence,
                            mode="quick", now=now, status=ReservationStatus.CHECKED_IN,
                        )
                        bay.status = BayStatus.OCCUPIED
                    elif status == BayStatus.RESERVED:
                        _add_demo_reservation(
                            facility, bay, users["demo"], sequence,
                            mode="advance", now=now, status=ReservationStatus.BOOKED,
                        )
                        bay.status = BayStatus.RESERVED

    db.session.commit()

def _add_demo_reservation(facility, bay, user, sequence, mode, now, status):
    letters = "ABCDEFGH"
    reg = (
        f"MH-{sequence % 12 + 11:02d} "
        f"{letters[sequence % 8]}{letters[(sequence // 3) % 8]} "
        f"{sequence:04d}"
    )
    if status == ReservationStatus.CHECKED_IN:
        start = now - timedelta(hours=1)
        end = start + timedelta(hours=3)
        entry = now - timedelta(minutes=45)
        exit_ts = None
    else:
        start = now + timedelta(hours=2)
        end = start + timedelta(hours=3)
        entry = None
        exit_ts = None

    db.session.add(
        Reservation(
            reservation_code=new_reservation_code(),
            ticket_code=new_ticket_code(),
            facility_id=facility.id,
            bay_id=bay.id,
            user_id=user.id if user else None,
            vehicle_registration=reg,
            vehicle_type=bay.vehicle_type
            if bay.vehicle_type != VehicleType.ANY
            else VehicleType.CAR,
            mode=mode,
            status=status,
            start_time=start,
            end_time=end,
            entry_timestamp=entry,
            exit_timestamp=exit_ts,
            created_at=now,
        )
    )
