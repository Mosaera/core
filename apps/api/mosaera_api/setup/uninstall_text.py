"""What the uninstall confirm screen SAYS: the selection, and what the selection leaves behind.

Split out of `uninstall.py` at the 500-line ceiling. Both functions are pure `Removable -> str`
with no removal logic in them, which is the seam: `uninstall.py` decides what CAN be removed and
does it, this decides how that reads to the operator before they commit.
"""

from __future__ import annotations

from mosaera_api.setup.ui import DIM
from mosaera_api.setup.uninstall import Removable


def summary(selected: list[Removable]) -> str:
    """What is about to happen: the action on its own line, its cost indented beneath.

    One long line per item wrapped mid-sentence and dropped the continuation to column zero, so the
    list stopped looking like a list exactly where it mattered most.
    """
    return "\n".join(
        f"  {'· ' if not r.destructive else '! '}{r.label}\n      [{DIM}]{r.detail}[/]"
        for r in selected
    )


def survives(selected: list[Removable], offered: list[Removable]) -> str:
    """What this selection LEAVES, said before it runs rather than found on the next install.

    "Remove Mosaera itself" used to close with "the machine is left as it was before the install
    command was run". The database volume is a Docker volume — on macOS inside the Colima VM,
    nowhere near the install directory — so removing the installation without ticking "Delete all
    project data" left it, and the next install adopted it: a "clean" first run that opened on
    `Accounts: 1` (live macOS run, 2026-08-30). The bundled password is the static compose
    default, so a surviving volume authenticates against a fresh clone perfectly.

    Nothing is armed here (ADR-0119 §5, silence is not cleanliness): the leave-behind is NAMED and
    the operator decides, the same rule the result screen already follows.
    """
    keys = {r.key for r in selected}
    # Nothing to warn about unless a bundled volume is on offer (an external database has none),
    # is being KEPT, and something that decrypts or locates it is being taken.
    if not any(r.key == "data" for r in offered) or "data" in keys:
        return ""
    if not keys & {"install", "config"}:
        return ""
    kept = (
        "This removes the installation but KEEPS the database volume: your projects, runs and "
        "accounts survive, and a later install will find them and resume rather than start "
        "clean.  "
        if "install" in keys
        else ""
    )
    # MOSAERA_SECRET_KEY leaves with `.env` while the secrets it decrypts stay in the volume —
    # ADR-0039 names losing the key as exactly the cost of at-rest encryption, and since ADR-0126
    # it is a key the wizard minted rather than one the operator chose to hold.
    return (
        f"{kept}MOSAERA_SECRET_KEY goes with it — the GitLab token and provider keys stored in "
        "that volume are encrypted with it and cannot be read back without it; copy it out of "
        ".env if you intend to reuse the data. Tick 'Delete all project data' as well for a "
        "machine with nothing of Mosaera left on it."
    )
