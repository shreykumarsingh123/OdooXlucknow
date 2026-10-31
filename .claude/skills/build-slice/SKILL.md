---
name: build-slice
description: Implement one backlog slice end to end across database, API and UI, with tests and verification in the running app. Use when asked to build, implement or continue a feature or backlog item.
---

# Build a slice

## Steps

1. **Pick the slice** from the backlog in `PLAN.md`, and read its requirements and acceptance checks. If it is not in the backlog, ask whether to add it rather than building it silently.
2. **Read the surrounding code** and match its patterns. Reuse existing helpers and components.
3. **Branch** as `feat/<slice-id>-short-name`.
4. **Build from the inside out:**
   - Model and migration, with constraints.
   - Business logic in one place, not in views or components.
   - Endpoint, with authentication, role check and state check.
   - UI, with loading, empty and error states and clear validation messages.
   - Seed data that exercises the slice.
5. **Test the rules:** the expected path, one forbidden role, one invalid transition or violated rule. Prefer a few tests on real rules over many trivial ones.
6. **Verify in the running app.** Walk through each acceptance check as the relevant role. Passing tests alone do not complete a slice.
7. **Finish:** go through the definition of done in `CONTRIBUTING.md`, update the slice status in `PLAN.md`, and commit with the requirement ID.

## Guardrails

- Validate on the server even when the form already validates.
- Never trust an ID or role sent by the client without checking ownership and permission.
- Wrap multi-step writes in a transaction.
- Avoid N+1 queries on list and dashboard endpoints.
- Do not refactor unrelated code in the same change.
- Report honestly: if something is unverified or stubbed, say so and record it in `PLAN.md`.
