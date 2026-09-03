# Troubleshooting: the run stopped

The most common thing you'll troubleshoot in Mosaera is a run that stopped without delivering.
That isn't necessarily a bug — it's frequently the product doing exactly what it's supposed to:
stop and ask rather than ship something nobody has vouched for. This page walks through what you
see, why it happens, and what to do about it. See [the core workflow](core-workflow.md) for how a
run gets to this point in the first place.

## What you'll see

A run that needs you shows one of two headline chips on its page:

- **Needs your decision** — the run reached a real decision point (most often the delivery gate)
  and is waiting on you.
- **Budget reached** — the run used up what it was allowed (a revision limit, most often) before
  it could finish cleanly.

Either way, the run is not lost. A paused run is durable — it survives closing the browser tab, and
even a restart of the server itself — so there's no rush and nothing to lose by stepping away and
coming back.

## Why it stopped — the reasons you'll actually see

Under the headline, the run names the specific reason(s) it stopped, in plain language. The most
common ones, and what each means:

| What it says | What it means |
|---|---|
| "the automated checks failed" | The tests or build failed. This is the ordinary case — send it back with what needs fixing. |
| "no automated checks could run" / "no checks were attempted" | Nothing could verify the work. Give the project a test command, or turn on the Proctor (see below), so a run has something to prove itself against. |
| "the reviewer asked for changes" / "the reviewer blocked delivery" | An independent reviewer read the diff and objected. Read what it said — it's carried into your reply notes automatically when you send the item back. |
| "the reviewers disagreed" | Two independent reviewers reached different verdicts on the same work. Neither one is authoritative over the other — read both and decide yourself; that's a decision only a person can make honestly. |
| "the security scan found problems" | A scan (secrets, static analysis) found something. Read the findings; fix them or approve past them on the record. |
| "the work couldn't be independently verified" | Nothing independent could vouch for the change — the code's own tests don't count, since they were written by the same agent that wrote the code. This is the default outcome on a fresh, test-free repository unless you've given the run something to check against. |
| "the independent checker vetoed delivery" | A held-out model reviewed the finished change and objected. Read what it flagged. |
| "not every claim was verified" | One or more of the specific promises this item made were never checked. Open the claims list to see which. |
| "the run modified the tests it was judged by" | The run changed the tests it was supposed to be judged against — always worth reading the diff before deciding anything else. |
| "the revision limit was reached" | The item used every attempt it was allowed without converging. Raise the limit, or narrow the item's scope. |

Two further outcomes describe *how* a run stopped making progress at all, rather than what it
found wrong:

- **Stalled** — the run kept looping on the same failing tests, the same review feedback, the
  same lint fixes, or kept re-planning in circles, and a breaker tripped rather than let it grind
  forever on the same thing.
- **Gave up honestly** — the agents concluded, in their own words, that they couldn't finish the
  work and said so rather than shipping something wrong.

Either of those is deliberately never dressed up as success — a run that parks, stalls, or gives up
ends *incomplete*, never *completed*, no matter how much of the work looked right along the way.

## What to do next

For most reasons above, the next step is one of a small set of moves:

- **Review the diff or the finding.** Every reason names something specific — a failing check, a
  reviewer's objection, a security finding — and reading it is the fastest way to know whether the
  fix is obvious or the request needs to change.
- **Send it back with a note.** "Send back to revise" restarts the run with your notes attached;
  a reviewer's own objection is pre-filled into that note so you don't have to retype it.
- **Adjust the item.** If the acceptance criteria were wrong, too strict, or asked for something
  that turned out to be unreasonable, editing the item and re-launching is often more useful than
  another revision.
- **Approve past an objection, on the record.** Some gates offer "Approve anyway" — shipping
  despite a flagged warning. That's allowed, but it's never silent: the override is recorded
  alongside the decision, permanently.
- **Re-run.** A few reasons ("the verdict came back unreadable", "the scan could not read this
  change") are transient — the fix is trying again, sometimes with a stronger model chosen for
  that role in Settings → Models.

## When nothing can vouch for the work at all

On a brand-new or test-free repository, a run finishing its self-checks cleanly is *not* the same
as the work being proven — the run's own tests were written by the same agent that wrote the code,
so a green run there only proves the work agrees with itself. That's why a run on a fresh
repository commonly stops and asks even when everything "looks" fine: nothing independent has
vouched for it yet. Two ways to give it something to check against:

- Turn on the **Proctor** — a separate agent that writes the acceptance test the item is judged
  against, so the coder can't grade its own homework. This is a deployment-wide setting: turning it
  on applies to every project on this instance, not just one.
- Give the project's setup a real **test command** so there's something for a run to execute and
  fail loudly on.

That stop is the product working as intended, not a defect — but knowing it's coming on a fresh
project, rather than discovering it as an unexplained dead end, is the point of this section.
