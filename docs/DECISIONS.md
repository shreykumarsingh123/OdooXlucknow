# Decisions

Short architecture decision records. Add a new entry instead of editing an old one, and mark the old one as superseded.

## ADR-001: Standalone Django and React, not Odoo modules

- **Date:** 2026-10-31
- **Status:** accepted
- **Context:** The brief asks for a software platform and does not require Odoo. MySQL was already installed, and Odoo needs PostgreSQL.
- **Decision:** Django 5.2 LTS, Django REST Framework, React with Vite, MySQL 8.
- **Consequences:** Full control of the rules and a small codebase. Accounting features Odoo would include are out of scope, and the brief does not ask for them.

## ADR-002: Double billing is blocked by a unique database key

- **Date:** 2026-10-31
- **Status:** accepted
- **Context:** The brief requires that nothing is billed twice or skipped. MySQL has no conditional unique indexes.
- **Decision:** `Invoice.billing_key` holds `<subscription>:<period start>` and is unique. It is set to NULL only when an invoice is cancelled for rebilling, as MySQL allows many NULLs. Billing catches up from `next_invoice_date` under a row lock.
- **Consequences:** Concurrent or repeated runs cannot double bill, even with a bug in the application logic.

## ADR-003: Billing runs by command and button, without a task queue

- **Date:** 2026-10-31
- **Status:** accepted
- **Context:** Runs cover hundreds of subscriptions a day, and a queue adds infrastructure the brief does not need.
- **Decision:** `run_billing` is a management command for a daily schedule, and the same service backs a Run billing button. Each subscription has its own transaction.
- **Consequences:** Simple to operate. A very large run holds the web request open, so the scheduled command is the normal route. Bulk sending is limited to 500 invoices per request, and is synchronous.
