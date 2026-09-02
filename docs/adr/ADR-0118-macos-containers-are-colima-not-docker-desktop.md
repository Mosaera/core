# ADR-0118: On macOS the wizard installs Colima; Docker Desktop stays a manual choice

- Status: accepted
- Implementation: shipped
- Date accepted: 2026-08-27
- Owners: engineering
- Related issue / MR: #119 (first-run setup)
- Supersedes / Superseded by: —
- Related threat model: —
- Review trigger: Docker publishes a way to accept the subscription agreement that does not require
  a human to read it; or Colima stops being maintained; or macOS becomes a supported target rather
  than one that merely works.

**Decision summary:** The setup wizard offers to install **Colima** on macOS and never installs
Docker Desktop. Docker Desktop remains available and documented, by hand, with the reason stated.
The blocker is not technical — Docker's own installer supports `--accept-license` — it is that the
licence being accepted is a **commercial subscription agreement**, and a setup wizard may not agree
to one on an operator's behalf.

## Context

A first-run on macOS reported `Docker  not installed` / `Docker Compose  needs Docker first` and
offered no action: *"Docker must be installed by hand — see docs.docker.com/desktop/install/mac-install/"*.
The code said why, in one line — *"Docker Desktop is a signed application, not a package we may
install for someone"* — and that sentence was doing more work than it could carry.

It was also **inconsistent with the file it lived in**. `plan_for` routes `docker`/`compose` to
`_docker_plan` *before* reaching `package_command`, so the Homebrew path was never considered for
Docker — while two rows above, the same wizard will happily run `brew install node`. A Mac with
Homebrew was handed a dead end for a reason that applied to only one of the available routes.

Three facts settled the question:

1. **A signed application IS installable.** A Homebrew *cask* exists precisely for this, and
   Docker's own documentation gives a scriptable install with
   `sudo /Volumes/Docker/Docker.app/Contents/MacOS/install --accept-license --user=$USER`, where
   `--user` "performs the privileged configurations once during installation" and removes the
   first-run root prompt. So the original reason was not the real obstacle.
2. **The licence is the real obstacle.** Docker Desktop is free for personal use, education,
   non-commercial open source, and companies under **250 employees AND under $10M revenue** — paid
   above either threshold, and paid for government entities. `--accept-license` means *Mosaera
   accepts a commercial subscription agreement on behalf of an operator who has not read it*. That
   is not a thing a setup wizard may do, whatever its consent screen says.
3. **The cask route cannot finish anyway.** `open -a Docker --args --accept-license` is inert
   ([docker/for-mac#6979](https://github.com/docker/for-mac/issues/6979), open since 2023, "There
   are no workarounds"), so `brew install --cask docker` dead-ends at a GUI licence screen no
   terminal wizard can drive — the same class of invisible interactive block ADR-0116 engineered
   around.

## Decision

**On macOS with Homebrew present, the Docker gap is closed by installing Colima**, in three
unprivileged steps:

```
brew install colima docker docker-compose
mkdir -p ~/.docker/cli-plugins && ln -sfn "$(brew --prefix)/opt/docker-compose/bin/docker-compose" ~/.docker/cli-plugins/docker-compose
colima start
```

**Without Homebrew, nothing is installed** and both routes are named: Docker Desktop from its own
page, or install Homebrew and re-run so the wizard can help. Naming the route that *would* let us
help is the point — the previous text hid it.

Three details are load-bearing:

- **No step is privileged.** Colima needs no `sudo`, so it cannot hit the interactive-root deadlock
  under Textual's raw mode that ADR-0116 exists to avoid. Homebrew's *own* installer does want root,
  which is why a brew-less Mac is told to install it by hand rather than handed a command that
  would hang.
- **The CLI-plugin symlink is not optional.** `_probe_compose` runs `docker compose version` — the
  plugin form. Homebrew installs the Compose binary and leaves the link to you, so without this step
  the wizard would install Compose, report success, and still show Compose as missing.
  `brew --prefix` rather than a literal path: `/opt/homebrew` on Apple Silicon, `/usr/local` on
  Intel.
- **The row names what it runs.** `Plan` gains `offer`, used when the action's name is not the
  prerequisite's name. Without it the row read *"Install Docker   brew install colima …"* — naming
  one product while running another.

**Docker Desktop is not removed as an option.** It is named in the plan's note, with the reason it
is not automated, so the operator chooses between a runtime the wizard can set up and one they
install themselves. That is the whole shape of the decision: *offer both, automate only the one we
can honestly own.*

## Consequences

- **No product change was needed, and this was verified rather than assumed.** `DockerSandbox`
  shells out to the `docker` CLI (`docker_bin`, default `docker`) and presence is probed with
  `docker info`; no socket path is hardcoded anywhere in the runtime. A Colima context satisfies
  both unmodified.
- **Colima is a different runtime, not Docker Desktop**, and is therefore offered explicitly rather
  than substituted silently. An operator who wanted Desktop gets Desktop.
- **A test changed because the decision changed.** `test_macos_is_told_where_to_read_rather_than_handed_a_command`
  asserted the dead end and now asserts the offer. It is renamed and carries the reason, so the
  change reads as a recorded amendment rather than an assertion quietly relaxed to make CI pass.
- **`explain()` for a missing Compose plugin is platform-dependent now.** On Linux a missing plugin
  is answered by reinstalling the engine; on macOS it is answered by the link, because the binary is
  already there. Answering with a reinstall would have fixed nothing.
- **Uninstall is unchanged and still does not remove prerequisites** — `commands_for` returns `[]`
  for `prereq:` keys, deferring to the platform's own remover. Colima adds no new obligation here,
  but it also does not gain one: a Colima the wizard installed is a Colima the operator removes.
- **macOS remains "works", not the supported target** (`README.md`, `install.sh`). This narrows a
  gap on a platform we do not gate releases on; it does not promote it.

## Alternatives considered

- **`brew install --cask docker`.** Consistent with `brew install node`, and rejected: it inherits
  the subscription agreement *and* cannot complete unattended (#6979).
- **The documented `--accept-license --user=$USER` installer.** Technically sufficient, rejected on
  the licence alone. Available to an operator who chooses it, which is the correct place for that
  decision.
- **OrbStack.** Faster and pleasant, with a free tier that does not cover all commercial use — the
  same class of problem, so it buys nothing here.
- **Podman.** Genuinely free for commercial use and daemonless, but it is not the `docker` CLI;
  `docker info` and every `docker run` in `DockerSandbox` would need a compatibility shim or a
  socket alias. Colima needs neither.
- **Leaving it as documentation only.** The status quo, rejected: it neither installs anything nor
  explains itself, and it sits two rows below a `brew install node` the wizard will run.
