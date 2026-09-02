# Demo repos — feel reliability on real shapes (#53)

Three representative repo shapes to drive through the engine and *watch how it
concludes* — the qualitative counterpart to the reliability scoreboard (`#43`).
In-repo fixtures, driven by **local path** (the host dev server clones a local
path directly — no GitLab repos needed).

| Shape | What it is | Reliability property it exercises | Expected terminal bucket |
|---|---|---|---|
| [`greenfield/`](greenfield/EXPECTED.md) | empty repo + a build-from-scratch brief | coder + oracle building from nothing | `clean_deliver` / `honest_park` (or `thrash_park` on weak models) |
| [`brownfield/`](brownfield/EXPECTED.md) | a `tests/` suite **+** a root out-of-scope invariant test | **whole-suite validation (#45)** catches an out-of-scope regression | `clean_deliver` (correct fix) or `validation_failed → honest_park` (naive fix caught) |
| [`spaghetti/`](spaghetti/EXPECTED.md) | tangled `.py`, no tests, no pytest config | the **weak-oracle testless path** (`shallow` strength) | `honest_park` (silent reviewer) / syntax-only `clean_deliver` (explicit approve) |

Each shape's `BRIEF.md` is the task handed to the engine; its `EXPECTED.md` spells
out the intended outcome + why.

## Materialize a demo as a git repo

The fixtures live as plain dirs; `materialize.py` turns one into a throwaway git
repo (greenfield = empty repo/no commit — the greenfield trigger; the others get
one seed commit), reusing the bench's git-init pattern:

```bash
python demos/materialize.py brownfield            # prints the materialized path + drive steps
python demos/materialize.py brownfield --dest /tmp/bf   # pick the location
```

## Drive it

**Fidelity caveat — read this first.** The CLI `--approve-all` **blindly approves
every gate** — it does NOT consult the gate policy, so it will happily "ship" a
`validation_failed` run. Use it only as a quick "does it run" smoke. To observe
the **real terminal buckets** (which is the point), drive the **webUI autonomous**
path — it resolves the gate through the real `autonomous_resolution` policy (parks
on blocking evidence).

### webUI (faithful gate) — recommended

1. `make up` (or `uv run mosaera-api`) so the API serves at `http://localhost:8000`.
2. New project → **`source_repo`** = the materialized path (e.g. `/tmp/bf`), set
   the project **Autonomous** flag on.
3. Approve the overview, then either **run a backlog item in Autonomous mode**, or
   **start the autonomous sweep**.
4. Watch the run page: the terminal **outcome + reason**. Cross-check it against
   the scoreboard bucket in the table above / the shape's `EXPECTED.md`.

### CLI smoke (blind approve — not faithful)

```bash
python demos/materialize.py greenfield --drive cli   # materialize + run --approve-all
# or by hand:
mosaera run --repo <materialized-path> --task "<the BRIEF>" --approve-all
```

## Record what you saw

Log the observed terminal outcome (bucket / reason / cost) vs the expected one in
[`docs/demos/observed-outcomes.md`](../docs/demos/observed-outcomes.md). Per the
50%-thrash re-baseline, expect greenfield/brownfield to sometimes **thrash** too —
capture that as a live repro for the wrong-test work (spec-lint / Proctor repair /
Layer-2 disposition — ADR-0073/0058/0075; not a new role).
