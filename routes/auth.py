"""Registration, login and logout."""

import re

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from extensions import db
from models import Role, User

bp = Blueprint("auth", __name__)

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")


def _safe_next(target):
    """Only allow local redirect targets after login."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return None


def _find_user(username):
    from sqlalchemy import func

    return User.query.filter(func.upper(User.username) == username.upper()).first()


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip() or None
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm_password") or ""

        if not USERNAME_RE.match(username):
            flash(
                "Username must be 3-32 characters and may only contain letters, numbers and underscores.",
                "error",
            )
        elif email and ("@" not in email or len(email) > 120):
            flash("Please enter a valid email address.", "error")
        elif len(password) < 8:
            flash("Your password must be at least 8 characters long.", "error")
        elif password != confirm:
            flash("The two passwords do not match.", "error")
        elif _find_user(username) is not None:
            flash("That username is already taken. Please choose another one.", "error")
        else:
            user = User(username=username, email=email, role=Role.DRIVER)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash("Your account is ready. Please sign in to continue.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = _find_user(username)
        if user is None or not user.check_password(password):
            flash("Incorrect username or password. Please try again.", "error")
        elif not user.is_active:
            flash("This account has been disabled. Please contact the administrator.", "error")
        else:
            login_user(user, remember=bool(request.form.get("remember")))
            next_url = _safe_next(request.args.get("next"))
            return redirect(next_url or url_for("main.index"))
    return render_template("auth/login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been signed out.", "success")
    return redirect(url_for("main.index"))
