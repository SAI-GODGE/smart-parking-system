"""TC group 2, 3, 17: authentication, roles and private data access."""

from extensions import db
from models import Reservation, Role, User

from .conftest import (
    bay_ids,
    create_facility,
    create_user,
    login,
    make_reservation,
    next_window,
)


def test_register_and_login(app, client):
    response = client.post(
        "/register",
        data={
            "username": "driver_one",
            "password": "secretpass1",
            "confirm_password": "secretpass1",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Your account is ready" in response.get_data(as_text=True)

    response = client.post(
        "/login",
        data={"username": "driver_one", "password": "secretpass1"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    # A protected page now renders for the signed-in driver.
    response = client.get("/my-bookings")
    assert response.status_code == 200
    assert "My Bookings" in response.get_data(as_text=True)


def test_login_rejects_wrong_password(app, client):
    create_user(app, "bob")
    response = client.post(
        "/login", data={"username": "bob", "password": "wrongpass"}, follow_redirects=True
    )
    assert "Incorrect username or password" in response.get_data(as_text=True)


def test_registration_validates_password_length(app, client):
    response = client.post(
        "/register",
        data={"username": "tiny", "password": "abc", "confirm_password": "abc"},
        follow_redirects=True,
    )
    assert "at least 8 characters" in response.get_data(as_text=True)


def test_admin_requires_admin_role(app, client):
    create_user(app, "regular", role=Role.DRIVER)
    create_user(app, "helper", role=Role.OPERATOR)

    # Anonymous users are redirected to login.
    response = client.get("/admin/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]

    # Drivers and operators are forbidden.
    login(client, "regular")
    assert client.get("/admin/").status_code == 403

    client.post("/logout")
    login(client, "helper")
    assert client.get("/admin/").status_code == 403


def test_operator_panel_requires_operator_role(app, client):
    create_user(app, "plain_driver", role=Role.DRIVER)
    login(client, "plain_driver")
    assert client.get("/operator/").status_code == 403


def test_admin_dashboard_renders_for_admin(app, client):
    create_user(app, "boss", password="adminpass1", role=Role.ADMIN)
    login(client, "boss", password="adminpass1")
    response = client.get("/admin/")
    assert response.status_code == 200
    assert "Administrator Dashboard" in response.get_data(as_text=True)


def test_user_cannot_cancel_another_users_reservation(app, client):
    owner_id = create_user(app, "owner")
    fid = create_facility(app, "Private Lot")
    bays = bay_ids(app, fid)
    start, end = next_window()
    res_id = make_reservation(
        app, fid, bays[0], registration="MH-99 PRIV 9999",
        start=start, end=end, user_id=owner_id,
    )

    # An unrelated signed-in driver must not cancel it.
    create_user(app, "intruder")
    login(client, "intruder")
    response = client.post(
        f"/my-bookings/{res_id}/cancel", follow_redirects=True
    )
    assert response.status_code == 403

    # And it does not show up in their booking list.
    response = client.get("/my-bookings")
    assert "MH-99 PRIV 9999" not in response.get_data(as_text=True)

    # Anonymous users are redirected to login.
    client.post("/logout")
    response = client.post(f"/my-bookings/{res_id}/cancel")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_owner_sees_and_cancels_own_reservation(app, client):
    owner_id = create_user(app, "mine")
    fid = create_facility(app, "Owner Lot")
    bays = bay_ids(app, fid)
    start, end = next_window()
    res_id = make_reservation(
        app, fid, bays[0], registration="MH-77 MINE 7777",
        start=start, end=end, user_id=owner_id,
    )
    login(client, "mine")

    response = client.get("/my-bookings")
    assert "MH-77 MINE 7777" in response.get_data(as_text=True)

    response = client.post(f"/my-bookings/{res_id}/cancel", follow_redirects=True)
    assert "cancelled and the space is free again" in response.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(Reservation, res_id).status == "cancelled"
