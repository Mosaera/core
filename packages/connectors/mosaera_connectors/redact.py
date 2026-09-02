"""Scrub credentials from text before it leaves a connector.

git echoes the full remote URL — including an injected ``oauth2:<token>@host``
(GitLab) or ``x-access-token:<token>@host`` (GitHub) — in its failure messages,
which are otherwise returned verbatim to API clients. This is the single helper
that strips those credentials at every stderr/exception exit.
"""

from __future__ import annotations

import re

# scheme://user[:secret]@host  →  scheme://***@host
_CRED_URL = re.compile(r"(https?://)[^/\s@]+@")


def scrub_credentials(text: str) -> str:
    """Replace ``user[:secret]@`` in any http(s) URL with ``***@``."""
    return _CRED_URL.sub(r"\1***@", text)
