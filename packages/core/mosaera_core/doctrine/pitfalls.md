# Common pitfalls (and how planning prevents them)

Recurring failure modes in autonomous software work, and the planning move that heads
each one off. Anticipate these in the design's risks/mitigations.

## Scope creep

The change grows "while we're here." → Scope strictly to the task; list only the files
the task requires; defer anything else to a separate item.

## Half-finished structural work

A refactor extracts helpers but leaves the original function fat, or scatters work into
a stray second file — and it can still pass behavioural tests. → State the structural
acceptance explicitly (what "decomposed" means, where the code must live) so the target
is unambiguous and verifiable, and consolidate — do not leave parallel versions.

## Thrashing on a subtle edge

A tricky rule (associativity, precedence, off-by-one, boundary) is missed, and the run
churns with scratch files and repeated attempts. → Call the edge out in the acceptance
criteria with a concrete example (e.g. "left-associative: `8/2/2 == 2`") so it is built
deliberately, not stumbled on. Do not leave debug/scratch files behind.

## Guessing an interface

The plan invents a signature that doesn't exist. → Read the file first; if you can't,
mark it "unknown — read <file>" rather than inventing.

## Silent breakage of existing behaviour

A change quietly breaks a caller or an existing test. → Make "existing tests still
pass" an explicit acceptance criterion; identify callers of anything you modify.

## Task that contradicts an existing test

The task changes a contract that an existing test encodes (e.g. "saving a label twice
now UPDATES instead of appending" while a test asserts the old append behaviour). The
coder cannot resolve this alone: it is forbidden to weaken tests, so it either thrashes
or — worse — declares the failing test "expected" and ships broken. → When decomposing
or re-scoping, detect this collision and state it explicitly: name the specific test(s)
whose contract the task changes, and make "update <test> to the new contract" an
explicit, acceptance-checked step in the plan. That authorization is what lets the coder
legitimately update the test instead of stopping. If the collision is unintended, the
task — not the test — is wrong.

## Unhandled failure paths

Only the happy path is built; bad input crashes with a raw traceback. → Enumerate the
failure modes (missing file, malformed data, wrong type) and specify clean, typed
handling for each.

## Integration gaps

Individually-correct pieces don't work together. → Plan explicit end-to-end checks;
don't assume integration is free.

## Trusting the reviewer as an oracle

An approving review is not proof of correctness — reviewers miss things. → Rely on
concrete acceptance tests as ground truth, not on approval alone.
