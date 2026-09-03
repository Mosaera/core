# The narrow probe: a sweep of the setup wizard, 2026-08-31

**One defect class, six live instances, found across four days — three of them by an operator
running the product rather than by a test.** This is the record of the deliberate sweep that
followed, and of what the sweep found that the incidents had not.

## The shape

> A probe answers a narrower question than the one asked of it, and the caller treats the narrow
> answer as the broad one.

It is not a bug in the probes. Every one of them is correct about what it literally measures. The
defect is at the seam, where a measurement becomes a **claim to the operator**.

| the check | what it establishes | what the caller concluded |
|---|---|---|
| `psycopg` connect fails | the connection did not succeed | nobody else holds this port |
| `socket.create_connection` | a port accepted a TCP connection | the server works |
| `/healthz` answers | *a* server is healthy | **our** server is up |
| `write_env_file` returns | the file was written | the setting is in effect |
| `index.html` exists | a bundle was built once | the dashboard is current |
| `image inspect` exits 0 | an image has that tag | the image matches its Dockerfile |
| `shutil.which("node")` | node is installed | the dashboard can be built |
| `docker volume ls` exits non-zero | **the check could not run** | the volume is gone |

The last row is the sharpest: an inability to verify was read as a successful verification.

## What the sweep found that the incidents had not

The three incidents were reported by an operator. The sweep — reading every probe in the setup
surface against every claim its callers make — found three more, plus one introduced by the fixes
for the first three:

- **A stale dashboard is not a missing one.** `install.sh` updates the clone *in place*, so
  presence-only meant every update served a new backend behind the previous UI. The API already
  had `_warn_if_stale_dist` calling this "the classic reason freshly-added UI doesn't appear" — it
  warned into `api.log`, unread, and too late to rebuild.
- **A stale sandbox image is not a present one.** `image inspect` succeeding says a tag exists,
  not that it was built from the recipe on disk. The sandbox is the containment boundary, so an
  update that hardens `infra/` and is skipped because "the image is present" leaves the weaker
  container running with nothing on screen to say so.
- **`node` is not `npm`.** What runs is `npm --prefix apps/web install`; this file's own install
  plans spell the package `"nodejs npm"` because the two are separable.
- **A failed mint is not a mint that was not needed.** `ensure_secret_key` returned `False` for
  both, so a read-only `.env` left credentials in plaintext while ADR-0126 stated the opposite.
  Introduced by the fix for the plaintext finding, four days earlier.

## What was already right

Worth recording, because it shows the class is not universal and the seam is where to look:

- **`_probe_docker`** checks the daemon, and separates "not running" from "this user may not talk
  to it" — the two failures most likely on a fresh machine.
- **`admin_exists`** fails CLOSED on a store that raises: "a database we cannot read is not a
  database we may assume is empty."
- **`create_admin`** treats its own precheck as a courtesy and puts the control in an atomic
  `require_first`, because two racing wizards both passed the precheck.
- **`our_pid`** refuses to signal a pid it has not verified is our process, out of this install.
- **`_write_env`** reports a failed write rather than swallowing it.

Four of those five carry a comment naming the incident that produced them. The class is not
ignorance of the rule; it is that the rule has to be applied at *every* seam, one at a time.

## The rule

**A probe may only be read for exactly what it measured.** Three outcomes, never two: *yes*, *no*,
and *could not tell* — and the third is never silently folded into either of the others. Where a
claim is made to an operator, the claim must be established by the check standing behind it, not
by the nearest available proxy.

## Cost

Six incidents. One destroyed database and one destroyed installation (the port-conflict instance).
Three "fresh" installs that were not fresh. Five wrong diagnoses issued before the first one was
understood — every one of them asserted rather than measured, which is the same defect one level
up.
