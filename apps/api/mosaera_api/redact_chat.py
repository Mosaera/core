"""Keep credential-shaped strings out of the PM transcript.

The transcript is stored verbatim in Postgres and replayed into the model's context on every
subsequent turn, so a credential pasted into the conversation does not merely leak once — it
persists indefinitely and is re-sent to the provider on each turn. Nothing redacted it, which was
tolerable while the chat had no reason to discuss credentials. ADR-0105 puts a GitLab setup control
in the conversation, so the topic now comes up there by design.

**This is deliberately narrow, and it is a mitigation rather than a control.** It matches only
credential shapes that are unambiguous by prefix — GitLab's own token formats and the URL-embedded
form the connectors already scrub. It makes no attempt to detect an arbitrary secret, because a
heuristic broad enough to catch one is broad enough to silently corrupt legitimate messages, and a
mangled transcript is its own kind of damage.

What actually keeps a credential out of the chat is that there is never a reason to type one there:
the setup control posts straight to the admin-gated credential endpoint, and the chat prompt tells
Quincy never to ask. This catches the paste that happens anyway.
"""

from __future__ import annotations

import re

from mosaera_connectors.redact import scrub_credentials

# Prefix-anchored GitLab credential formats. Each prefix is documented by GitLab and is not a shape
# that occurs in ordinary prose, so precision here is high and false positives are implausible.
#   glpat-  personal access token      gloas-  OAuth application secret
#   glrt-   runner token               glcbt-  CI job token
#   gldt-   deploy token               glsoat- scim oauth token
#   glptt-  pipeline trigger token     glagent- agent token
_GITLAB_TOKEN = re.compile(
    r"\b(gl(?:pat|oas|rt|cbt|dt|soat|ptt|agent)-)[A-Za-z0-9_.\-]{8,}", re.IGNORECASE
)

_REDACTED = "«redacted»"


def redact_secrets(text: str) -> str:
    """Replace credential-shaped substrings before a message is persisted.

    Returns the text unchanged when nothing matches, so an ordinary message is never touched.
    """
    if not text:
        return text
    return _GITLAB_TOKEN.sub(rf"\1{_REDACTED}", scrub_credentials(text))
