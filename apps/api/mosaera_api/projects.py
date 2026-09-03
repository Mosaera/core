"""Project intake: clone the source and cache a repo overview for the PM.

Runs in a background thread (like RunSession) so the create request returns
immediately and the UI polls project status: draft → drafting → ready (intake
chat open). The project understanding is synthesized from that chat later, when
the stakeholder clicks "Build the backlog" (run_decompose).
"""

from __future__ import annotations

import contextlib
import threading
import uuid

from mosaera_agents import pm
from mosaera_core.clauses import load_clauses
from mosaera_core.config import Settings
from mosaera_core.doctrine import load_global_doctrine
from mosaera_core.grounding_text import ground_project_files
from mosaera_core.intake_ask import (
    divert_undecidable_to_asks,
    settled_findings,
)
from mosaera_core.mapview import render_project_map
from mosaera_core.models import get_chat_model
from mosaera_core.spec_lint import (
    checkability_findings,
    curate_instruction,
    decidability_findings,
    lint_backlog,
)
from mosaera_core.tools.repo import (
    OVERVIEW_RULES_VERSION,
    build_overview,
    clone_project,
    describe_coder_capabilities,
    init_project,
    open_project_workspace,
)
from mosaera_memory import MemoryStore, conversation_turns

# Ops that renumber positions and mint/remove item ids — can't share a changeset with
# reorder/set_dependencies (which reference a now-stale id/position snapshot).
_STRUCTURAL_OPS = frozenset({"split", "merge", "delete"})


def _overview_key(head_sha: str) -> str:
    """The cache key: the clone's HEAD *and* the version of the rules that rendered it.

    HEAD alone answers "have the files changed?" and misses "have the rules changed?" — so a fix
    to what the listing contains reaches no existing project until its clone happens to move. That
    was observed, not theorised: excluding tool caches changed nothing live because no clone had
    moved since the previous refresh.
    """
    return f"{OVERVIEW_RULES_VERSION}:{head_sha}"


def refresh_repo_overview(
    memory: MemoryStore, settings: Settings, project_id: str
) -> tuple[str, bool]:
    """The project's repo overview, rebuilt if the clone has moved. ``(overview, is_current)``.

    `repo_overview` used to be written once, here at intake, and never again — while the project
    clone advances with every approved delivery. A project cloned when its repository was empty
    therefore kept an empty view of itself permanently, and the PM planned against a tree that had
    not existed for weeks (see migration 0030 for the measured case and what it cost).

    The check is a HEAD-sha comparison, not a tree walk: this runs on the interactive chat path,
    and `Workspace.tree_hash` — designed as exactly this memo key (#23/ADR-0003) — stats every
    entry. The clone only gains content through `commit_all` at deliver and is reset at run start,
    so HEAD can over-refresh but never under-refresh.

    **Read-only, and no fetch.** `open_project_workspace` is opened with its read defaults
    (`reset=False`, no `item_branch`); `diff.py` records that the single `git fetch` in this
    codebase belongs to run launch under the project mutex, because a fetch on a read path mutates
    `.git` and races a live run.

    ``is_current`` is False when the clone could not be read at all. The stored text is still
    returned — a month-old listing beats none — but the caller must SAY it may be stale rather
    than presenting it as current, the same rule the delivery block's NOT CHECKED branch follows.
    A rebuild that raises is not a reason to lose the operator's conversation.
    """
    stored = memory.get_repo_overview(project_id)
    try:
        workspace = open_project_workspace(settings.projects_dir, project_id, project_id)
        head = _overview_key(str(workspace.repo.head.commit.hexsha))
    except Exception:
        return stored, False
    if head and head == memory.get_repo_overview_key(project_id) and stored:
        return stored, True
    try:
        fresh = build_overview(workspace)
    except Exception:
        return stored, False
    memory.set_repo_overview(project_id, fresh, head)
    return fresh, True


def new_project_id(name: str) -> str:
    slug = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")[:24] or "project"
    return f"proj-{slug}-{uuid.uuid4().hex[:6]}"


