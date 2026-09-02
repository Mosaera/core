#!/usr/bin/env bash
# Mosaera one-liner installer / updater.
#
#   curl -fsSL https://install.mosaera.dev | bash
#
# THE CONTRACT (ADR-0117), because the ambiguity about who installs what is what broke this:
#
#   * It REQUIRES exactly one thing it cannot provide: `git`.
#   * It INSTALLS exactly one thing: `uv` — user-space, no root, announced before it runs.
#   * It DELEGATES everything else — Docker, Compose, Node — to `mosaera-setup`, which runs in a
#     terminal the operator owns and can therefore ASK before it touches anything (ADR-0116).
#
# The refusal to install system packages has not gone away; it lives where consent is possible. A
# script piped to `sh` cannot prompt at all — its own stdin is the script — which is precisely why
# hard-failing here on a missing Docker was wrong: the component that installs Docker with consent
# was never reached.
#
# Idempotent. The FIRST run clones Mosaera at the newest release tag and hands over to setup; EVERY
# later run moves to a newer tag and hands over again. It never touches your config — an existing
# `.env` is always preserved — and it will not move an install directory with uncommitted changes.
#
# Knobs (env vars, all optional):
#   MOSAERA_INSTALL_DIR   where to clone            (default: $HOME/.mosaera/core)
#   MOSAERA_REPO_URL      git remote to clone       (default: the public mirror below)
#   MOSAERA_REF           pin an exact tag or sha   (default: the newest v* tag on the remote)
#   MOSAERA_BRANCH        track a branch instead    (development, and a pre-release test)
#   MOSAERA_NO_BOOTSTRAP=1  never install uv; report it missing and stop
#   MOSAERA_NO_SETUP=1      install/update only; print the setup command instead of running it
#
# Linux is the supported target. macOS works; Windows is WSL2, from inside the distro.
# BASH, and this check has to come first and be POSIX itself. A shebang is IGNORED when a script
# is piped, so `curl … | sh` runs this under whatever /bin/sh is — dash on Debian and Ubuntu, which
# rejects `set -o pipefail` on the very next line and dies with "Illegal option -o pipefail". The
# script is otherwise POSIX-clean (no `[[`, no arrays, no here-strings); pipefail is the one thing
# it needs, and it needs it — `resolve_ref` deliberately avoids `| head -1` because a closed pipe
# under pipefail makes git exit 141. So: name the shell, print the command that works, and stop.
if [ -z "${BASH_VERSION:-}" ]; then
  printf 'This installer needs bash, and it was started with a different shell.\n' >&2
  printf 'Re-run:  curl -fsSL https://install.mosaera.dev | bash\n' >&2
  exit 2
fi
set -euo pipefail

# The public push mirror (ADR-0117 §3), created 2026-08-27. Development happens on the authenticated
# GitLab origin; this URL is the distribution artifact an unauthenticated operator can clone. An
# operator with credentials — or a fork — passes MOSAERA_REPO_URL to install from somewhere else.
REPO_URL="${MOSAERA_REPO_URL:-${MOSAERA_REPO:-https://github.com/Mosaera/core.git}}"
DOCS_URL="https://github.com/Mosaera/core/blob/main/docs/getting-started.md"
# NOT `MOSAERA_HOME`. That variable is the application's DATA directory (config/_from_env.py), and
# using it here meant an operator pointing their data at /srv/mosaera got the repository cloned into
# it. Refuse rather than guess which of the two they meant.
# `set -u` turns an unset HOME into "line 57: HOME: unbound variable" — a bash internal, from a
# script that otherwise never shows the operator one. Rare, but `env -i`, some cron setups and a
# few container images all get here.
if [ -z "${HOME:-}" ] && [ -z "${MOSAERA_INSTALL_DIR:-}" ]; then
  printf 'HOME is not set, so there is no default place to install.\n' >&2
  printf 'Set MOSAERA_INSTALL_DIR to the directory you want, and re-run.\n' >&2
  exit 2
