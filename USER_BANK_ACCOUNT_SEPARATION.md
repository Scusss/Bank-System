# User account vs. bank accounts

## How it works now
1. **Register** -> creates only a *user account* (`app_users` + `customer_details`). No bank account is created any more.
2. **My Account** (user account page) holds the *account information*: name, birth date, phone, address (plus username/email).
3. **Verification request**: once the information is complete, the user just clicks **Request verification** (nothing else is sent) and the officer reviews the account information.
4. A **verification officer** (new role `verification_officer`, console at `/verification`) verifies or rejects it (reject needs a reason). The user is notified.
5. Only **verified** users can **request a bank account**, **once per bank type** (savings/checking/business, or whatever is active in `account_type_limits`). A type can be requested again only if the earlier request was rejected. Enforced in code and by a partial unique index.
6. An **admin** approves/rejects bank requests at `/admin/account-requests`. Approval creates the `accounts` row (12-digit number, balance 0).
7. Bank pages (dashboard, deposit, withdraw, transfer, transactions) show **only bank data** (type, number, balance). Users with several accounts get an account switcher; transactions are always checked against the user's own accounts.

## Files
- `app/models.py` - your new models + `Role`, `TransactionList`, `LoginHistory`, `Notification` (routes still need them), relationships, FK to `auth.users`, partial unique indexes.
- `app/services.py` (new) - verification state, bank-type states, audit, notifications.
- `app/routes/pages.py`, `auth.py`, `transactions.py`, `admin.py`, `verification.py` (new).
- `templates/account.html` (now the user account page), `verification.html` (new), `_account_switcher.html` (new), `admin.html`, `home.html` (+ switcher/no-account notice), `deposit/withdraw/transfer/receipts.html` (+ switcher, hidden `account_id`).
- `migrations/001_separate_user_and_bank_accounts.sql` - review before running.

## Decisions to confirm
- Bank requests are approved by an **admin** (you only specified the officer for verification).
- Verified name/birth date can no longer be edited by the user.
- Existing account holders are not verified automatically; see optional step 9 in the SQL.
