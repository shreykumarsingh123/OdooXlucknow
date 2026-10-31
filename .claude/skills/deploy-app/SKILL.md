---
name: deploy-app
description: Get the app running for judges with a production checklist for Django and React, a local demo fallback, and hosting steps. Use when asked about deployment, hosting, a live URL, production settings, or running the app for the demo.
---

# Deploy the app

Read the submission rules in `docs/PROBLEM.md` first. If a live URL is not required, a reliable local demo beats a fragile deployment, so do not spend P0 time here.

Do this early, right after the walking skeleton, because first deployments often surface problems. Check current pricing and free tier limits before choosing a host, and confirm with the user before creating accounts or anything paid.

## Choosing a host

Pick the one the team already knows. The app needs three things:

- A Python host for Django.
- A static host for the React build.
- Managed MySQL. Many free tiers only offer PostgreSQL, so confirm this first. Django makes switching databases possible, but record it as an ADR and retest, especially locking and raw queries.

## Django production checklist

- [ ] `DEBUG=false`, with a new random `SECRET_KEY` set in the host's environment.
- [ ] `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS` list only the real domains.
- [ ] Served by `gunicorn` on Linux, not `runserver`.
- [ ] Static files handled by `collectstatic` with WhiteNoise.
- [ ] `python manage.py migrate` runs on each deploy.
- [ ] `python manage.py check --deploy` reviewed.
- [ ] `mysqlclient` build dependencies are available on the host, or use its documented alternative.

## React checklist

- [ ] `VITE_API_BASE_URL` is set at build time to the deployed API.
- [ ] The host rewrites unknown paths to `index.html`, so that refreshing a page works.

## Demo data

Seed demo accounts only. Change or disable them after judging, and never reuse real passwords.

## Local fallback

Keep this working even if a deployment exists:

- A fresh database with `python manage.py migrate` and `python manage.py seed_demo`.
- Backend on port 8000 and frontend on port 5173.
- A tunnel only if judges must reach your laptop, and only for the duration of the demo.

## Check before finishing

- [ ] A full walkthrough on the deployed URL, in a private window, as each role.
- [ ] The URL and demo logins are recorded for the submission, as the rules require.
