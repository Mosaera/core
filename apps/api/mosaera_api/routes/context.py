"""Compatibility shim — AppContext moved to mosaera_api.app_context.

(Relocated out of routes/; owns no HTTP route.)
"""

from __future__ import annotations

from mosaera_api.app_context import AppContext, GraphFactory

__all__ = ["AppContext", "GraphFactory"]
