from flask import Blueprint, render_template, abort, redirect, url_for, flash, session
from functools import wraps

from app.models import Account, Customer, TransactionList

pages = Blueprint("pages", __name__)

def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "customer_id" not in session:
            flash("Please log in to continue.")
            return redirect(url_for("auth.login"))

        return view(*args, **kwargs)

    return wrapped_view

def get_current_customer():
    customer_id = session.get("customer_id")

    customer = db.session.get(Customer, customer_id)

    if customer is None:
        session.clear()
        abort(401)

    return customer

def get_customer_account(customer):
    return Account.query.filter_by(
        customer_id=customer.customer_id
    ).order_by(Account.account_id.asc()).first()


from app.extensions import db


@pages.route("/")
@login_required
def home():
    customer = get_current_customer()
    account = get_customer_account(customer)

    balance = account.balance if account else 0

    return render_template(
        "home.html",
        balance=balance,
        username=customer.username,
        first_name=customer.first_name,
        last_name=customer.last_name,
    )



@pages.route("/account")
@login_required
def account_page():
    customer = get_current_customer()
    account = get_customer_account(customer)

    balance = account.balance if account else 0

    return render_template(
        "account.html",
        balance=balance,
        fname=customer.first_name,
        lname=customer.last_name,
        email=customer.email,
    )


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

    return render_template(f"{operation}.html")

@pages.route("/receipts")
@login_required
def receipts():
    customer = get_current_customer()
    account = get_customer_account(customer)

    if account is None:
        flash("No bank account is associated with your profile.")
        return redirect(url_for("pages.home"))

    transactions = (
        TransactionList.query
        .filter_by(account_id=account.account_id)
        .order_by(TransactionList.created_at.desc())
        .all()
    )

    return render_template(
        "receipts.html",
        receipts=transactions,
        account=account,
    )
