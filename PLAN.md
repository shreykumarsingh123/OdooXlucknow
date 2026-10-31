# Project plan

**Problem:** Brightloop subscription management system. Requirements in [docs/ANALYSIS.md](docs/ANALYSIS.md), design in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

| # | Slice | Requirements | Status |
|---|-------|--------------|--------|
| 1 | Accounts, roles, signup, login, password reset, staff and customer admin | R-01 to R-05 | Done |
| 2 | Catalog: products, variants, taxes, plans, payment terms, discounts, templates | R-06 to R-10, R-14, R-17 | Done |
| 3 | Subscriptions, lifecycle, template conversion, plan options, add-ons | R-09 to R-12, R-23 | Done |
| 4 | Billing engine, invoices, taxes, discounts | R-13 to R-16, R-18 | Done |
| 5 | Payments and outstanding tracking | R-19, R-20 | Done |
| 6 | Finance dashboard and filters | R-21 | Done |
| 7 | React UI and customer portal | All | Done |
| 8 | Tests, volume check, demo seed | R-22 | Done |
| 9 | Stripe online payment, overdue reminders, ARR and churn | R-24 to R-26 | Done |
| 10 | Google sign-in | R-27 | Done |

## Not doing

Not requested in the brief: PDF files, proration, multi-currency, usage billing, notifications beyond invoice and account emails.
