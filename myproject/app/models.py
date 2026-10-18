import enum
from datetime import datetime

from app.extensions import db


class TransactionType(enum.Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAW = "WITHDRAW"
    TRANSFER = "TRANSFER"


class Customer(db.Model):
    __tablename__ = "customer"

    customer_id = db.Column(
        db.Integer, primary_key=True, autoincrement=True
    )
    username = db.Column(
        db.String(50), unique=True, nullable=False
    )
    acc_password = db.Column(
        db.String(255), nullable=False
    )
    first_name = db.Column(
        db.String(100), nullable=False
    )
    last_name = db.Column(
        db.String(100), nullable=False
    )
    email = db.Column(
        db.String(100), unique=True, nullable=False
    )
    failed_attempts = db.Column(
        db.Integer, default=0, nullable=False
    )
    is_locked = db.Column(
        db.Boolean, default=False, nullable=False
    )


class Account(db.Model):
    __tablename__ = "accounts"

    account_id = db.Column(db.Integer, primary_key=True)
    account_number = db.Column(
        db.String(100), nullable=False
    )
    customer_id = db.Column(
        db.Integer,
        db.ForeignKey("customer.customer_id"),
        nullable=False,
    )
    balance = db.Column(
        db.Numeric(15, 2), default=0.00, nullable=False
    )

    __table_args__ = (
        db.CheckConstraint(
            "balance >= 0",
            name="check_balance_positive",
        ),
    )


class TransactionList(db.Model):
    __tablename__ = "transaction_list"

    transaction_id = db.Column(
        db.Integer, primary_key=True, autoincrement=True
    )
    account_id = db.Column(
        db.Integer,
        db.ForeignKey("accounts.account_id"),
        nullable=False,
    )
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    type_of_transaction = db.Column(
        db.Enum(TransactionType), nullable=False
    )
    created_at = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False
    )