"""Mosaera Capability Benchmark (MCB) — NS-3.

Objective, repeatable, model-INDEPENDENT measurement of Mosaera's engineering
capability: run the governed loop over a fixed brief, grade the delivered code
against a hidden acceptance suite, and emit a deterministic scorecard. No LLM
judge anywhere — a judge's verdict would depend on the judge model and break
"model-independent". See ``docs`` / GitLab #3, #20.
"""

from __future__ import annotations

from mosaera_core.bench.scorecard import Dimension, Scorecard, ScoreInputs, score

__all__ = ["Dimension", "ScoreInputs", "Scorecard", "score"]
