
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import logging
import re
from functools import wraps
from uuid import UUID

from flask import (
    Blueprint,
    render_template,
    abort,
    redirect,
    url_for,
    flash,
    session,
    request,
)

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.extensions import db, get_supabase_client, get_supabase_admin_client
from app.models import (
    Account,
    AccountApplication,
    AccountSelfLimit,
    AppUser,
    CustomerDetails,
    IdentityVerification,
    TransactionList,
    Notification,
    Beneficiary,
)
from app.services import (
    APPLICATION_PENDING,
    account_limits,
    VERIFICATION_PENDING,
    bank_type_states,
    find_account_by_number,
    is_staff,
    is_admin,
    is_verification_officer,
    is_verified,
    missing_profile_fields,
    notify,
    role_name,
    selected_account,
    user_accounts,
    verification_state,
    write_audit,
)


pages = Blueprint("pages", __name__)
logger = logging.getLogger(__name__)


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):

        customer_id = session.get("customer_id")
        access_token = session.get("access_token")

        if not customer_id or not access_token:
            session.clear()
            flash("Please log in to continue.")
            return redirect(url_for("auth.login"))

        try:
            customer_uuid = UUID(str(customer_id))

            # Verify the Supabase access token
            supabase = get_supabase_client()

            response = supabase.auth.get_user(access_token)

            if not response.user:
                raise ValueError("Invalid session")

            authenticated_id = UUID(str(response.user.id))

            if authenticated_id != customer_uuid:
                raise ValueError("User identity mismatch")

            # Verify customer still exists and is active
            customer = db.session.get(AppUser, customer_uuid)

            if (
                customer is None
                or customer.is_locked
                or customer.account_status != "active"
            ):
                session.clear()
                flash("Your account is unavailable.")
                return redirect(url_for("auth.login"))

            # Staff use their own consoles, not customer banking.
            if is_admin(customer):
                return redirect(url_for("admin.dashboard"))

            if is_verification_officer(customer):
                return redirect(url_for("verification.dashboard"))

        except Exception:
            session.clear()
            flash("Your session has expired. Please log in again.")
            return redirect(url_for("auth.login"))

        return view(*args, **kwargs)

    return wrapped_view


def get_current_customer():

    customer_id = session.get("customer_id")

    try:
        customer_uuid = UUID(str(customer_id))
    except (ValueError, TypeError, AttributeError):
        session.clear()
        abort(401)

    customer = db.session.get(AppUser, customer_uuid)

    if customer is None:
        session.clear()
        abort(401)

    return customer


def get_customer_account(customer):
    """The bank account currently selected by the user (or None)."""
    return selected_account(customer.user_id)


def get_customer_details(customer):

    return CustomerDetails.query.filter_by(
        customer_id=customer.user_id
    ).first()


def account_label(account):
    if account is None:
        return "No bank account"
    return (account.account_type or "savings").replace("_", " ").title()


@pages.route("/")
@login_required
def home():
    customer = get_current_customer()
    account = get_customer_account(customer)
    details = get_customer_details(customer)

    balance = account.balance if account else 0

    # Count unread notifications for this customer.
    unread_count = Notification.query.filter_by(
        customer_id=customer.user_id,
        is_read=False,
    ).count()

    return render_template(
        "home.html",
        account=account,
        accounts=user_accounts(customer.user_id),
        balance=balance,
        username=customer.username,
        first_name=details.first_name if details else "",
        last_name=details.last_name if details else "",
        account_type=account_label(account),
        unread_count=unread_count,
        role_name=role_name(customer) or "customer",
        verification=verification_state(customer.user_id)[0],
    )


@pages.route("/accounts/switch", methods=["POST"])
@login_required
def switch_account():
    """Choose which bank account the banking pages operate on."""
    customer = get_current_customer()
    raw = request.form.get("account_id", "")

    owned = {str(a.account_id) for a in user_accounts(customer.user_id)}
    if raw in owned:
        session["account_id"] = raw
    else:
        flash("That bank account could not be selected.", "error")

    target = request.form.get("next") or ""
    # Only allow same-site relative redirects.
    if not target.startswith("/") or target.startswith("//"):
        target = url_for("pages.home")
    return redirect(target)


