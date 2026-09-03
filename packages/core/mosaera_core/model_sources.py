"""Ollama model-list discovery, split out of ``models.py`` at the 500-line ceiling.

Pure/httpx-only helpers with NO ``Settings`` dependency (a plain ``base_url`` in, a plain
model-name list out) — deliberately, so this module never needs to import back from
``mosaera_core.models`` and there is nothing to get circular about.
"""

from __future__ import annotations

import httpx

_PROBE_TIMEOUT_S = 5.0


def served_ollama_tags(base_url: str) -> list[str]:
    """The Ollama tags the server at ``base_url`` ACTUALLY reports pulled right now — the
    ``served`` half of a picker entry (#119 O1-O3). Best-effort: an unreachable server just
    reports nothing pulled (never raises), matching ``list_models``'s own tolerance — this is
    a picker convenience, not the ``preflight`` module's honest-failure probe."""
    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=_PROBE_TIMEOUT_S)
        resp.raise_for_status()
        tags = resp.json().get("models", [])
        return [str(m["name"]) for m in tags if isinstance(m, dict) and m.get("name")]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return []


def ollama_model_list(served: list[str], configured: list[str]) -> list[str]:
    """``served`` plus any configured-but-untagged role models, Ollama's order preserved — a
    model in use must never vanish from the list because a tag query blipped."""
    seen: set[str] = set()
    ordered: list[str] = []
    for name in [*served, *configured]:
        if name and name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered
