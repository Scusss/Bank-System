# Account status and UI updates

- Admins can set each customer's status to **Active**, **Frozen**, or **Closed** from Admin Tools → Manage Users.
- Frozen and closed customers cannot sign in. Existing sessions are rejected on the next protected request, and transaction POSTs independently verify the customer's status.
- Admin status changes are written to the audit log. Administrators cannot freeze or close their own currently signed-in account.
- Active restores access. Closed is inaccessible until an administrator explicitly changes the status back to Active.
- Customer status is displayed with one shared badge style. The redundant top-bar profile/avatar is hidden; the sidebar account initial uses a consistent style.

## Deployment note

This change uses the existing `customer.account_status` and `customer.is_locked` columns. No database migration is required. `is_locked` is synchronized for compatibility with existing code.