# --------------------------------------------------
# USER ACCOUNT (profile, verification, bank requests)
# --------------------------------------------------

def _parse_birth_date(raw):
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    today = date.today()
    age = today.year - parsed.year - (
        (today.month, today.day) < (parsed.month, parsed.day)
    )
    if parsed > today or age > 120:
        return None
    return parsed


def _bank_management(user_id):
    """One entry per bank type for the account page.

    Each entry is a bank_type_states() dict plus ``limits`` (daily limits,
    only when the user has that bank account). Accounts whose type is no
    longer offered are still listed so they never disappear from view.
    """
    entries = []
    seen_ids = set()
    for bt in bank_type_states(user_id):
        acct = bt.get("account")
        if acct is not None:
            seen_ids.add(acct.account_id)
        entries.append({**bt, "limits": account_limits(acct) if acct else None})

    for acct in user_accounts(user_id):
        if acct.account_id not in seen_ids:
            entries.append({
                "type": acct.account_type,
                "label": (acct.account_type or "").replace("_", " ").title(),
                "state": "approved",
                "application": None,
                "account": acct,
                "limits": account_limits(acct),
            })
    return entries


@pages.route("/account")
@login_required
def account_page():
    customer = get_current_customer()
    details = get_customer_details(customer)
    state, record = verification_state(customer.user_id)

    history = (
        IdentityVerification.query
        .filter_by(customer_id=customer.user_id)
        .order_by(IdentityVerification.submitted_at.desc())
        .limit(5)
        .all()
    )

    return render_template(
        "account.html",
        customer=customer,
        details=details,
        email=customer.email,
        verification_state=state,
        verification=record,
        verification_history=history,
        missing_fields=missing_profile_fields(details),
        bank_types=bank_type_states(customer.user_id),
        accounts=user_accounts(customer.user_id),
        bank_management=_bank_management(customer.user_id),
        account_type="User account",
    )



@pages.route("/manage-bank-accounts")
@login_required
def manage_bank_accounts():
    customer = get_current_customer()
    state, record = verification_state(customer.user_id)
    return render_template(
        "manage_bank_accounts.html",
        customer=customer,
        bank_management=_bank_management(customer.user_id),
        verification_state=state,
        verification=record,
        accounts=user_accounts(customer.user_id),
        account_type="Manage Bank Accounts",
    )



@pages.route("/account/profile", methods=["POST"])
@login_required
def update_account_profile():
    """Update the user's username; email changes use the verified flow below."""
    customer = get_current_customer()
    username = (request.form.get("username") or "").strip()

    if not username or len(username) > 50 or not re.fullmatch(r"[A-Za-z0-9_.-]+", username):
        flash("Username must be 1–50 characters and may contain letters, numbers, dots, underscores, or hyphens.", "error")
        return redirect(url_for("pages.account_page"))

    duplicate = AppUser.query.filter(
        func.lower(AppUser.username) == username.lower(),
        AppUser.user_id != customer.user_id,
    ).first()
    if duplicate:
        flash("That username is already in use. Please choose another.", "error")
        return redirect(url_for("pages.account_page"))

    old_username = customer.username
    customer.username = username
    session["username"] = username
    write_audit(
        "account_username_updated", "app_user", customer.user_id,
        "User updated their username.",
        subject_id=customer.user_id,
        old_values={"username": old_username},
        new_values={"username": username},
    )
    try:
        db.session.commit()
        flash("Username updated successfully.", "success")
    except IntegrityError:
        db.session.rollback()
        session["username"] = old_username
        flash("That username is already in use.", "error")
    except Exception:
        db.session.rollback()
        session["username"] = old_username
        flash("Could not update your username. Please try again.", "error")
    return redirect(url_for("pages.account_page"))


