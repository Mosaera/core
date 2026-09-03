"""Deny-by-default tool allowlist, scoped per agent role.

A tool not named here is not available to any agent, and a role not named here
gets no tools at all. Widening this mapping is a security-sensitive change.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import NamedTuple, TypeVar

from langchain_core.tools import BaseTool


class OutOfCapability(NamedTuple):
    """One thing the delivery agent cannot do, why, and the words a spec uses to ask for it.

    ``phrase`` is what the PM prompt reads; ``because`` is the evidence — which tool is absent or
    which guard refuses, so this is a claim about the engine rather than an opinion; ``asks_for``
    are the surface forms an acceptance criterion uses to demand it.
    """

    id: str
    phrase: str
    because: str
    # Unambiguous demands — an acceptance criterion containing one of these is asking for the
    # capability outright.
    asks_for: tuple[str, ...]
    # Words that indicate this capability ONLY alongside a `context` word. Item 88's criterion —
    # "No file under src/budget_tracker.egg-info/ remains TRACKED in the REPOSITORY" — never says
    # "git" at all, so a keyword list missed it; and adding bare "git" as a trigger would fire on
    # "the README documents the git workflow", which is perfectly buildable. Two parts, so a term
    # too weak to trigger alone can still be recognised in the right company.
    weak_terms: tuple[str, ...] = ()
    context: tuple[str, ...] = ()


# THE capability boundary, as DATA (F76, #78). It was a prose sentence inside a prompt string, and
# the entire control against unbuildable work was "tell the PM what the coder cannot do and hope it
# filters" — an instruction, not a control point. Item 88 is what that cost: five runs, ~2.9M
# tokens, an acceptance criterion demanding a git operation no tool performs, and nothing anywhere
# noticed until a human read a transcript.
#
# Structured so ONE rule can read it. The intake reachability check matches an acceptance criterion
# against these entries, and the PM prompt renders from the same list — so a capability added here
# reaches both, and neither can drift from the other. That is deliberate: ADR-0085's lesson is that
# a detector per defect is "a photograph of a defect we already saw", so the next unreachable class
# is closed by NAMING A CAPABILITY here, never by adding a seventh regex somewhere else.
#
# Positive capability still lives in ROLE_TOOL_ALLOWLIST; absence is still the real limit. This list
# does not define what is refused — it names the absences a SPEC is likely to demand, so they can be
# caught while an item is still text.
OUT_OF_CAPABILITY: tuple[OutOfCapability, ...] = (
    OutOfCapability(
        "vcs",
        "running git or any version-control command",
        "no git tool exists in any role's allowlist; the engine stages and commits at delivery",
        ("run git", "git command", "git rm", "git mv", "untrack", "unstage", "rebase"),
        weak_terms=("track", "stage", "commit", "branch"),
        context=("repositor", "version control", "git", "index"),
    ),
    OutOfCapability(
        "shell",
        "running shell commands",
        "no shell tool exists; sandbox_exec runs a Python snippet read-only and network-off",
        ("shell command", "run the command", "command line", "from the terminal"),
    ),
    OutOfCapability(
        "move",
        "renaming or moving files",
        "write_file and edit_file address one path; there is no rename or move tool",
        ("rename", "move the file", "relocate"),
    ),
    OutOfCapability(
        "network",
        "making network calls",
        "the sandbox runs --network none for everything except the install phase",
        ("network call", "http request", "call the api", "fetch from"),
    ),
    OutOfCapability(
        "migration",
        "running database migrations",
        "no migration tool exists; a migration is authored as a file, never applied",
        ("run the migration", "apply the migration", "migrate the database"),
    ),
    OutOfCapability(
        "install",
        "running an ad-hoc package install",
        "installs happen only in the validation plan's install phase, from the manifest",
        # Literal command invocations only, on purpose. DECLARING a dependency is buildable — the
        # coder edits the manifest and the install phase reads it — so "add the requests package
        # and use it for the HTTP client" is reachable work, and firing on it would block
        # legitimate items. The unreachable thing is running the installer, not needing the dep.
        ("pip install", "npm install", "run the installer", "install it manually"),
    ),
)

# The framing that turns a positive tool list into a capability contract: the delivery agent can do
# ONLY what is listed, so absence is the (implicit) limit. Rendered FROM `OUT_OF_CAPABILITY` so the
# sentence the PM reads and the list the intake check matches against are the same fact.
_CAPABILITY_FRAMING = (
    "These are the ONLY actions the delivery agent can perform. Anything a task "
    "needs beyond them — "
    + "; ".join(entry.phrase for entry in OUT_OF_CAPABILITY)
    + " — is OUT OF CAPABILITY and must not be turned into work for it."
)

ROLE_TOOL_ALLOWLIST: Mapping[str, frozenset[str]] = {
    # PM plans; it may look but not touch.
    "pm": frozenset({"list_files", "read_file", "search"}),
    # The PM in CONVERSATION (ADR-0111). A separate role from "pm" above, and the separation is
    # the control: the chat may read the project's own ledgers and may NOT read the repository,
    # while the planner keeps the repo tools and gains no ledger tool it has no use for. Widening
    # this entry to a repo tool would make ADR-0105's rejected option true in one line.
    #
    # A capability CEILING, not an identity — the chat path has no actor (ADR-0105). Like
    # delete_file and sandbox_exec below, the tool is only BUILT when its flag is set
    # (Settings.pm_chat_tools), so naming it here is a no-op until then.
    "pm_chat": frozenset({"project_history"}),
    # Coder implements inside the workspace clone only. edit_file (surgical anchored
    # replace) is the preferred mutation; write_file remains for new/whole-file writes.
    # All mutations are human-gated (see approval.GATED_ACTIONS) and path-confined to
    # the clone. delete_file and sandbox_exec are allowlist CEILINGS: each tool is only
    # BUILT (and only advertised to the PM) when its flag is set — delete_file via
    # Settings.delete_tool_enabled, sandbox_exec via Settings.coder_repl_enabled — so
    # listing them here is a no-op until then. sandbox_exec (ADR-0059, #55) runs a
    # Python snippet in the sandbox with the workspace mounted READ-ONLY (network-off):
    # the coder can import + run repo code to observe behaviour but CANNOT persist, so
    # it can never bypass the write-gate / protected_paths / ADR-0036 tamper guard — a
    # sanctioned probe replacing the debug-scripts-into-tests/ leak. Red-teamed (ADR-0059).
    "coder": frozenset(
        {
            "list_files",
            "read_file",
            "search",
            "edit_file",
            "write_file",
            "run_tests",
            "delete_file",
            "sandbox_exec",
        }
    ),
    # Reviewer verifies the change against the ACTUAL repo (read-only): it reads
    # files to confirm the acceptance criteria are met, so an already-satisfied
    # task with an empty diff is approved rather than looped. No write/run.
    "reviewer": frozenset({"list_files", "read_file", "search"}),
    # Tester / Proctor (test-first, strict separation of duties — ADR-0013; validate+repair — #54,
    # ADR-0058): authors the acceptance tests from the PM's spec BEFORE the coder implements, AND —
    # while still coder-blind (before the coder is deployed) — VALIDATES + REPAIRS them against the
    # spec, so `edit_file` now lets it fix an over-strict/wrong test or strengthen a weak one. It
    # reads the repo, writes + EDITS test files, runs the suite — but has NO delete_file, and its
    # writes are confined to tests/ (build_repo_tools write_prefix), so it can never touch source.
    # The coder is refused on the tester's authored tests (protected_paths). The tester's up-front,
    # coder-blind, quality-gated edits to PRE-EXISTING tests are excused from the ADR-0036 tamper
    # guard actor-scoped (proctor_edits); the coder's excuse is NOT widened. Coder-blind timing is
    # what makes this ungameable — the tester never sees the coder's diff, so it cannot relax a test
    # to fit wrong code (the reactive on-thrash path NEVER edits; it diagnoses + parks for a human).
    "tester": frozenset(
        {"list_files", "read_file", "search", "edit_file", "write_file", "run_tests"}
    ),
    # Critic / Judge (#60, ADR-0065): a held-out, veto-only judge of the DELIVERED OUTCOME
    # against the spec. Read-only — same capability contract as the reviewer (it reads the repo
    # to confirm a specific spec requirement is unmet before it vetoes), never writes or runs.
    # Its verdict can only DOWNGRADE ship->park at the gate; it can never create a delivery.
    "critic": frozenset({"list_files", "read_file", "search"}),
}

# Security scanners the orchestrator may run over a workspace (deny-by-default).
# Scanners run inside the sandbox and feed findings to the Reviewer + report;
# widening this set is a security-sensitive change (CODEOWNERS-gated).
ALLOWED_SCANNERS: frozenset[str] = frozenset({"gitleaks", "semgrep"})

T = TypeVar("T", bound=BaseTool)


def scoped_tools(role: str, tools: Iterable[T]) -> list[T]:
    """Filter ``tools`` down to what ``role`` is allowed to use (deny-by-default)."""
    allowed = ROLE_TOOL_ALLOWLIST.get(role, frozenset())
    return [t for t in tools if t.name in allowed]


def scanner_allowed(name: str) -> bool:
    """Whether a scanner is permitted to run (deny-by-default)."""
    return name in ALLOWED_SCANNERS


def render_capabilities(capabilities: Mapping[str, str]) -> str:
    """Render a role's live tool set into a PM-facing capability block.

    ``capabilities`` maps tool name → one-line description; feed it either from a
    static description map or straight from live tool objects
    (``{t.name: t.description for t in tools}``). The output is positive-only —
    the negative (what the agent CANNOT do) is implied by absence and stated once
    in the framing line, so nothing has to be kept in sync as tools are added.
    """
    lines = [f"- `{name}`: {desc}" for name, desc in capabilities.items()]
    body = "\n".join(lines) if lines else "- (no tools available)"
    return (
        "The delivery agent (Coder) that builds the work can use these tools:\n"
        f"{body}\n\n{_CAPABILITY_FRAMING}"
    )
