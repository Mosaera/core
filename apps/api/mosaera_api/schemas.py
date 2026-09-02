"""Request/response bodies for the Mosaera API.

Plain Pydantic models with no app state — the leaf of the API module graph
(``schemas`` ← ``routes/*`` ← ``app``). ``app`` re-exports ``RunSubmit`` and
``ApproveBody`` for backwards compatibility (they are in ``app.__all__``).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class ProjectBusy(RuntimeError):
    """A run is already holding this project's clone."""


class ItemBlocked(RuntimeError):
    """A backlog item can't run — it depends on items that aren't delivered yet."""

    def __init__(self, blocking: list[int]):
        self.blocking = blocking
        super().__init__(f"blocked by unfinished dependencies: {blocking}")


class ItemLocked(RuntimeError):
    """A backlog item is soft-locked by the PM — advisory, overridable by the user."""

    def __init__(self, reason: str = ""):
        self.reason = reason
        super().__init__(reason or "item is soft-locked; unlock or override to run")


class ItemNeedsClarification(RuntimeError):
    """The item has an OPEN intake clarification (ADR-0080 §1). Overridable (the operator's
    explicit escape hatch), like the soft-lock.

    Two axes, and the second is counter-intuitive enough that the wording has to carry it:
    `checkability` means no material claim binds, so the run burns toward an uncheckable "done";
    `decidability` means a check DOES bind and the text still never fixes the answer — the run
    would pass tests written against a value the coder invented. `axis` is derived at the raise
    site and falls back to today's wording when it cannot be determined."""

    def __init__(self, claim_text: str = "", axis: str = ""):
        self.claim_text = claim_text
        self.axis = axis
        super().__init__(
            f"open clarification: {claim_text[:120]}" if claim_text else "open clarification"
        )


