"""Operator and administrator workflows over HTTP."""

import re
from datetime import datetime, timedelta

from extensions import db
from models import BayStatus, ParkingFacility, Reservation, ReservationStatus, Role, User

from .conftest import (
    bay_ids,
    create_facility,
    create_user,
    login,
    make_reservation,
    next_window,
    set_bay_status,
)


def _flashes(html):
    return " ".join(
        f.strip()
        for f in re.findall(
            r"alert alert-\w+[^>]*>\s*<i[^>]*></i>\s*([^<]+)", html
        )
    )


def test_operator_can_check_in_and_check_out(app, client):
    create_user(app, "staffer", password="operatorpass", role="operator")
    fid = create_facility(app, "Staff Lot")
    bays = bay_ids(app, fid)
    start, end = next_window()
    res_id = make_reservation(
        app, fid, bays[0], registration="MH-50 STAF 5050", start=start, end=end
    )

    login(client, "staffer", password="operatorpass")
    page = client.get("/operator/")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "MH-50 STAF 5050" in html

    token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    # Check in from the operator panel.
    response = client.post(
        f"/operator/checkin/{res_id}",
        data={"csrf_token": token},
        follow_redirects=True,
    )
    assert "recorded as parked" in _flashes(response.get_data(as_text=True))
    with app.app_context():
        res = db.session.get(Reservation, res_id)
        assert res.status == ReservationStatus.CHECKED_IN
        assert res.bay.status == BayStatus.OCCUPIED

    # Check out from the operator panel.
    page = client.get("/operator/")
    html = page.get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    response = client.post(
        f"/operator/checkout/{res_id}",
        data={"csrf_token": token},
        follow_redirects=True,
    )
    assert "Checked out" in _flashes(response.get_data(as_text=True))
    with app.app_context():
        res = db.session.get(Reservation, res_id)
        assert res.status == ReservationStatus.COMPLETED
        assert res.exit_timestamp is not None
        assert res.bay.status == BayStatus.VACANT


def test_operator_ticket_search(app, client):
    create_user(app, "searcher", password="operatorpass", role="operator")
    fid = create_facility(app, "Search Lot")
    bays = bay_ids(app, fid)
    start, end = next_window()
    res_id = make_reservation(
        app, fid, bays[0], registration="MH-51 SRCH 5151", start=start, end=end
    )
    with app.app_context():
        ticket = db.session.get(Reservation, res_id).ticket_code

    login(client, "searcher", password="operatorpass")
    response = client.get(f"/operator/?q={ticket}")
    html = response.get_data(as_text=True)
    assert "MH-51 SRCH 5151" in html
    assert "Check in" in html

    response = client.get("/operator/?q=PK-DOESNOTEXIST")
    assert "No ticket found" in response.get_data(as_text=True)


def test_admin_facility_and_bay_management(app, client):
    create_user(app, "rootadmin", password="adminpass1", role="admin")
    login(client, "rootadmin", password="adminpass1")

    # Create a facility.
    response = client.post(
        "/admin/facilities/new",
        data={
            "name": "Managed Lot",
            "location_description": "Somewhere",
            "address": "42 Road",
            "parking_type": "Street parking",
            "hourly_rate": "35",
            "default_duration_hours": "3",
            "hold_minutes": "25",
        },
        follow_redirects=True,
    )
    assert "Now add parking spaces" in _flashes(response.get_data(as_text=True))
    with app.app_context():
        facility = ParkingFacility.query.filter_by(name="Managed Lot").one()
        fid = facility.id

    # Add a bay.
    response = client.post(
        f"/admin/facilities/{fid}/bays/new",
        data={
            "slot_number": "01",
            "floor": "0",
            "zone": "A",
            "vehicle_type": "ev",
            "status": "vacant",
            "distance_from_gate": "12",
            "is_accessible": "1",
        },
        follow_redirects=True,
    )
    assert "added" in _flashes(response.get_data(as_text=True)).lower()
    with app.app_context():
        from models import ParkingBay

        bay = ParkingBay.query.filter_by(facility_id=fid, slot_number="01").one()
        bay_id = bay.id
        assert bay.vehicle_type == "ev"
        assert bay.is_accessible is True

    # Edit the bay and close it for maintenance.
    response = client.post(
        f"/admin/bays/{bay_id}/edit",
        data={
            "slot_number": "01",
            "floor": "0",
            "zone": "A",
            "vehicle_type": "ev",
            "status": "vacant",
            "distance_from_gate": "18",
        },
        follow_redirects=True,
    )
    assert "updated" in _flashes(response.get_data(as_text=True))

    response = client.post(
        f"/admin/bays/{bay_id}/status",
        data={"target": "maintenance"},
        follow_redirects=True,
    )
    assert "closed for maintenance" in _flashes(response.get_data(as_text=True))

    # It disappears from driver availability as bookable.
    api = client.get(f"/api/facilities/{fid}/availability").get_json()
    bay_row = [b for b in api["bays"] if b["id"] == bay_id][0]
    assert bay_row["status"] == BayStatus.MAINTENANCE
    assert bay_row["bookable"] is False

    # Restore it to service.
    response = client.post(
        f"/admin/bays/{bay_id}/status",
        data={"target": "service"},
        follow_redirects=True,
    )
    assert "returned to service" in _flashes(response.get_data(as_text=True))


def test_admin_can_view_reservations_and_users(app, client):
    create_user(app, "superroot", password="adminpass1", role="admin")
    fid = create_facility(app, "Visible Lot")
    bays = bay_ids(app, fid)
    start, end = next_window()
    make_reservation(
        app, fid, bays[0], registration="MH-52 ADMS 5252", start=start, end=end
    )

    login(client, "superroot", password="adminpass1")

    response = client.get("/admin/reservations")
    assert response.status_code == 200
    assert "MH-52 ADMS 5252" in response.get_data(as_text=True)

    response = client.get("/admin/reservations?status=booked")
    assert "MH-52 ADMS 5252" in response.get_data(as_text=True)

    response = client.get("/admin/reservations?status=completed")
    assert "MH-52 ADMS 5252" not in response.get_data(as_text=True)

    response = client.get("/admin/users")
    assert response.status_code == 200
    assert "superroot" in response.get_data(as_text=True)


def test_driver_is_not_offered_admin_links(app, client):
    """Drivers must not be pointed at administrator actions anywhere."""
    create_user(app, "nodriver")
    login(client, "nodriver")
    html = client.get("/").get_data(as_text=True)
    nav = html.split("</nav>")[0]
    assert 'href="/admin' not in nav
    assert 'href="/operator' not in nav
    assert "Administrator" not in nav


def test_admin_can_view_user_history(app, client):
    """Admin can view the full booking history of any user."""
    admin_id = create_user(app, "rootadmin", role=Role.ADMIN)
    customer_id = create_user(app, "targetcustomer", role=Role.DRIVER)
    fid = create_facility(app, "History Lot")
    bays = bay_ids(app, fid)
    start, end = next_window()

    make_reservation(
        app,
        fid,
        bays[0],
        registration="MH-88 HIST 8888",
        start=start,
        end=end,
        user_id=customer_id,
    )

    login(client, "rootadmin")
    response = client.get(f"/admin/users/{customer_id}/history")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "targetcustomer" in html
    assert "MH-88 HIST 8888" in html
    assert "History Lot" in html
