"""TC group 15, 16: dashboard counts and public-page privacy."""

import re
from datetime import datetime, timedelta

from sqlalchemy import func

from extensions import db
from models import BayStatus, ParkingBay, Reservation, ReservationStatus
from services.availability import facility_counts, global_counts

from .conftest import (
    bay_ids,
    create_facility,
    make_reservation,
    next_window,
    set_bay_status,
)


def _mixed_facility(app):
    fid = create_facility(app, "Counted Lot", bays=10)
    bays = bay_ids(app, fid)
    set_bay_status(app, bays[0], BayStatus.MAINTENANCE)
    set_bay_status(app, bays[1], BayStatus.MAINTENANCE)
    make_reservation(
        app, fid, bays[2], registration="MH-40 CNTA 4040",
        status=ReservationStatus.CHECKED_IN,
        start=datetime.now() - timedelta(hours=1),
        end=datetime.now() + timedelta(hours=1),
        entry=datetime.now() - timedelta(minutes=30),
    )
    start, end = next_window()
    make_reservation(
        app, fid, bays[3], registration="MH-41 CNTB 4141",
        start=start, end=end,
    )
    return fid, bays


def test_api_counts_match_database_records(app, client):
    fid, _bays = _mixed_facility(app)

    response = client.get(f"/api/facilities/{fid}/availability")
    assert response.status_code == 200
    counts = response.get_json()["counts"]

    with app.app_context():
        rows = (
            db.session.query(ParkingBay.status, func.count(ParkingBay.id))
            .filter(ParkingBay.facility_id == fid)
            .group_by(ParkingBay.status)
            .all()
        )
    expected = dict(rows)
    assert counts["vacant"] == expected.get("vacant", 0)
    assert counts["maintenance"] == expected.get("maintenance", 0)
    assert counts["occupied"] == expected.get("occupied", 0)
    assert counts["reserved"] == expected.get("reserved", 0)
    assert counts["total"] == sum(counts[s] for s in BayStatus.ALL)


def test_admin_dashboard_shows_database_totals(app, client):
    from .conftest import create_user, login

    _mixed_facility(app)
    create_user(app, "counter", password="adminpass1", role="admin")
    login(client, "counter", password="adminpass1")

    response = client.get("/admin/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    counts = global_counts()
    # The dashboard must render the real total computed from the database.
    assert f">{counts['total']}</div>" in html
    assert f">{counts['vacant']}</div>" in html
    assert f">{counts['maintenance']}</div>" in html


def test_facility_cards_show_recorded_availability(app, client):
    fid, _bays = _mixed_facility(app)
    response = client.get("/facilities")
    html = response.get_data(as_text=True)
    counts = facility_counts(fid)
    assert "Counted Lot" in html
    assert f"{counts['vacant']} free" in html


def test_public_pages_do_not_expose_vehicle_registrations(app, client):
    fid, bays = _mixed_facility(app)
    secret_reg = "MH-66 SPYX 6666"
    start, end = next_window()
    make_reservation(app, fid, bays[4], registration=secret_reg, start=start, end=end)
    make_reservation(
        app, fid, bays[5], registration="MH-67 SPYY 6767",
        status=ReservationStatus.CHECKED_IN,
        start=datetime.now() - timedelta(hours=1),
        end=datetime.now() + timedelta(hours=2),
        entry=datetime.now() - timedelta(minutes=20),
    )

    public_pages = [
        "/",
        "/facilities",
        f"/parking/facility/{fid}",
        f"/api/facilities/{fid}/availability",
        "/how-it-works",
        "/book",
    ]
    for path in public_pages:
        html = client.get(path).get_data(as_text=True)
        assert "MH-66 SPYX 6666" not in html, f"sensitive data leaked on {path}"
        assert "MH-67 SPYY 6767" not in html, f"sensitive data leaked on {path}"


def test_public_api_exposes_only_slot_status(app, client):
    fid, bays = _mixed_facility(app)
    response = client.get(f"/api/facilities/{fid}/availability")
    data = response.get_json()
    allowed_keys = {
        "id", "number", "label", "floor", "zone", "status",
        "bookable", "vehicle_type", "accessible", "distance",
    }
    for bay in data["bays"]:
        assert set(bay.keys()) <= allowed_keys


def test_unknown_facility_returns_404(app, client):
    assert client.get("/parking/facility/9999").status_code == 404
    assert client.get("/api/facilities/9999/availability").status_code == 404
