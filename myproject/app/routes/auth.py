from flask import (Blueprint, render_template, request, redirect, url_for, flash, session)
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import Customer
from hmac import compare_digest

auth = Blueprint("auth", __name__)


@auth.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if (
            not username
            or len(username) > 50
            or not first_name
            or len(first_name) > 100
            or not last_name
            or len(last_name) > 100
        ):
            flash("Please enter valid name and username details.")
            return render_template("register.html")

        if not email or len(email) > 100 or "@" not in email:
            flash("Please enter a valid email address.")
            return render_template("register.html")

        if len(password) < 12 or len(password) > 256:
            flash("Password must be between 12 and 256 characters.")
            return render_template("register.html")

        customer = Customer(
            username=username,
            first_name=first_name,
            last_name=last_name,
            email=email,
            acc_password=generate_password_hash(password),
        )

        db.session.add(customer)

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("That username or email may already be registered.")
            return render_template("register.html")

        flash("Registration successful. Please log in.")
        return redirect(url_for("auth.login"))

    return render_template("register.html")


@auth.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        customer = Customer.query.filter(
            db.func.lower(Customer.username) == username.lower()
        ).first()

        if customer is None:
            flash("Invalid username or password.")
            return render_template("login.html"), 401

        if customer.is_locked:
            flash("Your account is locked. Please contact support.")
            return render_template("login.html"), 403

        stored_password = customer.acc_password or ""

        is_werkzeug_hash = (
            stored_password.startswith(("scrypt:", "pbkdf2:"))
            and stored_password.count("$") >= 2
        )

        if len(password) > 256:
            valid_password = False
        elif is_werkzeug_hash:
            valid_password = check_password_hash(
                stored_password, password
            )
        else:
            # Temporary support for legacy plain-text records.
            valid_password = compare_digest(
                stored_password, password
            )

            if valid_password:
                # Upgrade the legacy password immediately.
                customer.acc_password = generate_password_hash(
                    password
                )

        if not valid_password:
            customer.failed_attempts += 1

            if customer.failed_attempts >= 5:
                customer.is_locked = True

            db.session.commit()
            flash("Invalid username or password.")
            return render_template("login.html"), 401

        customer.failed_attempts = 0
        db.session.commit()

        session.clear()
        session["customer_id"] = customer.customer_id
        session["username"] = customer.username

        return redirect(url_for("pages.home"))

    return render_template("login.html")


@auth.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have logged out successfully.")
    return redirect(url_for("auth.login"))