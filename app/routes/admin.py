import logging
from functools import wraps
from uuid import UUID

from datetime import datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import func, select

from app.extensions import db
from app.models import (
    Account,
    AccountApplication,
    AppUser,
    AuditLog,
    CustomerDetails,
    IdentityVerification,
    LoginHistory,
    Role,
    TransactionList,
)
from app.services import (
    APPLICATION_APPROVED,
    APPLICATION_PENDING,
    APPLICATION_REJECTED,
    VERIFICATION_PENDING,
    VERIFICATION_VERIFIED,
    available_bank_types,
    generate_unique_account_number,
    is_admin,
    is_verified,
    notify,
    write_audit,
)

admin = Blueprint("admin", __name__, url_prefix="/admin")
logger = logging.getLogger(__name__)


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        customer_id = session.get("customer_id")
        if not customer_id:
            flash("Please log in to continue.", "error")
            return redirect(url_for("auth.login"))
        try:
            customer = db.session.get(AppUser, UUID(str(customer_id)))
        except (ValueError, TypeError, AttributeError):
            customer = None
        if (customer is None or customer.is_locked or customer.account_status != "active"):
            session.clear()
            flash("Your account is unavailable. Please log in again.", "error")
            return redirect(url_for("auth.login"))
        if not is_admin(customer):
            abort(403)
        return view(*args, **kwargs)
    return wrapped


@admin.route("/")
@admin_required
def dashboard():
    total_customers = AppUser.query.count()
    pending_verifications = IdentityVerification.query.filter_by(
        verification_status=VERIFICATION_PENDING
    ).count()
    pending_applications = AccountApplication.query.filter_by(
        application_status=APPLICATION_PENDING
    ).count()
    total_accounts = Account.query.count()
    total_transactions = TransactionList.query.count()
    total_balance = db.session.query(func.coalesce(func.sum(Account.balance), 0)).scalar()
    recent_transactions = TransactionList.query.order_by(TransactionList.created_at.desc()).limit(12).all()
    recent_logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(12).all()
    return render_template(
        "admin.html",
        view_name="dashboard",
        total_customers=total_customers,
        pending_verifications=pending_verifications,
        pending_applications=pending_applications,
        total_accounts=total_accounts,
        total_transactions=total_transactions,
        total_balance=total_balance,
        recent_transactions=recent_transactions,
        recent_logs=recent_logs,
    )


@admin.route("/users")
@admin_required
def users():
    customers = AppUser.query.order_by(AppUser.created_at.desc()).all()
    roles = Role.query.order_by(Role.role_name.asc()).all()
    verified_ids = {
        str(row[0]) for row in db.session.query(
            IdentityVerification.customer_id
        ).filter_by(verification_status=VERIFICATION_VERIFIED).distinct()
    }
    details_by_id = {str(d.customer_id): d for d in CustomerDetails.query.all()}
    accounts_by_customer = {}
    for account in Account.query.order_by(Account.account_id.asc()).all():
        accounts_by_customer.setdefault(str(account.customer_id), []).append(account)
    return render_template(
        "admin.html", view_name="users", customers=customers, roles=roles,
        details_by_id=details_by_id, accounts_by_customer=accounts_by_customer,
        verified_ids=verified_ids,
    )


@admin.route("/users/<uuid:customer_id>/role", methods=["POST"])
@admin_required
def update_role(customer_id):
    target = db.session.get(AppUser, customer_id)
    role_id = request.form.get("role_id", type=int)
    role = db.session.get(Role, role_id) if role_id is not None else None
    if target is None or role is None:
        flash("Customer or role was not found.", "error")
        return redirect(url_for("admin.users"))
    actor_id = UUID(str(session.get("customer_id")))
    if target.user_id == actor_id and role.role_name.strip().lower() != "admin":
        flash("You cannot remove your own admin role here.", "error")
        return redirect(url_for("admin.users"))
    old_role = target.role.role_name if target.role else "unknown"
    target.role_id = role.role_id
    write_audit(
        "customer_role_changed", "app_user", target.user_id,
        f"Changed role for username '{target.username}' from '{old_role}' to '{role.role_name}'.",
        subject_id=target.user_id,
    )
    try:
        db.session.commit()
        flash(f"Updated {target.username}'s role to {role.role_name}.", "success")
    except Exception:
        db.session.rollback()
        flash("Could not update the role. Please try again.", "error")
    return redirect(url_for("admin.users"))


@admin.route("/users/<uuid:customer_id>/status", methods=["POST"])
@admin_required
def update_account_status(customer_id):
    target = db.session.get(AppUser, customer_id)
    new_status = (request.form.get("account_status") or "").strip().lower()
    if target is None:
        flash("Customer was not found.", "error")
        return redirect(url_for("admin.users"))
    if new_status not in {"active", "frozen", "closed"}:
        flash("Choose a valid account status.", "error")
        return redirect(url_for("admin.users"))
    actor_id = UUID(str(session.get("customer_id")))
    if target.user_id == actor_id and new_status != "active":
        flash("You cannot freeze or close your own administrator account.", "error")
        return redirect(url_for("admin.users"))

    old_status = target.account_status or "active"
    target.account_status = new_status
    # Keep the legacy lock flag synchronized for existing checks/integrations.
    target.is_locked = new_status != "active"
    write_audit(
        "customer_account_status_changed", "app_user", target.user_id,
        f"Changed account status for username '{target.username}' from '{old_status}' to '{new_status}'.",
        subject_id=target.user_id,
    )
    try:
        db.session.commit()
        flash(f"{target.username}'s account status is now {new_status.title()}.", "success")
    except Exception:
        db.session.rollback()
        flash("Could not update the account status. Please try again.", "error")
    return redirect(url_for("admin.users"))


