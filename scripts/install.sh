#!/usr/bin/env bash
# Mosaera one-liner installer / updater.
#
#   curl -fsSL https://install.mosaera.dev | bash
#
# What it does:
#
#   * REQUIRES one thing it cannot provide: git.
#   * INSTALLS one thing: uv — user-space, no root, and it asks first.
#   * DELEGATES the rest — Docker, Compose, Node — to `mosaera-setup`, which runs in your
#     terminal and asks before installing anything.
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

# A shebang is ignored when a script is piped, so `curl … | sh` runs this under /bin/sh — which on
# Debian and Ubuntu is dash, and dash rejects `set -o pipefail` on the next line. Check first, in
# POSIX, and name the shell that works.
if [ -z "${BASH_VERSION:-}" ]; then
  printf 'This installer needs bash, and it was started with a different shell.\n' >&2
  printf 'Re-run:  curl -fsSL https://install.mosaera.dev | bash\n' >&2
  exit 2
fi
set -euo pipefail

# The public distribution mirror. Set MOSAERA_REPO_URL to install from a fork or a private remote.
REPO_URL="${MOSAERA_REPO_URL:-${MOSAERA_REPO:-https://github.com/Mosaera/core.git}}"
DOCS_URL="https://github.com/Mosaera/core/blob/main/docs/getting-started.md"
# MOSAERA_INSTALL_DIR is where the CODE goes; MOSAERA_HOME is where your DATA goes. They are
# deliberately different variables, and this one never reads the other.
#
# HOME is checked explicitly: under `set -u` an unset one would surface as a bash internal error.
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
# Set when THIS run created the directory, so a later failure knows whether the install is ours to
# clean up or was already here.
FRESH_CLONE=0
BOOTSTRAPPED_UV=0

# --- pretty output (orange ▸, matching scripts/dev-up.sh) ---
say()  { printf '\033[38;5;214m▸\033[0m %s\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# You may have arrived here via wget, so do not assume curl exists.
fetch() {
  # Refuse to be redirected off HTTPS, and refuse an obsolete TLS version.
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
# git, and only git. Everything else is installed later by `mosaera-setup`, which can ask first.
require_git() {
  command -v git >/dev/null 2>&1 || die \
    "git is required, and this script does not install system packages.
    Install it with your package manager (the package is called 'git' everywhere), then re-run."
  say "git is present"
}

# --- the one thing this script installs ---------------------------------------------------------
#
# uv is more than a package manager here: Mosaera needs Python 3.11+, and `uv sync` fetches a
# managed CPython when the host has none. Nothing else can run until it exists — so it is installed
# into your home directory, never with root, from one published URL, and only after you agree.
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

  # Ask first. This is the only software this script installs, so it is also the one thing you
  # would least expect to find on your machine afterwards.
  if [ "$ASSUME_YES" -ne 1 ] && [ -r /dev/tty ]; then
    printf '\n  Mosaera needs uv (the Python installer). It is not on this machine.\n'
    printf '    It installs to %s — user-space, no root, and removable later\n' "$UV_BIN_DIR"
    printf '    from the wizard or with: rm -f %s/uv %s/uvx\n\n' "$UV_BIN_DIR" "$UV_BIN_DIR"
    printf '  Install uv? [Y/n] '
    read -r reply < /dev/tty || reply=""
    case "$reply" in
      ""|y|Y|yes|YES|Yes) printf '\n' ;;
      *)
        printf '\n'
        die "uv is required. Install it yourself and re-run:
    curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/install.sh | sh"
        ;;
    esac
  fi
  say "installing uv (user-space, no root):"
  say "    curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/install.sh | sh"
  # The destination is passed explicitly rather than left for the vendor installer to infer from
  # XDG_BIN_HOME or CARGO_HOME.
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
  # git's own version sort, because `sort -V` is GNU-only and would break on macOS. No `| head -1`
  # either: under pipefail the closed pipe makes git exit 141.
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
    # A clone this run started and could not finish is ours to clean up, so a failed pin does not
    # leave a half-installed directory the next run mistakes for an existing install.
    FRESH_CLONE=1
    mkdir -p "$(dirname "$INSTALL_DIR")"
    # The cause decides the advice, so a non-empty directory is not reported as an auth failure.
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

  # Never update over uncommitted edits. `--untracked-files=no` is required: this script creates
  # `.env` on the first run, and counting it would make every later run refuse to update over a
  # file it wrote itself. Untracked files survive a checkout anyway.
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
# Sync explicitly rather than letting `uv run` do it implicitly: a cold resolve prints a hundred
# lines and takes minutes, and it must finish visibly BEFORE a full-screen application takes over.
# A failure here is also reported as a failed sync rather than as a missing program.
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

  # Hand over to the wizard, which sets up the database, creates your account, and starts the
  # server itself. Starting the server here would land you on a login form for an instance with no
  # account to log in with.
  #
  # The redirect is on the CHILD, not on this script. Piped to bash, this script's own stdin IS the
  # script — redirecting fd 0 here would hand the shell your keyboard as its source and the
  # installer would appear to hang after setup exits.
  if [ "${MOSAERA_NO_SETUP:-0}" != "1" ] && [ -r /dev/tty ]; then
    say "starting setup…"
    local code=0
    ( cd "$INSTALL_DIR" && exec uv run --no-sync mosaera-setup ) < /dev/tty || code=$?
    if [ "$code" -ne 0 ]; then
      # The wizard did not finish — abandoned, refused to start, or failed. Under `set -e` a
      # non-zero exit used to kill this script on the line above, so the one thing the operator
      # needed next — how to get back into setup — was printed only on the no-terminal branch,
      # and an interactive abandon ended in silence. The install itself is intact and the
      # wizard's answers are saved; say so, say how to resume, and pass its exit code through
      # rather than dressing a non-finish up as success.
      warn "setup did not finish (exit $code). Your install at $INSTALL_DIR is intact."
      printf '  Run setup again with:\n'
      printf '    cd %q && uv run mosaera-setup\n\n' "$INSTALL_DIR"
      exit "$code"
    fi
    return 0
  fi

  # No terminal — CI, a container build, a cron. A success, not a degraded run: the environment is
  # built and verified, and the wizard needs a terminal it was never given.
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

