"""Dataset generator for intent → dialog response pairs.

Pairs each intent utterance with the dialog response templates that its
Python handler calls via ``self.speak_dialog()``.  The mapping is extracted
from ``context.triggers_dialog`` which is populated by the AST analyzer
(``ovos_localize.analyzers.context_builder``) at data-generation time.

Each record contains the input utterance (what the user says) and one or more
response templates (what the assistant replies), all in the same language.
Records where a language has intent utterances but no matching dialog
translation are skipped.
"""

from typing import Any, Dict, Iterator, List, Set

from ovos_localize.bracket_expansion import expand_template, clean_text


def generate_response_pairs(skill_id: str, skill_data: dict) -> Iterator[Dict[str, Any]]:
    """Yield (utterance, responses) pairs extracted via AST handler analysis.

    For every intent file whose ``context.triggers_dialog`` is non-empty,
    collects the dialog templates called by the handler and emits pairs of
    expanded intent utterances with the corresponding dialog texts.

    Args:
        skill_id: Skill identifier (e.g. ``'ovos-skill-hello-world'``).
        skill_data: Parsed skill JSON dictionary.

    Yields:
        Dicts with keys:

        - ``lang`` — BCP-47 language code.
        - ``skill`` — skill identifier.
        - ``intent`` — source intent filename.
        - ``handler`` — Python handler method name (from AST).
        - ``utterance`` — a single expanded intent utterance.
        - ``responses`` — list of expanded dialog response strings.
    """
    files = skill_data.get("files", {})

    # Index dialog files: filename stem → {lang: [expanded texts]}
    dialog_index: Dict[str, Dict[str, List[str]]] = {}
    for filename, file_info in files.items():
        if file_info.get("type") != "dialog":
            continue
        stem = filename.replace(".dialog", "")
        dialog_index[stem] = {}
        for lang, lang_data in file_info.get("langs", {}).items():
            texts: List[str] = []
            seen_d: Set[str] = set()
            for entry in lang_data.get("entries", []):
                template = entry.get("text", "").strip()
                if not template or template.startswith("#"):
                    continue
                for expanded in expand_template(template):
                    text = clean_text(expanded)
                    if text and text not in seen_d:
                        seen_d.add(text)
                        texts.append(text)
            if texts:
                dialog_index[stem][lang] = texts

    for filename, file_info in files.items():
        if file_info.get("type") not in ("intent",):
            continue

        ctx = file_info.get("context") or {}
        triggered: List[str] = ctx.get("triggers_dialog") or []
        handler: str = ctx.get("handler_method") or ""

        if not triggered:
            continue

        intent_langs = file_info.get("langs", {})
        for lang, lang_data in intent_langs.items():
            # Collect all dialog response texts for this lang
            responses: List[str] = []
            for dialog_stem in triggered:
                responses.extend(dialog_index.get(dialog_stem, {}).get(lang, []))
            if not responses:
                continue

            seen_u: Set[str] = set()
            for entry in lang_data.get("entries", []):
                template = entry.get("text", "").strip()
                if not template or template.startswith("#"):
                    continue
                for expanded in expand_template(template):
                    utterance = clean_text(expanded)
                    if not utterance or utterance in seen_u:
                        continue
                    seen_u.add(utterance)

                    yield {
                        "lang": lang,
                        "skill": skill_id,
                        "intent": filename,
                        "handler": handler,
                        "utterance": utterance,
                        "responses": responses,
                    }
