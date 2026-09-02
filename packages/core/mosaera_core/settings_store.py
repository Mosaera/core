"""UI-managed settings persisted to ``<home>/settings.json``.

Holds settings a user configures in the dashboard (currently the GitLab
connection). Secrets live here only on the server; the API never returns them
verbatim. The file is created 0600 and lives under ``.mosaera/`` (gitignored).
Real environment variables always take precedence over this file (deploy
override); see ``Settings.from_env``.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

_FILENAME = "settings.json"

# Keys this store is allowed to hold — keeps stray/unknown input out of the file.
# role_models: {role: {provider, model}}; providers: {id: {api_key, base_url}} (BYOM #21).
# cost_modes: {mode: {role: {provider, model}}}; default_cost_mode: str (#7).
_ALLOWED_KEYS = frozenset(
    {
        "gitlab_url",
        "gitlab_token",
        # Who may destroy delivery branches (ADR-0004 amendment). Must be here or an admin's save
        # is silently dropped — the persistence half of "a toggle that gates nothing".
        "member_branch_delete",
        # ADR-0104 OAuth "Connect" (amended): UI-settable like gitlab_token. The client SECRET is
        # stored encrypted (encrypt_secret); client_id + base_url are not secret.
        "gitlab_oauth_client_id",
        "gitlab_oauth_client_secret",
        "base_url",
        # ADR-0121: the GitHub App the setup wizard registers (or an operator pastes). Same rule
        # as the GitLab pair above and for the same reason — a key missing here is silently
        # dropped, so the wizard would report success and store nothing. The private key and the
        # client secret are stored encrypted; the id, slug and client_id are not secret.
        "github_app_id",
        "github_app_private_key",
        "github_app_slug",
        "github_oauth_client_id",
        "github_oauth_client_secret",
        "model_prices",
        # Anthropic prompt caching. Persisted so the A/B is a UI save, not a redeploy.
        "prompt_cache_enabled",
        "ollama_keep_alive",
        "role_models",
        "providers",
        "cost_modes",
        "default_cost_mode",
        "role_escalation",
        "reason_escalation",
        "delete_tool_enabled",
        # The first-run flow's ONE stored key: the steps the operator has ANSWERED. Completion is
        # otherwise derived from observable facts (an account exists, a backend answers, an app is
        # registered) so it cannot go stale — but an answer leaves no fact behind, and without it a
        # working instance that later loses its backend would lock everyone OUT of the application
        # instead of merely showing the banner. Must be here or the save is silently dropped.
        "setup_steps_acked",
        # What the WIZARD installed, so uninstall can offer to remove those and nothing else. A box
        # that already had Docker must never have it taken away by us — the difference between
        # "present" and "we put it there" is not observable after the fact, so it is recorded when
        # it happens or it is lost.
        "setup_installed",
        # A BREADCRUMB, never a cursor. It records the step the last run was on so the next one can
        # say "picking up where you left off" — it produces a sentence and nothing else. The
        # position itself is always re-derived by probing the machine, because a stored "you were at
        # images" is a lie the moment someone removes Docker in between. Must be here or the write
        # is silently dropped.
        "setup_progress",
        # Operational knobs the Settings page manages (mirror config.GENERAL_KNOBS
        # field names; a drift test keeps these two in sync).
        # Intent profiles (ADR-0122) — these DERIVE the mechanics below when the operator has
        # not set them directly.
        "autonomy_profile",
        "quality_profile",
        "recovery_profile",
        "verification_profile",
        "run_max_seconds",
        "run_max_usd",
        "run_max_tokens",
        "run_max_tool_calls",
        "run_quota_per_day",
        "run_hard_max_usd",
        "run_hard_max_tokens",
        "max_iterations",
        "max_iterations_ceiling",
        "stall_detection_enabled",
        "stall_limit",
        "honest_stop_projection",
        "honest_stop_no_signal",
        "plan_stall_limit",
        "gate_stall_limit",
        "reliability_sensitivity",
        "coder_test_repeat_limit",
        "coder_repl_enabled",
        "coder_scratch_enabled",
        "coder_diagnose_loop",
        "reduced_lane",
        "inert_oracle_scaffold",
        "static_testkit",
        "max_escalations",
        "reason_on_stall_enabled",
        "max_reason_attempts",
        "stream_reasoning",
        "deliver_unverified",
        "quality_revise_enabled",
        "quality_min",
        "quality_dim_floor",
        "quality_max_revises",
        "review_fix_enabled",
        "review_max_fixes",
        "hygiene_gate_enabled",
        "hygiene_max_fixes",
        "coder_step_limit",
        "reviewer_step_limit",
        "tester_step_limit",
        "tester_file_cap",
        "tester_enabled",
        "tester_repairs_tests",
        "repair_loosen_only",
        "coder_prefetch",
        "proctor_faithfulness_guard",
        "critic_enabled",
        "critic_claim_protocol",
        "behavior_preservation_guard",
        "refactor_oracle_scaffold",
        "oracle_mutation_check",
        "oracle_mutation_comprehensive",
        "oracle_structural_spec",
        "oracle_coverage",
        "onboarding_map_scoping",
        "model_escalation_enabled",
        "max_model_escalations",
        "allow_cloud_egress",
        "resilient_sweep",
        "resilient_recuration",
        "backlog_spec_lint",
        "clauses_enabled",
        "intake_ask_undecidable",
        "intake_ask_unreachable",
        "disposition_gap_close",
        "escalate_arm",
        "amendment_gate",
        "pm_step_limit",
        "pm_chat_tools",
        "doctrine_enabled",
        "auto_open_mr",
        "mr_granularity",
        "autonomous_verified",
        "scan_enabled",
        "sandbox_timeout",
        "sandbox_install",
        "sandbox_install_timeout",
        "sandbox_install_network",
        "sandbox_index_url",
        "ollama_base_url",
        "ollama_num_ctx",
        "coder_num_ctx",
        "ollama_timeout",
    }
)


def _path(home: Path) -> Path:
    return home / _FILENAME


def read_settings(home: Path) -> dict[str, Any]:
    """Return the stored settings dict, or ``{}`` if absent/unreadable."""
    try:
        return _read_or_raise(home)
    except (OSError, ValueError):
        return {}


def _read_or_raise(home: Path) -> dict[str, Any]:
    """The same read, but it says so when the file is there and cannot be understood.

    `read_settings` degrades to ``{}`` on purpose — a reader wants defaults, not an exception. A
    WRITER must not: merging into ``{}`` and rewriting turned one unreadable read into permanent
    loss of ``setup_installed``, ``providers``, ``gitlab_token`` and every role binding.
    """
    data = json.loads(_path(home).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("settings.json does not contain an object")
    return {k: v for k, v in data.items() if k in _ALLOWED_KEYS}


def write_settings(home: Path, updates: dict[str, Any]) -> dict[str, Any]:
    """Merge ``updates`` into the stored settings and persist (0600). Returns the
    merged dict. Keys with a ``None`` value are removed."""
    home.mkdir(parents=True, exist_ok=True)
    target = _path(home)
    try:
        merged = _read_or_raise(home)
    except FileNotFoundError:
        merged = {}  # a first write, which is the one case an empty base is correct
    except (OSError, ValueError) as exc:
        # The file exists and cannot be read. Rewriting it from an empty base is how a transient
        # unreadable read — a half-written file from a second wizard, a bad sector — became
        # permanent data loss.
        raise OSError(f"refusing to overwrite an unreadable {target}: {exc}") from exc
    for key, value in updates.items():
        if key not in _ALLOWED_KEYS:
            continue
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    _atomic_write(target, json.dumps(merged, indent=2) + "\n")
    return merged


def _atomic_write(target: Path, text: str) -> None:
    """Replace `target` in one step, 0600 from creation.

    `write_text` truncates and then writes, so a crash or a concurrent reader saw a half-written
    file — and `read_settings` turns a half-written file into ``{}``, which the next write then
    persists. Same discipline as the wizard's `.env` writer, for the same reason.
    """
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".settings.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)  # before any content exists
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def mask_secret(value: str | None) -> str:
    """A safe display form of a secret: never the value, just a hint."""
    if not value:
        return ""
    return f"…{value[-4:]}" if len(value) > 4 else "…"
