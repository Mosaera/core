"""Provider-credential merge for the settings routes.

Extracted from ``settings.py`` so that hot route file stays under the god-file ceiling
(the same split ``config/_settings.py`` → ``config/_from_env.py`` makes). Pure
dict-in/dict-out apart from the at-rest key encryption; the caller owns the HTTP error
type, so this stays free of FastAPI.
"""

from __future__ import annotations

from typing import Any

from mosaera_core.models import on_box_declaration_error
from mosaera_memory import encrypt_secret

from mosaera_api.schemas import ProviderCredBody


def merge_provider_entry(
    stored: dict[str, Any], cred: ProviderCredBody
) -> tuple[dict[str, Any], str | None]:
    """One stored provider entry merged with a partial credential update.

    Returns ``(entry, error)``: a blank ``api_key`` keeps the saved one; an explicit ``""``
    clears ``base_url``. ``error`` is a human-readable message when the RESULTING on-box
    declaration is invalid — validated on the effective post-merge state, so neither
    "declare on-box on a hosted URL" nor "point an already-declared provider off-box" can
    persist a flag that silently means nothing (ADR-0024). ``None`` when the entry is fine.
    """
    entry = dict(stored)
    if cred.api_key:  # non-empty only — blank keeps the saved key
        entry["api_key"] = encrypt_secret(cred.api_key)  # encrypted at rest (ADR-0039)
    if cred.base_url is not None:  # explicit "" clears the endpoint
        cleaned = cred.base_url.strip()
        if cleaned:
            entry["base_url"] = cleaned
        else:
            entry.pop("base_url", None)
    if cred.on_box is not None:
        entry["on_box"] = bool(cred.on_box)
    return entry, on_box_declaration_error(entry.get("base_url"), bool(entry.get("on_box")))
