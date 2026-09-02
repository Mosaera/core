"""Which git forge a project's source repo lives on (ADR-0112).

Two concrete providers, named — not a plugin seam. ADR-0102 said "no forge abstraction
is introduced by this ADR, and none is authorized"; ADR-0112 authorizes exactly these
two and nothing generic. A third forge is a new decision, not a new registry entry.

The answer is DERIVED from the source URL on every call, never stored. A stored copy
is a second origin for a fact the URL already carries, and would go stale the moment
a project's source changed.

Naming: ``delivery_provider``, never bare ``provider`` — that word already means an LLM
backend (``mosaera_core.models``) and a backlog store (``mosaera_connectors.backlog``).
"""

from __future__ import annotations

from typing import Literal

from mosaera_connectors._shared import host_of
from mosaera_connectors.gitlab import is_gitlab_source

DeliveryProvider = Literal["gitlab", "github", "unknown"]

# github.com only. GitHub Enterprise Server lives on the customer's own host, which is
# indistinguishable from any other self-hosted forge by URL alone, so it reads as
# ``unknown`` — an honest "I can't tell" rather than a guess that fails at the finish
# line. Supporting GHES means asking the operator, which is a decision, not a parser fix.
_GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})


def detect_delivery_provider(source_url: str, gitlab_url: str) -> DeliveryProvider:
    """Which forge ``source_url`` lives on, judged by host EQUALITY.

    The configured GitLab wins first: a self-hosted instance is the deployment's own
    host and its answer must not depend on how ``github.com`` happens to be spelled.

    Equality, never substring — ``github.com.evil.io`` and ``…/github.com/…`` in a path
    both match a substring test, which is precisely the defect ``is_gitlab_source``
    documents having been fixed. A wrong answer here is not cosmetic: it decides which
    credential a later slice would spend, and against which host.
    """
    if is_gitlab_source(source_url, gitlab_url):
        return "gitlab"
    return "github" if host_of(source_url) in _GITHUB_HOSTS else "unknown"
