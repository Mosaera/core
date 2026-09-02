# Planning methodology

The end-to-end approach a strong PM follows to turn a task into a plan the coder can
execute in one governed run.

## The loop

1. **Understand.** Restate the task in one sentence and the outcome that proves it
   done. If the task is ambiguous, plan the smallest interpretation that is clearly
   correct rather than guessing at scope.
2. **Locate.** Read the parts of the repo the task touches. Identify the module that
   owns the behaviour, its callers, its tests, and the conventions in play. Prefer
   extending an existing seam to introducing a new one.
3. **Design the change.** Decide the interfaces and data shapes first, then the code
   that fills them. Name the exact files and functions to add or modify.
4. **Define acceptance.** Write the concrete conditions that will be tested (see the
   acceptance-criteria playbook). Acceptance is the contract the coder builds to and
   the reviewer verifies against.
5. **Foresee.** Do a quick pre-mortem: assume the change shipped and broke — what
   broke, and what check would have caught it? Fold each answer into the plan.
6. **Sequence.** Order the steps by dependency so each is independently correct and
   the run never blocks on future work.

## Right-sizing a step

A planned step should be a single, testable unit of work — roughly what one focused
change achieves: touch a small number of files, have a clear pass/fail, and not mix
unrelated concerns. If a step needs "and" to describe it, split it.

## What not to do

Do not write implementation code in the plan. Do not expand scope "while we're here."
Do not depend on undocumented behaviour — read it or treat it as unknown.
