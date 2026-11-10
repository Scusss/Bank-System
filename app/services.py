"""Shared business logic for user accounts, identity verification and
bank account requests.

A *user account* (``AppUser``) holds login and personal information.
A *bank account* (``Account``) holds money only and is created after the user
has been verified and an administrator has approved the request.
"""

import re
import secrets
import string
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from flask import request, session
from sqlalchemy import func, or_

from app.extensions import db
from app.models import (
    Account,
    AccountApplication,
    AccountLimitOverride,
    AccountSelfLimit,
    AccountTypeLimit,
    AppUser,
    AuditLog,
    IdentityVerification,
    Notification,
    TransactionList,
)

# --------------------------------------------------
# Constants
# --------------------------------------------------

ROLE_CUSTOMER = "customer"
ROLE_ADMIN = "admin"
ROLE_VERIFICATION_OFFICER = "verification_officer"

VERIFICATION_PENDING = "pending"
# Must match the database check constraint valid_verification_status
# (pending, approved, rejected, requires_resubmission).
VERIFICATION_VERIFIED = "approved"
VERIFICATION_REJECTED = "rejected"

APPLICATION_PENDING = "pending"
APPLICATION_APPROVED = "approved"
APPLICATION_REJECTED = "rejected"

# Used only when the account_type_limits table has no active rows.
DEFAULT_ACCOUNT_TYPES = ["savings", "checking", "business"]

# --------------------------------------------------
# Roles
# --------------------------------------------------

def role_name(user):
    if user is None or user.role is None:
        return ""
    return user.role.role_name.strip().lower()


def is_admin(user):
    return role_name(user) == ROLE_ADMIN


def is_verification_officer(user):
    return role_name(user) == ROLE_VERIFICATION_OFFICER


def is_staff(user):
    """Admins and verification officers use their own consoles."""
    return is_admin(user) or is_verification_officer(user)


# --------------------------------------------------
# Audit log and notifications
# --------------------------------------------------

def write_audit(
    action,
    entity_type=None,
    entity_id=None,
    description=None,
    subject_id=None,
    old_values=None,
    new_values=None,
    actor=None,
):
    """Add an audit entry to the current DB session (caller commits).

    ``subject_id`` is the user the action affects; the actor is the signed-in
    user (or ``actor`` when given, e.g. at registration).
    """
    try:
        actor_user = actor or db.session.get(
            AppUser, UUID(str(session.get("customer_id")))
        )
        actor_id = actor_user.user_id

        db.session.add(
            AuditLog(
                customer_id=subject_id or actor_id,
                performed_by=actor_id,
                performed_by_role=role_name(actor_user) or None,
                action=action,
                entity_type=entity_type,
                entity_id=str(entity_id) if entity_id is not None else None,
                old_values=old_values,
                new_values=new_values,
                description=description,
                ip_address=request.remote_addr,
            )
        )
    except Exception:
        # Audit logging must not hide the primary operation.
        pass


def notify(user_id, title, message, notification_type="account"):
    """Add a notification to the current DB session (caller commits)."""
    db.session.add(
        Notification(
            customer_id=user_id,
            title=title,
            message=message,
            notification_type=notification_type,
            is_read=False,
        )
    )


# --------------------------------------------------
# Identity verification
# --------------------------------------------------

REQUIRED_PROFILE_FIELDS = [
    ("first_name", "first name"),
    ("last_name", "last name"),
    ("birth_date", "birth date"),
    ("phone_number", "phone number"),
    ("address", "address"),
]


def missing_profile_fields(details):
    """Names of required personal details that are still empty."""
    if details is None:
        return [label for _, label in REQUIRED_PROFILE_FIELDS]
    return [
        label
        for field, label in REQUIRED_PROFILE_FIELDS
        if not getattr(details, field, None)
        or (isinstance(getattr(details, field), str)
            and not getattr(details, field).strip())
    ]


def latest_verification(user_id):
    return (
        IdentityVerification.query
        .filter_by(customer_id=user_id)
        .order_by(IdentityVerification.submitted_at.desc(),
                  IdentityVerification.verification_id.desc())
        .first()
    )


def is_verified(user_id):
    return (
        db.session.query(IdentityVerification.verification_id)
        .filter_by(
            customer_id=user_id,
            verification_status=VERIFICATION_VERIFIED,
        )
        .first()
        is not None
    )


def verification_state(user_id):
    """Return ``(state, record)``.

    state is one of: unverified, pending, verified, rejected.
    A verified user stays verified even if an older request was rejected.
    """
    if is_verified(user_id):
        record = (
            IdentityVerification.query
            .filter_by(
                customer_id=user_id,
                verification_status=VERIFICATION_VERIFIED,
            )
            .order_by(IdentityVerification.reviewed_at.desc())
            .first()
        )
        return "verified", record

    record = latest_verification(user_id)
    if record is None:
        return "unverified", None
    return record.verification_status, record


# --------------------------------------------------
# Bank types and bank account requests
# --------------------------------------------------

def available_bank_types():
    """Bank types a user may request (active rows in account_type_limits)."""
    rows = (
        db.session.query(AccountTypeLimit.account_type)
        .filter(AccountTypeLimit.is_active.is_(True))
        .distinct()
        .order_by(AccountTypeLimit.account_type.asc())
        .all()
    )
    types = [row[0] for row in rows]
    return types or list(DEFAULT_ACCOUNT_TYPES)


