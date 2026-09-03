"""Can this instance actually run anything — and if not, what exactly is missing? (#119)

**Why this exists.** A fresh Mosaera showed one password form and then dropped you into an
application that could not run a single task and did not say so. Whether Docker is up, whether the
sandbox images were ever built, whether Ollama has the models the bindings name, whether a cloud key
is *funded* — none of it was asked, checked, or reported. That is this codebase's most-measured
defect shape wearing a new hat: a path that fails silently is indistinguishable from a path that ran
and produced that answer.

**Three consumers, one origin.** The first-run wizard (`GET /api/preflight`), the `mosaera doctor`
CLI (the surface a clean-VM smoke test drives with no browser), and the launch refusal all read
THIS module. A second copy of "what does this deployment need" is exactly the drift already sitting
in `scripts/dev-up.sh`, which hardcodes three model tags and therefore lies the moment an operator
rebinds a role. Here the required set is DERIVED from the active bindings.

**Report-only, on purpose.** Nothing in this module builds an image, pulls a model or writes config.
A diagnostic that acts is a diagnostic you stop trusting — and the operator, not us, decides when a
multi-gigabyte pull happens. Every failure instead carries a `fix`: a command you can paste.

**Honest tri-state.** `unknown` ("we could not determine") is never collapsed into `ok`, and `note`
("true, and not a failure") is never collapsed into either. That is ADR-0035 applied to a report
rather than a boot: the whole value of this screen is that a stranger can trust it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

# Re-exported: `check_docker` / `check_images` live in `preflight_host` (the split at the 500-line
# ceiling) but every caller has always reached them through this module.
from mosaera_core.preflight_host import check_docker, check_images
from mosaera_core.preflight_types import _PROBE_TIMEOUT, Check

if TYPE_CHECKING:
    from mosaera_core.config import Settings

# The roles whose model bindings decide what this deployment must be able to serve. Read from the
# settings' own resolution (`role_model`), never a literal model list — the `dev-up.sh` defect.
_ROLES: tuple[str, ...] = ("pm", "coder", "reviewer", "tester", "critic")


@dataclass(frozen=True)
class Inventory:
    """What this box actually HAS — the wizard leads with this instead of a blank form.

    Discovery and verdicts live in one module deliberately: the CLI and the wizard must not be able
    to disagree about what is installed here.
    """

    #: Whether the Ollama server answered at all. `None` = not probed.
    ollama_reachable: bool | None = None
    #: The tags Ollama reports as pulled, in its own order. Empty when unreachable.
    ollama_tags: tuple[str, ...] = ()
    ollama_error: str = ""
    #: Hosted providers whose native API-key env var is set — "we found a key you already have".
    env_keys: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "ollama_reachable": self.ollama_reachable,
            "ollama_tags": list(self.ollama_tags),
            "ollama_error": self.ollama_error,
            "env_keys": list(self.env_keys),
        }


@dataclass(frozen=True)
class Preflight:
    checks: list[Check] = field(default_factory=list)
    inventory: Inventory = field(default_factory=Inventory)

    #: The configuration gap the launch guard refuses on, or ``""``. Set by `run_preflight` —
    #: `Preflight` itself is assembled from checks and has no `Settings` to ask.
    launch_gap: str = ""

    def as_dict(self) -> dict[str, Any]:
        ready, reason = self.can_run()
        return {
            "checks": [c.as_dict() for c in self.checks],
            "inventory": self.inventory.as_dict(),
            "can_run": ready,
            "reason": reason,
            "blocks_launch": bool(self.launch_gap),
        }

    def can_run(self) -> tuple[bool, str]:
        """Is there a reachable, credentialed model backend for every role?

        THE predicate the whole feature turns on, and deliberately the only derived one: the wizard
        decides whether to appear, the banner whether to show, and the launch endpoint whether to
        refuse — all from this. Three readers, one origin, so they cannot tell the operator three
        different stories about the same instance.

        Deliberately NOT included: Docker, the images, the database. Those block a run *later* and
        are reported honestly on their own rows — but gating the whole application on them would
        lock a newcomer out of the product while they fix a daemon, and the run itself already
        fails loudly on a missing sandbox (`SandboxUnavailable`).
        """
        blocking = [c for c in self.checks if c.key.startswith("backend") and c.status != "ok"]
        if not blocking:
            return True, ""
        first = blocking[0]
        return False, first.detail


def check_database(settings: Settings) -> Check:
    """Postgres for durable history — or an honest notice that this instance forgets.

    A missing DB is a `note`, not a `fail`: running without one is a legitimate, supported state
    (the store degrades to in-memory). Saying "ok" would hide it; saying "fail" would tell a
    newcomer their instance is broken when it is not. Both would be lies of a different kind.
    """
    from mosaera_memory import MemoryStore

    if not settings.db_url:
        return Check(
            "database",
            "Database",
            "note",
            "no MOSAERA_DB_URL — running in memory; runs and history will NOT survive a restart",
            fix="make up  # starts Postgres and sets MOSAERA_DB_URL",
        )
    store, reason = MemoryStore.open_or_reason(settings.db_url)
    if store is not None:
        return Check("database", "Database", "ok", "reachable; history is durable")
    return Check(
        "database",
        "Database",
        "fail",
        f"MOSAERA_DB_URL is set but unreachable: {reason[:200]}",
        fix="make up  # starts Postgres via infra/docker/compose.yaml",
    )


def ollama_probe(
    settings: Settings, base_url: str | None = None
) -> tuple[bool, tuple[str, ...], str]:
    """``(reachable, tags, error)`` from Ollama's ``/api/tags``.

    Deliberately NOT ``models.list_models``: that one swallows every transport error into an empty
    list AND unions the configured names back in, which is right for a picker (a model in use must
    not vanish on a blip) and exactly wrong here. Preflight has to tell "Ollama is down" from
    "Ollama is up with nothing pulled" — collapsing those is the failure this module exists to end.

    ``base_url`` overrides ``settings.ollama_base_url`` (mirrors ``_build_model_kwargs``'
    precedence) — a role/provider may point at a different Ollama server, and the caller wants to
    probe the server a binding will ACTUALLY use, not always the global default.
    """
    import httpx

    effective = (base_url or settings.ollama_base_url).rstrip("/")
    url = f"{effective}/api/tags"
    try:
        resp = httpx.get(url, timeout=_PROBE_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except httpx.HTTPError as exc:
        return False, (), f"{type(exc).__name__}: {exc}"[:200]
    except ValueError as exc:  # a 200 that is not JSON — something else is on that port
        return False, (), f"the server at {url} did not return JSON ({exc})"[:200]
    raw = payload.get("models") if isinstance(payload, dict) else None
    tags = tuple(str(m["name"]) for m in (raw or []) if isinstance(m, dict) and m.get("name"))
    return True, tags, ""


def required_ollama_models(settings: Settings) -> list[str]:
    """Every model an Ollama-bound role needs, plus the embedding model, DERIVED from the active
    bindings.

    This is the whole point. `scripts/dev-up.sh` checks a hardcoded
    ``gpt-oss:20b qwen3-coder:30b nomic-embed-text``, so an operator who rebinds the coder gets a
    green check for a model nothing uses and no warning about the one that is actually missing.
    """
    wanted: list[str] = []
    for role in _ROLES:
        binding = settings.role_model(role)  # type: ignore[arg-type]
        if binding.provider == "ollama" and binding.model:
            wanted.append(binding.model)
    # Embeddings are Ollama-only by construction (`models.get_embeddings`) and durable memory needs
    # them, so the embed model belongs in the required set whatever the chat roles are bound to.
    if settings.embed_model:
        wanted.append(settings.embed_model)
    seen: set[str] = set()
    unique: list[str] = []
    for model in wanted:
        if model and model not in seen:
            seen.add(model)
            unique.append(model)
    return unique


def _tag_present(tags: tuple[str, ...], wanted: str) -> bool:
    """Ollama reports ``name:tag``; a binding may omit the tag, which Ollama resolves to
    ``:latest``. Match both spellings so a legitimately-pulled model is never reported missing."""
    if wanted in tags:
        return True
    if ":" not in wanted:
        return f"{wanted}:latest" in tags
    return False


def check_ollama(settings: Settings, inventory: Inventory) -> Check | None:
    """Ollama reachability + the models the ACTIVE bindings need. ``None`` when no role is bound to
    Ollama and no embedding is required — there is nothing to check and a green row for an unused
    dependency is noise."""
    wanted = required_ollama_models(settings)
    if not wanted:
        return None
    if inventory.ollama_reachable is not True:
        return Check(
            "backend.ollama",
            "Ollama",
            "fail",
            f"not reachable at {settings.ollama_base_url} ({inventory.ollama_error})",
            fix="ollama serve  # or point MOSAERA_OLLAMA_BASE_URL at where it runs",
        )
    missing = [m for m in wanted if not _tag_present(inventory.ollama_tags, m)]
    if missing:
        return Check(
            "backend.ollama",
            "Ollama models",
            "fail",
            f"reachable, but not pulled: {', '.join(missing)}",
            fix=" && ".join(f"ollama pull {m}" for m in missing),
        )
    return Check(
        "backend.ollama",
        "Ollama models",
        "ok",
        f"{len(wanted)} required model(s) present at {settings.ollama_base_url}",
    )


def check_hosted_providers(settings: Settings, *, verify: bool = True) -> list[Check]:
    """One check per hosted provider an active binding uses: is a key present, and does it WORK?

    Presence is not funding. `cloud_tier_allowed` requires a model be *priced* — correctly, since
    that is what lets the USD cap bound the spend — but an exhausted key, a revoked key and a
    typo'd model name all clear it identically. That gap is what let 45 of 61 recorded escalations
    no-op against an unfunded Anthropic key with `error` left `None` (2026-08-10). Here the key is
    put to the provider's own list-models endpoint, so "present" and "accepted" are different rows.

    ``verify=False`` skips the network call (presence only) for callers that must not egress.
    """
    from mosaera_core.models import ProviderAuthError, fetch_provider_models, provider_is_local

    in_use: dict[str, list[str]] = {}
    for role in _ROLES:
        binding = settings.role_model(role)  # type: ignore[arg-type]
        if binding.provider and not provider_is_local(binding.provider):
            in_use.setdefault(binding.provider, []).append(role)

    checks: list[Check] = []
    for pid, roles in sorted(in_use.items()):
        who = ", ".join(roles)
        # "coder are bound to anthropic" — seen on the setup screen. The row is a sentence an
        # operator reads, so it agrees with however many roles it names.
        verb = "is" if len(roles) == 1 else "are"
        key = _provider_key(settings, pid)
        if not key:
            checks.append(
                Check(
                    f"backend.{pid}",
                    f"{pid} API key",
                    "fail",
                    f"{who} {verb} bound to {pid}, and no API key is configured",
                    fix=f"set it in Settings → Models, or export {_env_key_name(pid)}=…",
                )
            )
            continue
        if not verify:
            checks.append(
                Check(f"backend.{pid}", f"{pid} API key", "ok", f"a key is configured for {who}")
            )
            continue
        try:
            granted = fetch_provider_models(pid, key, settings.provider_config(pid).base_url)
        except ProviderAuthError as exc:
            checks.append(
                Check(
                    f"backend.{pid}",
                    f"{pid} API key",
                    "fail",
                    f"{pid} REJECTED the configured key: {exc}",
                    fix="replace the key in Settings → Models (check it is funded and not revoked)",
                )
            )
            continue
        except Exception as exc:  # transport, DNS, proxy — we could not tell, and must say so
            checks.append(
                Check(
                    f"backend.{pid}",
                    f"{pid} API key",
                    "unknown",
                    f"could not reach {pid} to check the key: {type(exc).__name__}: {exc}"[:200],
                    fix="check network access to the provider, then re-run",
                )
            )
            continue
        # A validated key is NOT a validated model: the documented way this fails is a green key
        # plus a model id that does not exist, which surfaces only on the first real call.
        bound = {settings.role_model(r).model for r in roles}  # type: ignore[arg-type]
        unknown = sorted(m for m in bound if m and granted and m not in granted)
        if unknown:
            checks.append(
                Check(
                    f"backend.{pid}",
                    f"{pid} models",
                    "fail",
                    f"the key works, but {pid} does not offer: {', '.join(unknown)}",
                    fix="pick a model from the list in Settings → Models",
                )
            )
            continue
        checks.append(
            Check(f"backend.{pid}", f"{pid} models", "ok", f"key accepted; {who} can be served")
        )
    return checks


def _env_key_name(provider: str) -> str:
    from mosaera_core.models import provider_catalog

    entry = next((p for p in provider_catalog() if p["id"] == provider), None)
    return str((entry or {}).get("env_key") or f"{provider.upper()}_API_KEY")


def _provider_key(settings: Settings, provider: str) -> str:
    """The key in force for ``provider``: the stored (decrypted) one, else its native env var."""
    from mosaera_memory import try_decrypt

    cfg = settings.provider_config(provider)
    _ok, stored = try_decrypt(cfg.api_key) if cfg.api_key else (True, "")
    return (stored or os.environ.get(_env_key_name(provider), "")).strip()


def discover(settings: Settings) -> Inventory:
    """What this box HAS — probed before the wizard asks the operator anything.

    Leading with "we found Ollama running with 4 models" instead of an empty form is the single
    biggest difference between a setup screen a stranger completes and one they abandon.
    """
    from mosaera_core.models import provider_catalog

    reachable, tags, err = ollama_probe(settings)
    env_keys = tuple(
        str(p["id"])
        for p in provider_catalog()
        if not p["local"] and p.get("env_key") and os.environ.get(str(p["env_key"]), "").strip()
    )
    return Inventory(
        ollama_reachable=reachable, ollama_tags=tags, ollama_error=err, env_keys=env_keys
    )


def run_preflight(settings: Settings, *, verify_keys: bool = True) -> Preflight:
    """Every check plus the inventory. Deterministic given the same environment."""
    inventory = discover(settings)
    checks: list[Check] = [
        check_docker(settings),
        check_images(settings),
        check_database(settings),
    ]
    ollama = check_ollama(settings, inventory)
    if ollama is not None:
        checks.append(ollama)
    checks.extend(check_hosted_providers(settings, verify=verify_keys))
    # Carried so the banner can say what ACTUALLY happens on submit. `can_run` (reachability) and
    # the launch guard (`config_gap`) answer different questions on purpose, and a banner that
    # promises a refusal the guard does not perform is the same silent-degradation shape this
    # issue exists to close — measured live on a fresh instance on 2026-08-24.
    return Preflight(checks=checks, inventory=inventory, launch_gap=config_gap(settings))


def config_gap(settings: Settings) -> str:
    """The blocking CONFIGURATION gap, or ``""`` — offline, instant, and network-free.

    The launch path's question is deliberately narrower than the wizard's. `can_run` asks "is a
    backend REACHABLE", which needs a probe: fine on a setup screen the operator is looking at,
    wrong on every run submit. It would put a network round-trip on the hot path, let a blip refuse
    a legitimate run, and — measured while building this — make the whole API suite depend on
    whether the machine happens to have Ollama running, since the test harness strips `MOSAERA_*`
    and every `Settings.from_env()` falls back to `localhost:11434`.

    So the guard asks the question that is answerable from config alone: **is a role bound to a
    hosted provider with no key?** That is the unconfigured instance, and it is a fact, not a probe.

    An UNREACHABLE local backend is deliberately NOT blocked here. It already fails loudly at the
    first model call (`robust_invoke` re-raises; the run records the connection error), and the
    banner built on the full check is already telling the operator. Refusing here would trade a
    loud, accurate run failure for a guess made a second earlier.
    """
    from mosaera_core.models import provider_is_local

    for role in _ROLES:
        binding = settings.role_model(role)  # type: ignore[arg-type]
        if not binding.provider or provider_is_local(binding.provider):
            continue
        if not _provider_key(settings, binding.provider):
            return (
                f"the {role} role is bound to {binding.provider}, which has no API key configured"
            )
    return ""
