
import logging
import secrets
import string
from uuid import UUID

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
)

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.extensions import (
    db,
    get_supabase_client,
    get_supabase_admin_client,
)

from app.models import (
    AppUser,
    CustomerDetails,
    Role,
    LoginHistory,
)

from app.services import (
    ROLE_ADMIN,
    ROLE_CUSTOMER,
    ROLE_VERIFICATION_OFFICER,
    notify,
    write_audit,
)


auth = Blueprint("auth", __name__)

logger = logging.getLogger(__name__)


# --------------------------------------------------
# HELPER FUNCTIONS
# --------------------------------------------------

def delete_supabase_user(user_id):
    """Delete an Auth user after a failed database registration."""

    admin = get_supabase_admin_client()

    admin.auth.admin.delete_user(str(user_id))


def get_customer_role():
    return Role.query.filter_by(
        role_name=ROLE_CUSTOMER
    ).first()


def record_login_attempt(
    customer_id=None,
    username=None,
    status="failed",
):
    """Record a login attempt without interrupting authentication."""

    try:
        history = LoginHistory(
            customer_id=customer_id,
            username_attempted=username,
            ip_address=request.remote_addr,
            device_info=request.user_agent.string,
            login_status=status,
        )

        db.session.add(history)
        db.session.commit()

    except Exception:
        db.session.rollback()

        logger.exception(
            "Unable to record login history."
        )


def cleanup_supabase_user(user_id):
    """Attempt cleanup without hiding the original failure."""

    try:
        delete_supabase_user(user_id)

    except Exception:
        logger.exception(
            "Supabase user cleanup failed for user ID %s.",
            user_id,
        )


# --------------------------------------------------
# REGISTRATION
# --------------------------------------------------

@auth.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "GET":
        return render_template("register.html")

    username = request.form.get(
        "username", ""
    ).strip()

    first_name = request.form.get(
        "first_name", ""
    ).strip()

    last_name = request.form.get(
        "last_name", ""
    ).strip()

    email = request.form.get(
        "email", ""
    ).strip().lower()

    password = request.form.get("password", "")

    # Validate required fields
    if (
        not username
        or len(username) > 50
        or not first_name
        or len(first_name) > 100
        or not last_name
        or len(last_name) > 100
    ):
        flash("Please enter valid registration details.")
        return render_template("register.html"), 400

    if (
        not email
        or len(email) > 150
        or "@" not in email
    ):
        flash("Please enter a valid email address.")
        return render_template("register.html"), 400

    if len(password) < 12 or len(password) > 256:
        flash(
            "Password must be between 12 and 256 characters."
        )
        return render_template("register.html"), 400

    # Check for existing username or email
    existing_customer = AppUser.query.filter(
        db.or_(
            func.lower(AppUser.username) == username.lower(),
            func.lower(AppUser.email) == email,
        )
    ).first()

    if existing_customer:
        flash(
            "Username or email is already registered."
        )
        return render_template("register.html"), 409

    customer_role = get_customer_role()

    if customer_role is None:
        flash("Customer role is not configured.")
        return render_template("register.html"), 500

    auth_user_id = None

    try:
        supabase = get_supabase_client()

        # Create Supabase Auth user
        response = supabase.auth.sign_up({
            "email": email,
            "password": password,
        })

        if response.user is None:
            raise RuntimeError(
                "Supabase did not return an authentication user."
            )

        auth_user_id = UUID(str(response.user.id))

        # Create the USER account. No bank account is created here: the user
        # must be verified first and then request a bank account.
        user = AppUser(
            user_id=auth_user_id,
            role_id=customer_role.role_id,
            username=username,
            email=email,
        )

        db.session.add(user)
        db.session.flush()

        # Account information lives with the user account.
        details = CustomerDetails(
            customer_id=auth_user_id,
            first_name=first_name,
            last_name=last_name,
        )

        db.session.add(details)

        notify(
            auth_user_id,
            "Welcome to JAB Bank",
            "Complete your account information and request identity "
            "verification from the My Account page to open a bank account.",
        )

        write_audit(
            "user_registered",
            "app_user",
            auth_user_id,
            f"User '{username}' registered.",
            subject_id=auth_user_id,
            actor=user,
        )

        # Commit PostgreSQL records
        db.session.commit()

        if response.session is None:
            flash(
                "Registration successful! You can now log in.",
                "success",
            )

        return redirect(url_for("auth.login"))

    except IntegrityError:
        db.session.rollback()

        if auth_user_id:
            cleanup_supabase_user(auth_user_id)

        logger.exception(
            "Database integrity error during registration."
        )

        flash(
            "Registration could not be completed. "
            "Please check your details and try again."
        )

        return render_template("register.html"), 409

    except Exception:
        db.session.rollback()

        if auth_user_id:
            cleanup_supabase_user(auth_user_id)

        logger.exception(
            "Registration failed."
        )

        flash(
            "Registration failed. Please try again."
        )

        return render_template("register.html"), 400


