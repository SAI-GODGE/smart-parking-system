"""Individual parking bay (slot) model."""

from datetime import datetime

from extensions import db

from .constants import BayStatus


class ParkingBay(db.Model):
    __tablename__ = "parking_bays"
    __table_args__ = (
        db.UniqueConstraint(
            "facility_id", "floor", "zone", "slot_number", name="uq_bay_position"
        ),
        db.Index("ix_bay_facility_status", "facility_id", "status"),
    )

    id = db.Column(db.Integer, primary_key=True)
    facility_id = db.Column(
        db.Integer,
        db.ForeignKey("parking_facilities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slot_number = db.Column(db.String(20), nullable=False)
    floor = db.Column(db.Integer, nullable=False, default=0)
    zone = db.Column(db.String(20), nullable=False, default="A")
    vehicle_type = db.Column(db.String(20), nullable=False, default="any")
    status = db.Column(
        db.String(20),
        nullable=False,
        default=BayStatus.VACANT,
        index=True,
    )
    distance_from_gate = db.Column(db.Integer, nullable=False, default=20)
    is_accessible = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    facility = db.relationship("ParkingFacility", back_populates="bays")

    @property
    def label(self):
        return f"{self.zone}-{self.slot_number}"

    @property
    def status_label(self):
        return BayStatus.LABELS.get(self.status, self.status)

    @property
    def short_status_label(self):
        return BayStatus.SHORT_LABELS.get(self.status, self.status)

    @property
    def vehicle_type_label(self):
        from .constants import VehicleType

        return VehicleType.LABELS.get(self.vehicle_type, self.vehicle_type)

    def supports(self, vehicle_type):
        """True when this bay can accept the requested vehicle type."""
        return self.vehicle_type in ("any", vehicle_type)

    def __repr__(self):  # pragma: no cover - debugging helper
        return f"<ParkingBay {self.label} {self.status}>"
