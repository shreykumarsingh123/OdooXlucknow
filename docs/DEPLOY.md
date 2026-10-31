# Free deployment

Render runs the API and the website. Aiven provides MySQL. Brevo sends email, because Render's free plan blocks SMTP. None of these needs a paid plan for a demo. Check each provider's current limits before relying on them.

## 1. Database on Aiven

Create a free MySQL service, and find its host, port, user, password, database name and CA certificate.

## 2. API and website on Render

1. Choose New, then Blueprint, and pick this repository.
2. Enter these six values from Aiven: `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, and `DB_CA_CERT` (the whole certificate text). Also enter `STRIPE_SECRET_KEY`, a Stripe test key.
3. Deploy. Render makes `SECRET_KEY`, `SEED_PASSWORD` and `ADMIN_PASSWORD` by itself. The API creates its tables and starting data on first start.

If Render changes a service name because it is taken, correct `FRONTEND_URL`, `CORS_ALLOWED_ORIGINS` and `VITE_API_BASE_URL`, then redeploy both services.

## 3. Check it

1. Open `https://brightloop-api-shrey.onrender.com/api/health/` and wait for `{"status": "ok"}`.
2. In Render, open `brightloop-api-shrey`, then Environment, and copy `ADMIN_PASSWORD` and `SEED_PASSWORD`.
3. Open `https://brightloop-shrey.onrender.com` and sign in as `asha@admin.com` with `ADMIN_PASSWORD`. Demo accounts use `SEED_PASSWORD`.

## 4. Optional, later

Add these under Environment on `brightloop-api-shrey`.

| Feature | Values |
|---------|--------|
| Password codes by email, using Brevo | `EMAIL_BACKEND` = `config.email.BrevoEmailBackend`, `BREVO_API_KEY`, and `DEFAULT_FROM_EMAIL` set to your verified Brevo sender |

Without email, Forgot password cannot reach anyone on the live site, and the code is never shown on screen there.

## Run everything in Docker on your own machine

```bash
docker compose up --build
```

Then open http://localhost:8080 and sign in with the local seed password in `backend/billing/management/commands/seed_demo.py`. Keys such as Stripe and Twilio are read from `.env`. This runs with `DEBUG` on, so it is for your own machine only.

Render does not use `docker-compose.yml`. It runs the API from `backend/Dockerfile`, and serves the website as a free static site.

## Limits of the free plans

- The API sleeps after 15 minutes without visits, and the next visit takes about a minute. Open it before a demo.
- Nothing runs on a schedule, so use the Run billing and Send reminders buttons.
- Files on the API server are lost on restart. All real data is in MySQL.
- Starting accounts use addresses such as `priya@gmail.com`, which may belong to real people. Do not send them invoices or reminders, and replace them before real use.
