
import os

from datetime import timedelta
from dotenv import load_dotenv
from flask import Flask, session, render_template

from app.extensions import db, server_session

load_dotenv()


def create_app():

    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static",
    )

    # Flask configuration
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL"
    )

    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
    }

    # Server-side session configuration
    app.config["SESSION_TYPE"] = "filesystem"

    app.config["SESSION_FILE_DIR"] = os.path.join(
        app.instance_path,
        "flask_session"
    )

    app.config["SESSION_PERMANENT"] = True

    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
        minutes=30
    )

    app.config["SESSION_USE_SIGNER"] = True
    app.config["SESSION_COOKIE_NAME"] = "jabbank_session"

    # Cookie security
    app.config["SESSION_COOKIE_HTTPONLY"] = True

    app.config["SESSION_COOKIE_SECURE"] = (
        os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
    )

    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # Validate configuration
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("SECRET_KEY is not configured.")

    if not app.config["SQLALCHEMY_DATABASE_URI"]:
        raise RuntimeError("DATABASE_URL is not configured.")

    # Create session storage directory
    os.makedirs(
        app.config["SESSION_FILE_DIR"],
        exist_ok=True
    )

    # Initialize extensions
    db.init_app(app)

    # Initialize server-side sessions first
    server_session.init_app(app)


    @app.context_processor
    def inject_shared_navigation_context():
        """Provide shared navigation values to every page template."""
        from uuid import UUID
        from app.models import AppUser, Notification

        customer_id = session.get("customer_id")
        customer = None
        if customer_id:
            try:
                customer = db.session.get(AppUser, UUID(str(customer_id)))
            except (ValueError, TypeError, AttributeError):
                customer = None

        unread_count = 0
        if customer is not None:
            unread_count = Notification.query.filter_by(
                customer_id=customer.user_id,
                is_read=False,
            ).count()

        return {
            "current_account_status": (
                customer.account_status if customer else "active"
            ),
            "unread_count": unread_count,
        }

    # Register blueprints
    from app.routes.pages import pages
    from app.routes.transactions import transactions
    from app.routes.auth import auth
    from app.routes.admin import admin
    from app.routes.verification import verification

    app.register_blueprint(pages)
    app.register_blueprint(transactions)
    app.register_blueprint(auth)
    app.register_blueprint(admin)
    app.register_blueprint(verification)

    return app