def run_intake(memory: MemoryStore, project_id: str, source: str) -> None:
    """Clone the source and cache the repo overview, then open the intake chat.

    No brief is drafted up front anymore — the stakeholder shapes the project by
    talking to Quincy, and the understanding is synthesized at "Build the backlog"
    time (run_decompose). Status advances draft → drafting → ready (intake open).
    """
    settings = Settings.from_env()
    try:
        # `error=""` on the way IN, not only on success: a project whose intake FAILED is left at
        # status "draft" with an error, which is the only thing that distinguishes it from one that
        # is merely starting. Carrying a stale error into a retry would keep it reading as failed
        # while the clone is actually running again.
        memory.update_project(project_id, status="drafting", error="")
        # Zero-trust: clone a private source with THIS project's own scoped token — but only
        # inject it when the source is on the configured GitLab (host equality, ADR-0042), so a
        # project pointed at a look-alike host can't exfiltrate the PAT at clone time.
        # Empty repos are initialized with a base branch inside clone_project.
        if source.strip():
            clone_token = memory.get_project_token(project_id)
            workspace = clone_project(
                source,
                settings.projects_dir,
                project_id,
                clone_token,
                gitlab_url=settings.gitlab_url,
            )
        else:
            # Local-first (ADR-0123): no upstream, nothing to clone. The project's working
            # repository starts here. `clone_project` refuses a blank source — `Path("")` is cwd.
            workspace = init_project(settings.projects_dir, project_id)
        memory.update_project(project_id, branch=workspace.branch, status="ready", error="")
        # Overview and its HEAD key are written together (0030). Writing the text alone is what
        # made this a snapshot that could never be detected as stale.
        memory.set_repo_overview(
            project_id,
            build_overview(workspace),
            _overview_key(str(workspace.repo.head.commit.hexsha)),
        )
    except Exception as exc:
        memory.update_project(project_id, status="draft", error=f"intake failed: {exc}")


def start_intake(memory: MemoryStore, project_id: str, source: str) -> None:
    threading.Thread(target=run_intake, args=(memory, project_id, source), daemon=True).start()


def run_decompose(memory: MemoryStore, project_id: str) -> None:
    """Synthesize the project understanding from the intake conversation, then
    decompose it into backlog items over the project clone."""
    settings = Settings.from_env()
    try:
        detail = memory.project_detail(project_id)
        if not detail:
            return
        model = get_chat_model("pm", settings)
        # Rebuild when the clone has moved, not merely when the cache is empty. Decompose is the
        # one place that used to recover a missing overview — it recomputed and then threw the
        # result away, so the next turn was stale again.
        overview, _ = refresh_repo_overview(memory, settings, project_id)
        # The conversation IS the brief now: synthesize it, persist it (so the
        # merge report + PM context stay meaningful), then decompose.
        # Tell the PM exactly what the delivery agent can build, so it captures
        # out-of-capability work as manual steps and never emits un-buildable items.
        capabilities = describe_coder_capabilities(
            settings.delete_tool_enabled, settings.coder_repl_enabled
        )
        doctrine = load_global_doctrine() if settings.doctrine_enabled else ""
        # The synthesis (ADR-0047 §3, "the one model call") consumes the TRUSTED charter and
        # the UNTRUSTED map — both pre-rendered here so the agents layer stays decoupled from
        # persistence shapes. Best-effort: absent charter/map simply omit their blocks.
        from mosaera_api.pm_context_builder import charter_prompt_block

        charter_block = ""
        map_block = ""
        with contextlib.suppress(Exception):
            charter_block = charter_prompt_block(memory.get_charter(project_id))
        with contextlib.suppress(Exception):
            map_block = render_project_map(memory.list_map_dimensions(project_id))
        understanding = pm.synthesize_understanding(
            model,
            # The brief is synthesized from what the stakeholder SAID — a `note` recording that
            # some turn failed is not part of the project's intent.
            conversation_turns(memory.list_messages(project_id)),
            overview,
            capabilities,
            doctrine,
            charter_block=charter_block,
            map_block=map_block,
        )
        memory.update_project(project_id, brief=understanding)
        items = pm.decompose_brief(
            model,
            understanding,
            overview,
            capabilities,
            doctrine,
            code_evidence=ground_project_files(settings.projects_dir, project_id, understanding),
        )
        # Continue positions after any existing items so ordering stays unique/sequential.
        existing = memory.list_backlog_items(project_id)
        start = max((i["position"] for i in existing), default=-1) + 1
        created_ids = [
            memory.add_backlog_item(
                project_id, item["title"], item["description"], item["acceptance"], start + offset
            )
            for offset, item in enumerate(items)
        ]
        # Wire the dependency DAG Quincy authored. depends_on holds 1-based positions in
        # `items` (all strictly backward), so map them onto the freshly-minted ids; the
        # store re-validates (same-project, no self/cycle) as a backstop.
        for item, item_id in zip(items, created_ids, strict=True):
            dep_ids = [created_ids[p - 1] for p in item.get("depends_on", [])]
            if dep_ids:
                with contextlib.suppress(ValueError):
                    memory.set_item_dependencies(item_id, dep_ids)
        if settings.backlog_spec_lint:
            _lint_and_recurate(memory, project_id)
    except Exception as exc:
        memory.update_project(project_id, error=f"backlog generation failed: {exc}")


