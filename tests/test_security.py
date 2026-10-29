"""Security and reliability checks: CSRF, safe errors, session handling."""

import re

from app import create_app


def test_csrf_protects_post_requests_when_enabled(tmp_path):
    """With CSRF enabled (production default) token-less POSTs are refused."""
    db_file = tmp_path / "csrf.db"
    application = create_app(
        {
            "TESTING": True,
            "WTF_CSRF_ENABLED": True,
            "SEED_ON_START": False,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_file.as_posix()}",
        }
    )
    with application.app_context():
        from extensions import db

        db.create_all()

    client = application.test_client()
    response = client.post(
        "/login", data={"username": "anyone", "password": "anything"}
    )
    assert response.status_code == 400

    # A login page does render and includes the CSRF token.
    page = client.get("/login")
    assert page.status_code == 200
    assert re.search(r'name="csrf_token" value="[^"]+"', page.get_data(as_text=True))


def test_missing_pages_show_safe_error_templates(app, client):
    response = client.get("/does-not-exist-at-all")
    assert response.status_code == 404
    html = response.get_data(as_text=True)
    assert "could not find that page" in html
    assert "Traceback" not in html
    assert "File \"" not in html


def test_forbidden_page_shows_safe_message(app, client):
    from .conftest import create_user, login

    create_user(app, "plainjane")
    login(client, "plainjane")
    response = client.get("/admin/")
    assert response.status_code == 403
    html = response.get_data(as_text=True)
    assert "do not have access" in html
    assert "Traceback" not in html


def test_login_next_parameter_cannot_redirect_offsite(app, client):
    from .conftest import create_user

    create_user(app, "safeuser")
    response = client.post(
        "/login?next=https://evil.example.com/phish",
        data={"username": "safeuser", "password": "password123"},
    )
    assert response.status_code == 302
    location = response.headers["Location"]
    assert "evil.example.com" not in location

    client.post("/logout")
    response = client.post(
        "/login?next=//evil.example.com",
        data={"username": "safeuser", "password": "password123"},
    )
    assert "evil.example.com" not in response.headers.get("Location", "/")


def test_passwords_are_stored_hashed(app):
    from werkzeug.security import check_password_hash

    from extensions import db
    from models import Role, User

    with app.app_context():
        user = User(username="hashed", role=Role.DRIVER)
        user.set_password("plainpassword1")
        db.session.add(user)
        db.session.commit()
        stored = db.session.get(User, user.id).password_hash
        assert "plainpassword1" not in stored
        assert stored.startswith(("scrypt:", "pbkdf2:"))
        assert check_password_hash(stored, "plainpassword1")
        assert not check_password_hash(stored, "wrongpassword")


def test_disabled_account_cannot_log_in(app, client):
    from extensions import db
    from models import Role, User

    with app.app_context():
        user = User(username="disabled1", role=Role.DRIVER)
        user.set_password("password123")
        user.account_status = "disabled"
        db.session.add(user)
        db.session.commit()

    response = client.post(
        "/login",
        data={"username": "disabled1", "password": "password123"},
        follow_redirects=True,
    )
    assert "disabled" in response.get_data(as_text=True).lower()


def test_sql_injection_style_inputs_are_handled(app, client):
    """Quoted/SQL-shaped inputs never break a page or leak errors."""
    response = client.post(
        "/checkout",
        data={"ticket_code": "PK-' OR 1=1--", "vehicle_registration": "' OR 1=1--"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "No parking ticket matches" in response.get_data(as_text=True)
    assert "Traceback" not in response.get_data(as_text=True)
