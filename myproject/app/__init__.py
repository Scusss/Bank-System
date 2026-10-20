import os

from dotenv import load_dotenv
from flask import Flask
from flask_wtf.csrf import CSRFProtect
from app.extensions import db

load_dotenv()

csrf = CSRFProtect()

def create_app():
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static",
    )

    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    if not app.config["SECRET_KEY"]:
        raise RuntimeError("SECRET_KEY is not configured.")

    if not app.config["SQLALCHEMY_DATABASE_URI"]:
        raise RuntimeError("DATABASE_URL is not configured.")

    db.init_app(app)
    csrf.init_app(app)

    from app.routes.pages import pages
    from app.routes.transactions import transactions
    from app.routes.auth import auth

    app.register_blueprint(pages)
    app.register_blueprint(transactions)
    app.register_blueprint(auth)

    return app