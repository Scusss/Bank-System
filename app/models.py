
import enum
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import UUID, INET, JSONB

from app.extensions import db

# External Supabase Auth table reference.
# Registers auth.users in SQLAlchemy metadata (not managed by Flask).
auth_users = db.Table(
    "users",
    db.metadata,
    db.Column("id", UUID(as_uuid=True), primary_key=True),
    schema="auth",
)


# =========================================================
# ENUMS
# =========================================================

class TransactionType(enum.Enum):
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    LOAN_DISBURSEMENT = "loan_disbursement"
    LOAN_PAYMENT = "loan_payment"
    ADJUSTMENT = "adjustment"


# =========================================================
# ROLES
# =========================================================

class Role(db.Model):
    __tablename__ = "roles"

    role_id = db.Column(db.SmallInteger, primary_key=True)
    role_name = db.Column(db.String(30), unique=True, nullable=False)
    description = db.Column(db.Text)


# =========================================================
# APP USERS  (the USER account - no bank data lives here)
# =========================================================

class AppUser(db.Model):
    __tablename__ = "app_users"

    user_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("auth.users.id", ondelete="RESTRICT"),
        primary_key=True
    )

    role_id = db.Column(
        db.SmallInteger,
        db.ForeignKey("roles.role_id"),
        nullable=False
    )

    username = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )

    email = db.Column(
        db.String(150),
        unique=True,
        nullable=False
    )

    is_locked = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )

    account_status = db.Column(
        db.String(30),
        nullable=False,
        default="active"
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now()
    )

    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now()
    )

    role = db.relationship("Role")

    # Account information (name, phone, birth date, address) belongs to the
    # user account, not to any bank account.
    details = db.relationship(
        "CustomerDetails",
        back_populates="user",
        uselist=False
    )

    accounts = db.relationship(
        "Account",
        back_populates="owner",
        order_by="Account.account_id"
    )


# =========================================================
# ACCOUNT APPLICATIONS
# =========================================================

class AccountApplication(db.Model):
    __tablename__ = "account_applications"
    __table_args__ = (
        # A user can request each bank type only once while the request is
        # pending or approved (a rejected request may be re-submitted).
        db.Index(
            "uq_account_applications_active_type",
            "customer_id",
            "account_type",
            unique=True,
            postgresql_where=db.text(
                "application_status IN ('pending', 'approved')"
            ),
        ),
    )

    application_id = db.Column(
        db.BigInteger,
        primary_key=True
    )

    customer_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("app_users.user_id"),
        nullable=False
    )

    account_type = db.Column(
        db.String(50),
        nullable=False
    )

    application_status = db.Column(
        db.String(30),
        nullable=False
    )

    reviewed_by = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("app_users.user_id")
    )

    review_remarks = db.Column(db.Text)

    submitted_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now()
    )

    reviewed_at = db.Column(
        db.DateTime(timezone=True)
    )

    resulting_account_id = db.Column(
        db.BigInteger,
        db.ForeignKey("accounts.account_id")
    )

    customer = db.relationship("AppUser", foreign_keys=[customer_id])
    reviewer = db.relationship("AppUser", foreign_keys=[reviewed_by])
    resulting_account = db.relationship(
        "Account", foreign_keys=[resulting_account_id]
    )


# =========================================================
# ACCOUNT TYPE LIMITS
# =========================================================

class AccountTypeLimit(db.Model):
    __tablename__ = "account_type_limits"

    limit_id = db.Column(
        db.BigInteger,
        primary_key=True
    )

    account_type = db.Column(
        db.String(50),
        nullable=False
    )

    minimum_balance = db.Column(
        db.Numeric(19, 2),
        nullable=False
    )

    maximum_balance = db.Column(
        db.Numeric(19, 2)
    )

    minimum_deposit = db.Column(
        db.Numeric(19, 2),
        nullable=False
    )

    maximum_deposit = db.Column(
        db.Numeric(19, 2)
    )

    minimum_withdrawal = db.Column(
        db.Numeric(19, 2),
        nullable=False
    )

    maximum_withdrawal = db.Column(
        db.Numeric(19, 2)
    )

    daily_withdrawal_limit = db.Column(
        db.Numeric(19, 2)
    )

    daily_transfer_limit = db.Column(
        db.Numeric(19, 2)
    )

    transfer_fee = db.Column(
        db.Numeric(19, 2),
        nullable=False
    )

    is_active = db.Column(
        db.Boolean,
        nullable=False,
        default=True
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now()
    )

    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now()
    )


