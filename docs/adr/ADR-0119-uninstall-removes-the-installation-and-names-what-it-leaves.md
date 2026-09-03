# ADR-0119: Uninstall removes the installation itself, and names what it leaves

- Status: accepted
- Implementation: shipped
- Date accepted: 2026-08-28
- Owners: engineering
- Related issue / MR: #119 (first-run setup)
- Supersedes / Superseded by: amends ADR-0118 (which gave the wizard a runtime to install and no way to remove one)
- Related threat model: —
- Review trigger: `uv` ships `uv self uninstall`; or the install layout stops nesting the data
  home inside the install directory; or a supported platform appears where `exec` is not available.

**Decision summary:** "Stop and remove" now removes the **installation itself** — the clone, its
virtualenv and the project data inside it — by **`exec`-ing a shell outside the tree** once the TUI
has torn down. Removal is **tiered by who can safely do it**, shared artefacts are offered
separately with a measured size and never ticked by default, and anything the wizard cannot remove
is **named on the result screen** rather than passed over in silence.

## Context

An operator ran the wizard on a fresh Mac, pressed Ctrl-X — "stop and remove" — and was left with
the entire installation on disk. Measured on a developer box:

| what | size | before this ADR |
|---|---|---|
| install directory (clone + `.venv`) | **663 MB** | **no row at all** |
| `~/.cache/uv` | **1014 MB** | never touched |
| `~/.local/share/uv` (managed CPython) | **116 MB** | never touched |
| `~/.local/bin/{uv,uvx}` | 64 MB | removed — the only thing that was |

So "remove" removed about 3% of what the install had put on the machine, and the largest single
item had no row. `install.sh` also bootstraps uv **without asking** (ADR-0117 §2), which makes its
footprint the one an operator is most entitled to get back.

ADR-0118 made this worse in one specific way: it let the wizard install **Colima**, recorded as
`prereq:docker`. Every `prereq:` key returns `[]` from `commands_for` and reports "run it yourself".
So the wizard could start a VM on a machine it chose the runtime for, and then hand the teardown
back to the operator.

**The reason the install directory had no row is real, not an oversight.** The process runs *from*
the directory — `install.sh` ends with `( cd "$INSTALL_DIR" && exec uv run … )` — and its
interpreter lives in that directory's `.venv`. Deleting it from inside works right up until the
first module that had not yet been imported, and Python imports lazily; the operator would get a
traceback on top of a half-removed install.

## Decision

### 1. Tier the removal by who can safely do it

- **The wizard does it** — containers, volume, images, config keys, Colima (`colima delete --force
  --data`, then `~/.colima` and `~/.lima`), the uv binaries, the uv shared trees. None of these is
  the ground it stands on.
- **The launcher does it** — the install directory, by `exec`, as the final act.
- **Nobody does it, and it is named** — Homebrew, brew packages other projects may use, Docker
  Desktop, anything present before us.

### 2. The installation is removed by `exec`-ing out of it

`_hand_off_removal` runs after `app.run()` returns, which is when Textual has restored the terminal:

```python
os.chdir("/")
os.execv("/bin/sh", ["sh", "-c", f"rm -rf -- {quoted} && rmdir {parent} 2>/dev/null; …"])
```

**A process must not be the last user of the thing it is deleting.** That is rustup's rule; it needs
a scheduled-copy dance on Windows and gets it for free on Unix, where `exec` replaces the process
image outright — every descriptor into the old virtualenv closes, and `/bin/sh` is outside the
doomed tree. The shell's exit status becomes ours, so the removal still **reports**: it re-tests the
path afterwards and says so if anything survived, rather than being fired and forgotten.

`rmdir` on the parent, never `rm -rf`: the default layout is `~/.mosaera/core`, and leaving an empty
`~/.mosaera` behind is untidy, while removing a parent that still holds something would take data no
row offered.

The intent is recorded **before** the removal runs, so an operator who asked for it still gets it
when an earlier item fails. A half-removed install that leaves the tree behind is the worst outcome
available.

### 3. Shared artefacts are their own row, sized, and never a default

uv's caches and downloaded interpreters are **shared with every other uv project on the machine**.
They get a row that states the measured size (`Remove uv's shared caches (1.0 GB)`), separate from
the two binaries, which are ours alone. Offered, never assumed.

### 4. What we did not put there, we do not take

Several published uninstall guides recommend `rm -rf ~/.docker` when removing Colima. **We do not.**
That directory holds Docker Desktop's configuration, the operator's contexts, and other tools' CLI
plugins. Only the one `cli-plugins/docker-compose` symlink ADR-0118 created is ours to take back.

### 5. Silence is not cleanliness

An uninstall that does not mention what it left is not clean, it is quiet. The result screen
distinguishes removed, left, and could-not-and-why.

## Consequences

- **"Stop and remove" now means it.** The default layout nests the data home inside the install
  directory, so one removal covers the clone, the virtualenv, `settings.json`, runs and workspaces.
- **The wizard can no longer install something it cannot remove.** That property is what ADR-0118
  broke and this restores; the Colima row exists because that ADR created the obligation.
- **`commands_for("install")` returns `[]` deliberately** — a signal, like `server`. `perform`
  reports it as "removed as this wizard exits" rather than claiming a completed removal before the
  fact, which is the honesty rule this repo applies to every other gate.
- **The uv shared caches are opt-in, so a default removal leaves ~1 GB.** That is the correct trade:
  they are not ours alone, and the row says how much and what it costs to re-fetch.
- **`exec` is POSIX-only.** Windows is WSL2 from inside the distro (`install.sh`), where this holds.
  A native-Windows target would need rustup's scheduled-copy approach and is out of scope.
- **Amended 2026-09-01: the checklist is one question.** §1's tiering stands, but the SCREEN that
  presented it does not. Nine rows arriving unticked was friction without protection: it asked the
  operator to assemble their own removal, and the obvious assembly was the unsafe one — ticking
  "Remove Mosaera itself" alone left the database volume AND the running server behind while the
  result screen reported a clean removal. Both were reported live, days apart, by the same
  operator. Destructive-action guidance is that friction should MATCH SEVERITY; a list of
  tickboxes is a lot of friction that protects nothing, because a checklist can be confirmed
  without reading a single row.

  So: one screen, one question, everything of ours already selected, the cursor resting on Cancel,
  and the consequences shown rather than assembled. **The unticked rule is reversed deliberately
  and only for the rows that are OURS** — §3's shared artefacts (uv's caches) leave the SELECTION
  rather than the screen, and are named under what is left behind, because taking them would be
  the worse failure and saying nothing about them is the other way to get this wrong (§5).
- **Amended 2026-08-31: removing the installation IMPLIES stopping its server.** The rows arrive
  unticked, which is right for destructive ones — but the install directory holds the data home,
  and the data home holds `api.pid`, the only handle `our_pid` has on the running server. Removing
  one without the other orphaned a process no wizard could ever find again: it kept port 8000,
  answered `/healthz`, and the NEXT install concluded it was already serving and skipped its own
  dashboard build and launch entirely, reporting success over a stranger's process. Observed end
  to end on macOS. Stopping a server destroys nothing, so implying it is a precondition of the row
  the operator ticked, not the pre-armed destructive checklist §1's unticked rule protects against.
- **The removal is not interruptible once started**, unchanged from before: a half-finished removal
  is a state nothing can describe.
