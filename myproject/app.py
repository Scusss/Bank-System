from flask import Flask, render_template, request, redirect, url_for, flash
from flask.views import MethodView
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from decimal import Decimal, InvalidOperation
import enum

MYSQL_USER = "root"
MYSQL_PASSWORD = "root"
MYSQL_HOST = "localhost"
MYSQL_PORT = "3306"
MYSQL_DB = "bank" 

app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class TransactionType(enum.Enum):
    DEPOSIT = 'DEPOSIT'
    WITHDRAW = 'WITHDRAW'

class Customer(db.Model):
    __tablename__ = 'customer'
    customer_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    acc_password = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    failed_attempts = db.Column(db.Integer, default=0, nullable=False)
    is_locked = db.Column(db.Boolean, default=False, nullable=False)

class Account(db.Model):
    __tablename__ = 'accounts'
    account_id = db.Column(db.Integer, primary_key=True)
    account_number = db.Column(db.String(100), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.customer_id'), nullable=False)
    balance = db.Column(db.Numeric(15, 2), default=0.00, nullable=False)
    __table_args__ = (
        db.CheckConstraint('balance >= 0', name='check_balance_positive'),
    )

class TransactionList(db.Model):
    __tablename__ = 'transaction_list'
    transaction_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.account_id'), nullable=False)
    amount = db.Column(db.Numeric(15, 2), nullable=False)
    type_of_transaction = db.Column(db.Enum(TransactionType), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime, nullable=False)

class HomeView(MethodView):
    def get(self):
        account = Account.query.get(1)
        current_balance = account.balance if account else 0.00
        return render_template('home.html', balance=current_balance)

class BankView(MethodView):
    def get(self, operation):
        valid_operations = ['deposit', 'withdraw', 'transfer', 'receipts', 'account', 'home']
        if operation in valid_operations:
            return render_template(f'{operation}.html')
        return "Page not found"

class TransactionView(MethodView):
    def post(self, operation):
        account = Account.query.get(1)
        amount = request.form.get("amount")
        try:
            amount = Decimal(amount)
            if amount <= 0:
                return "Amount must be greater than 0."
        except (TypeError, InvalidOperation):
            return "Invalid amount provided."
        
        if operation == 'deposit':
            account.balance += amount
        elif operation == 'withdraw':
            account.balance -= amount
            if account.balance < amount:
                return "Insufficient funds."
        else:
            return "Invalid operation"
        
        db.session.commit()
        return redirect(url_for('home'))

class AccountView(MethodView):
    def get(self):
        account = Account.query.get(1)
        customer = Customer.query.get(1)
        current_balance = account.balance if account else 0.00
        first_name = customer.first_name
        last_name = customer.last_name
        email = customer.email
        return render_template('account.html', balance=current_balance, fname=first_name, lname=last_name, email=email)


app.add_url_rule('/', view_func=HomeView.as_view('home'))
app.add_url_rule('/account', view_func=AccountView.as_view('account'))
app.add_url_rule('/<operation>', view_func=BankView.as_view('bank'))
app.add_url_rule('/transaction/<operation>', view_func=TransactionView.as_view('transaction'))

if __name__ == '__main__':
    app.run(debug=True)