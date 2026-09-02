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


def images(absent: int, total: int) -> Screen:
    """`total` is counted, not assumed. It was hardcoded to 4 while the set comes from
    `_image_tags(settings)`, so the two could disagree and the screen would be the one lying."""
    return Screen(
        title="Sandbox images",
        body=(
            f"{absent} of {total} images still to build. Every command an agent runs executes\n"
            "inside these; a run cannot start without them. The build takes several minutes."
        ),
        choices=["Build now", "Skip"],
    )


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
        options.append(split("Bind to this network", f"[{DIM}]{lan}:{port}[/]", width - 2))
    return Screen(
        title="Access",
        body=(
            f"Current bind: {'this network' if public_now else 'this machine only'}.\n"
            "A network bind is issued a service token automatically; the server refuses to\n"
            "start on one without it."
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
            "No models are configured. Configure them in the application, under\n"
            "Settings, Models. Until then a run is refused."
        ),
        choices=["Finish now", "Uninstall Mosaera"],
        hint=f"Closing in {seconds}s  ·  Enter to choose  ·  Ctrl-Q to leave it running",
    )


def uninstall(entries: list[str], lead: str = "") -> Screen:
    from mosaera_api.setup.paint import UNINSTALL_HINT

    return Screen(
        hint=UNINSTALL_HINT,
        title="Uninstall",
        # ONE line. The keys are already on the hint row, so repeating "Space toggles a row.
        # Enter continues." here made a screen that is mostly list open with two lines of prose
        # nobody needs twice.
        body=(f"{lead}\n\n" if lead else "")
        + "Only what this wizard installed is listed; anything already here is left alone.",
        choices=entries,
    )


def uninstall_confirm(what: str, count: int, survives: str = "") -> Screen:
    """The last beat before anything is removed.

    CANCEL IS FIRST, so the cursor rests on it: Enter alone cancels, and removing takes a deliberate
    move down. That is the whole gate now — it replaced a typed word, which stopped nothing an arrow
    key does not, while costing every reversible removal a spelling test.
    """
    return Screen(
        title="Confirm removal",
        # `body`, never `detail`: `#detail` is nowrap + ellipsis, so a sentence put there is cut at
        # the first line and the operator reads half a warning. That mistake has already hidden a
        # `FATAL: password authentication failed` on this same wizard.
        body=survives,
        # In `table`, not `body`: centred prose reads well, a centred LIST loses its left edge and
        # every item wraps to a different indent.
        table=what,
        choices=["Cancel", f"Remove these {count} items" if count != 1 else "Remove this item"],
        hint="Enter to choose  ·  Esc to go back",
    )


def configured(
    url: str,
    accounts: int,
    env_path: str,
    *,
    serving: bool,
    gaps: tuple[str, ...] = (),
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
        f"Still outstanding: {', '.join(gaps)}.\nRuns are refused until those are done.\n\n"
        if gaps
        else ""
    )
    # The first row has to MATCH the line above it. Hardcoded to "Leave it running", it told an
    # operator to leave running an instance the same screen had just said was not running.
    first = "Leave it running" if serving else "Start Mosaera"
    return Screen(
        title="Mosaera is configured",
        body=(
            f"{where}\nAccounts: {accounts}\n\n{outstanding}"
            f"Environment settings live in\n{env_path}"
        ),
        choices=[first, "Re-run setup", "Uninstall Mosaera"],
        hint="Enter to choose  ·  Ctrl-Q to leave",
    )


def removed(results: list[str]) -> Screen:
    """Where a removal ends. NOT a step — returning to the flow after an uninstall is how the
    wizard came to start the server it had just removed."""
    return Screen(
        title="Removed",
        table="\n".join(f"  · {line}" for line in results) or "  · Nothing was selected",
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
