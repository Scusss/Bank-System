from flask import Blueprint, render_template, abort, redirect, url_for, flash

from app.models import Account, Customer, TransactionList

pages = Blueprint("pages", __name__)


@pages.route("/")
def home():
    account = db_account()

    balance = account.balance if account else 0

    return render_template("home.html", balance=balance)


@pages.route("/account")
def account_page():
    account = db_account()
    customer = Customer.query.get(1)

    if customer is None:
        abort(404, description="Customer not found.")

    balance = account.balance if account else 0

    return render_template(
        "account.html",
        balance=balance,
        fname=customer.first_name,
        lname=customer.last_name,
        email=customer.email,
    )


@pages.route("/<operation>")
def bank_page(operation):
    valid_operations = {
        "deposit",
        "withdraw",
        "transfer",
        "receipts",
    }

    if operation not in valid_operations:
        abort(404)

    return render_template(f"{operation}.html")

@pages.route("/withdraw")
def withdraw():
    return render_template("withdraw.html")

@pages.route("/transfer")
def transfer():
    return render_template("transfer.html")

@pages.route("/receipts")
def receipts():
    # Current account ID, following your existing implementation.
    account_id = 1

    account = Account.query.filter_by(
        account_id=account_id
    ).first()

    if account is None:
        flash("Account not found.", "error")
        return redirect(url_for("pages.home"))

    receipts = (
        TransactionList.query
        .filter_by(account_id=account_id)
        .order_by(TransactionList.created_at.asc())
        .all()
    )

    return render_template(
        "receipts.html",
        receipts=receipts,
        account=account,
    )

def db_account():
    return Account.query.get(1)