"""Generators for creating machine-learning datasets from parsed OVOS skill data."""

from ovos_localize.datasets.classification import generate_intent_classification
from ovos_localize.datasets.response_pairs import generate_response_pairs
from ovos_localize.datasets.skill_metadata import generate_skill_metadata
from ovos_localize.datasets.slot_filling import generate_slot_filling
from ovos_localize.datasets.translation import generate_parallel_corpora
from ovos_localize.datasets.tts_corpus import generate_tts_corpus

__all__ = [
    "generate_intent_classification",
    "generate_parallel_corpora",
    "generate_slot_filling",
    "generate_response_pairs",
    "generate_tts_corpus",
    "generate_skill_metadata",
]
