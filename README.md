# Brightloop Subscription Management System

One platform for plans, subscriptions, recurring billing, payments and revenue reporting. Built with Django REST Framework, React and MySQL.

- Brief: [docs/PROBLEM.md](docs/PROBLEM.md)
- Requirements and assumptions: [docs/ANALYSIS.md](docs/ANALYSIS.md)
- Design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/DECISIONS.md](docs/DECISIONS.md)
- Plan and status: [PLAN.md](PLAN.md)

## What it does

| Area | Features |
|------|----------|
| Accounts | Sign-up, Google sign-in, password rules, reset link by email, admin, staff and customer roles |
| Catalog | Products with variants, plans with per-plan options, taxes, payment terms, discounts, quotation templates |
| Subscriptions | Draft → Quotation → Confirmed → Active → Closed, pause, renew, add-on switches, start from a template |
| Billing | One-click or scheduled billing run, automatic taxes and discounts, no double or skipped billing |
| Invoices | Draft → Confirmed → Paid, cancel, send, print, bulk confirm and send |
| Payments | Stripe online payment, method, amount, date and note, part payments, paid, outstanding and overdue views |
| Finance | Active subscriptions, MRR, ARR, churn, collected, owed, overdue, with date filters, and overdue reminders by email and SMS |
| Portal | Customers see only their own records and manage them where the plan allows |

## Run it

Prerequisites: Python 3.12 or later, Node 20 or later, MySQL 8. Run these from the repository root in PowerShell.

1. Create the database and user (SQL in [docs/SETUP.md](docs/SETUP.md), step 3).
2. Copy `.env.example` to `.env`, then set `SECRET_KEY` and `DB_PASSWORD`.
3. Set up the backend:

   ```powershell
   python -m venv .venv
   .venv\Scripts\pip install -r backend\requirements.txt
   .venv\Scripts\python backend\manage.py migrate
   .venv\Scripts\python backend\manage.py seed_demo
   .venv\Scripts\python backend\manage.py runserver
   ```

4. In a second terminal, start the frontend, then open http://localhost:5173:

   ```powershell
   cd frontend
   npm ci
   npm run dev
   ```

### Demo logins

All use the password in `backend/billing/management/commands/seed_demo.py`. The command refuses to run unless `DEBUG=true`.

| Role | Email |
|------|-------|
| Admin | `admin@brightloop.example` |
| Staff | `staff@brightloop.example` |
| Customer | `customer@acme.example` |
| Customer | `finance@globex.example` |

Without SMTP settings, emails such as reset links are saved in `backend/sent_emails/`.

## Optional integrations

All are set in `.env`, and stay hidden or inactive until configured. See `.env.example`.

| Integration | Needs | Notes |
|-------------|-------|-------|
| Stripe Checkout | `STRIPE_SECRET_KEY` | Add `STRIPE_WEBHOOK_SECRET`, with an endpoint at `/api/webhooks/stripe/`, so payments record even if the customer never returns to the site |
| Twilio SMS | `TWILIO_ACCOUNT_SID`, `TWILIO_API_KEY_SID`, `TWILIO_API_KEY_SECRET`, `TWILIO_FROM_NUMBER` | Customers need a phone number with country code |
| Google sign-in | `GOOGLE_CLIENT_ID` | Create an OAuth web client in Google Cloud, and add `http://localhost:5173` as an authorised JavaScript origin |

## Other commands

| Task | Command, from `backend/` |
|------|--------------------------|
| Run tests (needs MySQL) | `..\.venv\Scripts\python manage.py test` |
| Bill everything due | `..\.venv\Scripts\python manage.py run_billing` |
| Remind about overdue invoices | `..\.venv\Scripts\python manage.py send_reminders` |
| Add volume data for speed checks | `..\.venv\Scripts\python manage.py seed_demo --volume 5000` |

## Production

- Schedule `manage.py run_billing` and `manage.py send_reminders` daily with cron or Task Scheduler.
- Set `DEBUG=false`, a random `SECRET_KEY` of 50 or more characters, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `FRONTEND_URL`, `CSRF_TRUSTED_ORIGINS` and SMTP values.
- Serve Django with `gunicorn config.wsgi` behind HTTPS, run `migrate` and `collectstatic`, and host `frontend/dist` as a static site with `/api` proxied to Django.
- Create the first admin with `manage.py createsuperuser`.

## Landing page and growth features

Logged-out visitors at `/` see the landing page, with prices from `GET /api/public/plans/`. Logged-in users can see it at `/welcome`.

| Feature | Where |
|---------|-------|
| Free trial, public listing | Plan form: `trial_days`, `is_public` |
| Promo code | Discount form: `code`. The demo seed adds `WELCOME20` |
| Start a plan | Customer portal: Browse plans |
| Change plan, promo code, pause before closing | Subscription page |
| One-off charge or credit | Subscription page, admin only |
| CSV exports, recurring revenue by plan, overdue aging, churn reasons | Dashboard |
| Revenue recognition, deferred revenue, analysis and history | Revenue page, team only |
