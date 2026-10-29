"""Secure code generation for reservations and tickets."""

import secrets


def new_reservation_code():
    """Short human-friendly code shown on the booking, e.g. RS-8F3A21C4."""
    return "RS-" + secrets.token_hex(4).upper()


def new_ticket_code():
    """Unguessable ticket token used for lookup and checkout.

    Only uppercase hexadecimal characters are used so users can type the
    code without worrying about letter case.
    """
    return "PK-" + secrets.token_hex(10).upper()
