"""Re-export shim.

The quality engine is now a product capability living in ``mosaera_core.quality``
(reused by both the per-run quality ring and this benchmark). Kept here so the
benchmark harness/tests import path is stable; add nothing new here.
"""

from mosaera_core.quality import QualityReport, analyze, cleanliness_issues

__all__ = ["QualityReport", "analyze", "cleanliness_issues"]