Requires git. Installs uv (user-space, no root) after asking. Everything else — Docker,
Compose, Node — is handled by the setup wizard, which asks before each one.
USAGE
}

# Parsed before anything happens, so `--help` answers a question instead of performing an install,
# and an unknown flag stops rather than being ignored.
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

# State the destination and get agreement before writing anything: it is neither the current
# directory nor anything you typed. Reads from /dev/tty, not stdin — piped to bash, stdin is the
# script itself, and a plain `read` would swallow the rest of it.
confirm_target() {
  [ "$ASSUME_YES" -eq 1 ] && return 0
  [ -r /dev/tty ] || return 0  # no terminal: nothing to ask with, and `hand_off` already says so
  # An existing install is not a question. The only true answer is the directory it is already in,
  # and a wrong one would strand it.
  [ -d "$INSTALL_DIR/.git" ] && return 0

  while :; do
    printf '\n  Mosaera will be installed at:\n    %s\n\n' "$INSTALL_DIR"
    printf '  Continue? [Y/n] '
    read -r reply < /dev/tty || reply=""
    case "$reply" in
      ""|y|Y|yes|YES|Yes) printf '\n'; return 0 ;;
    esac
    # "No" asks where instead of ending the run — you have a terminal open and have just said the
    # path is wrong.
    printf '\n  Where should it go?\n'
    printf '    1) here — %s/mosaera\n' "$PWD"
    printf '    2) somewhere else (type a path)\n'
    printf '    3) cancel\n\n'
    printf '  Choose [1/2/3] '
    read -r choice < /dev/tty || choice="3"
    case "$choice" in
      1) INSTALL_DIR="$PWD/mosaera" ;;
      2)
        printf '  Path: '
        read -r typed < /dev/tty || typed=""
        # `~` is a shell expansion and `read` does not perform it; without this, `~/apps/mosaera`
        # would create a directory literally named `~`.
        case "$typed" in
          "~") typed="$HOME" ;;
          "~/"*) typed="$HOME/${typed#"~/"}" ;;
        esac
        [ -n "$typed" ] || continue
        INSTALL_DIR="$typed"
        ;;
      *)
        printf '\n'
        say "nothing was installed."
        exit 0
        ;;
    esac
  done
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
  # The wizard's uninstall offers back only what it recorded installing, and uv is installed before
  # the wizard exists — so the fact is handed over for it to record, never written from here.
  export MOSAERA_BOOTSTRAPPED_UV="$BOOTSTRAPPED_UV"
  hand_off
}

main "$@"

# Exit explicitly. Piped to bash, this script IS stdin, and bash keeps reading it after the last
# command — with no `exit` that final read blocks until the writer closes the pipe, leaving the
# terminal apparently hung long after setup has finished.
exit $?
