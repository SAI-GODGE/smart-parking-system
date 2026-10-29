"""TC group 1: application startup and database initialisation."""

from extensions import db
from models import (
    BayStatus,
    ParkingBay,
    ParkingFacility,
    ParkingTransaction,
    Reservation,
    User,
)

from .conftest import create_facility


def test_app_starts_and_creates_tables(app):
    assert app is not None
    assert app.config["TESTING"] is True
    inspector_tables = db.inspect(db.engine).get_table_names()
    for table in (
        "users",
        "parking_facilities",
        "parking_bays",
        "reservations",
        "parking_transactions",
    ):
        assert table in inspector_tables, f"missing table: {table}"


def test_database_starts_empty_without_seeding(app):
    with app.app_context():
        assert ParkingFacility.query.count() == 0
        assert User.query.count() == 0
        assert Reservation.query.count() == 0


def test_seed_runs_only_once(app):
    """Sample data must never be duplicated on startup."""
    from services.seed import seed_if_empty

    with app.app_context():
        assert seed_if_empty() is True
        first_count = ParkingFacility.query.count()
        assert first_count > 0
        assert seed_if_empty() is False
        assert ParkingFacility.query.count() == first_count


def test_home_page_renders_two_modes(app, client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Smart Parking Management System" in html
    assert "Find a parking space. Book with ease. Park with confidence." in html
    assert "Book in Advance" in html
    assert "Quick Parking" in html
    assert "Book Parking" in html
    assert "Find Parking Now" in html


def test_bay_status_values_are_known(app, client):
    fid = create_facility(app, "Status Facility")
    response = client.get(f"/api/facilities/{fid}/availability")
    assert response.status_code == 200
    for bay in response.get_json()["bays"]:
        assert bay["status"] in BayStatus.ALL