fi
if [ -n "${MOSAERA_HOME:-}" ] && [ -z "${MOSAERA_INSTALL_DIR:-}" ]; then
  printf 'MOSAERA_HOME is the data directory, not the install directory.\n' >&2
  printf 'Set MOSAERA_INSTALL_DIR for the clone target, and re-run.\n' >&2
  exit 2
fi
INSTALL_DIR="${MOSAERA_INSTALL_DIR:-$HOME/.mosaera/core}"
UV_BIN_DIR="${UV_INSTALL_DIR:-${HOME:-/tmp}/.local/bin}"

# Set by resolve_ref; read by sync_repo and the closing report.
REF=""
TRACKING=0
#: Set by `sync_repo` when THIS run created the directory — so a later failure knows whether the
#: install predates us and must be left alone, or is ours to take back.
FRESH_CLONE=0
BOOTSTRAPPED_UV=0

# --- pretty output (orange ▸, matching scripts/dev-up.sh) ---
say()  { printf '\033[38;5;214m▸\033[0m %s\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# We may have arrived via `wget -O- | bash`, so assuming curl exists because *we* were curl'd is a
# guess. Both, or neither and we say so.
fetch() {
  # `--proto '=https' --tlsv1.2` is rustup's hardening and it costs nothing: refuse to be
  # redirected off HTTPS, and refuse a TLS version nobody should still be negotiating. It does not
  # make a piped-to-shell install verified — ADR-0117 records that residual honestly — but a
  # product that argues for governed execution should not ship the un-hardened form of the one
  # command it asks operators to trust.
  if command -v curl >/dev/null 2>&1; then
    curl --proto '=https' --tlsv1.2 -fsSL "$1"
  elif command -v wget >/dev/null 2>&1; then
    wget --https-only --secure-protocol=TLSv1_2 -qO- "$1"
  else
    die "neither curl nor wget is available, so nothing can be downloaded."
  fi
}

# --- platform gate ---
platform_gate() {
  case "$(uname -s)" in
    Linux)  ;;
    Darwin) ;;
    *) die "Unsupported platform '$(uname -s)'. Mosaera installs on Linux and macOS; on Windows use WSL2 and run this from inside the distro. See $DOCS_URL" ;;
  esac
}

# --- the one hard requirement -------------------------------------------------------------------
#
# No per-distribution table here. This script cannot read `mosaera_core.prereqs` — it needs its
# advice BEFORE a clone and before uv exists — and duplicating that table is what produced two
# origins for the same facts. After delegating everything else, the residue is one package name,
# and `git` is the one case where the package is called `git` in every family the table declares,
# macOS included. `test_git_is_the_same_package_name_everywhere` fails if that ever stops being so.
require_git() {
  command -v git >/dev/null 2>&1 || die \
    "git is required, and this script does not install system packages.
    Install it with your package manager (the package is called 'git' everywhere), then re-run."
  say "git is present"
}

# --- the one thing this script installs ---------------------------------------------------------
#
# uv is not merely a package manager here: `requires-python >= 3.11`, and `uv sync` downloads a
# managed CPython when the host has none suitable. It is the interpreter bootstrap, so nothing
# else — not the wizard, not `mosaera doctor` — can run until it exists. A piped script cannot ask,
# so ADR-0117 records this as a bounded, announced exception: user-space, no root, one vendor URL,
# opt-out, and recorded so uninstall can offer to take it away.
ensure_uv() {
  if command -v uv >/dev/null 2>&1; then
    say "uv is present"
    return 0
  fi

  # Installed, but not on PATH — the NORMAL state under `curl | bash`, because the vendor installer
  # appends to your shell profile and a non-interactive shell never sourced it. Repair the PATH for
  # this run; do not install a second copy.
  if [ -x "$UV_BIN_DIR/uv" ]; then
    PATH="$UV_BIN_DIR:$PATH"; export PATH
    say "found uv at $UV_BIN_DIR/uv (added to PATH for this run)"
    return 0
  fi

  if [ "${MOSAERA_NO_BOOTSTRAP:-0}" = "1" ]; then
    die "uv is required and MOSAERA_NO_BOOTSTRAP=1.
    Install it yourself:  curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/install.sh | sh"
  fi

  say "installing uv — the only thing this script installs (user-space, no root):"
  say "    curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/install.sh | sh"
  # The destination is PASSED, never inferred. Letting the vendor installer resolve its own target
  # from XDG_BIN_HOME/CARGO_HOME is the inherit-a-destination failure this repo has paid for once.
  UV_INSTALL_DIR="$UV_BIN_DIR" fetch https://astral.sh/uv/install.sh | sh \
    || die "the uv installer did not succeed. Install it by hand and re-run this script."
  PATH="$UV_BIN_DIR:$PATH"; export PATH
  command -v uv >/dev/null 2>&1 \
    || die "uv was installed to $UV_BIN_DIR but is still not runnable. Add it to PATH and re-run."
  BOOTSTRAPPED_UV=1
  say "uv installed to $UV_BIN_DIR (remove with: rm -f $UV_BIN_DIR/uv $UV_BIN_DIR/uvx)"
}

