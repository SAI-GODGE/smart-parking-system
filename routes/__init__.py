"""Blueprint registration."""


def register_blueprints(app):
    from .main import bp as main_bp
    from .auth import bp as auth_bp
    from .booking import bp as booking_bp
    from .quick import bp as quick_bp
    from .checkout import bp as checkout_bp
    from .operator import bp as operator_bp
    from .admin import bp as admin_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(booking_bp)
    app.register_blueprint(quick_bp)
    app.register_blueprint(checkout_bp)
    app.register_blueprint(operator_bp)
    app.register_blueprint(admin_bp)
