#!/usr/bin/env python3
"""Slot-preserving machine translation over linguonnx.

Translates one en-US resource directory (``.intent``/``.dialog``/``.voc``/
``.entity`` files) into a target locale, line by line, and writes the result
under that locale's directory next to the source.

linguonnx alone is not safe for these files: ``{city}`` is dropped outright
translating en->pt, and ``{time}`` becomes ``{Zeit}`` translating en->de,
because the model treats the brace-delimited slot name as ordinary text.
Every ``{slot}`` is masked with a token before translation and restored
after, so a slot name never reaches the model. A line whose mask does not
come back intact -- some models still mangle a masked slot on a short,
multi-slot sentence -- is dropped rather than shipped wrong.

A ``(a|b|c)`` alternative group or a ``[optional]`` word is never sent to
the model as part of running text either, at any nesting depth: each
alternative and each optional body is translated on its own, keeping the
whitespace at its edges out of the call, and the template punctuation is
restored around the results, because a small model sent the whole group
whole has been seen collapsing distinct alternatives into copies of one of
them, fusing the group into a single run-together word, or swallowing the
space that used to separate it from the surrounding prose. A group two of
whose alternatives translate to the same word -- a lexical duplicate, not a
syntax bug -- drops the whole line rather than ship an alternation that no
longer alternates.

The route linguonnx picks (which model, or chain of models) is logged once
per locale. A locale with no route between the source and target language is
reported and skipped -- never silently dropped, and never charged files that
were never produced.

    translate_linguonnx.py <en-US dir> <out dir> <lang>
    translate_linguonnx.py <en-US dir> <out dir> <lang> --src-lang en
"""
import argparse
import logging
import re
import sys
from pathlib import Path

LOG = logging.getLogger("translate_linguonnx")

# A slot name is never translated: it is masked out before the model sees it
# and put back verbatim afterwards, by position. A bracketed digit survives
# tiny int8 Marian/OpenNMT models far more reliably than a longer alnum
# token, which BPE tokenizers on those models tend to split and mangle.
PLACEHOLDER_RE = re.compile(r"\{[^{}]+\}")
MASK_RE = re.compile(r"\[(\d+)\]")

SUFFIXES = (".intent", ".dialog", ".voc", ".entity")

# A word or comma-separated token repeated 3 or more times in a row: the
# shape a tiny int8 model collapses a short bare-word input into (e.g.
# ``Cześć, cześć, cześć...`` for pl-PL "hello", ``آه آه آه آه آه`` for
# fa-IR "hey there") -- caught independently on two skills and three
# languages (T-1664, T-1665), so it is a standing check rather than a
# per-unit rediscovery.
REPEAT_RE = re.compile(r"(\b\w+\b)([ ,]+\1){2,}", re.IGNORECASE)

# A single word that means nothing as a standalone intent-trigger phrase --
# a pronoun, article or other function word a model produces when it has no
# real translation for a short input (e.g. fa-IR "yo" -> "من", the Persian
# pronoun "I/me", T-1664). Not exhaustive; it only needs to catch the shape
# of defect actually seen, and grows as more are found.
STOP_WORDS = {
    # English
    "i", "me", "you", "he", "she", "it", "we", "they", "a", "an", "the",
    "and", "or", "but", "of", "to", "in", "on", "is", "am", "are",
    # Persian (fa-IR)
    "من", "تو", "او", "ما", "شما", "ایشان", "این", "آن",
    # Polish (pl-PL)
    "ja", "ty", "on", "ona", "ono", "my", "wy", "oni",
}


def mask_placeholders(line):
    """Replace every ``{slot}`` with an order-numbered mask token.

    Returns the masked line and the list of placeholders in the order they
    were found, so :func:`unmask_placeholders` can put them back by index.
    """
    placeholders = []

    def repl(m):
        placeholders.append(m.group(0))
        return f"[{len(placeholders) - 1}]"

    return PLACEHOLDER_RE.sub(repl, line), placeholders


def unmask_placeholders(text, placeholders):
    """Restore mask tokens to the placeholder they stood in for.

    A mask token the model dropped or mangled beyond ``QQQ<n>QQQ``
    recognition is not restorable and is left as whatever survived; that
    failure belongs to slot-survival testing, not to this function.
    """
    def repl(m):
        idx = int(m.group(1))
        return placeholders[idx] if idx < len(placeholders) else m.group(0)

    return MASK_RE.sub(repl, text)


CLOSE_OF = {"(": ")", "[": "]"}


