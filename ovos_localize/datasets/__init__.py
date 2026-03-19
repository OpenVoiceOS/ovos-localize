"""Generators for creating machine-learning datasets from parsed OVOS skill data."""

from ovos_localize.datasets.classification import generate_intent_classification
from ovos_localize.datasets.translation import generate_parallel_corpora

__all__ = [
    "generate_intent_classification",
    "generate_parallel_corpora",
]
