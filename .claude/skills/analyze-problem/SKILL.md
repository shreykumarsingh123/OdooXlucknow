---
name: analyze-problem
description: Turn the problem statement into structured requirements, roles, entities, workflows, business rules, assumptions and open questions in docs/ANALYSIS.md. Use when the problem statement arrives or changes, or when asked to analyse, break down or understand the problem.
---

# Analyze the problem

## Steps

1. Read `docs/PROBLEM.md`. If the statement section is empty, stop and ask for it. Never work from memory or from a guess about what the event usually asks.
2. Read it twice: once for the overall goal, once line by line, extracting every noun, verb, number and constraint.
3. Fill in `docs/ANALYSIS.md`:
   - **Requirements:** one row per testable behaviour, in the statement's wording, with an ID and an acceptance check an observer could verify.
   - **Roles:** what each can and must not do. Prohibitions are requirements too.
   - **Entities:** nouns that hold data over time.
   - **Workflows:** every state and transition, with who may trigger it and any side effect.
   - **Business rules:** limits, overlaps, deadlines, approvals and calculations.
   - **Metrics:** an exact definition for each number on a dashboard, including date boundaries and which states count.
   - **Edge cases:** concurrent actions, cancelling midway, deleting referenced records, empty states, past dates.
4. Prioritise. P0 means the demo fails without it. Anything the statement explicitly requests is P0 or P1, never P2.
5. Separate facts from inference. Everything not stated goes under Assumptions with a note on what changes if it is wrong.
6. Write open questions with a default, so that work is not blocked waiting for an answer.
7. Map the judging criteria to visible features, if criteria are known.

## Check before finishing

- [ ] Every sentence of the statement is reflected in a row, or deliberately noted as context.
- [ ] Every requirement has a priority and an acceptance check.
- [ ] Every state has a way in, and a way out or a clear reason it is final.
- [ ] Nothing is presented as a requirement without a source in the statement.

## Output

Update `docs/ANALYSIS.md` and the status line in `PLAN.md`. Report the requirement counts by priority, the riskiest ambiguity, and the questions to ask organisers.
