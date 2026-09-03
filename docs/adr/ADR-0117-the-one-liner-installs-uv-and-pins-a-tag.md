# ADR-0117: The one-liner installs uv and pins a tag, and refuses everything else

- Status: accepted
- Implementation: shipped 2026-08-26, with the ADR-0116 browser slimming it depends on
- Date accepted: 2026-08-26
- Owners: Alejandro Rengifo
- Related issue / MR: #119 (first-time setup)
- Supersedes / Superseded by: — (extends [ADR-0116](ADR-0116-setup-is-a-terminal-wizard.md) with the one exception its consent rule cannot cover)
- Related: [ADR-0116](ADR-0116-setup-is-a-terminal-wizard.md) (setup is a terminal wizard; the refusal that moves), [ADR-0055](ADR-0055-engine-versioning.md) (versioning — what a tag means), [ADR-0088](ADR-0088-engine-maturity-channel.md) (the maturity channel a release also carries)
- Related threat model: [TM-0002](../threat-models/TM-0002-mosaera-api-web-server.md) (the install one-liner runs a third-party installer and clones from a public mirror on the operator's host)
- Review trigger: a headless/container deployment of Mosaera appears; a second vendor bootstrap is proposed; or anyone asks the installer to install a system package

**Decision summary:** `scripts/install.sh` **requires** exactly one thing it cannot provide (`git`),
**installs** exactly one thing (`uv`, user-space, no root — a bounded exception to ADR-0116's consent
rule), and **delegates** everything else to `mosaera-setup`, which can ask. It clones from a public
GitHub mirror and checks out the **latest release tag**, not a branch.

## Context

ADR-0116 moved setup into a terminal wizard and said the installer's refusal to install packages
does not disappear — it *moves* to where consent is possible. That is right, and it left a hole that
only shows up on a machine nobody has ever installed on:

**The one-liner could not run on a clean box at all.** Three separate defects, each fatal on its own:

1. `install.sh` ended with `uv run --no-sync mosaera-setup` and never ran `uv sync`. On an unsynced
   clone that is `error: Failed to spawn: mosaera-setup`, exit 2. The hand-off ADR-0116 corrected in
   August was correct in shape and broken in fact.
2. The prerequisite check hard-failed on `docker` and `node` — but the wizard is the component that
   installs those *with consent*. The script refused to proceed on the grounds that the thing which
   fixes the problem had not yet fixed it.
3. `uv` was required by the script and installable by nothing: it is not in `PREREQS`, so neither the
   script nor the wizard could obtain it. A clean machine printed three warnings and exited.

**And `uv` is not merely a package manager here.** `requires-python = ">=3.11"`, and `uv sync`
downloads a managed CPython when the host has none suitable. It is the interpreter bootstrap. Every
other component — the wizard, `mosaera doctor`, the API — is downstream of it existing.

## Decision

### 1. One requirement, one installation, everything else delegated

Stated at the top of the script, because the ambiguity about who installs what is what produced all
three defects:

> Requires exactly one thing it cannot provide: `git`.
> Installs exactly one thing: `uv` (user-space, no root).
> Delegates everything else — Docker, Compose, Node — to `mosaera-setup`, which can ask.

### 2. The uv exception, and its exact boundary

ADR-0116's rule is that consent precedes installation and a piped script cannot obtain consent. This
is a deliberate, recorded waiver of that rule for exactly one binary, and CLAUDE.md is explicit that
a control is waived by a recorded exception or not at all. The boundary is the decision:

- **user-space only, never root** — `$HOME/.local/bin`, an explicit `UV_INSTALL_DIR`, never a system
  package manager;
- **one named vendor URL** (`https://astral.sh/uv/install.sh`), printed before it runs;
- **announced** — the operator sees the exact command in the transcript, not a silent side effect;
- **opt-out** — `MOSAERA_NO_BOOTSTRAP=1` restores the refusal;
- **recorded** — the installer states the fact (`MOSAERA_BOOTSTRAPPED_UV`) and the wizard writes it
  into `setup_installed`, so uninstall offers to remove uv exactly as it offers everything else the
  wizard put on the machine. One writer for that record; the shell reports, Python records. Without
  this, the uninstall screen would list everything installed *except* the one thing installed
  without being asked — which is the item an operator is most entitled to take back;
- **and it is the only thing the script installs.** A second entry on this list is a new ADR.

**Amended 2026-09-01: it asks.** The waiver above rested on "a piped script cannot obtain consent",
and that premise was simply wrong — `install.sh` already prompts for the install directory by
reading `/dev/tty`, which is the same terminal a uv prompt needs. The waiver was therefore buying
nothing, while costing the one property this section spends five bullets defending: that the
operator knows what went on their machine. The single piece of software they did not choose was
also the one they were least likely to know was there to remove.

So the exception narrows to what it always should have been: uv is still the ONLY thing the script
installs, still user-space, still from one named URL, still opt-out by `MOSAERA_NO_BOOTSTRAP=1` —
and now **announced as a question rather than as a fact**, with the removal command in the prompt
itself. Declining is not an error path: it states how to install uv by hand and stops. Everything
else in this section stands, including the `setup_installed` record, which is now a record of
something the operator agreed to.

The destination is **passed, never inferred**. Letting the vendor installer resolve its own target
from `XDG_BIN_HOME`/`CARGO_HOME` is the inherit-a-destination failure this repo has already paid for
once (CLAUDE.md, *Live data*).

`UV_NO_MODIFY_PATH` is deliberately **not** set. The wizard's completion screen and most of the docs
tell the operator to run `uv run …` in their own shell later; suppressing the profile edit would make
every one of those lines false at their next login. Touching `~/.bashrc` is the smaller harm, and it
is named here rather than discovered.

### 3. The clone source is a public mirror; the authenticated origin stays reachable

Development happens on the private `gitlab.rengifo.me/mosaera/core`. Distribution happens from a
**public GitHub mirror**. The mirror is a distribution artifact, not a second home for the work:
Actions, Issues and outside pull requests are closed there, because a one-way distribution cannot
honour a pull request and an unmonitored issue tracker is a promise made by accident.

`MOSAERA_REPO_URL` still reaches the authenticated origin, so an operator with credentials — or a
fork — installs from wherever they choose.

This is recorded rather than merely done because it is hard to reverse: every install writes that
URL into its `origin` and keeps it forever.

#### Amendment 2026-08-27 — it is a PUBLISH PIPELINE, not a push mirror

The original text said "push-mirrored one-way from it." **A push mirror was the wrong mechanism and
would have defeated its own purpose.** Publishing the real history publishes what history *is*, and
none of the following can be removed by deleting a file on a branch:

- **1,164 commits carry a personal email in the author field** and 1,090 carry an AI co-author
  trailer. Author identity lives in the commit object; no later commit removes it.
- **A deleted file stays readable at its parent commit.** Stripping a document on a `public` branch
  hides nothing — `git show` on the mirror still serves it.
- **Tags defeat the strip independently.** §4 has `install.sh` resolve `git ls-remote --tags 'v*'`,
  so the mirror MUST carry `v*` tags; pushing the origin's tags publishes the trees they point at.
  The origin also carries `backup/*` and `pre-rebase/*` tags naming in-progress branch states.

The mechanism is therefore **`scripts/publish_mirror.sh`**: it exports a ref, removes a declared
strip list, repairs the references that strip dangles, **runs all seven guards against the built
tree**, and publishes the result as a **single commit on an orphan history**, authored as the
organization and tagged `vX.Y.Z`. Only `main` and that one tag are pushed — never `--tags`.

Two consequences worth stating plainly:

- **The public repository has no development ancestry, deliberately.** That is what §3 already
  claimed the mirror was ("a distribution artifact, not a second home"); the push mirror simply did
  not implement it.
- **The public tree must pass the same gates as the origin.** The build refuses to publish
  otherwise. This is the reason the strip list is small: an earlier cut condensed `docs/roadmap.md`
  and would have shipped `check_roadmap_claims` in a **vacuously passing** state — a control that
  appears to run and constrains nothing. The roadmap ships whole instead.

**Outside pull requests cannot actually be disabled on a public GitHub repository** — there is no
such setting, and public repositories are always forkable. The closest control is a Moderation
→ Interaction limit ("Limit to repository collaborators"), which GitHub caps at **six months** and
which therefore **expires and must be renewed**. Recorded because the original text asserted a
control that does not exist.

### 4. What an operator runs is a release, not a branch

`install.sh` resolves the newest `v*` tag with `git ls-remote --tags --refs --sort=-v:refname` and
checks it out. A re-run fast-forwards to the next tag. `MOSAERA_REF` pins an exact tag or sha;
`MOSAERA_BRANCH` tracks a branch for development and for a pre-release stranger test. When a remote
has no tags at all, the fallback to the default branch is **announced**, never silent.

Three consequences, all deliberate:

- **The operator can name what they are running.** "Mosaera at `v0.6.3`" is a fact a bug report can
  carry; "whatever `main` was that afternoon" is not.
- **A tag is a supply-chain improvement**, though not integrity: a named release beats whatever HEAD
  happened to be, and neither is a signature (see *Residual risk*).
- **Tag-pinning means detached HEAD**, so the old `merge --ff-only` guard is gone. Its replacement is
  a **dirty-tree check**: a detached checkout cannot lose commits — a branch still points at them —
  but it can lose uncommitted edits, so a dirty install directory is not moved, and the script says
  so instead of proceeding.

### 5. The environment is built before the wizard starts, and by exactly one step

`uv sync` is its own announced step, and the hand-off keeps `uv run --no-sync`. Plain `uv run` would
also fix defect 1 and is still wrong: a sync failure must read as *could not build the Python
environment*, not as a spawn error two layers down (which is precisely how defect 1 presented); the
resolver's output must finish and be seen to finish before a full-screen Textual application takes
the terminal; and every other entrypoint already assumes a synced tree, so plain `uv run` would be a
fourth opinion about who syncs.

### 6. A correction to ADR-0116: `install.sh` is not a third reader of `prereqs`

ADR-0116 records that `mosaera_core.prereqs` is one table read by `doctor`, the wizard **and**
`install.sh`. That was never true and could not be — the script needs its advice *before* a clone and
before uv exists, so it cannot call the Python table at all. It hand-rolled a `distro_hint()`
instead: a second origin for exactly the facts that ADR was written about.

The fix is subtraction, not machinery. After §1 the script has an opinion about two tools, and one of
them it installs. The residue is a single package name — and `git` is the one case where the package
name equals the binary name in **every** family the table declares, macOS included. So the message
collapses to one sentence with no per-distro branching, and the assumption is pinned *from Python*: a
test asserts every value in `PREREQS["git"].packages` is `"git"`, and its docstring names
`scripts/install.sh` as the dependent. If a distribution ever packages git differently, that test
fails and tells the next person which shell script to fix.

`prereqs` therefore has **two readers and one named non-reader, with a reason** — which is a stronger
claim than the one it replaces, because it is true.

## Consequences

- A clean machine reaches a signed-in dashboard from one command. That is the whole point, and it was
  not previously possible on any machine.
- `install.sh` gets shorter, not longer: `distro_hint()` and the docker/node/daemon branches are
  deleted as copies of `plan_for`'s output.
- `scripts/fresh-machine-check.sh` drops Docker from its stage-1 check and lets `mosaera doctor`
  report it from the table — making its own comment ("the same check `install.sh` makes for the same
  reason") true again.
- A non-tty run (CI, a container build, cron) becomes a **first-class success**: because sync now
  precedes the branch, it leaves a complete, verified installation and exits 0, printing the wizard
  command rather than pretending to be one.
- The docs that describe a Linux-only installer and a browser first-run screen become false and are
  corrected in the same change.

## Residual risk

**`curl | sh` from two vendors is trust-on-first-use.** No signature or checksum is verified — not
for the Astral installer, and not for this script. Neither does any comparable installer, which is an
explanation and not a defence. What is actually reduced: the pinned tag means the *repository* half
of the trust is a named artifact rather than a moving branch, and the uv half is bounded to one
user-space binary from one printed URL with an opt-out. Recorded in TM-0002 rather than dressed as
closed.

**The mirror is one-way.** A contribution offered there cannot be merged from there; the read-only
posture and a banner in `README.md` say so, rather than leaving an Apache-2.0 repository carrying a
`CONTRIBUTING.md` to imply otherwise.
