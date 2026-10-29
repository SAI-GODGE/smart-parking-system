"""Application configuration for the Smart Parking Management System."""

import os
import secrets
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _env_bool(name, default="true"):
    raw = os.environ.get(name, default)
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _load_secret_key():
    """Use SECRET_KEY from the environment when provided.

    Otherwise generate once and store it in instance/secret_key so sessions
    stay valid across restarts without hard-coding a secret in the repo.
    """
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    instance_dir = BASE_DIR / "instance"
    instance_dir.mkdir(exist_ok=True)
    key_file = instance_dir / "secret_key"
    if key_file.exists():
        stored = key_file.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    new_key = secrets.token_hex(32)
    key_file.write_text(new_key, encoding="utf-8")
    try:
        key_file.chmod(0o600)
    except OSError:
        pass
    return new_key


def _database_uri():
    uri = os.environ.get("DATABASE_URL")
    if uri:
        return uri
    db_path = (BASE_DIR / "instance" / "smart_parking.db").resolve()
    return f"sqlite:///{db_path.as_posix()}"


class Config:
    """Default configuration."""

    SECRET_KEY = _load_secret_key()
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"timeout": 30}}

    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    # Application behaviour -------------------------------------------------
    BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:5000").rstrip("/")
    FEE_CALCULATION_ENABLED = _env_bool("FEE_CALCULATION_ENABLED", "true")
    RESERVATION_HOLD_MINUTES = int(os.environ.get("RESERVATION_HOLD_MINUTES", "30"))
    MAX_ADVANCE_DAYS = int(os.environ.get("MAX_ADVANCE_DAYS", "30"))
    MAX_RESERVATION_HOURS = 72
    QUICK_PARKING_DEFAULT_HOURS = 4
    HOURLY_RATE_DEFAULT = 40.0

    # Weights for the slot recommendation score (lower score = better).
    RECOMMENDATION_WEIGHTS = {"distance": 0.5, "floor": 0.3, "vehicle": 0.2}

    # Seed sample data only when the database is empty.
    SEED_ON_START = True

    TESTING = False


class TestConfig(Config):
    """Configuration used by the automated test suite."""

    TESTING = True
    WTF_CSRF_ENABLED = False
    SEED_ON_START = False
    FEE_CALCULATION_ENABLED = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    BASE_URL = "http://localhost"