@pages.route("/account/email/request", methods=["POST"])
@login_required
def request_email_change():
    """Change the login email immediately; verification remains optional."""
    customer = get_current_customer()
    new_email = (request.form.get("email") or "").strip().lower()

    if (not new_email or len(new_email) > 150
            or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", new_email)):
        flash("Enter a valid email address.", "error")
        return redirect(url_for("pages.account_page"))

    if new_email == customer.email.lower():
        flash("That is already your current email address.", "error")
        return redirect(url_for("pages.account_page"))

    duplicate = AppUser.query.filter(
        func.lower(AppUser.email) == new_email,
        AppUser.user_id != customer.user_id,
    ).first()
    if duplicate:
        flash("That email address is already registered.", "error")
        return redirect(url_for("pages.account_page"))

    old_email = customer.email
    try:
        # Use the server-side Supabase admin API so the login email can be
        # changed immediately without requiring the user to confirm first.
        admin = get_supabase_admin_client()
        admin.auth.admin.update_user_by_id(
            str(customer.user_id),
            {"email": new_email, "email_confirm": False},
        )
        customer.email = new_email
        write_audit(
            "account_email_updated", "app_user", customer.user_id,
            "User changed their email without completing optional verification.",
            subject_id=customer.user_id,
            old_values={"email": old_email},
            new_values={"email": new_email},
        )
        db.session.commit()
        session["pending_email_change"] = new_email
        flash("Email address changed. It is currently unverified; use the separate verification option if you want to verify it.", "success")
    except IntegrityError:
        db.session.rollback()
        flash("That email address is already registered.", "error")
    except Exception:
        db.session.rollback()
        logger.exception("Could not change email for user %s.", customer.user_id)
        flash("Could not change your email address. Please try again.", "error")

    return redirect(url_for("pages.account_page"))


@pages.route("/account/email/send-verification", methods=["POST"])
@login_required
def send_email_change_verification():
    """Send an optional verification code for the already-updated email."""
    customer = get_current_customer()
    pending_email = session.get("pending_email_change")
    if not pending_email or pending_email.lower() != customer.email.lower():
        flash("Change your email address first.", "error")
        return redirect(url_for("pages.account_page"))
    try:
        supabase = get_supabase_client()
        supabase.auth.set_session(session.get("access_token"), session.get("refresh_token"))
        supabase.auth.update_user({"email": pending_email})
        flash("A verification code has been sent. Enter it below to verify your email.", "success")
    except Exception:
        logger.exception("Could not send optional email verification for user %s.", customer.user_id)
        flash("Could not send a verification code. Please try again.", "error")
    return redirect(url_for("pages.account_page"))


@pages.route("/account/email/verify", methods=["POST"])
@login_required
def verify_email_change():
    """Confirm the email-change OTP before updating the local app_users row."""
    customer = get_current_customer()
    pending_email = session.get("pending_email_change")
    code = (request.form.get("verification_code") or "").strip()

    if not pending_email:
        flash("Request an email change first so we can send you a verification code.", "error")
        return redirect(url_for("pages.account_page"))
    if not re.fullmatch(r"\d{6,8}", code):
        flash("Enter the verification code from your email.", "error")
        return redirect(url_for("pages.account_page"))

    try:
        supabase = get_supabase_client()
        response = supabase.auth.verify_otp({
            "email": pending_email,
            "token": code,
            "type": "email_change",
        })
        if not response.user or str(response.user.id) != str(customer.user_id):
            raise ValueError("Email verification returned an unexpected user.")

        duplicate = AppUser.query.filter(
            func.lower(AppUser.email) == pending_email,
            AppUser.user_id != customer.user_id,
        ).first()
        if duplicate:
            db.session.rollback()
            flash("That email address has since been registered by another user.", "error")
            session.pop("pending_email_change", None)
            return redirect(url_for("pages.account_page"))

        # The local email was already changed when the user chose Save.
        # This endpoint now only completes Supabase's optional verification.

        # Keep the active Flask session aligned with the newly issued tokens.
        if response.session:
            session["access_token"] = response.session.access_token
            session["refresh_token"] = response.session.refresh_token
        session.pop("pending_email_change", None)
        flash("Your email address has been verified.", "success")
    except IntegrityError:
        db.session.rollback()
        flash("That email address is already registered.", "error")
    except Exception:
        db.session.rollback()
        logger.exception("Email verification failed for user %s.", customer.user_id)
        flash("The code is invalid, expired, or could not be verified. Request a new code and try again.", "error")

    return redirect(url_for("pages.account_page"))


@pages.route("/account/details", methods=["POST"])
@login_required
def update_account_details():
    """Save the account information held by the user account."""
    customer = get_current_customer()
    details = get_customer_details(customer)

    first_name = (request.form.get("first_name") or "").strip()
    middle_name = (request.form.get("middle_name") or "").strip()
    last_name = (request.form.get("last_name") or "").strip()
    suffix = (request.form.get("suffix") or "").strip()
    phone = (request.form.get("phone_number") or "").strip()
    address = (request.form.get("address") or "").strip()
    birth_raw = (request.form.get("birth_date") or "").strip()

    if (not first_name or len(first_name) > 100
            or not last_name or len(last_name) > 100
            or len(middle_name) > 100 or len(suffix) > 20):
        flash("Enter a valid first and last name.", "error")
        return redirect(url_for("pages.account_page"))

    if phone and (len(phone) > 20 or not all(
            c.isdigit() or c in "+- ()" for c in phone)):
        flash("Enter a valid phone number.", "error")
        return redirect(url_for("pages.account_page"))

    if len(address) > 500:
        flash("Address is too long (500 characters maximum).", "error")
        return redirect(url_for("pages.account_page"))

    birth_date = None
    if birth_raw:
        birth_date = _parse_birth_date(birth_raw)
        if birth_date is None:
            flash("Enter a valid birth date.", "error")
            return redirect(url_for("pages.account_page"))

    # Details that were already verified must not be changed silently.
    if is_verified(customer.user_id) and details is not None and (
        (details.first_name, details.last_name, details.birth_date)
        != (first_name, last_name, birth_date or details.birth_date)
    ):
        flash(
            "Your name and birth date are verified and can no longer be "
            "changed here. Contact support to correct them.",
            "error",
        )
        return redirect(url_for("pages.account_page"))

    if details is None:
        details = CustomerDetails(
            customer_id=customer.user_id,
            first_name=first_name,
            last_name=last_name,
        )
        db.session.add(details)

    details.first_name = first_name
    details.middle_name = middle_name or None
    details.last_name = last_name
    details.suffix = suffix or None
    details.phone_number = phone or None
    details.address = address or None
    if birth_date is not None:
        details.birth_date = birth_date

    write_audit(
        "account_details_updated", "customer_details", customer.user_id,
        "User updated their account information.",
        subject_id=customer.user_id,
    )

    try:
        db.session.commit()
        flash("Account information saved.", "success")
    except Exception:
        db.session.rollback()
        flash("Could not save your information. Please try again.", "error")
    return redirect(url_for("pages.account_page"))


@pages.route("/account/verification", methods=["POST"])
@login_required
def request_verification():
    """Send an identity verification request to the verification officers."""
    customer = get_current_customer()
    state, _ = verification_state(customer.user_id)

    if state == "verified":
        flash("Your identity is already verified.", "error")
        return redirect(url_for("pages.account_page"))

    if state == VERIFICATION_PENDING:
        flash("You already have a verification request awaiting review.",
              "error")
        return redirect(url_for("pages.account_page"))

    details = get_customer_details(customer)
    missing = missing_profile_fields(details)
    if missing:
        flash(
            "Complete your account information first: "
            + ", ".join(missing) + ".",
            "error",
        )
        return redirect(url_for("pages.account_page"))

    verification = IdentityVerification(
        customer_id=customer.user_id,
        verification_status=VERIFICATION_PENDING,
    )
    db.session.add(verification)
    db.session.flush()

    write_audit(
        "verification_requested", "identity_verification",
        verification.verification_id,
        "Account information submitted for verification.",
        subject_id=customer.user_id,
    )
    notify(
        customer.user_id,
        "Verification request sent",
        "Your account information was sent to a verification officer. "
        "You will be notified once it has been reviewed.",
    )

    try:
        db.session.commit()
        flash("Verification request sent to the verification officer.",
              "success")
    except IntegrityError:
        db.session.rollback()
        flash("You already have a verification request awaiting review.",
              "error")
    except Exception:
        db.session.rollback()
        flash("Could not send the request. Please try again.", "error")
    return redirect(url_for("pages.account_page"))


def _parse_limit(raw, cap, label):
    """Return ``(value, error)``. Blank clears the limit (value ``None``)."""
    raw = (raw or "").strip().replace(",", "")
    if raw == "":
        return None, None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None, f"Enter a valid amount for the daily {label} limit."
    if (not value.is_finite() or value <= 0
            or value.as_tuple().exponent < -2
            or value >= Decimal("10000000000000")):
        return None, (f"The daily {label} limit must be a positive amount "
                      "with at most two decimal places.")
    if cap is not None and value > cap:
        return None, (f"The daily {label} limit cannot exceed the bank "
                      f"maximum of \u20b1{cap:,.2f}.")
    return value, None


@pages.route("/account/bank-accounts/<int:account_id>/limits",
             methods=["POST"])
@login_required
def update_account_limits(account_id):
    """Let the owner set daily limits on one of their bank accounts."""
    customer = get_current_customer()
    account = Account.query.filter_by(
        account_id=account_id,
        customer_id=customer.user_id,
    ).first_or_404()

    if account.status == "closed":
        flash("A closed bank account's limits cannot be changed.", "error")
        return redirect(url_for("pages.manage_bank_accounts"))

    current = account_limits(account)
    new_values = {}
    for kind, label in (("withdrawal", "withdrawal"), ("transfer", "transfer")):
        column = current[kind]["column"]
        value, error = _parse_limit(
            request.form.get(column), current[kind]["cap"], label
        )
        if error:
            flash(error, "error")
            return redirect(url_for("pages.manage_bank_accounts"))
        new_values[column] = value

    row = db.session.get(AccountSelfLimit, account.account_id)
    if row is None:
        row = AccountSelfLimit(account_id=account.account_id)
        db.session.add(row)

    old_values = {
        column: (str(getattr(row, column)) if getattr(row, column) is not None
                 else None)
        for column in new_values
    }
    for column, value in new_values.items():
        setattr(row, column, value)

    write_audit(
        "account_limits_updated", "account", account.account_id,
        f"Customer updated daily limits on account {account.account_number}.",
        subject_id=customer.user_id,
        old_values=old_values,
        new_values={c: (str(v) if v is not None else None)
                    for c, v in new_values.items()},
    )

    try:
        db.session.commit()
        flash("Daily limits updated.", "success")
    except Exception:
        db.session.rollback()
        flash("Could not save your limits. Please try again.", "error")
    return redirect(url_for("pages.manage_bank_accounts"))


@pages.route("/account/bank-requests", methods=["POST"])
@login_required
def request_bank_account():
    """Request a bank account of a given type (once per type)."""
    customer = get_current_customer()

    if not is_verified(customer.user_id):
        flash("Your account must be verified before you can request a "
              "bank account. Complete verification under My Account.",
              "error")
        return redirect(url_for("pages.manage_bank_accounts"))

    account_type = (request.form.get("account_type") or "").strip().lower()
    states = {s["type"]: s for s in bank_type_states(customer.user_id)}
    entry = states.get(account_type)

    if entry is None:
        flash("Choose a valid bank account type.", "error")
        return redirect(url_for("pages.manage_bank_accounts"))

    if entry["state"] == APPLICATION_PENDING:
        flash(f"Your {entry['label']} request is already awaiting review.",
              "error")
        return redirect(url_for("pages.manage_bank_accounts"))

    if entry["state"] == "approved":
        flash(f"You already have a {entry['label']} account.", "error")
        return redirect(url_for("pages.manage_bank_accounts"))

    application = AccountApplication(
        customer_id=customer.user_id,
        account_type=account_type,
        application_status=APPLICATION_PENDING,
    )
    db.session.add(application)
    db.session.flush()

    write_audit(
        "bank_account_requested", "account_application",
        application.application_id,
        f"Requested a {entry['label']} bank account.",
        subject_id=customer.user_id,
    )
    notify(
        customer.user_id,
        "Bank account request sent",
        f"Your request for a {entry['label']} account was submitted and "
        "is awaiting review.",
    )

    try:
        db.session.commit()
        flash(f"{entry['label']} account request submitted.", "success")
    except IntegrityError:
        db.session.rollback()
        flash(f"You already requested a {entry['label']} account.", "error")
    except Exception:
        db.session.rollback()
        flash("Could not submit the request. Please try again.", "error")
    return redirect(url_for("pages.manage_bank_accounts"))


@pages.route("/<operation>")
@login_required
def bank_page(operation):

    valid_operations = {
        "deposit",
        "withdraw",
        "transfer",
        "receipts",
    }

    if operation not in valid_operations:
        abort(404)

    if operation == "receipts":
        return redirect(url_for("pages.receipts"))

    customer = get_current_customer()
    account = get_customer_account(customer)

    if account is None:
        flash(
            "You don't have a bank account yet. Verify your identity and "
            "request one from My Account.",
            "error",
        )
        return redirect(url_for("pages.account_page"))

    account_type_label = account_label(account)
    current_balance = account.balance
    saved_recipients = []
    if operation == "transfer":
        saved_recipients = (
            Beneficiary.query
            .filter_by(customer_id=customer.user_id)
            .order_by(Beneficiary.beneficiary_name.asc())
            .all()
        )

    return render_template(
        f"{operation}.html",
        account=account,
        accounts=user_accounts(customer.user_id),
        balance=current_balance,
        account_type=account_type_label,
        saved_recipients=saved_recipients,
    )


@pages.route("/transfer/contacts", methods=["POST"])
@login_required
def add_transfer_contact():
    customer = get_current_customer()
    name = (request.form.get("beneficiary_name") or "").strip()
    account_value = (request.form.get("recipient_id") or "").strip()

    if not name or len(name) > 150:
        flash("Enter a contact name (up to 150 characters).", "error")
        return redirect(url_for("pages.bank_page", operation="transfer"))
    recipient_account = find_account_by_number(account_value)
    if recipient_account is None:
        flash("Enter a valid recipient account ID (e.g. 1234-5678).", "error")
        return redirect(url_for("pages.bank_page", operation="transfer"))

    if ( recipient_account.status != "active"
            or recipient_account.customer_id == customer.user_id):
        flash("That active recipient account could not be found.", "error")
        return redirect(url_for("pages.bank_page", operation="transfer"))

    duplicate = Beneficiary.query.filter_by(
        customer_id=customer.user_id,
        account_number=recipient_account.account_number,
    ).first()
    if duplicate:
        flash("That recipient is already in your saved contacts.", "error")
        return redirect(url_for("pages.bank_page", operation="transfer"))

    contact = Beneficiary(
        customer_id=customer.user_id,
        beneficiary_name=name,
        account_number=recipient_account.account_number,
        bank_name="Coria Bank",
        nickname=name[:50],
    )
    db.session.add(contact)
    db.session.commit()
    flash("Recipient saved to your contacts.", "success")
    return redirect(url_for("pages.bank_page", operation="transfer"))


@pages.route("/transfer/contacts/<int:beneficiary_id>/delete", methods=["POST"])
@login_required
def delete_transfer_contact(beneficiary_id):
    customer = get_current_customer()
    contact = Beneficiary.query.filter_by(
        beneficiary_id=beneficiary_id,
        customer_id=customer.user_id,
    ).first_or_404()
    db.session.delete(contact)
    db.session.commit()
    flash("Saved recipient removed.", "success")
    return redirect(url_for("pages.bank_page", operation="transfer"))


@pages.route("/receipts")
@login_required
def receipts():

    customer = get_current_customer()
    account = get_customer_account(customer)

    if account is None:
        flash("You don't have a bank account yet.", "error")
        return redirect(url_for("pages.account_page"))

    transactions = (
        TransactionList.query
        .filter_by(account_id=account.account_id)
        .order_by(TransactionList.created_at.desc())
        .all()
    )

    account_type_label = account_label(account)

    # Transfers only store the other account's number in their description
    # ("... to/from account #<number>"). Look up that account's owner so the
    # receipts page can show the first and last name of the other party.
    pattern = re.compile(r"account\s*#\s*([A-Za-z0-9-]+)")
    counterpart_numbers = {}
    for tx in transactions:
        if str(tx.transaction_type).lower() in ("transfer_out", "transfer_in"):
            match = pattern.search(tx.description or "")
            if match:
                counterpart_numbers[tx.transaction_id] = match.group(1)

    if counterpart_numbers:
        rows = (
            db.session.query(
                Account.account_number,
                CustomerDetails.first_name,
                CustomerDetails.last_name,
            )
            .outerjoin(
                CustomerDetails,
                CustomerDetails.customer_id == Account.customer_id,
            )
            .filter(
                Account.account_number.in_(set(counterpart_numbers.values()))
            )
            .all()
        )
        names = {
            number: " ".join(part for part in (first, last) if part)
            for number, first, last in rows
        }
        for tx in transactions:
            number = counterpart_numbers.get(tx.transaction_id)
            if number:
                tx.recipient_name = names.get(number) or None
                tx.recipient_account_number = number[-4:]

    return render_template(
        "receipts.html",
        receipts=transactions,
        account=account,
        accounts=user_accounts(customer.user_id),
        account_type=account_type_label,
    )

@pages.route("/notifications")
@login_required
def notifications():
    customer = get_current_customer()

    items = (
        Notification.query
        .filter_by(customer_id=customer.user_id)
        .order_by(Notification.created_at.desc())
        .all()
    )

    unread_count = sum(1 for item in items if not item.is_read)

    return render_template(
        "notifications.html",
        notifications=items,
        unread_count=unread_count,
        role_name=role_name(customer) or "customer",
    )


@pages.route("/notifications/read-all", methods=["POST"])
@login_required
def mark_all_notifications_read():
    """Mark every unread notification of the signed-in customer as read."""
    customer = get_current_customer()

    try:
        updated = (
            Notification.query
            .filter_by(customer_id=customer.user_id, is_read=False)
            .update({Notification.is_read: True}, synchronize_session=False)
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Could not mark notifications as read")
        flash("Could not mark your notifications as read. Please try again.",
              "error")
        return redirect(url_for("pages.notifications"))

    if updated:
        flash(f"{updated} notification{'s' if updated != 1 else ''} "
              "marked as read.", "success")
    else:
        flash("You have no unread notifications.", "success")
    return redirect(url_for("pages.notifications"))


@pages.route("/notifications/<int:notification_id>/read", methods=["POST"])
@login_required
def mark_notification_read(notification_id):
    customer = get_current_customer()

    item = Notification.query.filter_by(
        notification_id=notification_id,
        customer_id=customer.user_id,
    ).first_or_404()

    item.is_read = True
    db.session.commit()

    flash("Notification marked as read.", "success")
    return redirect(url_for("pages.notifications"))