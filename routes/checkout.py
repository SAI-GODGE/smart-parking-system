"""Checkout (leaving the parking facility)."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user

from services.booking import BookingError, checkout as do_checkout

bp = Blueprint("checkout", __name__)


@bp.route("/checkout", methods=["GET", "POST"])
def checkout():
    ticket_prefill = request.args.get("ticket", "") or request.form.get("ticket_code", "")
    if request.method == "POST":
        ticket = request.form.get("ticket_code", "")
        registration = request.form.get("vehicle_registration", "")
        try:
            reservation, duration_minutes, fee = do_checkout(
                ticket,
                vehicle_registration=registration,
                user=current_user if current_user.is_authenticated else None,
            )
        except BookingError as exc:
            flash(exc.user_message, "error")
            return render_template(
                "checkout/form.html", ticket_prefill=ticket, fee_enabled=None
            )
        return render_template(
            "checkout/done.html",
            reservation=reservation,
            duration_minutes=duration_minutes,
            fee=fee,
        )
    return render_template("checkout/form.html", ticket_prefill=ticket_prefill, fee_enabled=None)