# --------------------------------------------------
# LOGIN
# --------------------------------------------------

@auth.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "GET":
        return render_template("login.html")

    username = request.form.get(
        "username", ""
    ).strip()

    password = request.form.get("password", "")

    if (
        not username
        or not password
        or len(password) > 256
    ):
        record_login_attempt(
            username=username[:50] or None,
            status="failed",
        )

        flash("Invalid username or password.")
        return render_template("login.html"), 401

    # Find customer by username
    customer = AppUser.query.filter(
        func.lower(AppUser.username) == username.lower()
    ).first()

    if customer is None:
        record_login_attempt(
            username=username[:50],
            status="failed",
        )

        flash("Invalid username or password.")
        return render_template("login.html"), 401

    if (
        customer.is_locked
        or customer.account_status != "active"
    ):
        record_login_attempt(
            customer_id=customer.user_id,
            username=customer.username,
            status="failed",
        )

        flash(
            "Your account is unavailable. Please contact support."
        )

        return render_template("login.html"), 403

    try:
        supabase = get_supabase_client()

        # Supabase verifies the password
        response = supabase.auth.sign_in_with_password({
            "email": customer.email,
            "password": password,
        })

        if not response.user or not response.session:
            raise ValueError("Authentication failed.")

        authenticated_id = UUID(
            str(response.user.id)
        )

        # Verify authenticated identity
        if authenticated_id != customer.user_id:
            raise ValueError("User identity mismatch.")

        # Record successful login
        record_login_attempt(
            customer_id=customer.user_id,
            username=customer.username,
            status="success",
        )

        # Establish Flask server-side session
        session.clear()
        session.permanent = True

        session["customer_id"] = str(
            customer.user_id
        )

        session["username"] = customer.username

        session["access_token"] = (
            response.session.access_token
        )

        session["refresh_token"] = (
            response.session.refresh_token
        )

        role = (
            customer.role.role_name.strip().lower()
            if customer.role else ROLE_CUSTOMER
        )

        if role == ROLE_ADMIN:
            return redirect(url_for("admin.dashboard"))

        if role == ROLE_VERIFICATION_OFFICER:
            return redirect(url_for("verification.dashboard"))

        # Customers land on the account page, not the banking dashboard.
        return redirect(url_for("pages.home"))

    except Exception:
        logger.exception(
            "Authentication failed for username %s.",
            username[:50],
        )

        record_login_attempt(
            customer_id=customer.user_id,
            username=customer.username,
            status="failed",
        )

        flash("Invalid username or password.")
        return render_template("login.html"), 401


# --------------------------------------------------
# LOGOUT
# --------------------------------------------------

@auth.route("/logout", methods=["POST"])
def logout():

    access_token = session.get("access_token")
    refresh_token = session.get("refresh_token")

    # Attempt Supabase sign-out
    if access_token and refresh_token:
        try:
            supabase = get_supabase_client()

            supabase.auth.set_session(
                access_token,
                refresh_token,
            )

            supabase.auth.sign_out()

        except Exception:
            logger.exception(
                "Supabase sign-out failed."
            )

    # Always clear the Flask session
    session.clear()

    flash(
        "You have logged out successfully.",
        "success",
    )

    return redirect(url_for("auth.login"))
