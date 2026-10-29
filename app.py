"""Application factory for the Smart Parking Management System.

Run locally with:   python app.py
Or with Flask CLI:  flask --app app run
"""

import os

import click
from flask import Flask, render_template

from config import Config
from extensions import csrf, db, login_manager


def create_app(test_config=None):
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from routes import register_blueprints

    register_blueprints(app)

    # Expose status constants to every template (including imported macros).
    from models import BayStatus, ReservationStatus, Role, VehicleType

    app.jinja_env.globals.update(
        BayStatus=BayStatus,
        ReservationStatus=ReservationStatus,
        VehicleType=VehicleType,
        Role=Role,
    )

    _register_error_handlers(app)
    _register_cli(app)

    @login_manager.user_loader
    def load_user(user_id):
        from models import User

        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    with app.app_context():
        db.create_all()
        if app.config.get("SEED_ON_START", True):
            from services.seed import seed_if_empty

            if seed_if_empty():
                app.logger.info("Seeded sample parking facilities and demo accounts.")
            from models import Role, User
            if not User.query.filter_by(role=Role.ADMIN).first():
                admin_acc = User(
                    username="admin",
                    email="admin@smartparking.local",
                    role=Role.ADMIN,
                )
                admin_acc.set_password("admin1234")
                db.session.add(admin_acc)
                db.session.commit()
                app.logger.info("Created default administrator account 'admin'.")

    return app


def _register_error_handlers(app):
    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(405)
    def method_not_allowed(_error):
        return render_template("errors/404.html"), 405

    @app.errorhandler(500)
    def internal_error(_error):
        try:
            db.session.rollback()
        except Exception:  # pragma: no cover - defensive
            pass
        return render_template("errors/500.html"), 500


def _register_cli(app):
    @app.cli.command("init-db")
    def init_db_command():
        """Create the database tables and seed sample data if empty."""
        db.create_all()
        from services.seed import seed_if_empty

        if seed_if_empty():
            click.echo("Database created and sample data seeded.")
        else:
            click.echo("Database created. Existing data was left untouched.")


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    application = create_app()
    application.run(host="127.0.0.1", port=5000, debug=debug)
