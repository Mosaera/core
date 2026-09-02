# ADR-0123 — A project may start with no upstream

- **Status:** accepted
- **Date:** 2026-08-28
- **Issue:** #120
- **Builds on:** [ADR-0112](ADR-0112-two-named-delivery-providers.md), [ADR-0113](ADR-0113-the-oracle-plan-is-chosen-at-onboarding.md), [ADR-0120](ADR-0120-create-a-github-repository-on-a-discarded-user-grant.md)
- **Scope:** core + api + web

**Decision summary:** `source_repo` becomes **optional**. A project with none gets a working
repository initialized on the server (`init_project`); a project with one is cloned into the same
place, exactly as before, and keeps it as the upstream. Publishing to a forge becomes a later,
optional step rather than a precondition for existing.

## Context

A project could not exist without an existing repository: `ProjectSubmit.source_repo` was required
and the New project form demanded a path or URL. Two consequences, one of them invisible:

- The product could not do the thing it was being asked for — "make a project, then sync it to
  GitHub" — because there was no state in which a project had no repository.
- **Nothing on any instance could exercise repository creation.** ADR-0120's create-and-push only
  applies to a project not yet on a forge, and every project was on one by construction. Slices 4–6
  of the GitHub arc were therefore untestable end to end. That is why this ADR exists now.

## What was already true (and why this is small)

The model this decision needs was mostly already the architecture, which is the reason it costs a
function rather than a migration:

- **`clone_project` already maintains a long-lived working repository** at
  `projects_dir/<project_id>/repo` on `mosaera/project-<id>`, where work accumulates across runs.
  `source_repo` was already, in effect, *the upstream*. So the working path is **derived** from the
  project id — **no schema change and no Alembic revision** (head stays `0035_project_setup`).
- **`_init_empty` already existed** and already made the greenfield base commit, because a cloned
  repository with no commits hits the same case.
- **`reposhape` already has an `"empty"` shape** in `_NEEDS_AN_ORACLE` — ADR-0113 had already
  decided what onboarding does with a repository containing nothing.
- **`detect_delivery_provider("")` is `unknown`**, which is precisely what ADR-0120's create-and-push
  targets. The publish path for these projects did not need writing.

## Decision

### 1. `init_project` — the same destination, without a clone

`init_project(projects_dir, project_id)` does `Repo.init` at the same path `clone_project` uses,
reuses `_init_empty` for the base commit, and shares `_prepare_workspace` with the clone path.

The shared tail is **extracted rather than duplicated**, deliberately. It writes
`.git/info/exclude`, and that exclude list is load-bearing: it is what keeps `.venv`,
`node_modules` and the agent's scratch space out of every diff and every delivery. A second copy
would drift silently, and the first symptom would be shipping something that should never ship.

`origin` is **not** set. There is no upstream, and inventing one would make the later publish step
ambiguous about where it is meant to push.

### 2. A blank source is refused, loudly

`_clone_into` now rejects a blank or whitespace source. This guards a defect that did not exist
yet and would have been severe: `Path("")` **resolves to the current working directory** and
`Path("").exists()` is `True`, so a blank source would have cloned whatever directory the server
was started in into the project. That is the same cwd-inheritance shape that destroyed the
evidence store on 2026-08-10, and the guard costs one line.

### 3. Publishing pushes the working repository

ADR-0120 Amendment 1 pushed from `Path(source_repo)`. For a local-first project that is empty, so
the push now comes from `projects_dir/<project_id>/repo`. This is also *more* correct for an
imported local path, whose working clone holds committed agent work the source directory does not.
The create → push → repoint ordering and its fail-closed behaviour are unchanged.

### 4. The form leads with the empty case

Name is required; the source field is framed as *importing*. The copy changes with the field: with
a source, it explains that merge requests still go back to it; without one, it says the project
starts as a repository here **and that its code lives only here until published**.

## Consequences

- The Lovable-shaped flow is reachable: name a project, work in it, publish when ready.
- **Repository creation becomes testable for the first time.** A local-first project is the only
  kind that qualifies, and until now none could exist — so this also unblocks the open question in
  ADR-0120 about whether GitHub accepts an App *user* token for `POST /user/repos`.
- Existing projects are untouched: they carry a non-empty `source_repo` and take the clone path
  exactly as before. `source_repo: str = ""` is a default, not a type change, so every stored
  payload and existing caller keeps working.
- **A durability change worth naming.** Until a project is published, its code exists in exactly
  one place — this server, under `Settings.home`. Publishing is not only distribution; it is the
  first backup. The form says so; making that a prompt rather than a sentence is a follow-up.

## Alternatives rejected

- **A separate `working_repo` column.** Would have meant a migration and two sources of truth for
  a path that is deterministically `projects_dir/<project_id>/repo`. Storing a derivable value is
  how it drifts.
- **Reusing `clone_project("")`.** The path that made it "work" is the cwd hazard in §2 — it would
  have silently cloned the server's working directory. Rejected and then guarded against.
- **A `starts_empty` flag on the request.** The presence or absence of a source already carries the
  intent; a second field could contradict the first.

## Status of the evidence

Unit-tested: `init_project`'s branch, single commit, absent origin, exclude file and scratch dir;
the blank-source refusal (both `""` and whitespace) including that nothing is created on the
refused path; project creation with no source reaching intake with an explicit empty upstream;
intake taking the init path and **never** the clone path; the publish pushing the working
repository; and the form's submit gate and its two explanations.

**Not yet demonstrated live** ([ADR-0110](ADR-0110-agent-ownership-and-environment-truth.md)):
creating an empty project on a real instance, its intake reaching `ready` with an empty repository,
and publishing it with create-and-push — which is the same click that settles ADR-0120's open
token-type question.
