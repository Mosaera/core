#!/bin/sh
# Does install.mosaera.dev serve what the mirror serves?
#
# The one-liner's URL is a SECOND ORIGIN for `install.sh`, and on 2026-09-02 it was six commits and
# 8,832 bytes behind: four installer fixes had shipped, been verified against the mirror, and been
# reported as delivered, while every operator kept running a script from 28 August. "It is fixed"
# and "it is still broken" were both true, because they were about different files.
#
# So this compares the two FETCHED BYTES. It asks neither origin what it thinks it is serving, and
# it is the reason a deploy can be checked rather than assumed.
#
#   sh scripts/check-install-endpoint.sh
#     exit 0  IN SYNC
#     exit 1  DRIFTED       the endpoint is serving something else
#     exit 2  INCONCLUSIVE  one of them could not be fetched — NOT the same answer as in sync
#
# It changes nothing. Finding is not fixing.

ENDPOINT="${MOSAERA_INSTALL_URL:-https://install.mosaera.dev}"
MIRROR="${MOSAERA_MIRROR_URL:-https://raw.githubusercontent.com/Mosaera/core/main/scripts/install.sh}"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

fetch() {  # url, dest -> 0 ok
  curl -fsSL --proto '=https' --tlsv1.2 --max-time 20 "$1" -o "$2" 2>/dev/null
}

if ! fetch "$MIRROR" "$tmp/mirror"; then
  printf 'INCONCLUSIVE — could not fetch the mirror (%s).\n' "$MIRROR"
  printf '  This is NOT "in sync": nothing was compared.\n'
  exit 2
fi
if ! fetch "$ENDPOINT" "$tmp/endpoint"; then
  printf 'INCONCLUSIVE — could not fetch the endpoint (%s).\n' "$ENDPOINT"
  printf '  This is NOT "in sync": nothing was compared.\n'
  exit 2
fi

sum() { sha256sum < "$1" 2>/dev/null | cut -c1-16 || shasum -a 256 < "$1" | cut -c1-16; }
e="$(sum "$tmp/endpoint")"; m="$(sum "$tmp/mirror")"

printf '  endpoint %s  %s bytes  %s\n' "$e" "$(wc -c < "$tmp/endpoint" | tr -d ' ')" "$ENDPOINT"
printf '  mirror   %s  %s bytes  %s\n' "$m" "$(wc -c < "$tmp/mirror" | tr -d ' ')" "$MIRROR"

if [ "$e" = "$m" ]; then
  printf '\nIN SYNC — the one-liner runs the current installer.\n'
  exit 0
fi

printf '\nDRIFTED — the one-liner is NOT running the current installer.\n'
# WHICH fixes are missing, not just that something differs: "the bytes are unequal" sends someone
# hunting, and the missing lines say what an operator is actually running without.
for marker in 'exit $?' ') < /dev/tty' 'Install uv? [Y/n]' '1) here'; do
  if grep -qF -- "$marker" "$tmp/mirror" && ! grep -qF -- "$marker" "$tmp/endpoint"; then
    printf '  missing from the endpoint: %s\n' "$marker"
  fi
done
printf '\n  Fix: see docs/runbooks/install-endpoint.md — the endpoint should PROXY the mirror\n'
printf '  rather than hold a copy, so that deploying is not a step that can be forgotten.\n'
exit 1
