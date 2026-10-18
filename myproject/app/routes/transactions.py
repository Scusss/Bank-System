from decimal import Decimal, InvalidOperation

from flask import Blueprint, request, redirect, url_for, flash
from sqlalchemy import update

from app.extensions import db
from app.models import Account, TransactionList, TransactionType

transactions = Blueprint("transactions", __name__)


@transactions.route("/transaction/<operation>", methods=["POST"])
def transaction(operation):
    if operation not in {"deposit", "withdraw", "transfer"}:
        flash("Invalid transaction operation.", "error")
        return redirect(url_for("pages.home"))

    destination = (
        "pages.withdraw" if operation == "withdraw"
        else "pages.transfer" if operation == "transfer"
        else "pages.home"
    )

    try:
        amount = Decimal(request.form.get("amount", ""))
    except (InvalidOperation, ValueError, TypeError):
        flash("Please enter a valid amount.", "error")
        return redirect(url_for(destination))

    if not amount.is_finite() or amount <= 0:
        flash("Amount must be greater than zero.", "error")
        return redirect(url_for(destination))

    # Existing sender account.
    account_id = 1

    recipient_id = None

    if operation == "transfer":
        try:
            recipient_id = int(request.form.get("recipient_id", ""))
        except (ValueError, TypeError):
            flash("Please enter a valid recipient account ID.", "error")
            return redirect(url_for("pages.transfer"))

        if recipient_id == account_id:
            flash("You cannot transfer money to your own account.", "error")
            return redirect(url_for("pages.transfer"))

    try:
        # Lock both accounts in a consistent order for transfers.
        account_ids = (
            sorted([account_id, recipient_id])
            if operation == "transfer"
            else [account_id]
        )

        accounts = (
            Account.query
            .filter(Account.account_id.in_(account_ids))
            .order_by(Account.account_id)
            .with_for_update()
            .all()
        )

        account_map = {a.account_id: a for a in accounts}
        account = account_map.get(account_id)

        if account is None:
            flash("Account not found.", "error")
            return redirect(url_for("pages.home"))

        if operation == "deposit":
            account.balance += amount
            record = TransactionList(
                account_id=account.account_id,
                amount=amount,
                type_of_transaction=TransactionType.DEPOSIT,
            )

        elif operation == "withdraw":
            if account.balance < amount:
                flash("Insufficient funds.", "error")
                return redirect(url_for("pages.withdraw"))

            account.balance -= amount
            record = TransactionList(
                account_id=account.account_id,
                amount=amount,
                type_of_transaction=TransactionType.WITHDRAW,
            )

        elif operation == "transfer":
            recipient = account_map.get(recipient_id)

            if recipient is None:
                flash("Recipient account not found.", "error")
                return redirect(url_for("pages.transfer"))

            if account.balance < amount:
                flash("Insufficient funds.", "error")
                return redirect(url_for("pages.transfer"))

            account.balance -= amount
            recipient.balance += amount

            # Record the outgoing transfer.
            db.session.add(
                TransactionList(
                    account_id=account.account_id,
                    amount=amount,
                    type_of_transaction=TransactionType.TRANSFER,
                )
            )

            # Record the incoming side of the transfer.
            db.session.add(
                TransactionList(
                    account_id=recipient.account_id,
                    amount=amount,
                    type_of_transaction=TransactionType.TRANSFER,
                )
            )

            db.session.commit()
            flash("Transfer completed successfully.", "success")
            return redirect(url_for("pages.home"))

        db.session.add(record)
        db.session.commit()

        flash("Transaction completed successfully.", "success")

    except Exception:
        db.session.rollback()
        raise

    return redirect(url_for("pages.home"))