# =========================================================
# ACCOUNTS
# =========================================================

class Account(db.Model):
    __tablename__ = "accounts"

    account_id = db.Column(
        db.BigInteger,
        primary_key=True
    )

    customer_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("app_users.user_id"),
        nullable=False
    )

    account_number = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )

    account_type = db.Column(
        db.String(50),
        nullable=False
    )

    balance = db.Column(
        db.Numeric(19, 2),
        nullable=False,
        default=0
    )

    currency = db.Column(
        db.String(3),
        nullable=False,
        default="PHP"
    )

    status = db.Column(
        db.String(30),
        nullable=False,
        default="active"
    )

    frozen_at = db.Column(
        db.DateTime(timezone=True)
    )

    closed_at = db.Column(
        db.DateTime(timezone=True)
    )

    status_reason = db.Column(
        db.Text
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now()
    )

    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now()
    )

    owner = db.relationship("AppUser", back_populates="accounts")


# =========================================================
# ACCOUNT LIMIT OVERRIDES
# =========================================================

class AccountLimitOverride(db.Model):
    __tablename__ = "account_limit_overrides"

    override_id = db.Column(
        db.BigInteger,
        primary_key=True
    )

    account_id = db.Column(
        db.BigInteger,
        db.ForeignKey("accounts.account_id"),
        nullable=False
    )

    daily_transfer_limit = db.Column(
        db.Numeric(19, 2)
    )

    daily_withdrawal_limit = db.Column(
        db.Numeric(19, 2)
    )

    reason = db.Column(
        db.Text,
        nullable=False
    )

    approved_by = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("app_users.user_id"),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now()
    )

    expires_at = db.Column(
        db.DateTime(timezone=True)
    )

# =========================================================
# ACCOUNT SELF-SET LIMITS
# =========================================================

class AccountSelfLimit(db.Model):
    """Daily limits a customer sets on their own bank account.

    These can only be at or below the bank's maximum (account type limit /
    admin override), so they never raise what the bank allows.
    """
    __tablename__ = "account_self_limits"

    account_id = db.Column(
        db.BigInteger,
        db.ForeignKey("accounts.account_id", ondelete="CASCADE"),
        primary_key=True
    )

    daily_withdrawal_limit = db.Column(
        db.Numeric(19, 2)
    )

    daily_transfer_limit = db.Column(
        db.Numeric(19, 2)
    )

    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now()
    )

# =========================================================
# CUSTOMER DETAILS
# =========================================================

class CustomerDetails(db.Model):
    __tablename__ = "customer_details"

    detail_id = db.Column(
        db.BigInteger,
        primary_key=True
    )

    customer_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("app_users.user_id"),
        unique=True,
        nullable=False
    )

    first_name = db.Column(
        db.String(100),
        nullable=False
    )

    middle_name = db.Column(
        db.String(100)
    )

    last_name = db.Column(
        db.String(100),
        nullable=False
    )

    suffix = db.Column(
        db.String(20)
    )

    phone_number = db.Column(
        db.String(20)
    )

    birth_date = db.Column(
        db.Date
    )

    address = db.Column(
        db.Text
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now()
    )

    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now(),
        onupdate=db.func.now()
    )

    user = db.relationship("AppUser", back_populates="details")


# =========================================================
# BENEFICIARIES
# =========================================================

class Beneficiary(db.Model):
    __tablename__ = "beneficiaries"

    beneficiary_id = db.Column(
        db.BigInteger,
        primary_key=True
    )

    customer_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("app_users.user_id"),
        nullable=False
    )

    beneficiary_name = db.Column(
        db.String(150),
        nullable=False
    )

    account_number = db.Column(
        db.String(50),
        nullable=False
    )

    bank_name = db.Column(
        db.String(100),
        nullable=False
    )

    nickname = db.Column(
        db.String(50)
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now()
    )


# =========================================================
# IDENTITY VERIFICATIONS
# =========================================================

