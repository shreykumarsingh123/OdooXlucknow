---
name: harden
description: Audit the app against the requirements, then check permissions, workflow integrity, data correctness, security and error handling, and fix what matters most. Use before the feature freeze, before merging risky work, or when asked to review, test or find bugs across the app.
---

# Harden the app

Report what you actually tested. Do not mark a check as passed from reading the code alone if it can be run.

## 1. Requirements audit

Go through `docs/ANALYSIS.md` row by row and mark each requirement **working**, **partial** or **missing**, based on exercising it in the app. Fix missing P0 items before anything else below.

## 2. Permissions

Call each sensitive endpoint directly, without using the UI:

- [ ] Not logged in returns 401.
- [ ] Wrong role returns 403.
- [ ] Another user's record, reached by changing the ID, is refused.
- [ ] Privileged fields such as role, status or owner cannot be set through normal update requests.

## 3. Workflow integrity

- [ ] Every invalid transition is rejected, including repeating a completed one.
- [ ] Two simultaneous actions on a limited resource cannot both succeed.
- [ ] Multi-step writes leave nothing half-done on failure.
- [ ] Deleting a referenced record is refused or handled deliberately.

## 4. Data correctness

- [ ] Each dashboard number matches a manual count on seeded data.
- [ ] Date boundaries behave correctly: today, yesterday, timezones.
- [ ] Numeric rounding and zero or negative inputs are handled.

## 5. Security

- [ ] No secrets in the repo: search the tree and the git history.
- [ ] Debug mode is off in any deployed environment, and CORS is restricted.
- [ ] Passwords are hashed by the framework. Queries are parameterised. User content is escaped when rendered.
- [ ] Dependencies are audited with `pip-audit` and `npm audit`, as applicable.

## 6. Experience

- [ ] Clean clone plus README gives a running app.
- [ ] No console errors on the demo path, and no raw stack traces shown to users.
- [ ] Failed requests show a useful message.

## Output

List findings by severity with reproduction steps. Fix what affects the demo path or data integrity, and record the rest in `PLAN.md` as known issues.
