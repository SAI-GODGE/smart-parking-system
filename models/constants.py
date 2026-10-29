"""Shared status constants for the parking models."""


class BayStatus:
    VACANT = "vacant"
    RESERVED = "reserved"
    OCCUPIED = "occupied"
    MAINTENANCE = "maintenance"
    ALL = (VACANT, RESERVED, OCCUPIED, MAINTENANCE)
    LABELS = {
        VACANT: "Vacant",
        RESERVED: "Reserved",
        OCCUPIED: "Occupied",
        MAINTENANCE: "Maintenance",
    }
    SHORT_LABELS = {
        VACANT: "Free",
        RESERVED: "Held",
        OCCUPIED: "Taken",
        MAINTENANCE: "Closed",
    }


class ReservationStatus:
    BOOKED = "booked"
    CHECKED_IN = "checked_in"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    ACTIVE = (BOOKED, CHECKED_IN)
    ALL = (BOOKED, CHECKED_IN, COMPLETED, CANCELLED, EXPIRED)
    LABELS = {
        BOOKED: "Booked",
        CHECKED_IN: "Parked",
        COMPLETED: "Completed",
        CANCELLED: "Cancelled",
        EXPIRED: "Expired",
    }


class Role:
    DRIVER = "driver"
    OPERATOR = "operator"
    ADMIN = "admin"
    ALL = (DRIVER, OPERATOR, ADMIN)
    LABELS = {
        DRIVER: "Driver",
        OPERATOR: "Parking Operator",
        ADMIN: "Administrator",
    }


class VehicleType:
    CAR = "car"
    BIKE = "bike"
    VAN = "van"
    EV = "ev"
    ANY = "any"
    ALL = (CAR, BIKE, VAN, EV, ANY)
    BOOKABLE = (CAR, BIKE, VAN, EV)
    LABELS = {
        CAR: "Car",
        BIKE: "Motorbike",
        VAN: "Van / SUV",
        EV: "Electric vehicle",
        ANY: "Any vehicle",
    }


class BookingMode:
    ADVANCE = "advance"
    QUICK = "quick"
    ALL = (ADVANCE, QUICK)