class CloudEgressBlocked(RuntimeError):
    """An AUTONOMOUS run binds a role to a cloud model that isn't permitted to run unattended
    — off-box egress isn't consented (``allow_cloud_egress``) or the model isn't priced (so the
    USD cap can't bound it). Carries a human-readable reason for the project note (ADR-0024)."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class RunSubmit(BaseModel):
    repo: str
    task: str
    max_iterations: int | None = None
    scan: bool = True
    sandbox: str | None = None
    test_cmd: str | None = None  # explicit override; default: planner-detected validation
    project_id: str | None = None  # set for a project backlog-item run
    item_id: int | None = None
    cost_mode: str | None = None  # routing tier (#7); None → settings default_cost_mode
    # Set for a mode="autonomous" run → the factory's verify+recover overlay (ADR-0020).
    autonomous: bool = False
    # Structured acceptance claims (ADR-0079 Wave 1): serialized Claim dicts derived from the
    # backlog item's acceptance at launch. Optional and additive — absent ⇒ pre-claims behaviour.
    claims: list[dict[str, Any]] = []


class RunItemBody(BaseModel):
    # Per-run approval posture (never chains — that's the project Autonomous flag).
    #
    # None = "use the project's `default_run_mode`" (#121). It was a hard `"guided"` default, which
    # made the stored project default unreachable through the one path the UI actually calls — the
    # column would have been decorative, an invisible control. Behaviour is unchanged for every
    # existing project: the column itself defaults to `guided`.
    mode: Literal["guided", "autonomous", "high_assurance"] | None = None
    # Per-run limits (None = use the server default / no cap). max_iterations
    # bounds the revise loop; budget_tokens/budget_usd are spend ceilings that
    # park on exceed.
    max_iterations: int | None = None
    budget_tokens: int | None = None
    budget_usd: float | None = None
    # Per-run cost-mode routing tier (#7); None → the settings default_cost_mode.
    cost_mode: str | None = None
    # Manual escape hatch: run this item now even if it's soft-locked or has unfinished
    # dependencies (the user has read the caveat and chosen to run early). The autonomous
    # sweep NEVER overrides — this is a per-run, human-initiated bypass only.
    override: bool = False


class ApproveBody(BaseModel):
    approve: bool
    feedback: str = ""
    # ESCALATION GATE ONLY (ADR-0087, #65): test paths/node-ids the operator authorizes amending.
    # This body is shared by the delivery gate, the write gate and the escalation resume, so it
    # defaults empty and every OTHER consumer ignores it — only `_resolve_escalation`'s HUMAN
    # branch forwards it, and only into a run whose amendment knob is on. The engine then narrows
    # it to what is genuinely blocking; naming anything else authorizes nothing.
    authorize_tests: list[str] = []
    # WHICH option the operator chose, from the `outcomes` the gate declared (ADR-0082 §5).
    # An unknown id is REJECTED (400), never auto-approved — the direct mitigation for the
    # footgun ADR-0080 recorded. Its real value is catching a STALE screen: if you were shown
    # "Send back to revise" and the run has since hit the cap (where that answer would instead
    # END the run and discard your notes — F61), the mismatch is refused rather than silently
    # doing the opposite of what you clicked. Omitted ⇒ byte-identical to the old contract.
    option_id: str | None = None


class GitlabConfig(BaseModel):
    url: str | None = None
    token: str | None = None  # non-empty → set; omitted/empty → leave unchanged
    # ADR-0104 OAuth "Connect" app creds (amended: UI-settable). For these three, the semantics are
    # None → unchanged, "" → clear, non-empty → set (so an operator can disconnect). The secret is
    # encrypted at rest; client_id + base_url are not secret.
    oauth_client_id: str | None = None
    oauth_client_secret: str | None = None
    base_url: str | None = None


class DeleteToolBody(BaseModel):
    enabled: bool  # admin toggle: give the coder a human-gated delete_file tool


class PriceEntry(BaseModel):
    input: float  # $ per 1M input tokens
    output: float  # $ per 1M output tokens
    # Prompt-caching rates, $ per 1M. OPTIONAL so an existing 2-rate table keeps its exact
    # meaning: absent => cache buckets price at the input rate, which is what `cost._rate` has
    # always done for a 2-element entry. Present => the run is priced with the real cache
    # discount (a hit is ~0.1x input), without which a cached run overstates its own cost.
    cache_write: float | None = None
    cache_read: float | None = None


class PricingBody(BaseModel):
    # Full replacement of the model price table (model name -> rate).
    prices: dict[str, PriceEntry]


class ProviderCredBody(BaseModel):
    api_key: str | None = None  # non-empty → set; omitted/empty → leave unchanged
    base_url: str | None = None  # OpenAI-compatible endpoint; "" clears it
    # Operator's assertion that base_url executes on this machine (no off-box egress),
    # honoured only alongside a LOOPBACK base_url (ADR-0024). None → leave unchanged.
    on_box: bool | None = None


class RoleBindingBody(BaseModel):
    provider: str
    model: str


class ProvidersBody(BaseModel):
    # Partial update (BYOM #21): provider creds to set and/or role rebindings.
    providers: dict[str, ProviderCredBody] = {}
    roles: dict[str, RoleBindingBody] = {}


class TestProviderBody(BaseModel):
    # Validate a provider key and list the models it grants. api_key is the
    # just-typed (possibly unsaved) key; blank → use the stored/env key.
    provider: str
    api_key: str | None = None
    base_url: str | None = None


class CostModesBody(BaseModel):
    # Full replacement of the cost-mode profiles (#7): mode -> role -> binding.
    # A role a mode omits falls back to the base BYOM binding at resolution.
    modes: dict[str, dict[str, RoleBindingBody]] = {}
    default_cost_mode: str | None = None


class ProjectSubmit(BaseModel):
    name: str
    # Optional (ADR-0123): a project may start with no upstream at all, and Mosaera initializes a
    # working repository for it on the server. Defaulted rather than made `str | None` so every
    # existing caller and stored payload keeps working unchanged.
    source_repo: str = ""
    goal: str = ""
    gitlab_token: str = ""  # scoped project/group token; write-only, used only for this project
    autonomous: bool = False


class ClauseBody(BaseModel):
    """Ratify one standing decision (ADR-0082 §2).

    NOTE what is absent: there is no `scope` field. Scope is inherited from the cited standard,
    never chosen by the caller — a body carrying one would be rejected by pydantic's own extra
    handling rather than silently honoured. `value_kind` is a Literal, not a free string (the
    ADR-0005 enumerable rule); the number is an integer or absent, never prose.
    """

    standard_id: str
    binds: str
    value_kind: Literal["advisory", "number", "unbounded"]
    value_num: int | None = None
    because: str = ""
    author: str = ""
    provenance: dict[str, Any] | None = None
    when_param: str | None = None
    when_op: str | None = None
    when_num: int | None = None


class RetargetBody(BaseModel):
    """Repoint an existing item MR (0028 recovery). One field on purpose — this edits a target,
    it does not open, push, or merge anything."""

    target_branch: str = ""


class MergeBody(BaseModel):
    """Merge an item's MR, or queue it behind the pipeline.

    ``sha`` is the head the operator was shown in the confirmation. It rides through to GitLab,
    which refuses when the branch has moved — so approving one diff and merging another is not
    reachable from this endpoint (ADR-0108's rule on the one irreversible action here).
    """

    when_pipeline_succeeds: bool = False
    sha: str = ""


class MrStateBody(BaseModel):
    """End or revive an existing merge request. ``action`` is validated against GitLab's two
    lifecycle verbs at the route, so no other ``state_event`` can reach the API."""

    action: str = ""


class CharterBody(BaseModel):
    # The TRUSTED, operator-authored project charter (#42/ADR-0047 §1). Posture is an
    # enumerable — validated server-side against CHARTER_POSTURES (the ADR-0005 rule);
    # goal/constraints are genuinely freeform.
    #
    # posture is OPTIONAL and defaults to None, not to a posture value (ADR-0047 amendment
    # 2026-08-18). goal/constraints are operator intent — a member's job; posture is governance
    # and stays admin-only. `None` = leave it alone. A literal default here would make every
    # member save a silent posture reset, and since nothing enforces posture today, nothing
    # downstream would catch it.
    # All three are None-sentinelled: omitted means LEAVE UNCHANGED. Red-team 2026-08-18
    # finding 2 — posture got the sentinel, goal/constraints did not, so a member's PUT with a
    # field omitted silently erased admin-authored intent. Same class the posture sentinel exists
    # to prevent, on the two fields a member can actually write.
    goal: str | None = None
    constraints: str | None = None
    posture: str | None = None


class SetupBody(BaseModel):
    """The onboarding answers (#121) — the choices that decide whether a run can succeed.

    Every field is None-sentinelled: omitted means LEAVE UNCHANGED. That is the rule the charter
    learned the hard way (red-team 2026-08-18 finding 2 — an omitted field silently erased
    admin-authored intent), and it matters more here because this body spans THREE authorities:
    `posture` is governance (admin), `tester_enabled` is deployment-global config (admin), and the
    rest is per-project operator intent (member). A partial save must never exercise an authority
    the operator did not mean to use.

    `run_mode` is the per-run approval mode (ADR-0012 / ADR-0101), validated against `RUN_MODES` in
    the store; `posture` is the ADR-0046 governance tier, validated against `CHARTER_POSTURES`.
    They are different axes and are deliberately separate fields — collapsing them would be the
    "posture" conflation the flow exists to un-teach.

    `tester_enabled` writes the GLOBAL knob (there is no per-project settings overlay, and #121's
    scope forbids inventing one), so the UI must say deployment-wide where it is offered.
    """

    run_mode: str | None = None
    posture: str | None = None
    test_cmd: str | None = None  # "" clears it
    tester_enabled: bool | None = None
    budget_usd: float | None = None
    budget_tokens: int | None = None
    # Stamp the card as answered so it collapses instead of nagging. False re-opens it.
    completed: bool | None = None


class AutonomousBody(BaseModel):
    on: bool


class BudgetBody(BaseModel):
    # Per-project monthly ceilings; null = no cap (clears an existing one).
    budget_usd: float | None = None
    budget_tokens: int | None = None


class BriefBody(BaseModel):
    brief: str


class TokenBody(BaseModel):
    # None = leave unchanged; "" = clear; a value = set. Both tokens share these semantics so
    # each can be updated independently (setting the api token must not wipe the push token).
    token: str | None = None
    # OPTIONAL `api`-scoped token (ADR-0103) — operator REST metadata only, never transport.
    api_token: str | None = None


class MrComposeBody(BaseModel):
    """Operator edits for a merge request before it is sent (ADR-0103). All optional — an
    omitted field keeps the assembled default; a `None` body means "open with the defaults".

    Most fields need the project's api-scoped token; without one the call degrades to the
    push-options path (lossy body) and they are ignored. `target_branch` is the exception since
    2026-08-18: it is applied BEFORE the empty-diff check, so it reaches the degraded path too —
    which is the point, because a recomputed target that already contains the item's commits
    made the merge request unopenable and unrescuable."""

    title: str | None = None
    body: str | None = None  # the FULL multi-line description — faithful via the REST API
    target_branch: str | None = None
    squash: bool | None = None
    remove_source_branch: bool | None = None
    labels: list[str] | None = None
    # A2: cherry-pick only these commits onto a fresh branch and open the MR from it. None/[] =
    # the whole branch. Mutates the shared clone, so the endpoint holds the project mutex.
    commit_shas: list[str] | None = None


class AttachmentRef(BaseModel):
    attachment_id: str


class AttachmentPatchBody(BaseModel):
    scope: str


class MessageBody(BaseModel):
    text: str
    attachments: list[AttachmentRef] = []
    # The chat session to post into (issue #30). Omitted → the project's current session
    # (created on first send), so older clients keep working.
    session_id: str | None = None


class SessionCreateBody(BaseModel):
    title: str = ""  # optional; the first user turn auto-names an untitled session


class SessionPatchBody(BaseModel):
    # Session lifecycle: rename (title) and/or archive/unarchive (archived). Both optional —
    # a null field is left unchanged.
    title: str | None = None
    archived: bool | None = None


class CredentialsBody(BaseModel):
    """Login. There is no first-run variant any more: the first administrator is created by
    `mosaera-setup`, in a terminal, against the database directly (ADR-0116)."""

    username: str
    password: str


class CreateUserBody(BaseModel):
    """Admin creating another account."""

    username: str
    password: str
    is_admin: bool = False


class GeneralSettingsBody(BaseModel):
    """A patch of operational knobs to persist. Values are validated/coerced against
    ``config.GENERAL_KNOBS`` server-side; a ``null`` value unsets that stored key."""

    values: dict[str, Any] = {}


class BacklogItemBody(BaseModel):
    title: str
    description: str = ""
    acceptance: str = ""


class BacklogItemPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    acceptance: str | None = None
    status: str | None = None
    design: str | None = None


class ItemDependenciesBody(BaseModel):
    depends_on: list[int] = []


class BacklogReorderBody(BaseModel):
    # The complete new order of the project's backlog item ids (positions 0..n-1).
    ordered_ids: list[int]


class ItemLockBody(BaseModel):
    locked: bool
    reason: str = ""  # the caveat shown to the user (why it's better to wait)


class CurateBody(BaseModel):
    instruction: str = ""  # optional free-text steer for the curator


class ClarificationResolveBody(BaseModel):
    """Resolve a clarification (ADR-0080, ADR-0091): accept one proposal by index, accept an
    edited text, affirm that the bar stands, or reject the ask. One path; the endpoint validates.

    `disposition="bar_stands_retry"` is the operator position the card previously had no
    representation for — *the bar is right, the CODE is wrong* — which used to collapse into
    "Dismiss", the button labelled as giving up."""

    accepted_proposal_index: int | None = None
    edited_text: str = ""
    rejected: bool = False
    disposition: Literal["bar_stands_retry"] | None = None


class ApplyChangesetBody(BaseModel):
    # The (reviewed, approved) changeset of ops to apply to the backlog.
    changeset: list[dict[str, Any]]
    # Permit an op that DELETES the row of delivered work (`done`/`in_review`, or carrying a
    # branch or merge request). Deny by default.
    #
    # A REQUEST field, never an op field, and the distinction is the whole guard: the threat is a
    # model-authored changeset an operator accepts, so a flag living inside the changeset would be
    # granted by the very text it is meant to guard. This one can only come from the caller.
    allow_delivered: bool = False