# --- what to install: a release, not whatever the branch was this afternoon ----------------------
resolve_ref() {
  if [ -n "${MOSAERA_REF:-}" ]; then
    REF="$MOSAERA_REF"
    return 0
  fi
  if [ -n "${MOSAERA_BRANCH:-}" ]; then
    REF="$MOSAERA_BRANCH"; TRACKING=1
    say "tracking branch $REF (not a release)"
    return 0
  fi

  local lines
  # `--sort=-v:refname` is git's OWN version sort — `sort -V` is GNU coreutils and would break on
  # macOS. And no `| head -1`: under `set -o pipefail` the closed pipe makes git exit 141, which is
  # an intermittent, platform-dependent failure for no gain.
  lines="$(git ls-remote --tags --refs --sort=-v:refname "$REPO_URL" 'v*' 2>/dev/null || true)"
  if [ -z "$lines" ]; then
    REF="${MOSAERA_DEFAULT_BRANCH:-main}"; TRACKING=1
    warn "no release tags on $REPO_URL — falling back to the '$REF' branch."
    return 0
  fi
  REF="${lines%%$'\n'*}"
  REF="${REF#*refs/tags/}"
  say "newest release: $REF"
}

# --- clone (first run) or move to the newer ref (re-run) ----------------------------------------
sync_repo() {
  if [ ! -d "$INSTALL_DIR/.git" ]; then
    say "cloning Mosaera into $INSTALL_DIR"
    # A clone we started and could not finish is ours to clean up. Pinning a ref that does not
    # exist used to leave 35 MB and a `.git` sitting there with no mention of it, so the next run
    # took the UPDATE path over a directory the operator never successfully installed.
    FRESH_CLONE=1
    mkdir -p "$(dirname "$INSTALL_DIR")"
    # The cause decides the advice. "clone failed — set MOSAERA_REPO_URL to an authenticated
    # remote" was printed for EVERY failure, including a destination that merely already exists,
    # which sent the operator to fix authentication that was never the problem.
    if [ -e "$INSTALL_DIR" ] && [ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]; then
      die "$INSTALL_DIR already exists and is not empty.
    Move it aside, or set MOSAERA_INSTALL_DIR to somewhere else, and re-run."
    fi
    git clone --quiet "$REPO_URL" "$INSTALL_DIR" \
      || die "could not clone $REPO_URL.
    If the repository is private, set MOSAERA_REPO_URL to an authenticated remote
    (e.g. https://oauth2:<token>@host/mosaera/core.git). Otherwise check your network."
    checkout_ref
    return 0
  fi

  say "updating existing install at $INSTALL_DIR"
  git -C "$INSTALL_DIR" fetch --quiet --tags --force --prune origin || \
    warn "could not reach $REPO_URL — continuing with what is already here."

  # Tag-pinning means a detached HEAD, so `merge --ff-only` is not the guard any more. A detached
  # checkout cannot lose commits — a branch still points at them — but it CAN lose uncommitted
  # edits, and that is what this refuses to do.
  #
  # `--untracked-files=no` is load-bearing. A plain `--porcelain` counts untracked files, and this
  # script CREATES one on the first run (`.env`, ignored in the real repo but not in every checkout
  # a fork might produce) — so every re-run would refuse to update, forever, over a file it wrote
  # itself. Untracked files are not at risk anyway: git carries them across a checkout, and fails
  # loudly rather than clobbering one.
  if [ -n "$(git -C "$INSTALL_DIR" status --porcelain --untracked-files=no)" ]; then
    warn "uncommitted changes in $INSTALL_DIR — staying where you are, at your own version."
    warn "your working copy is untouched; review with:  git -C \"$INSTALL_DIR\" status"
    return 0
  fi
  checkout_ref
}

checkout_ref() {
  local target="$REF"
  [ "$TRACKING" -eq 1 ] && target="origin/$REF"
  if ! git -C "$INSTALL_DIR" rev-parse --verify --quiet "$target^{commit}" >/dev/null; then
    if [ "${FRESH_CLONE:-0}" -eq 1 ]; then
      rm -rf -- "$INSTALL_DIR"
      die "'$REF' does not exist on $REPO_URL.
    Nothing was installed; the partial clone has been removed."
    fi
    die "'$REF' does not exist on $REPO_URL.
    Your existing install at $INSTALL_DIR is untouched."
  fi
  if [ "$(git -C "$INSTALL_DIR" rev-parse HEAD)" = "$(git -C "$INSTALL_DIR" rev-parse "$target^{commit}")" ]; then
    say "already at $REF"
    return 0
  fi
  git -C "$INSTALL_DIR" checkout --quiet --detach "$target" || die "could not check out $REF."
  say "now at $REF"
}

# --- config: copy the example only when there's no .env; never overwrite ---
ensure_env() {
  if [ -f "$INSTALL_DIR/.env" ]; then
    say "keeping your existing .env (never overwritten)"
  elif [ -f "$INSTALL_DIR/.env.example" ]; then
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
    say "created .env from .env.example — setup will fill in what it needs."
  else
    warn ".env.example not found in the repo; skipping .env creation."
  fi
}

# --- build the Python environment, and say so when that is what failed --------------------------
#
# THE BUG THIS EXISTS FOR. The hand-off used to be `uv run --no-sync mosaera-setup` with no sync
# anywhere, so on every fresh clone it died as `error: Failed to spawn: mosaera-setup`, exit 2 — a
# sync failure mis-reported as a missing program. Plain `uv run` would sync implicitly and would
# also fix it, and is still the wrong shape: a cold resolve prints a hundred lines and takes
# minutes, and it must finish, visibly, BEFORE a full-screen terminal application takes over.
sync_deps() {
  say "building the Python environment (this takes a few minutes the first time)…"
  # shellcheck disable=SC2086 — MOSAERA_UV_SYNC_ARGS is a deliberate word-split knob.
  ( cd "$INSTALL_DIR" && uv sync ${MOSAERA_UV_SYNC_ARGS:-} ) \
    || die "could not build the Python environment in $INSTALL_DIR. The output above says why; a network or proxy problem is the usual cause."
  say "environment ready"
}

hand_off() {
  local rev
  rev="$(git -C "$INSTALL_DIR" rev-parse --short HEAD 2>/dev/null || echo '?')"
  say "installed at $INSTALL_DIR ($REF @ $rev)"

  # NOT `make up`. Starting the API is the LAST thing a fresh install needs: there is no database,
  # no account and nobody to sign in — `mosaera-setup` does all of that and starts the server itself
  # when it is finished (ADR-0116). Running the server first landed the operator on a login form for
  # an instance that could not be logged into.
  #
  # `exec < /dev/tty` is the whole trick. This script is piped to `sh`, so its stdin is the SCRIPT —
  # which is precisely why setup was made a separate command rather than prompts in here. Reopening
  # the controlling terminal gives the wizard a real stdin without this script trying to prompt
  # through itself.
  if [ "${MOSAERA_NO_SETUP:-0}" != "1" ] && [ -e /dev/tty ] && exec < /dev/tty; then
    say "starting setup…"
    ( cd "$INSTALL_DIR" && exec uv run --no-sync mosaera-setup )
    return 0
  fi

  # No controlling terminal — CI, a container build, a cron. This is a SUCCESS, not a degraded run:
  # the environment is built and verified, and the wizard was never promised without a terminal.
  say "installed. Run setup with:"
  printf '    cd %q && uv run mosaera-setup\n' "$INSTALL_DIR"
  if [ "$BOOTSTRAPPED_UV" -eq 1 ]; then
    # The profile edit the vendor installer made will not have reached this shell's successor.
    printf '    (uv is new here — a fresh shell may need: export PATH="%s:$PATH")\n' "$UV_BIN_DIR"
  fi
  printf '\n'
}

#: Set by `--yes`, or by MOSAERA_YES=1 for a scripted install.
ASSUME_YES="${MOSAERA_YES:-0}"

usage() {
  cat <<'USAGE'
Mosaera installer — clones Mosaera, builds its environment, and hands off to the setup wizard.

  curl -fsSL https://install.mosaera.dev | bash

Options:
  -y, --yes     do not ask before installing (implied when there is no terminal)
  -h, --help    show this and exit

Environment:
  MOSAERA_INSTALL_DIR   where to clone            (default: $HOME/.mosaera/core)
  MOSAERA_REPO_URL      git remote to clone       (default: the public distribution)
  MOSAERA_REF           pin an exact tag or sha   (default: the newest v* tag on the remote)
  MOSAERA_BRANCH        track a branch instead    (development, and a pre-release test)
  MOSAERA_NO_BOOTSTRAP=1  never install uv; report it missing and stop
  MOSAERA_NO_SETUP=1      install/update only; print the setup command instead of running it

This script REQUIRES git, INSTALLS only uv (user-space, no root), and DELEGATES Docker,
Compose and Node to the setup wizard, which asks before each one. See ADR-0117.
USAGE
}

# Flags are parsed BEFORE anything happens. `--help` used to fall through and perform a full
# install — several hundred megabytes for someone who asked a question — and an unknown flag was
# ignored silently, which is the same bug wearing a worse hat.
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    -y|--yes)  ASSUME_YES=1; shift ;;
    *)
      printf 'unknown option: %s\n\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

