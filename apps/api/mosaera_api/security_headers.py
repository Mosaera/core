"""Response security headers — the second layer under the PM chat's exfiltration fix.

The PM chat holds two legs of the lethal trifecta by design and says so: private data (the
charter, the backlog, the ledgers) and untrusted content (attachments and repo-derived strings
reach the model — ``quote_repo_text`` exists because of it, ADR-0105). What must never join them
is an exfiltration vector, and a model-authored reply is rendered as markdown, so any element the
renderer turns into a network fetch IS one.

``PmMarkdown`` overrides ``img`` so a model-authored image URL is shown as inert text rather than
fetched. This module is the layer under it: a Content-Security-Policy that blocks the request even
if a future renderer forgets, or someone adds a component map without reading the note. Two layers
because the first is one edit away from being undone, and its failure is silent.

Why here and not in a proxy: in production FastAPI serves the built ``dist/`` itself (see
``app.py``'s SPA catch-all, and vite.config.ts's note that the SPA and API share an origin), so
this process IS the origin. There is no nginx in this repository to put the header in.

The policy is deliberately tight because the app earns it — nothing is loaded cross-origin:
every asset is bundled, and the only non-``self`` image sources are ``blob:`` (pending-upload
previews, ``PmComposer``) and ``data:``. ``style-src`` needs ``'unsafe-inline'`` for React's
``style={{...}}`` attributes; ``frame-src`` needs ``blob:``/``self`` for the PDF previews in
``FilePreview`` and ``ProjectFilePreview``. Anything wanting a new external host should have to
come here and argue for it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request


# One directive per line, and each one justified, because a CSP nobody understands gets widened
# to 'unsafe-inline' the first time something breaks.
def _csp(form_action_extra: str = "") -> str:
    return "; ".join(
        (
            # Everything not named below: same origin only.
            "default-src 'self'",
            # The finding this file exists for. NOT 'unsafe-inline'-equivalent: no remote
            # host, ever.
            # `blob:` is pending-upload previews; `data:` is inline icons.
            "img-src 'self' data: blob:",
            # No CDN, no remote script. The bundle is served from this origin.
            "script-src 'self'",
            # React writes style attributes; there is no way to hash those.
            "style-src 'self' 'unsafe-inline'",
            # XHR/SSE/WebSocket. Same origin — the SPA proxies the API, so this is the whole API.
            "connect-src 'self'",
            "font-src 'self' data:",
            # PDF previews render same-origin/blob URLs in an iframe.
            "frame-src 'self' blob:",
            # Nothing legitimately embeds this app.
            "frame-ancestors 'none'",
            "object-src 'none'",
            "base-uri 'none'",
            # Cross-origin form POSTs are blocked by default, which is what we want everywhere
            # except one place: GitHub's App-manifest registration REQUIRES the browser to POST
            # the manifest to the GitHub host (ADR-0121). Without naming that host here the
            # button silently does nothing — the browser refuses the navigation and reports only
            # a console violation, which is the worst possible failure mode for a setup step.
            # Derived from `github_web_url`, not hardcoded, so GitHub Enterprise works too.
            f"form-action 'self'{form_action_extra}",
        )
    )


def _headers(csp: str) -> dict[str, str]:
    return {
        "Content-Security-Policy": csp,
        # A JSON body sniffed as HTML is the classic way a same-origin API becomes an XSS sink.
        "X-Content-Type-Options": "nosniff",
        # Project ids and run ids live in the path; no referrer should carry them anywhere.
        "Referrer-Policy": "no-referrer",
        # Belt to frame-ancestors' braces, for anything that predates CSP support.
        "X-Frame-Options": "DENY",
    }


def install_security_headers(app: FastAPI) -> None:
    """Attach the headers to every response, API and SPA alike.

    Registered LAST in ``app.py`` so it is the outermost layer: Starlette's ``add_middleware``
    inserts at position 0, and ``@app.middleware("http")`` appends — the same ordering subtlety
    ``ratelimit.py`` documents. Outermost is what we want here, so a response short-circuited by
    auth, the rate limiter, or an exception handler still carries the policy. A 401 that renders
    without a CSP is exactly the response an attacker would like to reach.
    """

    # Read once at install: the policy is a constant for the process, and re-reading settings
    # per response would put a file read on every request.
    from mosaera_core.config import Settings

    host = (Settings.from_env().github_web_url or "").rstrip("/")
    headers = _headers(_csp(f" {host}" if host.startswith("https://") else ""))

    @app.middleware("http")
    async def _security_headers(request: Request, call_next: Callable[..., Awaitable[Any]]) -> Any:
        response = await call_next(request)
        for name, value in headers.items():
            # setdefault, not assignment: a handler that deliberately set its own policy for one
            # response keeps it. Nothing does today, and the guard costs nothing.
            response.headers.setdefault(name, value)
        return response
