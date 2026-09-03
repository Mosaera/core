# The core workflow

The everyday loop for getting work done with Mosaera, start to finish: create a project, shape
it with the PM, launch an item, watch it run, answer it when it pauses, review the evidence, and
deliver. This page assumes nothing about Mosaera's internals — see
[the dashboard guide](dashboard.md) for a tour of the screens, and
[troubleshooting a stopped run](troubleshooting-runs.md) for what to do when a run doesn't finish
cleanly.

## 1. Create a project

From the Projects page, **New project** asks for a name and, optionally, a repository URL.

- Leave the repository field empty and the project starts as a fresh repository hosted on this
  server — nothing to connect first. You can publish it to GitHub later from the project's
  **Settings → Integration**.
- Point it at an existing repository and Mosaera clones it onto this server; work happens on that
  clone, and merge requests go back to the source. A private source needs the relevant provider
  (GitLab or GitHub) connected first, from the same Integration pane.

## 2. Shape the project with the PM

Every new project opens on a **Start** view: a short conversation with **Quincy**, Mosaera's PM
persona. Tell Quincy what you want built — goals, scope, constraints — the same way you'd brief a
person. When you're ready, one action ("Build the backlog") turns that conversation into a
concrete backlog of items, each with its own acceptance criteria, and the full project workspace
opens.

You can keep talking to Quincy after that point too, from the project's **PM** tab — asking what's
blocked, why something failed, or which items took several tries. Those questions are answered
from the project's own record, not guessed.

## 3. Launch an item

An item in the **Backlog** is a unit of work with acceptance criteria attached. Launching it starts
a run: an agent team plans, designs, writes the change, and validates it in an isolated sandbox
clone of the repository — your working copy is never touched directly.

Before launching, a run mode decides how much the run asks you along the way:

| Mode | What it means |
|---|---|
| **Guided** | You approve every write and the final delivery. The slowest setting, and nothing happens unwatched. The default for a new project. |
| **Autonomous** | Approves its own writes when the evidence is clear, and stops for you when it isn't. It never skips the delivery decision itself — that check is never the run's own to waive. |
| **High assurance** | Works on its own like Autonomous, but always asks you before delivering, even when everything is clear. |

Once a run is underway, its **live interaction mode** can be switched at any time from the run
page itself, independent of the setting it launched with:

| Live mode | What it does |
|---|---|
| **ask** | Every write asks you first. |
| **accept** | Writes are auto-accepted (each one is still recorded); direction changes, escalations, and delivery still ask. |
| **auto** | Only an escalation, a stuck run, or the delivery decision asks. |

A mode switch made while a gate is already open on your screen only takes effect from the run's
*next* pause — it can't reach back and resolve the one you're looking at.

## 4. Watch the run

The run page shows the agent team's work as it happens: which agent is active, what it's doing,
and a running ledger of the plan, the writes, and the checks as they complete. Nothing here is
narrated after the fact — it's the same record the run itself keeps.

## 5. Answer a gate when it pauses

A run pauses — a **gate** — whenever it reaches a point that needs a person, most commonly the
**delivery gate**: the work is finished and something has to decide whether it ships. What you can
do there depends on what the gate offers, but the shapes are consistent:

- **Approve** (labeled "Approve & deliver", or "Approve anyway" when the run is flagging a
  warning) — the change ships. Approving over a flagged warning is recorded as an override, on the
  record, not silently.
- **Revise** ("Send back to revise") — the run goes back to planning with your notes attached, and
  tries again, up to the item's revision limit.
- **Park** isn't a button you click — it's what a run does on its own when nothing independent can
  vouch for the work (see [troubleshooting a stopped run](troubleshooting-runs.md) for exactly
  when and why). A parked run is durable: it survives closing the tab, and even an API restart.

A write-level gate (an individual file write, mid-run) offers narrower choices — "Allow this
change" or "Reject it" — because it isn't the delivery decision and shouldn't borrow its verbs.

## 6. Review the evidence

Every gate is a real decision, not a formality: the panel shows what backs it up — which checks
ran, what they found, and which of the work's claims were actually verified versus merely
unchecked. A claim that couldn't be checked is never called "verified" — that distinction is kept
honest throughout the product, including in the final delivery verdict.

## 7. Deliver

Once a change is approved past the delivery gate, Mosaera commits it on the run's own branch and
writes a report. Opening it against the source repository is a separate, explicit step from your
project's **Changes** or **Delivery** view:

- A GitLab-connected project opens a **merge request**.
- A GitHub-connected project opens a **pull request**.
- A project with no provider connected keeps the work on this server until you connect one.

## 8. Merge

Merging happens on the provider itself (GitLab or GitHub) once you're satisfied with the merge or
pull request Mosaera opened — Mosaera doesn't merge on your behalf.
