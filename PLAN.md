# Project plan

**Problem:** Brightloop subscription management system. Requirements in [docs/ANALYSIS.md](docs/ANALYSIS.md), design in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Brief: complete

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

## Requested after the brief: complete

| # | Slice | Requirements | Status |
|---|-------|--------------|--------|
| 9 | Stripe online payment, overdue reminders, ARR and churn | R-24 to R-26 | Done |
| 10 | Google sign-in | R-27 | Done |

## Recurly-inspired features and public landing page: complete

| # | Slice | Requirements | Status |
|---|-------|--------------|--------|
| 11 | Public pricing and starting a plan online | R-28 | Done |
| 12 | Free trials, once per customer per plan, left out of recurring revenue | R-29 | Done |
| 13 | Change plan with proration, and credit balance on invoices | R-30 | Done |
| 14 | Promo codes | R-31 | Done |
| 15 | Admin one-off charges and credits | R-32 | Done |
| 16 | Pause offered before cancelling, and cancellation reasons | R-33 | Done |
| 17 | Subscription activity timeline | R-34 | Done |
| 18 | Analytics: revenue per customer, recurring revenue by plan, overdue aging, churn reasons; CSV exports | R-35 | Done |
| 19 | Customer profile page | R-36 | Done |
| 20 | Animated landing page at `/`, with pricing from the live API, and page transitions | R-37 | Done |

### Rules for this work

- Every money change runs in a transaction under a row lock, and no invoice may be billed twice.
- Customers can act only on their own subscriptions, and can choose only public plans.
- The landing page shows no invented customers, logos, testimonials or results. Sample figures are labelled as samples.
- Animation respects `prefers-reduced-motion`.

## Needs the project owner

| Item | Why |
|------|-----|
| SMTP settings in `.env` | Password reset, invite and invoice emails are written to files until these are set. The brief needs the reset link to reach the mailbox. |
| `TWILIO_FROM_NUMBER` | SMS stays off without a sender number. |
| `GOOGLE_CLIENT_ID` | The Google button stays hidden until it is set. |
| `STRIPE_WEBHOOK_SECRET` | Without it, a payment is recorded only when the customer returns to the site. |
| Hosting | The app runs locally. A public URL needs a hosting account. |

## Not doing

Recurly features that need outside services or far more scope: multiple payment gateways, fraud tools, machine-learning payment retries, revenue recognition, Shopify commerce, mobile SDKs, an AI assistant, and outgoing webhooks.

Also not doing: PDF files (invoices print from the browser), multi-currency, usage billing, and plan changes between different billing periods.
