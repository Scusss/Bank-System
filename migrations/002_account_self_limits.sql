-- JAB Bank: customer-set daily limits per bank account.
-- Review before running; take a backup first. Not tested against your database.
BEGIN;

CREATE TABLE IF NOT EXISTS account_self_limits (
  account_id             BIGINT PRIMARY KEY
                         REFERENCES accounts(account_id) ON DELETE CASCADE,
  daily_withdrawal_limit NUMERIC(19,2) CHECK (daily_withdrawal_limit IS NULL OR daily_withdrawal_limit > 0),
  daily_transfer_limit   NUMERIC(19,2) CHECK (daily_transfer_limit IS NULL OR daily_transfer_limit > 0),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;
