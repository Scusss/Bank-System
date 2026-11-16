# JAB Bank

A demo online banking web application built with Flask, PostgreSQL and
Supabase Auth.

> **Demo project, not a real bank.** JAB Bank is a student software project.
> It holds no real money. Do not enter real personal or financial information.

## Features

**Customers**

- Register and sign in (authentication handled by Supabase Auth).
- Manage account information: name, birth date, phone, address, login details.
- Change email with a one-time code sent by Supabase.
- Request identity verification, then request bank accounts (savings,
  checking or business, one per type).
- Deposit, withdraw and transfer between accounts, with saved transfer contacts.
- Switch between multiple bank accounts.
- Set personal daily withdrawal and transfer limits per account.
- View receipts and notifications.

**Verification officers** (`/verification`)

- Review identity verification requests and approve or reject them
  (a reason is required to reject).

**Administrators** (`/admin`)

- Approve or reject bank account requests.
- Manage users: change role, and set status to Active, Frozen or Closed.
- View transactions, login history and audit logs.
- Download or restore a database backup (see [Database backup](#database-backup-and-restore)).

## How the account flow works

1. **Register** creates a user account only. No bank account yet.
2. The user completes their account information and clicks **Request
   verification**.
3. A **verification officer** approves or rejects it. The user is notified.
4. Only **verified** users can request a bank account, once per bank type. A
   type can be requested again only if the earlier request was rejected.
5. An **admin** approves the request, which creates the bank account
   (a number in `XXXX-XXXX` format, starting balance 0).
6. Deposits, withdrawals and transfers are always checked against the
   signed-in user's own accounts.

### Account status

| Status | Effect |
|---|---|
| Active | Full access. |
| Frozen | The user can still sign in and view account details, receipts and notifications, but deposits, withdrawals and transfers are disabled on their bank accounts. |
| Closed | Cannot sign in. Existing sessions are rejected on the next protected request, until an admin sets the status back to Active. |

Admins cannot freeze or close their own signed-in account. All status changes
are written to the audit log.

### Roles

| Role | Access |
|---|---|
| `customer` | Customer pages. |
| `verification_officer` | `/verification` console. |
| `admin` | `/admin` console. |

Change a user's role from **Admin → Manage Users**.

## Project structure

```
Bank-System-main/
├── run.py                  # Entry point
├── requirements.txt
├── .env                    # Local secrets (never commit)
├── app/
│   ├── __init__.py         # App factory, sessions, security headers
│   ├── extensions.py       # SQLAlchemy, sessions, Supabase clients
│   ├── models.py           # Database models
│   ├── services.py         # Verification, limits, audit, notifications
│   ├── database_backup.py  # pg_dump / pg_restore / psql wrapper
│   └── routes/
│       ├── auth.py         # Register, login, logout, legal pages
│       ├── pages.py        # Customer pages and account management
│       ├── transactions.py # Deposit, withdraw, transfer
│       ├── verification.py # Verification officer console
│       └── admin.py        # Admin console and database backup
├── templates/              # Jinja2 templates
├── static/                 # CSS
├── migrations/             # SQL migrations (run in order)
└── tests/                  # Unit tests
```

## Requirements

- Python 3.12
- A PostgreSQL database (the project uses Supabase)
- A Supabase project (Auth, plus the API keys below)
- PostgreSQL client tools, only if you want the backup feature

## Setup

### 1. Create a virtual environment

A `.venv` folder cannot be moved between computers, so always create a fresh
one on each machine.

```powershell
# Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If PowerShell blocks activation, run once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### 2. Configure `.env`

Create a `.env` file in the project root:

```
SECRET_KEY=<long random string>
DATABASE_URL=postgresql://<user>:<password>@<host>:5432/postgres
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_PUBLISHABLE_KEY=<publishable key>
SUPABASE_SECRET_KEY=<secret key>
SESSION_COOKIE_SECURE=false
```

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Signs session cookies. Required. |
| `DATABASE_URL` | PostgreSQL connection string. Required, must be PostgreSQL. |
| `SUPABASE_URL` | Your Supabase project URL. |
| `SUPABASE_PUBLISHABLE_KEY` | Client-side key, used for sign-in and sign-up. |
| `SUPABASE_SECRET_KEY` | Server-side admin key. Keep private. |
| `SESSION_COOKIE_SECURE` | Set to `true` when served over HTTPS. |
| `PG_DUMP_PATH`, `PG_RESTORE_PATH`, `PSQL_PATH` | Optional. Full paths to the PostgreSQL tools (see below). |

**Where to find the Supabase values**

| Value | Where in the Supabase dashboard |
|---|---|
| `SUPABASE_URL`, API keys | Project Settings → API (or API Keys) |
| `DATABASE_URL` | Click **Connect** at the top of the project, then copy the connection string. The session pooler on port 5432 works for the app and for backups. Replace `[YOUR-PASSWORD]` with your database password. |

The database password is the one you set when creating the project. You can
reset it under Project Settings → Database.

Generate a secret key with:
`python -c "import secrets; print(secrets.token_urlsafe(48))"`

**Never commit `.env` or share it.** If a password or key has been exposed,
rotate it in the Supabase dashboard.

### 3. Prepare the database

**New database (most people):** open the Supabase **SQL Editor**, paste the
contents of `migrations/000_base_schema.sql`, and click **Run**. It creates
every table and index, and adds the starting data the app needs:

- the roles `customer`, `admin` and `verification_officer`
- the bank account types `savings`, `checking` and `business`

Migrations `001` to `003` are **not** needed on a new database, because the
base schema already includes them. They are kept only for upgrading an older
database that was created before those changes.

| File | Use it when |
|---|---|
| `000_base_schema.sql` | Setting up a new database. |
| `001_separate_user_and_bank_accounts.sql` | Upgrading an old database that still has a `customer` table. |
| `002_account_self_limits.sql` | Upgrading an old database without customer-set limits. |
| `003_account_number_format.sql` | Renumbering old accounts to `XXXX-XXXX`. Safe to re-run. |

Read any script before running it and take a backup first.

**Create the first admin:** register a normal user in the app, then run this
in the SQL Editor (replace the username):

```sql
UPDATE public.app_users
SET role_id = (SELECT role_id FROM public.roles WHERE role_name = 'admin')
WHERE username = 'your-username';
```

After that, the admin can change other users' roles from **Admin → Manage
Users**. To make a verification officer, use the same query with
`'verification_officer'`.

### 4. Configure Supabase Auth

**Sign-up:** turn **Confirm email** off (Authentication → Sign In / Providers
→ Email; the menu names can change between dashboard versions). The app
creates the user, saves their profile and sends them straight to the login
page, so people can sign in right after registering. With confirmation on,
Supabase would block sign-in until the user clicked an emailed link, and the
"you can now log in" message would be misleading.

**Email change:** the app uses Supabase's one-time code. Set it up like this:

1. Go to **Authentication → Email Templates → Change Email**.
2. Include the numeric code with `{{ .Token }}`, not only the link variable.
3. Make sure SMTP or email delivery is configured for your project.
4. Keep email-change confirmation enabled. If secure email change is on,
   Supabase may ask for confirmation at both the old and new addresses.

Users enter the code under **My Account → Login details**. The app only
updates its stored email after Supabase confirms the change. Test with a
non-production account first.

### 5. Run the app

```powershell
python run.py
```

Open <http://127.0.0.1:5000>.

`run.py` starts Flask in debug mode, which is for local development only.
For deployment, use gunicorn instead:

```bash
gunicorn "app:create_app()"
```

## Database backup and restore

Administrators can use **Database Backup** in the admin console to download a
custom-format backup of the `public` schema, or restore an uploaded one.
Backups are streamed to the administrator and are not kept on the server.

**Restoring is destructive.** It replaces the live `public` schema, and
requires ticking a checkbox and typing `RESTORE`.

Limits: 512 MB per backup file. PostgreSQL only.

### Requirements

The **server** running the app (not the admin's browser) needs PostgreSQL's
`pg_dump`, `pg_restore` and `psql`. Use client tools at least as new as your
database server version.

| OS | Install |
|---|---|
| Windows | PostgreSQL installer from postgresql.org, tick **Command Line Tools** only. |
| macOS | `brew install libpq` then `brew link --force libpq` |
| Ubuntu / Debian | `sudo apt install postgresql-client` |
| Docker | `RUN apt-get update && apt-get install -y postgresql-client` |

The app looks for the tools in this order:

1. `PG_DUMP_PATH`, `PG_RESTORE_PATH`, `PSQL_PATH` from `.env`
2. The system `PATH`
3. On Windows, `C:\Program Files\PostgreSQL\<version>\bin`

If you installed them elsewhere (for example on another drive), set the paths
without quotes:

```
PG_DUMP_PATH=D:\PostgreSQL\17\bin\pg_dump.exe
PG_RESTORE_PATH=D:\PostgreSQL\17\bin\pg_restore.exe
PSQL_PATH=D:\PostgreSQL\17\bin\psql.exe
```

Restart the app after changing `.env`.

### Troubleshooting

| Message | Meaning |
|---|---|
| "PostgreSQL backup utilities are unavailable on this server." | The tools were not found. Install them or set the paths above. |
| "PostgreSQL could not complete the database operation." | The tools ran but failed. Check the terminal for the real error, often a version mismatch or blocked port 5432. |
| "Database backup and restore require PostgreSQL." | `DATABASE_URL` does not point to PostgreSQL. |

Test a tool directly with:
`& "D:\PostgreSQL\17\bin\pg_dump.exe" --version`

## Testing

```powershell
python -m unittest discover tests
```

## Notes

- Daily limits reset at midnight in the `Asia/Manila` time zone.
- Sessions are stored on disk in `instance/flask_session` and last 30 minutes.
- Before deploying: turn off debug mode, set `SESSION_COOKIE_SECURE=true`,
  serve over HTTPS, and keep `.env` out of source control.
