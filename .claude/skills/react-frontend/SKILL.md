---
name: react-frontend
description: Conventions for the React and Vite frontend covering structure, the API client, JWT handling, routing by role, forms, tables, dashboards and UI states. Use when creating or changing frontend pages, components, forms, API calls, or scaffolding the frontend.
---

# React frontend

## Scaffolding

```powershell
npm create vite@latest frontend -- --template react
```

Pick one component library at the start and stay with it rather than hand-building tables, dialogs and forms.

```
frontend/src/
  api/          # one client, one module per resource
  auth/         # token handling, current user, route guards
  components/   # shared UI
  pages/        # one folder per screen
  routes.jsx
```

Commit `package-lock.json`, since CI runs `npm ci`.

## API client

All requests go through one client. Components never call `fetch` directly.

- Read the base URL from `import.meta.env.VITE_API_BASE_URL`. Vite exposes `VITE_` variables in the browser bundle, so never put secrets in them.
- Attach the access token, and on a 401 try one refresh and then log out.
- Convert errors into the API's `{code, message, fields}` format, so forms can show `fields` next to inputs.

## Server state

Use TanStack Query for fetching and caching. After a mutation, invalidate the affected lists and dashboard queries, so that numbers update without a reload.

## Routing and roles

Guard routes and hide actions by role for usability, but treat this as cosmetic. The server enforces access. Show a clear 403 page instead of a blank screen.

## Every data view handles

- **Loading:** skeleton or spinner.
- **Empty:** a message and the next action.
- **Error:** a readable message and a retry.
- **Success:** a toast, and updated data.

## Forms

Use React Hook Form. Disable submit while pending to prevent double submits. Show server validation errors on their fields. Show dates and currency in one consistent format.

## Workflows and dashboards

- Only show actions valid for the record's current state and the user's role.
- Show status as a consistent coloured badge with its text, not colour alone.
- Ask for confirmation on destructive or irreversible actions.
- Let dashboard cards link to the filtered list behind the number.
- Take metric definitions from `docs/ANALYSIS.md`, and compute them on the server rather than in the browser.

## Check before finishing

- [ ] `npm run lint` and `npm run build` pass.
- [ ] No console errors on the changed screens.
- [ ] Checked as each relevant role, and at a narrow width if the problem expects mobile use.
