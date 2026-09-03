"""Leaf config types: roles + provider/role model bindings (no I/O, no cycles)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"

# The agent roles a model can be bound to. Kept here (not in models.py) so the
# config layer can key per-role bindings without importing the model gateway.
Role = Literal["pm", "coder", "reviewer", "tester", "critic"]
_ROLES: tuple[Role, ...] = ("pm", "coder", "reviewer", "tester", "critic")


@dataclass(frozen=True)
class ProviderConfig:
    """Credentials/endpoint for one model provider (BYOM, #21). Keyed by the
    ``init_chat_model`` provider id in ``Settings.providers``. ``api_key`` is a
    write-only secret (masked on read); ``base_url`` enables OpenAI-compatible
    endpoints/proxies. A ``None`` api_key falls back to the provider's native
    env var (e.g. ``OPENAI_API_KEY``), which ``init_chat_model`` reads.

    ``on_box`` is the operator's explicit assertion that this endpoint executes
    on THIS machine, so using it is not off-box egress (a local vLLM/llama.cpp
    server reached through the ``openai`` provider). It is only honoured together
    with a loopback ``base_url`` — see ``models.endpoint_is_on_box`` — because a
    forwarding proxy also binds to loopback. Defaults OFF: an existing config
    keeps today's cloud classification exactly (ADR-0024, amended 2026-07-28)."""

    api_key: str | None = field(default=None, repr=False)
    base_url: str | None = None
    on_box: bool = False

    def __repr__(self) -> str:
        """Never renders the key. A dataclass repr is not a debugging convenience for a
        secret-bearing object — it is a disclosure channel, and the ones that matter are
        the ones nobody chose: an exception message, a log line, a crash report. Observed
        2026-08-04, a live provider key printed in a `TypeError` traceback from an
        unrelated call. `repr=False` alone would silently drop the field, so the presence
        of a key is still stated; only its value is withheld."""
        key = "set" if self.api_key else "unset"
        return f"ProviderConfig(api_key=<{key}>, base_url={self.base_url!r}, on_box={self.on_box})"


@dataclass(frozen=True)
class RoleModel:
    """The concrete ``(provider, model)`` bound to an agent role. ``provider`` is
    an ``init_chat_model`` id (``ollama`` by default → the local-first posture)."""

    provider: str = "ollama"
    model: str = ""
