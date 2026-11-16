-- JAB Bank: base schema for a NEW Supabase/PostgreSQL database.
-- Run once in the Supabase SQL editor. It already includes everything from
-- migrations 001-003, so a new install does NOT need those files.
-- Column lengths were not preserved in the exported schema, so plain VARCHAR
-- is used. Requires the Supabase "auth.users" table.

BEGIN;

CREATE TABLE IF NOT EXISTS public.roles (
  role_id     smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  role_name   varchar NOT NULL UNIQUE,
  description text
);

CREATE TABLE IF NOT EXISTS public.account_type_limits (
  limit_id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  account_type           varchar NOT NULL UNIQUE
                         CHECK (account_type IN ('savings', 'checking', 'business')),
  minimum_balance        numeric NOT NULL DEFAULT 0 CHECK (minimum_balance >= 0),
  maximum_balance        numeric,
  minimum_deposit        numeric NOT NULL DEFAULT 0,
  maximum_deposit        numeric,
  minimum_withdrawal     numeric NOT NULL DEFAULT 0,
  maximum_withdrawal     numeric,
  daily_withdrawal_limit numeric,
  daily_transfer_limit   numeric,
  transfer_fee           numeric NOT NULL DEFAULT 0,
  is_active              boolean NOT NULL DEFAULT true,
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.app_users (
  user_id        uuid PRIMARY KEY REFERENCES auth.users(id),
  role_id        smallint NOT NULL REFERENCES public.roles(role_id),
  username       varchar NOT NULL,
  email          varchar NOT NULL,
  is_locked      boolean NOT NULL DEFAULT false,
  account_status varchar NOT NULL DEFAULT 'active'
                 CHECK (account_status IN ('active', 'suspended', 'closed')),
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  email_verified boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS public.accounts (
  account_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_id   uuid NOT NULL REFERENCES public.app_users(user_id),
  account_number varchar NOT NULL UNIQUE,
  account_type  varchar NOT NULL REFERENCES public.account_type_limits(account_type),
  balance       numeric NOT NULL DEFAULT 0.00 CHECK (balance >= 0),
  currency      char(3) NOT NULL DEFAULT 'PHP',
  status        varchar NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'active', 'frozen', 'closed')),
  frozen_at     timestamptz,
  closed_at     timestamptz,
  status_reason text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.account_applications (
  application_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_id          uuid NOT NULL REFERENCES public.app_users(user_id),
  account_type         varchar NOT NULL REFERENCES public.account_type_limits(account_type),
  application_status   varchar NOT NULL DEFAULT 'pending'
                       CHECK (application_status IN ('pending', 'approved', 'rejected', 'cancelled')),
  reviewed_by          uuid REFERENCES public.app_users(user_id),
  review_remarks       text,
  submitted_at         timestamptz NOT NULL DEFAULT now(),
  reviewed_at          timestamptz,
  resulting_account_id bigint UNIQUE REFERENCES public.accounts(account_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_account_applications_active_type
  ON public.account_applications (customer_id, account_type)
  WHERE application_status IN ('pending', 'approved');

CREATE TABLE IF NOT EXISTS public.account_limit_overrides (
  override_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  account_id             bigint NOT NULL UNIQUE REFERENCES public.accounts(account_id),
  daily_transfer_limit   numeric,
  daily_withdrawal_limit numeric,
  reason                 text NOT NULL,
  approved_by            uuid NOT NULL REFERENCES public.app_users(user_id),
  created_at             timestamptz NOT NULL DEFAULT now(),
  expires_at             timestamptz
);

CREATE TABLE IF NOT EXISTS public.account_self_limits (
  account_id             bigint PRIMARY KEY REFERENCES public.accounts(account_id),
  daily_withdrawal_limit numeric CHECK (daily_withdrawal_limit IS NULL OR daily_withdrawal_limit > 0),
  daily_transfer_limit   numeric CHECK (daily_transfer_limit IS NULL OR daily_transfer_limit > 0),
  updated_at             timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.audit_logs (
  log_id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_id       uuid REFERENCES public.app_users(user_id),
  performed_by      uuid REFERENCES public.app_users(user_id),
  performed_by_role varchar,
  action            varchar NOT NULL,
  entity_type       varchar,
  entity_id         text,
  old_values        jsonb,
  new_values        jsonb,
  description       text,
  ip_address        inet,
  created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.beneficiaries (
  beneficiary_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_id      uuid NOT NULL REFERENCES public.app_users(user_id),
  beneficiary_name varchar NOT NULL,
  account_number   varchar NOT NULL,
  bank_name        varchar NOT NULL,
  nickname         varchar,
  created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.customer_details (
  detail_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_id  uuid NOT NULL UNIQUE REFERENCES public.app_users(user_id),
  first_name   varchar NOT NULL,
  middle_name  varchar,
  last_name    varchar NOT NULL,
  suffix       varchar,
  phone_number varchar,
  birth_date   date,
  address      text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.email_verification_codes (
  user_id    uuid PRIMARY KEY REFERENCES public.app_users(user_id),
  email      varchar NOT NULL,
  code_hash  varchar NOT NULL,
  expires_at timestamptz NOT NULL,
  sent_at    timestamptz NOT NULL,
  attempts   integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.identity_verifications (
  verification_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_id         uuid NOT NULL REFERENCES public.app_users(user_id),
  document_type       varchar,
  document_reference  text,
  verification_status varchar NOT NULL DEFAULT 'pending'
                      CHECK (verification_status IN ('pending', 'approved', 'rejected', 'requires_resubmission')),
  review_remarks      text,
  reviewed_by         uuid REFERENCES public.app_users(user_id),
  submitted_at        timestamptz NOT NULL DEFAULT now(),
  reviewed_at         timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_identity_verifications_one_pending
  ON public.identity_verifications (customer_id)
  WHERE verification_status = 'pending';

CREATE TABLE IF NOT EXISTS public.loans (
  loan_id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_id         uuid NOT NULL REFERENCES public.app_users(user_id),
  account_id          bigint REFERENCES public.accounts(account_id),
  loan_reference      varchar NOT NULL UNIQUE,
  loan_type           varchar NOT NULL,
  principal_amount    numeric NOT NULL CHECK (principal_amount > 0),
  interest_rate       numeric NOT NULL CHECK (interest_rate >= 0),
  loan_term_months    integer NOT NULL CHECK (loan_term_months > 0),
  monthly_payment     numeric CHECK (monthly_payment IS NULL OR monthly_payment > 0),
  outstanding_balance numeric NOT NULL,
  loan_status         varchar NOT NULL DEFAULT 'pending'
                      CHECK (loan_status IN ('pending', 'approved', 'rejected', 'active', 'paid', 'defaulted')),
  application_date    timestamptz NOT NULL DEFAULT now(),
  approval_date       timestamptz
);

CREATE TABLE IF NOT EXISTS public.transaction_list (
  transaction_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  account_id       bigint NOT NULL REFERENCES public.accounts(account_id),
  reference_number varchar NOT NULL UNIQUE,
  transaction_type varchar NOT NULL
                   CHECK (transaction_type IN ('deposit', 'withdrawal', 'transfer_in', 'transfer_out',
                                               'loan_disbursement', 'loan_payment', 'adjustment')),
  amount           numeric NOT NULL CHECK (amount > 0),
  balance_before   numeric,
  balance_after    numeric,
  description      text,
  performed_by     uuid REFERENCES public.app_users(user_id),
  status           varchar NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'completed', 'failed', 'reversed')),
  created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.loan_payments (
  payment_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  loan_id           bigint NOT NULL REFERENCES public.loans(loan_id),
  transaction_id    bigint UNIQUE REFERENCES public.transaction_list(transaction_id),
  payment_reference varchar NOT NULL UNIQUE,
  payment_amount    numeric NOT NULL CHECK (payment_amount > 0),
  payment_date      timestamptz NOT NULL DEFAULT now(),
  payment_status    varchar NOT NULL DEFAULT 'pending'
                    CHECK (payment_status IN ('pending', 'completed', 'failed', 'reversed'))
);

CREATE TABLE IF NOT EXISTS public.login_history (
  login_id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_id        uuid REFERENCES public.app_users(user_id),
  username_attempted varchar,
  ip_address         inet,
  device_info        text,
  login_status       varchar NOT NULL CHECK (login_status IN ('success', 'failed')),
  login_time         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.notifications (
  notification_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_id       uuid NOT NULL REFERENCES public.app_users(user_id),
  title             varchar NOT NULL,
  message           text NOT NULL,
  notification_type varchar,
  is_read           boolean NOT NULL DEFAULT false,
  created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.profile_change_requests (
  request_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  customer_id     uuid NOT NULL REFERENCES public.app_users(user_id),
  field_name      varchar NOT NULL
                  CHECK (field_name IN ('first_name', 'middle_name', 'last_name', 'suffix',
                                        'birth_date', 'phone_number', 'address')),
  old_value       jsonb,
  requested_value jsonb NOT NULL,
  reason          text,
  request_status  varchar NOT NULL DEFAULT 'pending'
                  CHECK (request_status IN ('pending', 'approved', 'rejected', 'cancelled')),
  reviewed_by     uuid REFERENCES public.app_users(user_id),
  review_remarks  text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  reviewed_at     timestamptz
);

CREATE TABLE IF NOT EXISTS public.transfers (
  transfer_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  sender_account_id    bigint NOT NULL REFERENCES public.accounts(account_id),
  recipient_account_id bigint REFERENCES public.accounts(account_id),
  beneficiary_id       bigint REFERENCES public.beneficiaries(beneficiary_id),
  reference_number     varchar NOT NULL UNIQUE,
  amount               numeric NOT NULL CHECK (amount > 0),
  description          text,
  transfer_status      varchar NOT NULL DEFAULT 'pending'
                       CHECK (transfer_status IN ('pending', 'completed', 'failed', 'reversed')),
  failure_reason       text,
  completed_at         timestamptz,
  created_at           timestamptz NOT NULL DEFAULT now()
);

-- Required starting data
INSERT INTO public.roles (role_name, description) VALUES
  ('customer', 'Regular bank customer'),
  ('admin', 'Administrator'),
  ('verification_officer', 'Reviews identity verification requests')
ON CONFLICT (role_name) DO NOTHING;

-- Bank account types (needed because accounts and applications reference them).
-- Adjust the limits and fees to taste.
INSERT INTO public.account_type_limits (account_type) VALUES
  ('savings'), ('checking'), ('business')
ON CONFLICT (account_type) DO NOTHING;

COMMIT;

-- Make the first admin: register a user in the app, then run:
--   UPDATE public.app_users
--   SET role_id = (SELECT role_id FROM public.roles WHERE role_name = 'admin')
--   WHERE username = '<your username>';