@admin.route("/transactions")
@admin_required
def transactions():
    items = TransactionList.query.order_by(TransactionList.created_at.desc()).limit(250).all()
    account_ids = {item.account_id for item in items}
    accounts = Account.query.filter(Account.account_id.in_(account_ids)).all() if account_ids else []
    accounts_by_id = {account.account_id: account for account in accounts}
    customers = AppUser.query.all()
    customers_by_id = {str(customer.user_id): customer for customer in customers}
    return render_template(
        "admin.html", view_name="transactions", transactions=items,
        accounts_by_id=accounts_by_id, customers_by_id=customers_by_id,
    )


@admin.route("/audit-logs")
@admin_required
def audit_logs():
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(250).all()
    actor_ids = {(log.performed_by or log.customer_id) for log in logs if (log.performed_by or log.customer_id)}
    actors = AppUser.query.filter(AppUser.user_id.in_(actor_ids)).all() if actor_ids else []
    actors_by_id = {str(customer.user_id): customer for customer in actors}
    return render_template("admin.html", view_name="audit", logs=logs, actors_by_id=actors_by_id)


@admin.route("/login-history")
@admin_required
def login_history():
    entries = LoginHistory.query.order_by(LoginHistory.login_time.desc()).limit(250).all()
    return render_template("admin.html", view_name="login_history", entries=entries)


# --------------------------------------------------
# BANK ACCOUNT REQUESTS
# --------------------------------------------------

@admin.route("/account-requests")
@admin_required
def account_requests():
    applications = (
        AccountApplication.query
        .order_by(
            (AccountApplication.application_status == APPLICATION_PENDING).desc(),
            AccountApplication.submitted_at.desc(),
        )
        .limit(250)
        .all()
    )
    user_ids = {a.customer_id for a in applications}
    users = AppUser.query.filter(AppUser.user_id.in_(user_ids)).all() if user_ids else []
    details = CustomerDetails.query.filter(CustomerDetails.customer_id.in_(user_ids)).all() if user_ids else []
    return render_template(
        "admin.html", view_name="account_requests", applications=applications,
        users_by_id={str(u.user_id): u for u in users},
        details_by_id={str(d.customer_id): d for d in details},
        pending_status=APPLICATION_PENDING,
    )


@admin.route("/account-requests/<int:application_id>/review", methods=["POST"])
@admin_required
def review_account_request(application_id):
    decision = (request.form.get("decision") or "").strip().lower()
    remarks = (request.form.get("remarks") or "").strip()[:1000]
    if decision not in {"approve", "reject"}:
        flash("Choose approve or reject.", "error")
        return redirect(url_for("admin.account_requests"))
    if decision == "reject" and not remarks:
        flash("Enter a reason when rejecting a request.", "error")
        return redirect(url_for("admin.account_requests"))

    application = db.session.execute(
        select(AccountApplication)
        .where(AccountApplication.application_id == application_id)
        .with_for_update()
    ).scalar_one_or_none()
    if application is None:
        flash("Request was not found.", "error")
        return redirect(url_for("admin.account_requests"))
    if application.application_status != APPLICATION_PENDING:
        db.session.rollback()
        flash("This request has already been reviewed.", "error")
        return redirect(url_for("admin.account_requests"))

    actor_id = UUID(str(session.get("customer_id")))
    label = application.account_type.replace("_", " ").title()
    now = datetime.now(timezone.utc)

    if decision == "approve":
        if not is_verified(application.customer_id):
            db.session.rollback()
            flash("The applicant is not identity-verified.", "error")
            return redirect(url_for("admin.account_requests"))
        if application.account_type not in available_bank_types():
            db.session.rollback()
            flash("That bank account type is no longer offered.", "error")
            return redirect(url_for("admin.account_requests"))
        if Account.query.filter_by(
            customer_id=application.customer_id,
            account_type=application.account_type,
        ).first():
            db.session.rollback()
            flash("The user already has an account of this type.", "error")
            return redirect(url_for("admin.account_requests"))

        account = Account(
            customer_id=application.customer_id,
            account_number=generate_unique_account_number(),
            account_type=application.account_type,
            balance=0,
            currency="PHP",
            status="active",
        )
        db.session.add(account)
        db.session.flush()
        application.resulting_account_id = account.account_id
        application.application_status = APPLICATION_APPROVED
        notify(
            application.customer_id, f"{label} account approved",
            f"Your {label} account request was approved. Account number: "
            f"{account.account_number}.",
        )
    else:
        application.application_status = APPLICATION_REJECTED
        notify(
            application.customer_id, f"{label} account request declined",
            f"Your {label} account request was declined. Reason: {remarks}",
        )

    application.reviewed_by = actor_id
    application.reviewed_at = now
    application.review_remarks = remarks or None
    write_audit(
        f"bank_account_request_{application.application_status}",
        "account_application", application.application_id,
        f"{decision.title()}d {label} account request.",
        subject_id=application.customer_id,
    )
    try:
        db.session.commit()
        flash(f"Request {application.application_status}.", "success")
    except Exception:
        db.session.rollback()
        logger.exception("Could not save the review.")
        flash("Could not save the review. Please try again.", "error")
    return redirect(url_for("admin.account_requests"))
