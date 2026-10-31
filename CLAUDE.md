# odooxlko

Read `PLAN.md` for the current phase and `docs/PROBLEM.md` for the problem before doing anything else.

## Rules

- `docs/PROBLEM.md` is the source of truth. Never invent a requirement. If it is empty, ask for the statement instead of guessing.
- Anything not stated in the problem is an assumption. Record it in `docs/ANALYSIS.md` and label it.
- Build vertical slices, not layers. Each slice traces to requirement IDs (`R-01`) in `docs/ANALYSIS.md`.
- Finish P0 before touching P1. Do not add features nobody asked for.
- Enforce permissions and state transitions on the server. Hiding a button is not access control.
- Never commit secrets. Configuration comes from the environment, and `.env.example` documents it with placeholders.
- A slice is done only when its acceptance checks pass and it has been exercised in the running app.
- Record significant technical choices as ADRs in `docs/DECISIONS.md`.

## Workflow skills

| When | Skill |
|------|-------|
| The problem statement has just arrived or changed | `/analyze-problem` |
| Choosing the stack, data model, APIs and screens | `/design-system` |
| Turning requirements into an ordered backlog | `/plan-slices` |
| Implementing one backlog item | `/build-slice` |
| Before the freeze, or before merging something risky | `/harden` |
| Getting ready to present and submit | `/prep-demo` |

## Tech skills

| Working on | Skill |
|------------|-------|
| Django project setup, models, settings, admin | `/django-backend` |
| REST endpoints, serializers, JWT, permissions | `/drf-api` |
| Schema, migrations, queries, locking | `/mysql-database` |
| React pages, API calls, forms, dashboards | `/react-frontend` |
| Building on Odoo itself | `/odoo-development` |
| Hosting the app for the demo | `/deploy-app` |

## Default stack

Django 5.2 LTS with Django REST Framework, React with Vite, and MySQL 8. MySQL is chosen because it is already installed and running on the main dev machine. This is a proposal, not a decision. `/design-system` confirms or replaces it against the problem. If the problem requires building on Odoo itself, use `/odoo-development` instead, because Odoo runs only on PostgreSQL.

## Commands

Machine setup is in `docs/SETUP.md`. On this Windows machine, Python is at `C:\Python314` and `python` may resolve to a Microsoft Store stub, so use the virtual environment. Run, test and seed commands are in `README.md`.

## Working efficiently

- Plan first for large or risky tasks, and review the plan before any edits.
- Give specific prompts that name the slice, requirement ID and files. Vague prompts cause wide codebase reads.
- Write the failing test for a business rule before implementing it.
- Check UI changes in the browser with a screenshot, not only through tests.
- Start a new session for each unrelated task, and prefer that to compacting midway. `PLAN.md` and `docs/` carry the context across.
- If work drifts into files or research the slice does not need, stop and redirect it.
- Use subagents only for broad research or isolated debugging, since each one costs a full conversation.
- Use a separate git worktree per slice when people or sessions work in parallel.
- Keep the skill set small. Add a skill only for a repeated need.
- Add an MCP server or tool only when the work needs an external system that nothing already available can reach.
- When finishing a change, briefly explain what changed and why, so the team understands the code it will present.

## Git

- Branch from `main` as `feat/<slice-id>-short-name` or `fix/<short-name>`.
- Use Conventional Commits, for example `feat(bookings): reject overlapping slots (R-07)`.
- Keep `main` runnable. Merge small and often.
