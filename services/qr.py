"""QR code generation for parking facilities.

Each facility has a QR code that opens its own mobile-friendly quick parking
page at:  <BASE_URL>/parking/facility/<facility_id>
"""

import io

import qrcode
from flask import current_app


def facility_public_url(facility_id):
    """Absolute URL of a facility's quick parking page."""
    base = current_app.config.get("BASE_URL", "http://127.0.0.1:5000").rstrip("/")
    return f"{base}/parking/facility/{facility_id}"


def generate_qr_png(url):
    """Render a QR code for the given URL and return PNG bytes."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