def bank_type_states(user_id):
    """One entry per bank type describing what the user may do with it.

    state: available | pending | approved | rejected
    A type can be requested once; it can only be requested again after a
    rejection.
    """
    applications = (
        AccountApplication.query
        .filter_by(customer_id=user_id)
        .order_by(AccountApplication.submitted_at.desc(),
                  AccountApplication.application_id.desc())
        .all()
    )
    accounts = (
        Account.query
        .filter_by(customer_id=user_id)
        .order_by(Account.account_id.asc())
        .all()
    )

    states = []
    for bank_type in available_bank_types():
        type_apps = [a for a in applications if a.account_type == bank_type]
        account = next(
            (a for a in accounts if a.account_type == bank_type), None
        )

        if account is not None or any(
            a.application_status == APPLICATION_APPROVED for a in type_apps
        ):
            state = APPLICATION_APPROVED
        elif any(a.application_status == APPLICATION_PENDING
                 for a in type_apps):
            state = APPLICATION_PENDING
        elif type_apps:
            state = APPLICATION_REJECTED
        else:
            state = "available"

        states.append({
            "type": bank_type,
            "label": bank_type.replace("_", " ").title(),
            "state": state,
            "application": type_apps[0] if type_apps else None,
            "account": account,
        })
    return states


# --------------------------------------------------
# Bank accounts
# --------------------------------------------------

def generate_unique_account_number():
    """Generate an 8-digit account number formatted as XXXX-XXXX that is not in use."""
    for _ in range(10):
        digits = "".join(secrets.choice(string.digits) for _ in range(8))
        number = f"{digits[:4]}-{digits[4:]}"
        if Account.query.filter_by(account_number=number).first() is None:
            return number
    raise RuntimeError("Unable to generate a unique account number.")


def normalize_account_number(value):
    """Return an account number in XXXX-XXXX form, or None if it is malformed.

    Accepts "12340001" as well as "1234-0001" (spaces are ignored).
    """
    cleaned = (value or "").replace(" ", "").strip()
    if re.fullmatch(r"\d{8}", cleaned):
        cleaned = f"{cleaned[:4]}-{cleaned[4:]}"
    if re.fullmatch(r"\d{4}-\d{4}", cleaned):
        return cleaned
    return None


def mask_account_number(number):
    """Mask the first 4 digits of an XXXX-XXXX account number: ****-5678."""
    number = (number or "").strip()
    if not number:
        return "—"
    if "-" in number:
        return "****-" + number.split("-", 1)[1]
    return "****" + number[4:] if len(number) > 4 else "****"


def find_account_by_number(value):
    """Look up a bank account by its customer-facing account number."""
    number = normalize_account_number(value)
    if number is None:
        return None
    return Account.query.filter_by(account_number=number).first()


def user_accounts(user_id):
    return (
        Account.query
        .filter_by(customer_id=user_id)
        .order_by(Account.account_id.asc())
        .all()
    )


def selected_account(user_id):
    """The bank account the user is currently working with.

    Uses the account chosen in the account switcher (kept in the session)
    when it belongs to the user, otherwise the user's first account.
    Returns ``None`` when the user has no bank account yet.
    """
    accounts = user_accounts(user_id)
    if not accounts:
        return None

    chosen = session.get("account_id")
    for account in accounts:
        if str(account.account_id) == str(chosen):
            return account
    return accounts[0]


# --------------------------------------------------
# Daily limits
# --------------------------------------------------

# Daily limits reset at midnight bank time.
BANK_TIMEZONE = ZoneInfo("Asia/Manila")

# kind -> (limit column, transaction_list.transaction_type it counts)
LIMIT_KINDS = {
    "withdrawal": ("daily_withdrawal_limit", "withdrawal"),
    "transfer": ("daily_transfer_limit", "transfer_out"),
}


def _today_bounds():
    start = datetime.combine(
        datetime.now(BANK_TIMEZONE).date(), time.min, tzinfo=BANK_TIMEZONE
    )
    return start, start + timedelta(days=1)


def daily_used(account_id, transaction_type):
    """Total completed amount of one transaction type for today."""
    start, end = _today_bounds()
    total = (
        db.session.query(func.coalesce(func.sum(TransactionList.amount), 0))
        .filter(
            TransactionList.account_id == account_id,
            TransactionList.transaction_type == transaction_type,
            TransactionList.status == "completed",
            TransactionList.created_at >= start,
            TransactionList.created_at < end,
        )
        .scalar()
    )
    return Decimal(total or 0)


def account_limits(account):
    """Daily limits for one bank account.

    For each kind (withdrawal, transfer) returns:
      cap   - the bank's maximum (active admin override, else the account
              type limit); ``None`` means the bank sets no daily maximum
      mine  - the limit the customer set, or ``None``
      used  - completed amount today
      remaining - what is left under ``mine`` today (``None`` if not set)
    """
    type_row = (
        AccountTypeLimit.query
        .filter_by(account_type=account.account_type, is_active=True)
        .order_by(AccountTypeLimit.limit_id.desc())
        .first()
    )
    override = (
        AccountLimitOverride.query
        .filter(
            AccountLimitOverride.account_id == account.account_id,
            or_(
                AccountLimitOverride.expires_at.is_(None),
                AccountLimitOverride.expires_at > datetime.now(timezone.utc),
            ),
        )
        .order_by(AccountLimitOverride.created_at.desc(),
                  AccountLimitOverride.override_id.desc())
        .first()
    )
    own = db.session.get(AccountSelfLimit, account.account_id)

    result = {}
    for kind, (column, tx_type) in LIMIT_KINDS.items():
        cap = getattr(override, column, None) if override else None
        if cap is None and type_row is not None:
            cap = getattr(type_row, column)
        mine = getattr(own, column, None) if own else None
        used = daily_used(account.account_id, tx_type)
        result[kind] = {
            "column": column,
            "cap": cap,
            "mine": mine,
            "used": used,
            "remaining": max(mine - used, Decimal("0")) if mine is not None
            else None,
        }
    return result
