"""Installing a prerequisite, with the terminal handed back to the operator.

WHY THIS IS NOT STREAMED INTO THE WIZARD. Every one of these needs root, and `sudo` prompts on
stdin. With Textual holding the terminal in raw mode that prompt is invisible and unanswerable, and
the wizard deadlocks with no way out — so the app SUSPENDS and the operator gets their real terminal
for the duration. They see the command, they answer the password prompt, they see the output, and
they press Enter to come back.

It also means the thing they consented to is the thing they watched happen.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from mosaera_core.prereqs import Found

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mosaera_api.setup.app import SetupApp


def install_with_consent(app: SetupApp, found: Found) -> tuple[str, bool]:
    """Run `found`'s install plan in a suspended terminal.

    Returns the line to show and whether it FAILED — the caller renders a failure red. Returning
    only a string meant "did not succeed" and "installed" arrived at the screen identically.
    """
    plan = found.plan
    if not plan.runnable:
        return f"{found.prereq.label} must be installed by hand — see {plan.docs}", True

    from mosaera_api.setup.uninstall import record_install

    failed = ""
    with app.suspend():
        print(f"\n  Installing {found.prereq.label}\n")
        for step in plan.steps:
            print(f"  $ {step.command}")
            # shell=True because these are the distribution's own documented one-liners, built by
            # `prereqs.plan_for` and never from anything the operator typed.
            if subprocess.run(step.command, shell=True, check=False).returncode != 0:  # noqa: S602
                failed = step.command
                break
        if not failed:
            # RECORDED BEFORE THE PROMPT. Textual's `suspend()` has no `try/finally`, so Ctrl-D at
            # the prompt below (EOFError) or Ctrl-C during the install (KeyboardInterrupt) unwinds
            # straight out — and the record written after it never happened. The package was
            # installed and uninstall would never offer to take it away.
            record_install(app.settings.home, _record_key(found.prereq.key))
            if plan.note:
                print(f"\n  {plan.note}")
        print("\n  Press Enter to return to setup…")
        try:
            input()
        except (EOFError, KeyboardInterrupt):
            # Not an error, and emphatically not a reason to leave the terminal in raw mode.
            print()

    if failed:
        return f"{found.prereq.label}: `{failed}` did not succeed", True

    return f"{found.prereq.label} installed", False


def _record_key(key: str) -> str:
    """What to remember installing.

    DOCKER, not compose. `prereqs` installs compose by running Docker's own script, and uninstall
    deliberately never offers compose on its own (it arrives and leaves with the engine) — so
    recording the key we were asked for meant the wizard installed Docker and then held no record
    that it might remove it.
    """
    return "docker" if key == "compose" else key
