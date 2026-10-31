# Free deployment

Render runs the API and the website. Aiven provides MySQL. Brevo sends email, because Render's free plan blocks SMTP. None of these needs a paid plan for a demo. Check each provider's current limits before relying on them.

## 1. Database on Aiven

1. Sign up at aiven.io and create a free MySQL service.
2. Open the service and note the host, port, user and password. The database name is usually `defaultdb`.
3. Download the CA certificate.

## 2. Email on Brevo

1. Sign up at brevo.com.
2. Verify a sender address under Senders. Your own Gmail works.
3. Create an API key under SMTP & API.

## 3. API and website on Render

1. Sign up at render.com with GitHub, and allow it to read this repository.
2. Choose New, then Blueprint, and pick this repository. Render reads `render.yaml`.
3. Fill in the values it asks for:

| Name | Value |
|------|-------|
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | From Aiven |
| `DB_CA_CERT` | The whole text of the CA certificate |
| `SEED_PASSWORD` | A new strong password for the starting accounts. More than 8 characters, with upper case, lower case and a special character |
| `BREVO_API_KEY` | From Brevo |
| `DEFAULT_FROM_EMAIL` | Your verified Brevo sender |
| `STRIPE_SECRET_KEY` | A newly created Stripe test key |
| `VITE_API_BASE_URL` | `https://brightloop-api.onrender.com/api` |
| `FRONTEND_URL` | `https://brightloop.onrender.com` |
| `CORS_ALLOWED_ORIGINS` | `https://brightloop.onrender.com` |

4. Deploy. Render may add letters to a name that is taken. If it does, correct the last three values with the real addresses, then redeploy both services.

The API creates its tables and starting data on its first start.

## 4. Check it

1. Open `https://brightloop-api.onrender.com/api/health/` and wait for `{"status": "ok"}`.
2. Open the website and sign in as `asha@admin.com` with your `SEED_PASSWORD`.
3. Sign in as each kind of account, and try Forgot password with a real recovery address.

## Limits of the free plans

- The API sleeps after 15 minutes without visits, and the next visit takes about a minute. Open it before a demo.
- Nothing runs on a schedule, so use the Run billing and Send reminders buttons.
- Files on the API server are lost on restart. All real data is in MySQL.
- Starting accounts use addresses such as `priya@gmail.com`, which may belong to real people. Do not send them invoices or reminders, and replace them before real use.
