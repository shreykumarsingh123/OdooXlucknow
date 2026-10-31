---
name: design-system
description: Choose the stack and design the data model, API, permissions and screens in docs/ARCHITECTURE.md, based on docs/ANALYSIS.md. Use after the analysis is done, or when asked about architecture, schema, database design, endpoints or tech choices.
---

# Design the system

Requires a completed `docs/ANALYSIS.md`. If it is empty, run `/analyze-problem` first.

## Steps

1. **Check constraints.** Read the required and banned technology in `docs/PROBLEM.md`. If the event requires building on Odoo, design Odoo modules (models, views, security rules, workflows) in place of a separate stack.
2. **Choose the stack.** Default to what the team can ship fastest, starting from the default in `CLAUDE.md`. Add a technology only when a requirement needs it. Record the choice as an ADR.
3. **Design the data model** before any screens:
   - Put invariants in the database where possible: foreign keys, unique constraints, check constraints.
   - Store state as an explicit field with a defined set of values.
   - Prevent races on limited resources with transactions and row locks. See `/mysql-database`.
   - Keep history where the problem needs an audit trail. Prefer status changes to hard deletes for records others reference.
   - Compute derived numbers rather than storing them, unless performance demands it.
4. **Design the API** around actions. State transitions get explicit endpoints, for example `POST /bookings/{id}/approve`, so each can check role and current state in one place. Define one error format and use it everywhere.
5. **Design permissions** as a role-to-action table enforced on the server, including row-level ownership where it applies.
6. **List the screens** per role, with their key actions and their loading, empty and error states.
7. **Fill in the traceability table** so that each P0 requirement has an entity, an endpoint and a screen. A blank cell is a design gap.

## Check before finishing

- [ ] Every business rule has a named enforcement point.
- [ ] Every transition in the analysis has an endpoint and a role check.
- [ ] Every dashboard metric can be computed from the schema.
- [ ] Nothing in the design lacks a requirement behind it.

## Output

Update `docs/ARCHITECTURE.md` with Mermaid diagrams and add ADRs to `docs/DECISIONS.md`.
