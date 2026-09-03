"""The words on each screen, as pure functions.

Separate from `app.py` because copy is not behaviour: what a step SAYS can be asserted without a
terminal, and the file that renders should not also be the file that decides how a machine is
described.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mosaera_core.prereqs import Found, Platform

from mosaera_api.setup.ui import DIM, MEASURE, gap_label, machine_table, split


@dataclass(frozen=True)
class Screen:
    """One painted screen: a heading, a paragraph, and an optional list to choose from."""

    title: str = ""
    body: str = ""
    choices: list[str] = field(default_factory=list)
    hint: str = ""
    #: A left-aligned block under the prose. Centred prose reads well; a TABLE centred loses its
    #: columns and stops being a table, so it gets its own widget rather than a shared alignment.
    table: str = ""
    #: The raw cause behind a summarised failure. Shown dim and small — summarising an error and
    #: then hiding what happened is how a diagnosis becomes unfalsifiable.
    detail: str = ""
    #: A dim reference line UNDER the input rule. On the Input itself it was a placeholder, which
    #: vanishes at the first keystroke — exactly when an example is most useful.
    note: str = ""


def welcome(resumed: str = "") -> Screen:
    """`resumed` is the acknowledgement from `resume.sentence`, or "" on a first run.

    It is a sentence and nothing more — the walk that follows probes the machine exactly as it
    always does, so what is skipped is decided by facts and never by the breadcrumb.
    """
    if resumed:
        # A resumed run does not need the description of what setup is — it needs to know where it
        # is. Reciting the introduction again reads as the wizard having forgotten.
        return Screen(title="Set up Mosaera", body=resumed)
    return Screen(
        title="Set up Mosaera",
        body=(
            "Configures the machine Mosaera runs on: required software, the database,\n"
            "network access, and the first account.\n\n"
            "Models are configured in the application, per agent — not here.\n"
            "Re-running changes only what is not already correct."
        ),
    )


def machine(found: list[Found], gaps: list[Found], plat: Platform, width: int = MEASURE) -> Screen:
    """The machine's shape, and what to do about it.

    A plan we cannot run must still say what the operator CAN do, on the screen, unprompted. Its
    `note` used to be reachable only by choosing the row and reading what came back — so a Mac
    without Homebrew was told "Docker — read <the Docker Desktop page>" and never told that
    installing Homebrew would let this wizard set up a runtime for it (ADR-0118). The guidance
    existed; nothing rendered it.
    """
    # Deduplicated: Docker and Compose are two gaps closed by one plan, and their note is one note.
    guidance = dict.fromkeys(g.plan.note for g in gaps if not g.plan.runnable and g.plan.note)
    # THE BODY, not `#detail`. That widget is `text-wrap: nowrap; text-overflow: ellipsis`, which is
    # right for the raw cause of a failure and wrong for a paragraph: the first cut put the guidance
    # there and it rendered as "Install Docker Desktop from the page above (it includes C…", cutting
    # off the half that says installing Homebrew lets this wizard do the work. Advice that is
    # visible but truncated is worse than advice that is absent, because it looks like all of it.
    body = "Required software, and the purpose of each."
    return Screen(
        title=f"This machine — {plat.pretty}",
        body="\n\n".join([body, *guidance]),
        table=machine_table(found, width),
        choices=[gap_label(f) for f in gaps] + ["Skip — install these manually"],
    )


#: The row that closes the one gap this screen can close by itself.
BUILD_IMAGES = "Build the sandbox images"

#: The two rows this step offers. Named because `choices.py` dispatches on the row's TEXT rather
#: than its index — a positional map is what made an earlier, conditional version run the wrong
#: action the moment the cause changed.
USE_BUNDLED = "Use the bundled database  (recommended)"
POINT_ELSEWHERE = "Enter a different database URL"
#: The bundled database has data from an earlier attempt whose credentials do not match ours.
#: Destructive, and named as such — but what it deletes is a setup that never finished.
RESET_BUNDLED = "Reset the bundled database  (deletes its data)"
#: The container is healthy and this machine cannot reach it — a publish address the host does
#: not share. Keeps the data; only where the port is published changes.
PUBLISH_FOR_HOST = "Publish the database so this machine can reach it"


def database(state: object, port: int) -> Screen:
    """One decision, two rows, whatever is wrong.

    The previous version offered up to three: create the database, use the bundled one, start the
    bundled Postgres. Those are not three choices — they are three PHASES of one job, and which of
    them appeared depended on which way the connection had failed. An operator was being asked to
    diagnose a database in order to be allowed to have one.

    Now the recommended row does all three, skipping whichever are already true, and the only real
    decision left is the one that was always real: ours, or yours.
    """
    from mosaera_api.setup.explain import explain

    why = explain(getattr(state, "reason", ""))
    url = getattr(state, "url", "") or ""
    declared = bool(getattr(state, "declared", False))
    reachable = bool(getattr(state, "reachable", False))
    missing = bool(getattr(state, "missing_database", False))

    # A FIRST RUN IS NOT A FAILURE. On a machine where nothing has been set up yet there is of
    # course nothing listening on 5432, and reporting that as "Nothing is listening on that address
    # and port" over a line of psycopg internals told the operator their brand-new installation was
    # already broken. It is only a failure when they pointed us somewhere: a declared
    # MOSAERA_DB_URL that does not answer is a real problem with a real cause.
    first_run = not declared and not reachable and not missing
    if first_run:
        lead = "No database yet — the bundled Postgres is not running."
    elif missing:
        lead = why.summary
    else:
        lead = why.summary

    lines = [lead]
    if url and not first_run:
        lines.append(f"Tried: {url}")
    if why.action and not first_run and not reachable:
        lines.append(why.action)
    lines.append("")
    lines.append(
        "Accounts, projects and run history are stored here. Setup requires one.\n"
        "PostgreSQL is the only supported engine."
    )
    return Screen(
        title=f"Database — port {port}",
        body="\n".join(lines),
        choices=[USE_BUNDLED, POINT_ELSEWHERE],
        # The raw driver text only where this wizard could not translate it. Where it could, the
        # sentence above IS that line in English and the action says what to do about it — a
        # truncated `OperationalError: (psycopg.OperationalError) connection failed: connection to
        # serve…` underneath adds nothing but alarm.
        detail="" if first_run or why.recognised else why.detail,
    )


def access(
    *,
    public_now: bool,
    blocked: str,
    port: int,
    lan: str,
    shadowed: list[str] | None = None,
    width: int = MEASURE,
) -> Screen:
    """The two binds, each showing the address it actually produces.

    "This machine only" and "Reachable on my network" describe an intent; an operator deciding who
    can reach their instance needs the address, not the adjective.
    """
    # The address goes to the box's right edge rather than after a hand-counted run of spaces, so
    # the two addresses line up under each other whatever their length. `width - 2` because
    # `choice_list` indents every option by two columns.
    options = [split("Bind to this machine only", f"[{DIM}]127.0.0.1:{port}[/]", width - 2)]
    if not blocked:
        # TWO network options, not one. `guard_bind` refuses an exposed bind whose TLS posture is
        # UNDECLARED (#124), and the reason it refuses rather than defaulting is that forcing the
        # cookie's `Secure` flag silently breaks plain-http LAN — a browser will not send a
        # `Secure` cookie over http://, and the operator's fix under pressure is to disable the
        # protection. Asking here makes the declaration the OPERATOR's: a wizard that wrote a
        # default on their behalf would satisfy the guard while waiving the control it enforces.
        options.append(
            split("Bind to this network, behind HTTPS", f"[{DIM}]{lan}:{port}[/]", width - 2)
        )
        options.append(
            split("Bind to this network, plain HTTP", f"[{DIM}]{lan}:{port}[/]", width - 2)
        )
    return Screen(
        title="Access",
        body=(
            f"Current bind: {'this network' if public_now else 'this machine only'}.\n"
            "A network bind gets a service token and encrypts stored credentials; the\n"
            "server refuses to start without both. Pick HTTPS only if a proxy\n"
            "terminates it — over plain http a Secure cookie is never sent."
            + (f"\n\nNetwork access is unavailable: {blocked}." if blocked else "")
            # Said out loud. Writing `.env` cannot change a value the shell is exporting, and
            # writing one anyway leaves the operator certain they configured something they did not.
            + (
                f"\n\n{', '.join(shadowed)} is set in your environment and wins over .env;\n"
                "unset it if you want this choice to take effect."
                if shadowed
                else ""
            )
        ),
        choices=options,
    )


def admin() -> Screen:
    return Screen(
        title="Administrator",
        body="Create the first account. It becomes this workspace's administrator.",
    )


def database_url_prompt(problem: str = "") -> Screen:
    """The URL prompt, and — when the last one failed — what was wrong with it.

    The URL is TESTED before it is kept, so this screen can be returned to any number of times
    without ever having written a URL that does not work into `.env`.

    The example lives in `note`, which is rendered UNDER the input rule. As the Input's placeholder
    it vanished at the first keystroke, which is exactly when an example starts being useful.
    """
    return Screen(
        title="Database URL",
        body=(
            (f"{problem}\n\n" if problem else "") + "Enter the full PostgreSQL connection string.\n"
            "The URL is opened and migrated before it is saved."
        ),
        note="postgresql://user:password@host:5432/mosaera",
    )


def done(
    url: str,
    username: str,
    *,
    serving: bool,
    log: str,
    seconds: int,
    cancelled: bool = False,
    attempted: bool = True,
    access: str = "",
) -> Screen:
    """The end. An address that resolves, the account that can sign into it, and a clock.

    When the server did not come up the address is NOT shown. A link that 404s or refuses is worse
    than being told where the log is, and this screen is the last thing the operator reads.
    """
    if serving:
        lead = f"Open  {url}\nSign in as  {username or 'the account created during setup'}."
    elif cancelled:
        # Not a timeout. Reporting a deliberate stop as a failure teaches the operator to distrust
        # every other failure the wizard reports.
        lead = f"Startup was cancelled.\nStart it with  make up , then open  {url} ."
    elif not attempted:
        # And neither is "we never tried". This screen used to point at a log with nothing in it
        # and blame a timeout that never elapsed — three false statements in one sentence.
        lead = (
            "The dashboard did not build, so the server was not started.\n"
            f"Fix the build, then run  make up  and open  {url} ."
        )
    else:
        lead = (
            "The server did not start within the timeout.\n"
            f"Its output is in  {log} . Start it again with  make up ."
        )
    return Screen(
        title="Mosaera is configured",
        body=(
            f"{lead}\n\n"
            f"{access + chr(10) if access else ''}"
            "Models are configured in the application, not here. Until one is set\n"
            "under Settings, Models, a run starts and then fails at its first\n"
            "model call — the dashboard banner will say so."
        ),
        # Three, matching `configured`. The finished screen offered only Finish and Uninstall, so
        # an operator who wanted to change one answer had to leave and run the installer again to
        # be offered "Re-run setup" — the same instance, the same wizard, two different menus
        # depending on which screen they happened to be looking at. Reported 2026-09-01.
        choices=["Finish now", "Re-run setup", "Uninstall Mosaera"],
        # "leave it running" is a claim, and it was made unconditionally — including on the branch
        # whose own lead says the server did not start. An operator reading the hint rather than
        # the paragraph was told the opposite of the truth, which is most of what "it said it was
        # running" meant when this was reported (2026-08-31).
        hint=(
            f"Closing in {seconds}s  ·  Enter to choose  ·  "
            + ("Ctrl-Q to leave it running" if serving else "Ctrl-Q to leave")
        ),
    )


def uninstall_confirm(removes: str, leaves: str, count: int) -> Screen:
    """The ONE screen an uninstall has. Cancel first, so the cursor rests on it.

    It replaced a nine-row checklist. Friction should match severity, and a list of tickboxes was
    friction without protection: it made the operator assemble the removal themselves, and the
    default assembly was WRONG — every destructive row arrived unticked, so the obvious path left
    the database volume and the running server behind while the screen reported a clean removal.
    "Uninstall" is one decision, and this asks it once.

    What is NOT ours stays off the list entirely rather than sitting on it unticked: uv's shared
    caches belong to every other uv project on the machine (ADR-0119 §3), and an uninstall that
    took them would be the worse failure. They are NAMED under `leaves`, because saying nothing
    about them is the other way to get this wrong (§5).
    """
    return Screen(
        title="Uninstall Mosaera?",
        body=leaves,
        # In `table`, not `body`: centred prose reads well, a centred LIST loses its left edge.
        table=removes,
        choices=["Cancel", f"Remove all {count} items" if count != 1 else "Remove it"],
        hint="Enter to choose  ·  Esc to go back",
    )


def configured(
    url: str,
    accounts: int,
    env_path: str,
    *,
    serving: bool,
    gaps: tuple[str, ...] = (),
    images_to_build: bool = False,
) -> Screen:
    """A finished instance is told so, instead of being walked through setup again.

    Every step self-skips when it is satisfied — except access, which always stops — so a configured
    box got dropped back into the flow with no acknowledgement that it was already done.

    The cursor rests on the row that changes nothing. Enter is the key people press to dismiss a
    screen, and on this one it must not start, re-run or remove anything.
    """
    where = f"Running at  {url}" if serving else f"Configured for  {url}  (not currently running)"
    # Named, not hidden. Setup being done and the box being able to RUN something are two different
    # questions; an instance with no sandbox images signs in perfectly well and runs nothing.
    outstanding = (
        f"Still outstanding: {', '.join(gaps)}.\nRuns cannot succeed until those are done.\n\n"
        if gaps
        else ""
    )
    # A GAP WITH NO WAY TO CLOSE IT is a dead end, and this screen had one: it reported "2 sandbox
    # images to build" and offered Start, Re-run, Reset and Uninstall. The only route was Re-run,
    # which walks the whole spine to reach the one thing actually missing. Reported 2026-09-02:
    # "there's no way to just run that part".
    fix = [BUILD_IMAGES] if images_to_build else []
    # The first row has to MATCH the line above it. Hardcoded to "Leave it running", it told an
    # operator to leave running an instance the same screen had just said was not running.
    #
    # And "Leave it running" was not an action: Ctrl-Q already leaves it running, so the row spent
    # the most prominent place on the screen doing what quitting does. What was MISSING is the
    # other direction — someone who wants the instance down, and does not want it uninstalled, had
    # only "Uninstall Mosaera" on offer. Stopping is not destructive: nothing is deleted, the row
    # flips back to "Start Mosaera", and Ctrl-Q still leaves things exactly as they are.
    first = "Stop Mosaera" if serving else "Start Mosaera"
    return Screen(
        title="Mosaera is configured",
        body=(
            f"{where}\nAccounts: {accounts}\n\n{outstanding}"
            f"Environment settings live in\n{env_path}"
        ),
        # A forgotten password on a self-hosted instance has no email to reset through, so without
        # this the answer was "open the database and rewrite the hash". Anyone who can run this
        # wizard can already do exactly that — it is the same local access — so what this adds is
        # a way to do it correctly rather than a permission that was not there before.
        choices=[first, *fix, "Re-run setup", "Reset a password", "Uninstall Mosaera"],
        hint=(
            "Enter to choose  ·  Ctrl-Q to leave it running"
            if serving
            else "Enter to choose  ·  Ctrl-Q to leave"
        ),
    )


def removed(results: list[str]) -> Screen:
    """Where a removal ends. NOT a step — returning to the flow after an uninstall is how the
    wizard came to start the server it had just removed.

    The body offers an INDEPENDENT check. Everything above it in `table` is this wizard's account
    of its own work, which is the weakest evidence there is for "the machine is clean" — six
    separate controls in this repo have reported an outcome they never verified. `residue-check.sh`
    shares no code with the uninstaller and is fetched over the network deliberately: the copy in
    the installation was removed along with it, and a checker that ships with the thing it checks
    is unavailable at exactly the moment it is needed.
    """
    return Screen(
        title="Removed",
        table="\n".join(f"  · {line}" for line in results) or "  · Nothing was selected",
        body=(
            "To confirm nothing is left — independently of this wizard:\n"
            "curl -fsSL https://raw.githubusercontent.com/Mosaera/core/main/scripts/"
            "residue-check.sh | sh"
        ),
        choices=["Finish"],
        hint="Enter to exit",
    )


def database_port_prompt(suggested: int, taken: int, problem: str = "") -> Screen:
    """Choose a port, with the conflict named and a working number already worked out.

    The wizard could see the collision and could only tell the operator to go and set an
    environment variable. Naming a problem the tool is holding the fix for is a diagnosis, not a
    fix — so the fix moved here.
    """
    return Screen(
        title="Database — a different port",
        body=(
            problem
            or (
                f"Something else already holds port {taken} on this machine, and it is not the "
                f"bundled database. Choosing another port changes where Postgres publishes and "
                f"what Mosaera connects to, together — nothing else on this machine moves."
            )
        ),
        hint="Enter to use it  ·  Esc to go back",
        note=f"{suggested} is free" if suggested else "",
    )


def api_port_prompt(suggested: int, taken: int, problem: str = "") -> Screen:
    """Choose a port for the dashboard, with the conflict named and a free number worked out.

    The same move `database_port_prompt` made, for the same reason and after the same report: the
    wizard could SEE that something else held the port and could only say so.

    It does NOT guess who the holder is. An earlier draft said "most often a Mosaera left running
    by a previous install", which was true of a bug and must never be true again: an uninstall
    leaves nothing behind, so a first-time operator reading that would be told their clean machine
    was probably dirty with our software. State the fact — the port is taken — and let the fact be
    the whole of it.
    """
    return Screen(
        title="A different port",
        body=(
            problem
            or (
                f"Port {taken} is already in use by another program on this machine. Choosing a "
                "different port moves this instance only; nothing else on this machine changes."
            )
        ),
        hint="Enter to use it  ·  Esc to go back",
        note=f"{suggested} is free" if suggested else "",
    )


def database_reset(port: int, evidence: str = "", raw: str = "") -> Screen:
    """The database refused our credentials. WHAT WE KNOW, and what can be done about it.

    This screen twice asserted a cause it had not established — first the password, then the data
    volume — because a credential refusal looks identical whatever is behind it, and asserting the
    wrong one sent an operator deleting things that were never the problem. It reports the
    observation now, offers both repairs, and SHOWS Postgres's own startup log, which is the thing
    that actually distinguishes the cases.
    """
    body = (
        f"The database on port {port} refused the credentials this install uses. Two things cause "
        f"that, and Postgres's own log below says which:\n\n"
        f"If it says the data directory already contained a database, the volume predates this "
        f"install — Postgres sets its password only when it first creates that directory, so it "
        f"cannot be re-keyed and has to be recreated. Resetting is safe: that data is from a setup "
        f"that never finished.\n\n"
        f"If it shows a fresh start instead, the server answering is not this container, and "
        f"pointing Mosaera at it with its own URL is the way through."
    )
    return Screen(
        title="Database — it refused these credentials",
        body=body,
        table=evidence or "",
        detail=raw or "",
        choices=[RESET_BUNDLED, POINT_ELSEWHERE],
    )


def database_unreachable(port: int, evidence: str = "", raw: str = "") -> Screen:
    """Postgres is up and healthy, and nothing here can connect to it.

    `compose up --wait` only returns once the healthcheck passes, so this is not a guess: the
    container is running, and the client still cannot open a socket. That means the port is
    published at an address this machine does not share — which is what happens on Colima and Lima,
    where a container published to `127.0.0.1` binds the VM's loopback, not the Mac's.

    `compose.yaml` has carried the fix all along (`MOSAERA_DB_BIND_HOST=0.0.0.0`) and named only
    WSL2 as the case for it. This is the same case on a different platform.
    """
    return Screen(
        title="Database — running, but not reachable from here",
        body=(
            f"Postgres started and reported healthy, and this machine still cannot open a "
            f"connection to it on port {port}.\n\n"
            f"What Docker published, and what Postgres reported, are both below — between them "
            f"they say whether the port ever left the container.\n\n"
            f"The usual cause on Docker Desktop alternatives is the publish ADDRESS: a port "
            f"published to 127.0.0.1 inside the VM binds the VM's loopback rather than this Mac's. "
            f"Publishing on 0.0.0.0 instead is worth trying, and is reversible. It also makes the "
            f"database reachable from other containers in that VM, which is why loopback is the "
            f"default. Your data is untouched either way."
        ),
        table=evidence or "",
        detail=raw or "",
        choices=[PUBLISH_FOR_HOST, POINT_ELSEWHERE],
    )
