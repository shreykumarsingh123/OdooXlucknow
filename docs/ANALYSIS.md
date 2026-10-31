# Problem analysis

Source: `docs/PROBLEM.md`. Priorities: P0 stated in the brief. Nothing outside the brief is built, apart from the assumptions listed below.

## Summary

Brightloop Software runs subscriptions, invoices and payments on spreadsheets. It needs one system covering catalog, quote-to-subscription, automatic recurring billing, payments and revenue reporting, with admin, staff and customer access.

## Roles

| Role | Can | Cannot |
|------|-----|--------|
| Admin | Everything, including catalog, taxes, discounts, templates and staff | |
| Staff | Customers, subscriptions, invoices, payments, billing runs, reports; read catalog | Change catalog, taxes, discounts or templates; add staff |
| Customer | See own subscriptions and invoices; print invoices; pause, resume, close or renew where the plan allows; switch add-ons on and off | See other customers' data, the catalog, reports, drafts |

## Requirements

| ID | Requirement | Acceptance check |
|----|-------------|------------------|
| R-01 | Sign up with email and password; one account per email | Duplicate email refused, in any letter case |
| R-02 | Password over 8 characters with uppercase, lowercase, special | `Short@1a` and `alllower@123` refused |
| R-03 | Reset link sent to the registered email | Link works once; unknown email gets the same response |
| R-04 | Admin, staff, customer access levels | Wrong role gets 403, other customers' records 404 |
| R-05 | Only admin adds staff | Staff creating staff gets 403 |
| R-06 | Product: name, type, sales price, cost price, notes | CRUD by admin |
| R-07 | Variants with extra price (Brand: Odoo +560) | Line price = sales price + 560 |
| R-08 | Plan: price, daily/weekly/monthly/yearly, minimum quantity, available dates | Below minimum or outside dates refused |
| R-09 | Per-plan options: auto-close, close early, pause, renew | Disallowed action refused; expired auto-close plan closes |
| R-10 | Quotation template: plan, product lines, validity days | Subscription prefilled; expired quotation cannot be confirmed |
| R-11 | Subscription: number, customer, plan, start, expiry, payment terms, lines | Number unique; amounts computed |
| R-12 | Draft → Quotation → Confirmed → Active → Closed, visible to the team | Skipping a state refused; stage shown on the page |
| R-13 | Invoices generated from subscriptions, in bulk | Customer, lines, taxes and totals filled in |
| R-14 | Taxes calculated from admin rules | Totals match the rule |
| R-15 | Confirm, cancel, send, print; Draft → Confirmed → Paid | Invalid actions refused |
| R-16 | Nothing billed twice or skipped | Repeat run creates none; missed periods caught up; database constraint |
| R-17 | Discounts admin-only: fixed or percent, minimum purchase or quantity, dates, usage limit | Staff gets 403 |
| R-18 | Discount on products or whole subscriptions, automatic on next invoice, stops on expiry or limit | Appears and stops without action |
| R-19 | Payments: method, amount, date, note, against an invoice | Overpayment refused; fully paid becomes Paid |
| R-20 | See paid, outstanding and overdue invoices | Filters match the data |
| R-21 | Finance view: active subscriptions, revenue, owed, payments, overdue, with filters and summary | Numbers match a manual count |
| R-22 | Pages respond in under 2 seconds with thousands of subscriptions | Measured on 5,000 subscriptions |
| R-23 | Customers manage their own subscriptions in a portal, and switch add-ons | Works without staff |

## Additions requested after the brief

The project owner supplied Stripe and Twilio keys and allowed ideas from products like Recurly.

| ID | Requirement | Acceptance check |
|----|-------------|------------------|
| R-24 | Customers pay confirmed invoices online with Stripe Checkout | A paid session is recorded once, and marks the invoice Paid |
| R-25 | Overdue reminders by email, and by Twilio SMS where a phone and sender exist | Spaced and capped; paid invoices are not chased |
| R-26 | Annual recurring revenue and churn on the finance view | Numbers match a manual count |
| R-27 | Sign in with Google | Verified Google email signs in; new users become customers; unverified refused |

## Assumptions

| ID | Assumption | If wrong |
|----|------------|----------|
| A-01 | Plan price is a recurring fee, added as an automatic line beside product lines | Remove the plan line in one service function |
| A-02 | "More than eight" means at least 9 characters | One constant |
| A-03 | Partial payments are allowed | One validation |
| A-04 | Paused subscriptions are not billed and paused time is not back-billed | Billing service |
| A-05 | Multiple discounts stack, and never take a line below zero | Discount service |
| A-06 | Cancelled invoices are not rebilled unless the user ticks "bill this period again" | Cancel option |
| A-07 | Renewing extends expiry by the original term | Renew service |
| A-08 | Currency is INR; the brief names none | One frontend constant |
| A-09 | Staff record offline payments; online payment arrived later as R-24 | |
| A-10 | Printing uses a browser print page; a PDF file is not requested | |
| A-11 | Pause is an extra state beside Active, since the brief allows pausing | |
