# Mosaera planning doctrine — core

The essential rules for planning and designing a software change. Apply them on every
task, in this order of priority.

1. **Read before you plan.** Open the modules you will touch; name the real files,
   functions, and signatures. Never invent an interface you have not seen — if a file
   you need is unread, read it (or say "unknown — read <file>").
2. **Smallest correct change.** Scope strictly to the task. Reuse existing modules,
   patterns, and conventions; do not refactor, rename, or add work the task did not
   ask for.
3. **Make "done" testable.** State acceptance as concrete, checkable conditions —
   exact inputs → outputs, error and exit behaviour, and the edge cases. If a claim
   cannot be tested, it cannot be trusted.
4. **Sequence by dependency.** Order steps so each builds on the last; no step may
   depend on work a later step does. Interfaces and data shapes come before the code
   that consumes them.
5. **Conform to the codebase.** Match its structure, naming, error handling, and test
   layout. New code should read as if it were already there.
6. **Name the edge cases now.** Empty or missing input, wrong types, boundaries,
   failure modes — call them out in the plan so they are built, not discovered in
   review.
7. **Anticipate, don't just react.** For each risky part, state how it could fail and
   the concrete check that proves it doesn't.
8. **Deterministic over clever.** Prefer simple, single-purpose functions and
   straightforward control flow over cleverness that is hard to verify.
