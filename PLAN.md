# Project plan

**Product:** Brightloop is a platform for many businesses. Each one runs its own plans, billing, payments, support and sales here, and Brightloop tracks the subscriptions made on their sites.

Requirements are in [docs/ANALYSIS.md](docs/ANALYSIS.md), and the design is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Done

| # | Slice | Requirements |
|---|-------|--------------|
| 1 | Accounts, roles, signup, login, password reset, staff and customer admin | R-01 to R-05 |
| 2 | Catalog: products, variants, taxes, plans, payment terms, discounts, templates | R-06 to R-10, R-14, R-17 |
| 3 | Subscriptions, lifecycle, template conversion, plan options, add-ons | R-09 to R-12, R-23 |
| 4 | Billing engine, invoices, taxes, discounts | R-13 to R-16, R-18 |
| 5 | Payments and outstanding tracking | R-19, R-20 |
| 6 | Finance dashboard and filters | R-21 |
| 7 | React UI and customer portal | All |
| 8 | Tests, volume check, demo seed | R-22 |
| 9 | Stripe online payment, overdue reminders, ARR and churn | R-24 to R-26 |
| 10 | Google sign-in | R-27 |
| 11 | Public pricing and starting a plan online | R-28 |
| 12 | Free trials, once per customer per plan | R-29 |
| 13 | Change plan with proration, and credit balance on invoices | R-30 |
| 14 | One-off charges and credits, pause before cancelling, cancellation reasons, activity timeline | R-32 to R-34 |
| 15 | Analytics, CSV exports, customer profile | R-35, R-36 |
| 16 | Animated landing page | R-37 |
| 17 | Revenue page: recognition, deferred revenue, analysis and history | R-38 |

## Running a subscriber business: complete

| # | Slice | Requirements | Decision |
|---|-------|--------------|----------|
| 18 | Back button no longer looks like a logout | R-39 | Signed-in users skip the login page. A server hiccup never clears the session. |
| 19 | Automatic renewal with opt-out | R-40 | Customers have no Renew button. A subscription renews at expiry unless they turn renewal off, and then it ends at expiry. The team keeps a manual Renew. |
| 20 | Clearer labels | R-41 | Setup records show Active or Inactive, never Closed. Customers do not see the internal Draft-to-Closed stepper. |
| 21 | Promo codes page for the admin | R-31, R-42 | Rewards: percent or fixed discount, account credit (money), free days, or a custom perk. |
| 22 | Customer care login | R-43 | Staff member with the Customer care department. Sees all tickets, replies, adds internal notes, escalates to the admin. Customers raise tickets in the portal. |
| 23 | Team chat | R-44 | Shared channel for the admin and staff. Refreshes every 10 seconds. |
| 24 | Sales login | R-45 | Staff member with the Sales department. Sees only subscriptions they sold, their monthly target and simple metrics. The admin sets targets and sees the whole team. |
| 25 | Stripe test payments, with admin approval as the other route | R-24, R-46 | Stripe Checkout stays in test mode. A customer who paid another way, or cannot use Stripe, sends a request that the admin approves or rejects. |
| 26 | Customer account view and assign any plan | R-47 | The admin sees plans, balances and tickets per customer, and can assign any active plan, optionally replacing a current subscription. |
| 27 | Subscriber import with a sample data button | R-48 | CSV of what subscribers bought: paste, upload or load a sample, preview, then import. Past periods are not back-billed. |

### Who can do what

| | Admin | General staff | Customer care | Sales | Customer |
|---|---|---|---|---|---|
| Catalog, promo codes, targets, staff, approvals, assign plan | Yes | Read catalog | No | Read catalog | No |
| Finance summary, revenue, payments, billing run, import | Yes | Yes | No | No | No |
| Subscriptions and invoices | All | All | All | Only what they sold | Own |
| Tickets | All | All | All | No | Own |
| Team chat | Yes | Yes | Yes | Yes | No |
| Sales metrics | Whole team | Whole team | No | Own | No |

### Where subscription data comes from

1. The team creates a subscription or starts from a quotation template.
2. A customer starts a plan online.
3. The admin assigns a plan to a customer.
4. A CSV import brings in subscribers the business already has, from a spreadsheet or another store.

Live store connections, such as Shopify or WooCommerce, are not built. Exporting their orders to the CSV format is the route today.

### Rules for this work

- Every money change runs in a transaction under a row lock, and no invoice may be billed twice.
- Permissions are enforced on the server, and hiding a menu item is never the only check.
- A customer never sees internal ticket notes.

## Many businesses on one platform: complete

| # | Slice | Requirements |
|---|-------|--------------|
| 28 | Email OTP in place of the reset link, sent to the recovery address | R-49 |
| 29 | The address decides the account type and where it lands | R-50 |
| 30 | Business ID, team joining with owner approval, staff add and delete | R-51 |
| 31 | One administrator, Brightloop staff, business owners and their staff | R-52 |
| 32 | Every record belongs to one business, and no business can reach another's | R-53 |
| 33 | Brightloop overview across all businesses, and managing users | R-54 |
| 34 | Team chat per business, and admin chat with Brightloop | R-55 |
| 35 | Public site per business, with Manbhwan Foods as the test site | R-56 |
| 36 | Compulsory recovery email after login | R-57 |

### Who is who

| Address | Account | Lands on |
|---------|---------|----------|
| `asha@admin.com` | The one administrator. A database rule allows only one | Brightloop overview |
| `name@adminsale.com` | Brightloop sales | Sales page |
| `name@support.com` | Brightloop customer care | Tickets |
| `name@gmail.com` | Business owner, or a customer if they signed up with a Business ID | Owner's dashboard, or customer portal |
| `nameBUSINESSID@sale.com` | That business's sales | Sales page |
| `name.BUSINESSID@support.com` | That business's customer care | Tickets |

Rules that keep this safe:

- Nobody can sign up with a Brightloop address. Only the administrator creates them.
- A team member joining with a Business ID stays locked until the owner approves them.
- One address belongs to one business. A person cannot use the same address as a customer of two businesses.

### Speed

Every list and report starts from one business, so composite indexes lead with `business`. Reports use grouped SQL, and results are joined in hash maps. The slowest page measured 199 ms with 5,000 subscriptions.

### Next

- Each business's own Stripe account, through Stripe Connect. Today all test payments land in one Stripe test account.
- A real API or script for businesses to report subscriptions made on their own sites. Today the hosted site at `/shop/BUSINESSID` does this.

## Needs the project owner

| Item | Why |
|------|-----|
| `TWILIO_FROM_NUMBER` | SMS stays off without a sender number. |
| `GOOGLE_CLIENT_ID` | The Google button stays hidden until it is set. |
| `STRIPE_WEBHOOK_SECRET` | Without it, a payment is recorded only when the customer returns to the site. |

## Not doing

Recurly features that need outside services or far more scope: multiple payment gateways, fraud tools, machine-learning payment retries, Shopify commerce, mobile SDKs, an AI assistant, and outgoing webhooks.

Also not doing: PDF files (invoices print from the browser), multi-currency, usage billing, and customer-initiated plan changes between different billing periods.
