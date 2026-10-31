# Contributing

## Branches

- `main` must always run.
- Branch as `feat/<slice-id>-short-name` or `fix/<short-name>`.
- Keep branches short-lived. Merge at least every few hours to avoid late integration pain.

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/) and cite the requirement where there is one:

```
feat(bookings): reject overlapping slots (R-07)
fix(auth): return 403 for non-admin role changes
docs(analysis): record assumption on partial returns
```

## Definition of done

A slice is done when:

- [ ] It traces to a requirement ID in `docs/ANALYSIS.md`.
- [ ] Its acceptance checks pass in the running app, not only in tests.
- [ ] Business rules and permissions are enforced on the server.
- [ ] Automated tests cover its core rule and one forbidden path.
- [ ] Forms show validation errors, and lists have loading and empty states.
- [ ] Seed data exercises it.
- [ ] CI is green and `PLAN.md` is updated.

## Secrets

Never commit credentials, tokens or `.env`. Add new settings to `.env.example` with a placeholder. If a secret is committed, rotate it, because removing it from history is not enough.
