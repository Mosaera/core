#!/bin/sh
# Is there any Mosaera left on this machine?
#
# ASKS THE MACHINE, NOT THE UNINSTALLER. Every probe is a plain system command; no Mosaera code is
# imported and no function the wizard also uses is called. That independence is the point — the
# uninstaller reporting its own success is the producer grading its own work, and this repo has
# measured six cases where a control reported an outcome it never checked.
#
# Run it BEFORE an install (expect: CLEAN) and again AFTER an uninstall (expect: CLEAN). Anything
# it reports in between is residue, and "uninstall means uninstall" is the claim that both runs
# come back identical.
#
#   sh scripts/residue-check.sh
#     exit 0  CLEAN         nothing found
#     exit 1  RESIDUE       something of ours is still here
#     exit 2  INCONCLUSIVE  a check could not run — NOT the same as clean, and never reported as it
#
# It never changes anything. Finding is not fixing.
#
# The first draft of this file had the very defect it exists to catch: one `--format` string used
# for containers, volumes AND images, which errors for each because those fields do not coexist.
# `2>/dev/null` swallowed the error and the section printed nothing while three mosaera images sat
# on the machine. Every docker query below now checks its own exit status and reports a failed
# query as INCONCLUSIVE.

FOUND=0
INCONCLUSIVE=0
note()   { printf '  %s\n' "$*"; }
residue(){ printf '  %s\n' "$*"; FOUND=1; }
unknown(){ printf '  ?? %s\n' "$*"; INCONCLUSIVE=1; }
sec()    { printf '\n== %s ==\n' "$1"; }
have()   { command -v "$1" >/dev/null 2>&1; }

INSTALL_DIR="${MOSAERA_INSTALL_DIR:-$HOME/.mosaera/core}"

sec "processes"
if have ps; then
  # OUR BINARIES, not the string "mosaera". Matching the bare word reported an unrelated
  # `mosaera.dev` website build, and the very grep doing the matching — a check nobody trusts is
  # a check nobody reads, and a false positive costs that trust as surely as a false negative
  # costs the machine.
  hits=$(ps ax -o pid=,command= 2>/dev/null \
         | grep -Ei 'mosaera-(api|setup)|/\.mosaera/' \
         | grep -v residue-check)
  if [ -n "$hits" ]; then
    printf '%s\n' "$hits" | while IFS= read -r l; do printf '  %s\n' "$l"; done
    FOUND=1
  else
    note "none"
  fi
else
  unknown "no ps on this machine — processes could not be checked"
fi

sec "listening ports"
ours=""
for port in 8000 8001 5432; do
  if have lsof; then
    pids=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null)
  elif have ss; then
    pids=$(ss -lptnH "sport = :$port" 2>/dev/null | sed -n 's/.*pid=\([0-9]*\).*/\1/p')
  else
    unknown "neither lsof nor ss — ports could not be checked"
    break
  fi
  for pid in $pids; do
    cmd=$(ps -p "$pid" -o command= 2>/dev/null)
    case "$cmd" in
      *mosaera*) ours="$ours $port/$pid" ;;
      *)         note "port $port held by something else (not ours): pid $pid" ;;
    esac
  done
done
if [ -n "$ours" ]; then
  for x in $ours; do residue "a Mosaera process is listening on port ${x%%/*} (pid ${x##*/})"; done
else
  note "no Mosaera process is listening"
fi

sec "docker"
if ! have docker; then
  note "docker is not installed — there is nothing of ours it could be holding"
elif ! docker info >/dev/null 2>&1; then
  unknown "the Docker daemon did not answer — containers, volumes and images WERE NOT CHECKED"
else
  # One query per kind, each with the field that kind actually has, each checked for failure.
  # A query that FAILS is unknown, never clean: that conflation is what this file exists about.
  for spec in "container:.Names:containers" "volume:.Name:volumes" "image:.Repository:images"; do
    kind=${spec%%:*}; rest=${spec#*:}; field=${rest%%:*}; label=${rest##*:}
    if out=$(docker "$kind" ls -a --format "{{$field}}" 2>/dev/null) ||
       out=$(docker "$kind" ls --format "{{$field}}" 2>/dev/null); then
      hits=$(printf '%s\n' "$out" | grep -i mosaera)
      if [ -n "$hits" ]; then
        printf '%s\n' "$hits" | while IFS= read -r n; do printf '  docker %s: %s\n' "$kind" "$n"; done
        FOUND=1
      fi
    else
      unknown "docker $label could not be listed"
    fi
  done
  [ "$FOUND" = 0 ] && note "no Mosaera containers, volumes or images"
fi

sec "files"
any=0
for p in "$HOME/.mosaera" "$INSTALL_DIR" "$HOME/.config/mosaera" "$HOME/.cache/mosaera"; do
  if [ -e "$p" ]; then residue "still on disk: $p"; any=1; fi
done
[ "$any" = 0 ] && note "none"
note "(uv, Homebrew, Colima and Docker are deliberately NOT listed — they are not ours,"
note " and an uninstall that removed them would be the worse failure)"

sec "environment"
keys=$(env | grep '^MOSAERA_' | cut -d= -f1)
if [ -n "$keys" ]; then
  printf '%s\n' "$keys" | while IFS= read -r k; do printf '  exported: %s\n' "$k"; done
  FOUND=1
else
  note "none"
fi

printf '\n'
if [ "$INCONCLUSIVE" = 1 ]; then
  printf 'INCONCLUSIVE — a check could not run. This is NOT a clean result.\n'; exit 2
fi
if [ "$FOUND" = 1 ]; then
  printf 'RESIDUE FOUND — this machine is not as it was before Mosaera.\n'; exit 1
fi
printf 'CLEAN — every check ran, and none of them found Mosaera.\n'
