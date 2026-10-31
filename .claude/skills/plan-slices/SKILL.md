---
name: plan-slices
description: Break requirements into an ordered backlog of vertical slices in PLAN.md, starting with a walking skeleton, with owners and dependencies. Use after the design is done, when asked to plan the work, split tasks, divide work between teammates, or re-plan because time is short.
---

# Plan vertical slices

## Steps

1. Read the requirements in `docs/ANALYSIS.md` and the traceability table in `docs/ARCHITECTURE.md`.
2. Make the first slice a **walking skeleton**: login, one real record created through the UI, stored and displayed, running from a clean clone.
3. Write the remaining slices. Each one is a behaviour a user can see, crossing database, API and UI. "Build the models" is not a slice. "Manager approves a request and the requester sees the new status" is.
4. Size each slice to fit a few hours at most. Split anything larger.
5. Order by dependency, then risk, then priority. Do the slices most likely to go wrong early.
6. Assign owners so that two people are not editing the same files. Agree shared contracts (schema, API shapes) before working in parallel.
7. Add a seed-data slice early, since every later slice and the demo rely on it.

## When time is short

Re-plan rather than rushing everything:

1. Cut P2, then P1, and move them to "Not doing" in `PLAN.md`.
2. Narrow P0 slices to the path the demo actually shows.
3. Never cut server-side permissions on a demoed path, or the seed script.
4. If an explicitly required feature is cut, say so openly in the handover.

## Output

Fill in the backlog table in `PLAN.md`. Every row cites requirement IDs, and every P0 requirement appears in at least one slice.
