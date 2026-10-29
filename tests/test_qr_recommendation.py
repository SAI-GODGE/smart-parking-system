"""QR code routing, generation and the recommendation algorithm."""

from services.qr import facility_public_url, generate_qr_png
from services.recommendation import recommend_slot, score_bay


def _bay(bid, distance, floor=0, zone="A", vehicle="any", accessible=False, bookable=True):
    return {
        "id": bid,
        "label": f"{zone}-{bid:02d}",
        "number": f"{bid:02d}",
        "floor": floor,
        "zone": zone,
        "status": "vacant",
        "bookable": bookable,
        "vehicle_type": vehicle,
        "accessible": accessible,
        "distance": distance,
    }


def test_facility_qr_route_opens_the_correct_facility(app, client):
    from .conftest import create_facility

    fid_a = create_facility(app, "Alpha Parking")
    fid_b = create_facility(app, "Beta Parking")

    response_a = client.get(f"/parking/facility/{fid_a}")
    response_b = client.get(f"/parking/facility/{fid_b}")
    assert response_a.status_code == 200
    assert response_b.status_code == 200
    assert "Alpha Parking" in response_a.get_data(as_text=True)
    assert "Beta Parking" not in response_a.get_data(as_text=True)
    assert "Beta Parking" in response_b.get_data(as_text=True)
    assert "Alpha Parking" not in response_b.get_data(as_text=True)


def test_facility_qr_url_points_to_public_parking_page(app):
    with app.app_context():
        url = facility_public_url(7)
    assert url.endswith("/parking/facility/7")
    assert "/admin" not in url


def test_qr_png_is_generated(app):
    png = generate_qr_png("http://localhost/parking/facility/1")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 200


def test_admin_qr_routes_require_admin(app, client):
    from .conftest import create_facility, create_user, login

    fid = create_facility(app, "Secure QR Lot")
    assert client.get("/admin/qr").status_code == 302
    assert client.get(f"/admin/facility/{fid}/qr.png").status_code == 302

    create_user(app, "notadmin")
    login(client, "notadmin")
    assert client.get("/admin/qr").status_code == 403
    assert client.get(f"/admin/facility/{fid}/qr.png").status_code == 403

    client.post("/logout")
    create_user(app, "realadmin", password="adminpass1", role="admin")
    login(client, "realadmin", password="adminpass1")
    response = client.get(f"/admin/facility/{fid}/qr.png")
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "image/png"


def test_recommendation_picks_closest_compatible_slot():
    candidates = [
        _bay(1, distance=80, vehicle="any"),
        _bay(2, distance=15, vehicle="any"),
        _bay(3, distance=40, vehicle="car"),
    ]
    best, score, reason = recommend_slot(candidates, vehicle_type="car")
    assert best["id"] == 2  # closest overall wins
    assert score is not None
    assert reason.startswith("Recommended because")


def test_recommendation_prefers_exact_vehicle_bay_at_same_distance():
    candidates = [
        _bay(1, distance=30, vehicle="any"),
        _bay(2, distance=30, vehicle="car"),
    ]
    best, _score, _reason = recommend_slot(candidates, vehicle_type="car")
    assert best["id"] == 2  # exact vehicle fit scores better


def test_recommendation_respects_floor_preference():
    candidates = [
        _bay(1, distance=20, floor=0),
        _bay(2, distance=25, floor=1),
    ]
    # No preference -> ground floor naturally scores better.
    best, _score, _reason = recommend_slot(candidates, vehicle_type="car")
    assert best["id"] == 1

    # Prefer floor 1 -> that candidate is chosen when it exists.
    best, _score, _reason = recommend_slot(
        candidates, vehicle_type="car", floor_pref=1
    )
    assert best["id"] == 2


def test_recommendation_never_returns_unbookable_slots():
    candidates = [_bay(1, distance=10, bookable=False)]
    best, score, message = recommend_slot(candidates, vehicle_type="car")
    assert best is None
    assert score is None
    assert "No suitable parking space" in message


def test_scoring_formula_is_documented_and_monotonic():
    """Lower score is better: closer bays must score strictly lower."""
    near = score_bay(_bay(1, distance=10), max_distance=100, max_floor=2)
    far = score_bay(_bay(2, distance=90), max_distance=100, max_floor=2)
    assert near < far

    ground = score_bay(_bay(1, distance=50, floor=0), max_distance=100, max_floor=2)
    upper = score_bay(_bay(2, distance=50, floor=2), max_distance=100, max_floor=2)
    assert ground < upper


def test_accessible_preference_narrows_candidates():
    candidates = [
        _bay(1, distance=10, accessible=False),
        _bay(2, distance=50, accessible=True),
    ]
    # Only the accessible bay is eligible when the user needs one.
    eligible = [b for b in candidates if b["accessible"] or not b["bookable"]]
    filtered = [b for b in candidates if b["accessible"]]
    best, _score, _reason = recommend_slot(filtered, vehicle_type="car")
    assert best["id"] == 2
