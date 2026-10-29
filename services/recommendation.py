"""Slot recommendation algorithm.

The algorithm follows the scoring formula documented in the project report:

    C(Si) = w1 * D(Si) + w2 * F(Si) + w3 * V(Si)

where:
    D = normalised distance from the entrance (0 = closest, 1 = farthest)
    F = floor preference score (lower floors score better; an extra penalty
        is added when the bay is not on the user's preferred floor)
    V = vehicle compatibility score (0 = exact vehicle-type bay, 0.25 = a
        shared "any vehicle" bay)
    w1, w2, w3 = configurable weights (default 0.5, 0.3, 0.2)

The eligible bay with the LOWEST total score is recommended. Eligibility
(maintenance, vehicle compatibility, accessibility, availability for the
chosen time window) is applied before scoring, so an ineligible bay can
never be recommended.
"""

from flask import current_app


def _weights():
    return current_app.config.get(
        "RECOMMENDATION_WEIGHTS",
        {"distance": 0.5, "floor": 0.3, "vehicle": 0.2},
    )


def score_bay(bay, max_distance, max_floor, floor_pref=None, vehicle_type=None, weights=None):
    """Score one eligible bay. Lower is better."""
    weights = weights or _weights()
    d_norm = (bay.get("distance") or 0) / max_distance if max_distance else 0.0
    floor = bay.get("floor") or 0
    f_score = floor / max_floor if max_floor else 0.0
    if floor_pref is not None and floor != floor_pref:
        f_score += 1.0
    if vehicle_type and bay.get("vehicle_type") == vehicle_type:
        v_score = 0.0
    else:
        v_score = 0.25
    total = (
        weights["distance"] * d_norm
        + weights["floor"] * f_score
        + weights["vehicle"] * v_score
    )
    return round(total, 4)


def recommend_slot(candidates, vehicle_type=None, floor_pref=None, zone_pref=None):
    """Return (best_candidate, score, reason) or (None, None, message)."""
    eligible = [b for b in candidates if b.get("bookable")]
    if not eligible:
        return None, None, "No suitable parking space is available for your requirements."

    # Optional preferences narrow the candidates when they can be satisfied.
    if floor_pref is not None:
        on_floor = [b for b in eligible if b.get("floor") == floor_pref]
        if on_floor:
            eligible = on_floor
    if zone_pref:
        in_zone = [b for b in eligible if b.get("zone") == zone_pref]
        if in_zone:
            eligible = in_zone

    if not eligible:
        return None, None, "No space matches your preferred floor or zone. You can pick any free space instead."

    weights = _weights()
    max_distance = max((b.get("distance") or 0) for b in eligible) or 1
    max_floor = max((b.get("floor") or 0) for b in eligible) or 1

    best = None
    best_score = None
    for bay in eligible:
        score = score_bay(bay, max_distance, max_floor, floor_pref, vehicle_type, weights)
        if best_score is None or score < best_score:
            best, best_score = bay, score

    return best, best_score, _explain(best, vehicle_type, floor_pref)


def _explain(bay, vehicle_type, floor_pref):
    """Short, plain-English reason shown next to the recommendation."""
    reasons = ["it is free at your chosen time"]
    if vehicle_type and bay.get("vehicle_type") == vehicle_type:
        reasons.append(f"it fits your {vehicle_type.upper()}")
    elif bay.get("vehicle_type") == "any":
        reasons.append("it accepts your vehicle type")
    if (bay.get("distance") or 0) <= 25:
        reasons.append("it is close to the entrance")
    if bay.get("floor") == 0:
        reasons.append("it is on the ground floor")
    elif floor_pref is not None and bay.get("floor") == floor_pref:
        reasons.append("it is on your preferred floor")
    if bay.get("accessible"):
        reasons.append("it is an accessible space")
    if len(reasons) > 1:
        text = ", ".join(reasons[:-1]) + " and " + reasons[-1]
    else:
        text = reasons[0]
    return f"Recommended because {text}."
