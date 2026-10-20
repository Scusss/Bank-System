
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request, redirect, url_for, flash, session
from sqlalchemy import select

from app.extensions import db
from app.models import Account, TransactionList, TransactionType

transactions = Blueprint("transactions", __name__)


@transactions.route("/transaction/<operation>", methods=["POST"])
def transaction(operation):
    if operation not in {"deposit", "withdraw", "transfer"}:
        flash("Invalid transaction operation.", "error")
        return redirect(url_for("pages.home"))

    customer_id = session.get("customer_id")

    if customer_id is None:
        flash("Please log in first.", "error")
        return redirect(url_for("auth.login"))

    # Return to the page where the transaction was performed.
    def return_to_form():
        return redirect(
            url_for("pages.bank_page", operation=operation)
        )

    try:
        amount = Decimal(request.form.get("amount", "").strip())
    except (InvalidOperation, ValueError, TypeError, AttributeError):
        flash("Please enter a valid amount.", "error")
        return return_to_form()

    if (
        not amount.is_finite()
        or amount <= 0
        or amount.as_tuple().exponent < -2
        or amount >= Decimal("10000000000000")
    ):
        flash(
            "Enter a positive amount with at most two decimal places.",
            "error",
        )
        return return_to_form()

    recipient_id = None

    if operation == "transfer":
        try:
            recipient_id = int(request.form.get("recipient_id", ""))
        except (ValueError, TypeError):
            flash("Please enter a valid recipient account ID.", "error")
            return return_to_form()

    try:
        # Find the logged-in customer's account.
        sender_ref = db.session.execute(
            select(Account.account_id)
            .where(Account.customer_id == customer_id)
            .order_by(Account.account_id)
            .limit(1)
        ).scalar_one_or_none()

        if sender_ref is None:
            flash("No account is associated with your profile.", "error")
            return return_to_form()

        if operation == "transfer" and recipient_id == sender_ref:
            flash("You cannot transfer money to your own account.", "error")
            return return_to_form()

        # Lock accounts in a consistent order for transfers.
        ids_to_lock = (
            sorted([sender_ref, recipient_id])
            if operation == "transfer"
            else [sender_ref]
        )

        locked_accounts = db.session.execute(
            select(Account)
            .where(Account.account_id.in_(ids_to_lock))
            .order_by(Account.account_id)
            .with_for_update()
        ).scalars().all()

        account_map = {
            account.account_id: account
            for account in locked_accounts
        }

        sender = account_map.get(sender_ref)

        if sender is None or sender.customer_id != customer_id:
            db.session.rollback()
            flash("Your account could not be verified.", "error")
            return return_to_form()

        if operation == "withdraw" and sender.balance < amount:
            db.session.rollback()
            flash("Insufficient funds.", "error")
            return return_to_form()

        if operation == "deposit":
            sender.balance += amount

            db.session.add(
                TransactionList(
                    account_id=sender.account_id,
                    amount=amount,
                    type_of_transaction=TransactionType.DEPOSIT,
                )
            )

        elif operation == "withdraw":
            sender.balance -= amount

            db.session.add(
                TransactionList(
                    account_id=sender.account_id,
                    amount=amount,
                    type_of_transaction=TransactionType.WITHDRAW,
                )
            )

        else:
            recipient = account_map.get(recipient_id)

            if recipient is None:
                db.session.rollback()
                flash("Recipient account not found.", "error")
                return return_to_form()

            if sender.balance < amount:
                db.session.rollback()
                flash("Insufficient funds.", "error")
                return return_to_form()

            sender.balance -= amount
            recipient.balance += amount

            # Record both sides of the transfer.
            db.session.add_all([
                TransactionList(
                    account_id=sender.account_id,
                    amount=amount,
                    type_of_transaction=TransactionType.TRANSFER,
                ),
                TransactionList(
                    account_id=recipient.account_id,
                    amount=amount,
                    type_of_transaction=TransactionType.TRANSFER,
                ),
            ])

        db.session.commit()
        flash("Transaction completed successfully.", "success")

    except Exception:
        db.session.rollback()
        raise

    # Return to the same operation page after success.
    return return_to_form()