# WHERE, before anything is written. The destination is not obvious — it is neither the current
# directory nor anything the operator typed — so it is stated and agreed to rather than discovered
# afterwards. Read from /dev/tty, NOT stdin: under `curl … | bash` the script IS stdin, and a plain
# `read` would swallow the rest of itself.
confirm_target() {
  [ "$ASSUME_YES" -eq 1 ] && return 0
  [ -r /dev/tty ] || return 0  # no terminal: nothing to ask with, and `hand_off` already says so
  printf '\n  Mosaera will be installed at:\n    %s\n\n' "$INSTALL_DIR"
  printf '  Continue? [Y/n] '
  read -r reply < /dev/tty || reply=""
  case "$reply" in
    ""|y|Y|yes|YES|Yes) printf '\n' ;;
    *)
      printf '\n'
      say "nothing was installed."
      printf '    To install somewhere else, name it and re-run:\n'
      printf '      MOSAERA_INSTALL_DIR=/path/you/want bash -c "$(curl -fsSL https://install.mosaera.dev)"\n\n'
      exit 0
      ;;
  esac
}

main() {
  say "Mosaera installer"
  confirm_target
  platform_gate
  require_git
  ensure_uv
  resolve_ref
  sync_repo
  ensure_env
  sync_deps
  # The wizard's uninstall offers only what the wizard RECORDED installing, and uv is the one thing
  # installed before the wizard exists — so the fact is handed over rather than written from here.
  # One writer for that record, and it is Python (ADR-0117 §2: the exception is recorded).
  export MOSAERA_BOOTSTRAPPED_UV="$BOOTSTRAPPED_UV"
  hand_off
}

main "$@"