class IdentityVerification(db.Model):
    __tablename__ = "identity_verifications"
    __table_args__ = (
        # Only one pending verification request per user at a time.
        db.Index(
            "uq_identity_verifications_one_pending",
            "customer_id",
            unique=True,
            postgresql_where=db.text("verification_status = 'pending'"),
        ),
    )

    verification_id = db.Column(
        db.BigInteger,
        primary_key=True
    )

    customer_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("app_users.user_id"),
        nullable=False
    )

    # Not used by the button-only verification flow; kept optional.
    document_type = db.Column(
        db.String(50)
    )

    document_reference = db.Column(
        db.Text
    )

    verification_status = db.Column(
        db.String(30),
        nullable=False
    )

    review_remarks = db.Column(
        db.Text
    )

    reviewed_by = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("app_users.user_id")
    )

    submitted_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now()
    )

    reviewed_at = db.Column(
        db.DateTime(timezone=True)
    )

    customer = db.relationship("AppUser", foreign_keys=[customer_id])
    reviewer = db.relationship("AppUser", foreign_keys=[reviewed_by])


# =========================================================
# LOANS
# =========================================================

class Loan(db.Model):
    __tablename__ = "loans"

    loan_id = db.Column(
        db.BigInteger,
        primary_key=True
    )

    customer_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("app_users.user_id"),
        nullable=False
    )

    account_id = db.Column(
        db.BigInteger,
        db.ForeignKey("accounts.account_id")
    )


# =========================================================
# LOAN PAYMENTS
# =========================================================

class LoanPayment(db.Model):
    __tablename__ = "loan_payments"

    payment_id = db.Column(
        db.BigInteger,
        primary_key=True
    )

    loan_id = db.Column(
        db.BigInteger,
        db.ForeignKey("loans.loan_id"),
        nullable=False
    )

    transaction_id = db.Column(
        db.BigInteger
    )

    payment_reference = db.Column(
        db.String(60),
        nullable=False
    )

    payment_amount = db.Column(
        db.Numeric(19, 2),
        nullable=False
    )

    payment_date = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now()
    )

    payment_status = db.Column(
        db.String(30),
        nullable=False
    )


# =========================================================
# TRANSACTIONS
# =========================================================

class TransactionList(db.Model):
    __tablename__ = "transaction_list"

    transaction_id = db.Column(db.BigInteger, primary_key=True)

    account_id = db.Column(
        db.BigInteger,
        db.ForeignKey("accounts.account_id"),
        nullable=False
    )

    reference_number = db.Column(
        db.String(60), unique=True, nullable=False
    )

    transaction_type = db.Column(db.String(30), nullable=False)
    amount = db.Column(db.Numeric(19, 2), nullable=False)
    balance_before = db.Column(db.Numeric(19, 2))
    balance_after = db.Column(db.Numeric(19, 2))
    description = db.Column(db.Text)

    status = db.Column(
        db.String(20), nullable=False, default="completed"
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now()
    )


# =========================================================
# LOGIN HISTORY
# =========================================================

class LoginHistory(db.Model):
    __tablename__ = "login_history"

    login_id = db.Column(db.BigInteger, primary_key=True)

    customer_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("app_users.user_id", ondelete="SET NULL"),
        nullable=True
    )

    username_attempted = db.Column(db.String(50))
    ip_address = db.Column(INET)
    device_info = db.Column(db.Text)
    login_status = db.Column(db.String(20), nullable=False)

    login_time = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now()
    )


# =========================================================
# NOTIFICATIONS
# =========================================================

class Notification(db.Model):
    __tablename__ = "notifications"

    notification_id = db.Column(db.BigInteger, primary_key=True)

    customer_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("app_users.user_id"),
        nullable=False
    )

    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    notification_type = db.Column(db.String(30))
    is_read = db.Column(db.Boolean, nullable=False, default=False)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now()
    )


# =========================================================
# AUDIT LOGS
# =========================================================

class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    log_id = db.Column(
        db.BigInteger,
        primary_key=True
    )

    customer_id = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("app_users.user_id")
    )

    performed_by = db.Column(
        UUID(as_uuid=True),
        db.ForeignKey("app_users.user_id")
    )

    performed_by_role = db.Column(
        db.String(50)
    )

    action = db.Column(
        db.String(100),
        nullable=False
    )

    entity_type = db.Column(
        db.String(50)
    )

    entity_id = db.Column(
        db.Text
    )

    old_values = db.Column(
        JSONB
    )

    new_values = db.Column(
        JSONB
    )

    description = db.Column(
        db.Text
    )

    ip_address = db.Column(
        INET
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=db.func.now()
    )