def _lint_and_recurate(memory: MemoryStore, project_id: str) -> None:
    """ONE bounded spec-lint pass over the freshly-decomposed backlog (ADR-0073).

    Deterministic detect (``lint_backlog``) → Quincy disposition (``curate_backlog`` with the
    findings as the instruction) → deterministic apply (the deny-by-default changeset applier).
    Best-effort by construction: any rejection/failure leaves the unlinted backlog in place —
    a lint bug can never break backlog generation. One shot, no loop (the re-lint is a log line).
    """
    items = memory.list_backlog_items(project_id)
    # Checkability (ADR-0079 §3): UNDER_SPECIFIED items join the SAME one-pass re-curate loop —
    # Quincy is asked to make the acceptance checkable. Deliberate ADR-0080 pre-wiring; no new
    # interrupt in this wave.
    # Decidability (the orthogonal axis) joins the same pass: a claim whose checker binds but
    # whose value the text never fixes is the one that ships green over an invented answer.
    findings = lint_backlog(items) + checkability_findings(items) + decidability_findings(items)
    # Standing decisions answer their own findings (ADR-0082 tier 2). This is the whole point of
    # the clause tier: a question the operator settled once must not be re-asked on the next item.
    # Suppression is by PARAMETER, deterministically — a finding is dropped only when a ratified
    # clause binds the exact oracle parameter that finding is about.
    clauses = load_clauses(memory, project_id, enabled=Settings.from_env().clauses_enabled)
    findings, settled = settled_findings(findings, clauses)
    for finding, clause in settled:
        print(
            f"  spec-lint: item #{finding.item_id}'s {finding.rule} is settled by {clause.id} "
            f"({finding.param} = {clause.value_num}) — not re-asking ({project_id})"
        )
    if not findings:
        return
    try:
        changeset = curate_backlog(memory, project_id, instruction=curate_instruction(findings))
        # An undecidable claim is a question only the OPERATOR can answer, so Quincy's rewrite of
        # such an item is diverted into an ask rather than applied (ADR-0080 §1). He remains the
        # right author of the proposal; he is not the right decider.
        changeset, asked = divert_undecidable_to_asks(
            memory,
            items,
            changeset,
            clauses,
            enabled=Settings.from_env().intake_ask_undecidable,
        )
        for item_id in asked:
            print(f"  intake: item #{item_id} asks the operator instead of guessing ({project_id})")
        if changeset:
            apply_backlog_changeset(memory, project_id, changeset)
    except ValueError:
        # A malformed / no-mix-violating changeset is rejected wholesale (same posture as the
        # resilient-sweep recuration): keep the unlinted backlog rather than break decompose.
        print(f"  spec-lint: re-curate changeset rejected; kept as-authored ({project_id})")
        return
    except Exception as exc:  # never let the lint pass break decompose
        print(f"  spec-lint: re-curate failed ({exc}); kept as-authored ({project_id})")
        return
    remaining = lint_backlog(memory.list_backlog_items(project_id))
    print(
        f"  spec-lint: {len(findings)} finding(s), {len(remaining)} remaining after "
        f"re-curation ({project_id})"
    )


def start_decompose(memory: MemoryStore, project_id: str) -> None:
    threading.Thread(target=run_decompose, args=(memory, project_id), daemon=True).start()


# Re-exported so every existing caller keeps importing these from here — the split is a
# file boundary, not an API change.
from mosaera_api.backlog_ops import (  # noqa: E402
    apply_backlog_changeset,
    curate_backlog,
)

__all__ = ["apply_backlog_changeset", "curate_backlog"]
