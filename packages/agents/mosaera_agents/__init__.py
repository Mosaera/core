"""Mosaera agent roles: PM, Coder, Reviewer.

Factories are dependency-injected (model + tools passed in) so this package
stays free of provider and orchestrator dependencies.
"""

# No per-package __version__ here on purpose: ADR-0055 makes `mosaera_core.__version__` THE single
# runtime source of truth ("all 7 packages move together — one product"). A second constant here
# was read by nothing and had drifted two full releases behind; removed rather than synced.
