# Decomposition

How to break a project brief into a backlog of items that each fit inside one
governed run and, together, deliver the whole.

## Properties of a good item (INVEST-style)

- **Independent** — buildable without waiting on a sibling item's internal details;
  cross-item needs are expressed as explicit dependencies, not assumptions.
- **Negotiable / small** — a focused unit of work, not an epic. If it touches many
  unrelated areas or can't be tested as one thing, split it.
- **Valuable** — moves the project toward the goal; no speculative scaffolding.
- **Estimable** — clear enough that its size and risk are obvious.
- **Testable** — ships with concrete acceptance criteria that can be checked.

## Ordering and dependencies

- Sequence so foundations come first: schema and data shapes before the services that
  use them; a service before the UI that calls it; a shared utility before its
  consumers.
- Record real dependencies between items — item B "depends on" item A when B needs A's
  delivered result. An item is only runnable once its dependencies are delivered.
- Establish a **project spine early**: the skeleton (framework, module layout,
  conventions, core interfaces) that later items slot into, so they extend rather than
  reinvent.

## Integration is its own work

Features that are individually correct can still be wrong together. Schedule explicit
**integration / end-to-end items** that verify the pieces work as a whole — do not
assume integration falls out of per-feature work.

## Keep items in the sweet spot

Aim each item at a well-scoped, testable change. Oversized, ambiguous items are where
runs thrash; if an item feels large or vague, decompose it further before running it.
