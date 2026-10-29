"""Parking facility model."""

from datetime import datetime

from extensions import db


class ParkingFacility(db.Model):
    __tablename__ = "parking_facilities"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False, index=True)
    location_description = db.Column(db.String(255), nullable=False, default="")
    address = db.Column(db.String(255), nullable=False, default="")
    parking_type = db.Column(db.String(80), nullable=False, default="General parking")
    hourly_rate = db.Column(db.Float, nullable=False, default=40.0)
    hold_minutes = db.Column(db.Integer, nullable=False, default=0)
    default_duration_hours = db.Column(db.Integer, nullable=False, default=4)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    bays = db.relationship(
        "ParkingBay",
        back_populates="facility",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    reservations = db.relationship("Reservation", back_populates="facility")

    @property
    def hold_minutes_effective(self):
        return self.hold_minutes if self.hold_minutes > 0 else None

    @property
    def bay_count(self):
        return self.bays.count()

    def __repr__(self):  # pragma: no cover - debugging helper
        return f"<ParkingFacility {self.name}>"
