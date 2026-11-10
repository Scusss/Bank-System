# Email change verification setup

The My Account page now uses Supabase Auth's email-change OTP flow.

## Supabase Dashboard configuration

1. Open **Authentication → Email Templates → Change Email**.
2. Configure the message to show the numeric code, using `{{ .Token }}` (not only the confirmation-link variable).
3. Save the template and make sure SMTP/email delivery is configured for your project.
4. In **Authentication → Settings**, keep email-change confirmation enabled. With secure email change enabled, Supabase may require confirmation at both the old and new addresses depending on your project settings.

Users enter the code sent by Supabase in **My Account → Login details**. The application updates its `app_users.email` value only after Supabase confirms the email change.

## Notes

- No database migration is required; the existing `app_users.username` and `app_users.email` columns are used.
- The current Supabase access and refresh tokens are used to authorize the email-change request.
- The user must verify the new address before the application treats it as their current email.
- Test the flow with a non-production account before deployment. Supabase Auth email templates and SMTP settings are managed in the Supabase project, not in this repository.