def _matching_close(s, open_pos):
    """Index just past the bracket that closes ``s[open_pos]``.

    Only the same bracket character nests (``(`` inside ``(...)``, ``[``
    inside ``[...]``); a template never mixes the two at the same nesting
    level, so this is enough to find the real close of a nested group like
    ``(a|(b|c))`` instead of stopping at the first ``)``.
    """
    open_ch = s[open_pos]
    close_ch = CLOSE_OF[open_ch]
    depth = 1
    i = open_pos + 1
    while i < len(s) and depth:
        if s[i] == open_ch:
            depth += 1
        elif s[i] == close_ch:
            depth -= 1
        i += 1
    return i


def _split_top_level(s, sep="|"):
    """Split ``s`` on ``sep`` at bracket depth 0 only.

    A ``|`` inside a nested ``(...)`` or ``[...]`` belongs to that inner
    group, not to this one -- ``(a|(b|c))`` has exactly one top-level
    alternative split, between ``a`` and ``(b|c)``.
    """
    parts = []
    depth = 0
    start = 0
    for i, c in enumerate(s):
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == sep and depth == 0:
            parts.append(s[start:i])
            start = i + 1
    parts.append(s[start:])
    return parts


def _translate_literal(translate_fn, text, src, tgt):
    """Translate ``text``, keeping its edge whitespace out of the call.

    A real model strips the leading/trailing space of whatever it is given
    and joining the pieces back with ``"".join`` then fuses two words that
    used to have a space between them (``[most]popular`` instead of
    ``[most] popular``). The space is put back around the model's output
    instead of being sent through it.
    """
    if not text.strip():
        return text
    lead = text[:len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    return lead + translate_fn(text.strip(), src, tgt) + trail


def translate_templated(translate_fn, masked_line, src, tgt):
    """Translate a masked line, keeping every ``(a|b|c)`` and ``[optional]``
    group intact, at any nesting depth.

    Each literal run, and each ``|``-separated alternative inside a ``(|)``
    or ``[|]`` group, is translated on its own (recursing into any group
    nested inside an alternative) and the template punctuation is put back
    around the results verbatim -- never the literal ``|``/``(``/``)``/``[``/
    ``]`` characters mixed into prose sent to the model, which is what
    produced shipped defects like ``(irudiak|irudiak)`` (an alternative
    collapsed into a duplicate) and ``filme-filme-filme`` (a whole group
    fused into one word).

    Returns ``None`` when a group ends up with two identical alternatives
    after translation -- a small model can translate two distinct source
    alternatives (``movies``, ``films``) to the same target word
    (``filmes``), which silently turns a real choice into a no-op the split
    was supposed to prevent; a line like that is dropped rather than shipped
    with a collapsed alternation.
    """
    out = []
    i = 0
    n = len(masked_line)
    lit_start = 0
    while i < n:
        c = masked_line[i]
        if c in "([":
            end = _matching_close(masked_line, i)
            body = masked_line[i + 1:end - 1]
            if c == "[" and body.isdigit():
                # a mask token ([0], [1], ...), not an optional group --
                # left in the literal run so the round-trip check finds it.
                i = end
                continue
            literal = masked_line[lit_start:i]
            if literal:
                out.append(_translate_literal(translate_fn, literal, src, tgt))
            translated_alts = []
            for alt in _split_top_level(body, "|"):
                if not alt.strip():
                    translated_alts.append(alt)
                    continue
                sub = translate_templated(translate_fn, alt, src, tgt)
                if sub is None:
                    return None
                translated_alts.append(sub)
            if len(translated_alts) > 1:
                seen = [a.strip() for a in translated_alts]
                if len(set(seen)) != len(seen):
                    return None
            out.append(c + "|".join(translated_alts) + CLOSE_OF[c])
            i = end
            lit_start = end
        else:
            i += 1
    literal = masked_line[lit_start:]
    if literal:
        out.append(_translate_literal(translate_fn, literal, src, tgt))
    return "".join(out)


def degenerate_reason(original, text):
    """Return why ``text`` looks like degenerate MT output, or ``None``.

    Checks, in order: a token repeated 3 or more times in a row, an output
    longer than 3x the input in words, an output identical to the input,
    and an output that is nothing but a single stop-word. Any one of these
    is a line a tiny int8 model has been caught producing for a short
    bare-word input where a real translation should have come back
    (T-1664, T-1665) -- never worth shipping.
    """
    if REPEAT_RE.search(text):
        return "token repeated 3+ times in a row"
    orig_words = original.split()
    out_words = text.split()
    if orig_words and len(out_words) > 3 * len(orig_words):
        return "output more than 3x longer than input"
    # The identical-output and single-stop-word checks only fire on a short
    # bare-word original: that is the shape of input actually seen
    # degenerating this way (T-1664, T-1665's "yo", "hello", "hey"). A
    # longer line legitimately keeping a shared word (a name, a number, a
    # slot placeholder) is not this defect.
    if len(orig_words) == 1:
        if text.strip() == original.strip():
            return "output identical to input"
        if len(out_words) == 1 and out_words[0].strip(".,!?;:\"'()").lower() in STOP_WORDS:
            return "output is a single stop-word"
    return None


def translate_line(translate_fn, line, src, tgt):
    """Translate one line, masking and restoring its placeholders.

    A blank line is passed through unchanged rather than sent to the model,
    which would otherwise translate empty input into filler text. Returns
    ``None`` when a mask did not come back intact -- some models drop or
    mangle a masked slot on a short, multi-slot sentence, and a line like
    that is dropped rather than shipped with a wrong or missing slot -- or
    when the result looks like degenerate output (see
    :func:`degenerate_reason`).
    """
    return _translate_line(translate_fn, line, src, tgt)[0]


def _translate_line(translate_fn, line, src, tgt):
    """Like :func:`translate_line`, also returning the drop reason if any."""
    if not line.strip():
        return line, None
    masked, placeholders = mask_placeholders(line)
    translated = translate_templated(translate_fn, masked, src, tgt)
    if translated is None:
        return None, "duplicate alternative after translation"
    survived = sorted(set(int(i) for i in MASK_RE.findall(translated)))
    if survived != list(range(len(placeholders))):
        return None, "mask did not survive"
    result = unmask_placeholders(translated, placeholders)
    reason = degenerate_reason(line, result)
    if reason:
        return None, reason
    return result, None


def translate_lines(translate_fn, lines, src, tgt):
    """Translate every line, dropping any that failed or looked degenerate.

    A dropped line is reported with its reason, never written. The output
    may be shorter than the input; a caller that needs to know how many
    lines were dropped should compare lengths itself.
    """
    out = []
    for line in lines:
        translated, reason = _translate_line(translate_fn, line, src, tgt)
        if translated is not None:
            out.append(translated)
        elif reason:
            LOG.warning("dropped line %r: %s", line, reason)
    return out


def iter_source_files(src_dir):
    for path in sorted(Path(src_dir).rglob("*")):
        if path.is_file() and path.suffix in SUFFIXES:
            yield path


def target_path(src_dir, out_dir, path, tgt_lang_dir):
    """Map a file under the source locale directory to its target-locale counterpart.

    ``src_dir`` names the source language directory itself (e.g.
    ``.../locale/en-US``), so the resource tree below it mirrors as-is under
    ``out_dir/tgt_lang_dir``.
    """
    rel = path.relative_to(src_dir)
    return Path(out_dir) / tgt_lang_dir / rel


def translate_tree(tx, src_dir, out_dir, tgt_lang_dir, src_lang, tgt_lang):
    """Translate every resource file under ``src_dir`` into ``out_dir``.

    Returns the list of files written, or ``None`` when linguonnx has no
    route between ``src_lang`` and ``tgt_lang`` -- the caller is expected to
    report that and move on rather than treat it as a crash.
    """
    try:
        route = tx.route(src_lang, tgt_lang)
    except Exception as exc:  # linguonnx.translate.graph.NoRouteError
        LOG.warning("no route %s -> %s: %s; skipping %s", src_lang, tgt_lang, exc, tgt_lang_dir)
        return None

    LOG.info("route %s -> %s: %s", src_lang, tgt_lang,
              " | ".join(f"{h.model_id}:{h.src}->{h.tgt}" for h in route.hops))

    def translate_fn(text, s, t):
        return tx.translate(text, src=s, tgt=t)

    written = []
    for path in iter_source_files(src_dir):
        lines = path.read_text(encoding="utf-8").splitlines()
        out_lines = translate_lines(translate_fn, lines, src_lang, tgt_lang)
        if not out_lines:
            LOG.warning("no line of %s survived translation; skipping", path)
            continue
        if len(out_lines) < len(lines):
            LOG.warning("%s: %d of %d lines dropped (see reasons above)",
                        path, len(lines) - len(out_lines), len(lines))
        dest = target_path(src_dir, out_dir, path, tgt_lang_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        written.append(dest)
        LOG.info("wrote %s (%d lines)", dest, len(out_lines))
    return written


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("src_dir", help="source locale directory, e.g. .../locale/en-US")
    p.add_argument("out_dir", help="the tree the target locale directory is written under")
    p.add_argument("lang", help="target locale tag, e.g. pt-PT")
    p.add_argument("--src-lang", default="en",
                   help="the source language code linguonnx should route from (default: en)")
    p.add_argument("--prefer", default="dedicated",
                   help="linguonnx routing preference, e.g. dedicated or fewest_hops (default: dedicated)")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    from linguonnx import load_translator
    tgt_lang = args.lang.split("-")[0].lower()
    tx = load_translator(prefer=args.prefer)
    written = translate_tree(tx, args.src_dir, args.out_dir, args.lang, args.src_lang, tgt_lang)
    if written is None:
        print(f"NO ROUTE: {args.src_lang} -> {tgt_lang}; {args.lang} skipped")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
