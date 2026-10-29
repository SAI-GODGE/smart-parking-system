"""Reservation and parking transaction models."""

from datetime import datetime

from extensions import db

from .constants import BookingMode, ReservationStatus


class Reservation(db.Model):
    __tablename__ = "reservations"
    __table_args__ = (
        db.Index("ix_res_bay_status", "bay_id", "status"),
        db.Index("ix_res_user_status", "user_id", "status"),
        db.Index("ix_res_facility_status", "facility_id", "status"),
        db.Index("ix_res_window", "bay_id", "start_time", "end_time"),
    )

    id = db.Column(db.Integer, primary_key=True)
    reservation_code = db.Column(db.String(30), unique=True, nullable=False, index=True)
    ticket_code = db.Column(db.String(40), unique=True, nullable=False, index=True)

    facility_id = db.Column(
        db.Integer,
        db.ForeignKey("parking_facilities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bay_id = db.Column(
        db.Integer,
        db.ForeignKey("parking_bays.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    vehicle_registration = db.Column(db.String(20), nullable=False, index=True)
    vehicle_type = db.Column(db.String(20), nullable=False)
    mode = db.Column(db.String(20), nullable=False, default=BookingMode.ADVANCE)
    status = db.Column(
        db.String(20),
        nullable=False,
        default=ReservationStatus.BOOKED,
        index=True,
    )

    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    entry_timestamp = db.Column(db.DateTime, nullable=True)
    exit_timestamp = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    facility = db.relationship("ParkingFacility", back_populates="reservations")
    bay = db.relationship("ParkingBay")
    user = db.relationship("User", back_populates="reservations")
    transaction = db.relationship(
        "ParkingTransaction", back_populates="reservation", uselist=False
    )

    @property
    def status_label(self):
        return ReservationStatus.LABELS.get(self.status, self.status)

    @property
    def mode_label(self):
        return "Advance booking" if self.mode == BookingMode.ADVANCE else "Quick parking"

    @property
    def bay_label(self):
        return self.bay.label if self.bay else "-"

    @property
    def duration_minutes(self):
        if self.entry_timestamp and self.exit_timestamp:
            delta = self.exit_timestamp - self.entry_timestamp
            return max(0, int(delta.total_seconds() // 60))
        return 0

    def is_active(self):
        return self.status in ReservationStatus.ACTIVE

    def __repr__(self):  # pragma: no cover - debugging helper
        return f"<Reservation {self.reservation_code} {self.status}>"


class ParkingTransaction(db.Model):
    """Fee calculation record. No payment gateway is integrated."""

    __tablename__ = "parking_transactions"

    id = db.Column(db.Integer, primary_key=True)
    reservation_id = db.Column(
        db.Integer,
        db.ForeignKey("reservations.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    duration_minutes = db.Column(db.Integer, nullable=False, default=0)
    rate_per_hour = db.Column(db.Float, nullable=False, default=0.0)
    amount = db.Column(db.Float, nullable=False, default=0.0)
    status = db.Column(db.String(20), nullable=False, default="calculated")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    reservation = db.relationship("Reservation", back_populates="transaction")

    def __repr__(self):  # pragma: no cover - debugging helper
        return f"<ParkingTransaction {self.id} {self.amount}>"
