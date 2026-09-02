#!/usr/bin/env bash
# Fresh-machine smoke check (#119): drive a clean box to "can run a task" without a browser.
#
# WHY THIS EXISTS. Mosaera had never been installed by anyone but its owner, and the acceptance
# criterion — one fresh-machine install by another person — is a thing a PERSON does. This script
# does not replace that. What it does is make the person's pass a CONFIRMATION rather than a
# discovery: everything mechanically checkable is checked here, on whatever OS the VM runs, so the
# human is left to judge the parts only a human can.
#
#   ./scripts/fresh-machine-check.sh          # report, exit non-zero if not ready
#   ./scripts/fresh-machine-check.sh --json   # same, machine-readable
#
# It is REPORT-ONLY. It never installs a package, builds an image or pulls a model — those are
# multi-gigabyte decisions that belong to the operator, and a diagnostic that acts is a diagnostic
# you stop trusting. Every failure prints the exact command that fixes it; run those, then re-run.
set -euo pipefail

say()  { printf '\033[38;5;214m▸\033[0m %s\n' "$*"; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

cd "$(dirname "$0")/.."

# Stage 1 — the host tools this script itself needs, and nothing more. `uv` must exist before
# anything Python can answer for itself, so this stage cannot delegate; it is the same pair
# `scripts/install.sh` requires, for the same reason.
#
# DOCKER IS NOT HERE ANY MORE. It was, and that made this a second origin for "is Docker usable" —
# a `command -v` that says yes to a CLI whose daemon is down, whose user is not in the group, or
# whose WSL shim errors on every invocation. Stage 2 asks the one module that knows.
for tool in git uv; do
  command -v "$tool" >/dev/null 2>&1 || die "$tool is required. See docs/getting-started.md."
done
say "host tools present (git, uv)"

# Stage 2 — everything else, from the one module the product itself reads. `mosaera doctor` derives
# the required models from the ACTIVE bindings, so this stays correct when an operator rebinds a
# role — unlike any list written here.
say "checking this deployment…"
exec uv run mosaera doctor "$@"
