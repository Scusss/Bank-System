-- Renumber existing bank accounts to the customer-facing XXXX-XXXX format
-- and keep saved transfer contacts pointing at the right accounts.
-- Run once in the Supabase SQL editor (paste the whole block and click Run).
-- Safe to re-run: accounts already in the new format are skipped.
-- Single DO block = one atomic statement, no temp tables.

DO $$
DECLARE
  r RECORD;
  candidate TEXT;
BEGIN
  FOR r IN
    SELECT account_id
    FROM accounts
    WHERE account_number !~ '^[0-9]{4}-[0-9]{4}$'
    ORDER BY account_id
  LOOP
    -- Pick a random XXXX-XXXX number nobody else has.
    LOOP
      candidate := lpad((floor(random() * 10000))::int::text, 4, '0') || '-' ||
                   lpad((floor(random() * 10000))::int::text, 4, '0');
      EXIT WHEN NOT EXISTS (
        SELECT 1 FROM accounts WHERE account_number = candidate
      );
    END LOOP;

    -- Saved contacts used to store the numeric account_id as text.
    UPDATE beneficiaries
    SET    account_number = candidate
    WHERE  account_number = r.account_id::text;

    UPDATE accounts
    SET    account_number = candidate
    WHERE  account_id = r.account_id;
  END LOOP;
END $$;

-- Check the result:
-- SELECT account_id, account_number FROM accounts ORDER BY account_id;
