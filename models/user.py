"""User account model."""

from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db

from .constants import Role


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=Role.DRIVER, index=True)
    account_status = db.Column(db.String(20), nullable=False, default="active")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    reservations = db.relationship("Reservation", back_populates="user", lazy="dynamic")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):
        """Flask-Login account flag (not parking-related)."""
        return self.account_status == "active"

    @property
    def is_admin(self):
        return self.role == Role.ADMIN

    @property
    def is_operator(self):
        return self.role in (Role.OPERATOR, Role.ADMIN)

    @property
    def display_role(self):
        return Role.LABELS.get(self.role, self.role)

    def __repr__(self):  # pragma: no cover - debugging helper
        return f"<User {self.username} ({self.role})>"
