"""Nirog healthcare platform application factory."""

from flask import Flask

from .config import get_config
from .extensions import db, jwt, cors, limiter, migrate


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(get_config(config_name))

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    cors.init_app(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}})
    limiter.init_app(app)
    # Use a shared Redis URL in production when configured; memory storage is safe
    # for local development but does not synchronize limits across app workers.
    app.config.setdefault("RATELIMIT_STORAGE_URI", "memory://")

    # Import blueprints
    from .routes.auth import bp as auth_bp
    from .routes.public import bp as public_bp
    from .routes.admin import bp as admin_bp
    from .routes.appointments import bp as appointments_bp
    from .routes.queues import bp as queues_bp
    from .routes.consultations import bp as consultations_bp
    from .routes.prescriptions import bp as prescriptions_bp
    from .routes.notifications import bp as notifications_bp
    from .routes.recommendations import bp as recommendations_bp
    from .routes.video import bp as video_bp
    from .routes.reports import bp as reports_bp
    from .routes.patients import bp as patients_bp
    from .routes.lab_reports import bp as lab_reports_bp
    from .routes.ui import bp as ui_bp
    from .routes.tenants import bp as tenants_bp
    from .routes.billing import bp as billing_bp
    from .routes.analytics import bp as analytics_bp
    from .routes.exports import bp as exports_bp
    from .routes.consent import bp as consent_bp
    from .routes.backup import bp as backup_bp
    from .routes.push_notifications import bp as push_bp
    from .routes.favorites import bp as favorites_bp
    from .routes.reviews import bp as reviews_bp
    from .routes.qr_routes import bp as qr_bp
    from .routes.reminders import bp as reminders_bp
    from .routes.smart_queue import bp as smart_queue_bp
    from .routes.pharmacy import bp as pharmacy_bp
    from .routes.mobile import bp as mobile_bp
    from .commands.reminders import check_reminders_command

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(queues_bp)
    app.register_blueprint(consultations_bp)
    app.register_blueprint(prescriptions_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(recommendations_bp)
    app.register_blueprint(video_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(lab_reports_bp)
    app.register_blueprint(ui_bp)
    app.register_blueprint(tenants_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(exports_bp)
    app.register_blueprint(consent_bp)
    app.register_blueprint(backup_bp)
    app.register_blueprint(push_bp)
    app.register_blueprint(favorites_bp)
    app.register_blueprint(reviews_bp)
    app.register_blueprint(qr_bp)
    app.register_blueprint(reminders_bp)
    app.register_blueprint(smart_queue_bp)
    app.register_blueprint(pharmacy_bp)
    app.register_blueprint(mobile_bp)
    app.cli.add_command(check_reminders_command)

    from .errors import register_error_handlers
    from .security import register_security_headers

    register_error_handlers(app)
    register_security_headers(app)

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "nirog", "timezone": app.config["BUSINESS_TIMEZONE"]}

    return app