"""The test side of the intents corpus: the skills' own golden utterances.

Every ``test/end2end/golden_utterances*.jsonl`` row a skill ships is a test
row, read at the same commit as the skill's locale lines. The label comes from
the one label function (:mod:`ovos_localize.corpus.labels`): the skill id the
entry point declares and the intent name without its ``.intent`` suffix. A gold
row's own ``skill_id`` field is not read for the label. The rules are those of
the ovos-m2v-pipeline gold reader (``train/build_eval.py``).
"""
import collections

from ovos_localize.corpus import labels
from ovos_localize.corpus.expansion import normalize_lang


def gold_rows(skill_id: str, golden: list, stats: collections.Counter) -> list:
    """Labelled test rows from the golden files a skill ships.

    A row marked ``needs_manual``, a row with no utterance, and a row that
    asserts a dialog rather than an intent are dropped and counted. A
    duplicate of ``(lang, label, utterance)`` is dropped. ``provenance`` is
    ``llm`` where the row says ``machine_generated: true``, else ``unknown``.
    """
    rows = []
    seen = set()
    for gold_file in golden:
        stats["gold_unparsable"] += gold_file["unparsable"]
        from_name = lang_from_gold_path(gold_file["path"])
        for d in gold_file["rows"]:
            lang = normalize_lang(d.get("lang") or from_name or "en-US")
            if d.get("needs_manual"):
                stats["gold_needs_manual"] += 1
                continue
            utterance = (d.get("utterance") or "").strip()
            intent = d.get("intent_label") or d.get("expected_intent")
            if not utterance:
                stats["gold_without_utterance"] += 1
                continue
            if not intent:
                # A fallback skill asserts the dialog it speaks, because no
                # intent claimed the utterance: there is no label to predict.
                stats["gold_asserts_a_dialog_not_an_intent"] += 1
                continue
            label = labels.label(skill_id, str(intent))
            key = (lang, label, utterance.lower())
            if key in seen:
                stats["gold_duplicate_rows_removed"] += 1
                continue
            seen.add(key)
            rows.append({
                "lang": lang,
                "label": label,
                "intent_name": labels.intent_name(str(intent)),
                "utterance": utterance,
                "source_file": gold_file["path"],
                "provenance": "llm" if d.get("machine_generated") is True else "unknown",
                "mt_engine": None,
            })
    return rows


def lang_from_gold_path(path: str):
    """The language a ``golden_utterances_<lang>.jsonl`` name carries, if any."""
    stem = path.rsplit("/", 1)[-1][: -len(".jsonl")]
    _, _, lang = stem.partition("golden_utterances_")
    return lang or None
