#!/usr/bin/env python3
"""Gap-fill the intents-translated dataset with the linguonnx MT helper.

Reads the parsed skills under ``data/skills/`` and finds every ``.intent``
file that has ``en-US`` entries but no entries for a target locale. Each
such ``(locale, skill, intent)`` pair is a gap. A gap already present in
the published ``ovos_localize_intents_translated.csv`` counts as done and
is kept as-is; the rest are translated line by line with
``translate_linguonnx.translate_lines`` (slots masked, groups split,
degenerate output dropped), then expanded to sentences with the same
``bracket_expansion`` the classification corpus uses.

Resumable: a checkpoint JSON under ``--state-dir`` records every pair that
is complete, and the per-locale ``<lang>.jsonl`` there holds its rows. A
run killed mid-pair drops that pair and redoes it. Nothing is written to
the repo tree.

    fill_intents_translated.py --published translated.csv --state-dir S --out OUT
    fill_intents_translated.py ... --lang de-DE          # one locale
    fill_intents_translated.py ... --status              # counts only, no MT
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from ovos_localize.bracket_expansion import (  # noqa: E402
    MAX_TEMPLATE_EXPANSIONS,
    clean_text,
    expand_template_cached,
)
from translate_linguonnx import _translate_line  # noqa: E402

try:
    from linguonnx.limits import DecodeError
except ImportError:  # tests run without linguonnx; the fake raises this one
    class DecodeError(RuntimeError):
        """The model produced no visible output for one input."""

LOG = logging.getLogger("fill_intents_translated")

TARGET_LOCALES = [
    "az-AZ", "bg-BG", "ca-ES", "cs-CZ", "da-DK", "de-DE", "el-GR", "es-ES",
    "eu-ES", "fa-IR", "fi-FI", "fr-FR", "gl-ES", "hr-HR", "hu-HU", "it-IT",
    "lt-LT", "nb-NO", "nl-BE", "nl-NL", "pl-PL", "pt-BR", "pt-PT", "ro-RO",
    "ru-RU", "sk-SK", "sl-SI", "sv-FI", "sv-SE", "tr-TR", "uk-UA",
]
CSV_COLUMNS = ("lang", "domain", "intent", "sentence")


def load_sources(skills_dir: Path) -> dict[tuple[str, str], dict]:
    """Map (skill, intent file) to en-US template lines and the locales that have entries."""
    out = {}
    for path in sorted(skills_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        skill = data.get("id") or path.stem
        for fname, finfo in data.get("files", {}).items():
            if finfo.get("type") != "intent" or not fname.endswith(".intent"):
                continue
            langs = finfo.get("langs", {}) or {}
            en = langs.get("en-US") or {}
            lines = [e.get("text", "").strip() for e in en.get("entries", [])]
            lines = [l for l in lines if l and not l.startswith("#")]
            if not lines:
                continue
            have = {l for l, d in langs.items() if (d or {}).get("entries")}
            out[(skill, fname)] = {"lines": lines, "have": have}
    return out


def load_published(csv_path: Path | None) -> dict[str, dict[tuple[str, str], int]]:
    """Per locale, the row count of every (skill, intent) already published."""
    done: dict[str, dict[tuple[str, str], int]] = defaultdict(Counter)
    if not csv_path:
        return done
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            done[row["lang"]][(row["domain"], row["intent"])] += 1
    return done


def expand(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for template in lines:
        for expanded in expand_template_cached(template, MAX_TEMPLATE_EXPANSIONS):
            cleaned = clean_text(expanded)
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                out.append(cleaned)
    return out


class State:
    def __init__(self, state_dir: Path, lang: str) -> None:
        self.dir = state_dir
        self.lang = lang
        self.dir.mkdir(parents=True, exist_ok=True)
        self.ckpt = self.dir / f"{lang}.checkpoint.json"
        self.rows = self.dir / f"{lang}.jsonl"
        self.data = {"done": {}, "started": None}
        if self.ckpt.exists():
            self.data = json.loads(self.ckpt.read_text(encoding="utf-8"))
        self._purge_orphans()

    def _purge_orphans(self) -> None:
        """Drop rows of a pair that has no marker: what a kill mid-pair leaves.

        Without this the redo appends a second copy of every row of that
        pair next to the half-written first copy.
        """
        if not self.rows.exists():
            return
        self._heal_truncated_tail()
        keys = set(self.data["done"])
        kept, dropped = [], 0
        with self.rows.open(encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if self.key(r["domain"], r["intent"]) in keys:
                    kept.append(line)
                else:
                    dropped += 1
        if dropped:
            LOG.warning("%s: %d orphan rows of an unfinished pair dropped", self.lang, dropped)
            tmp = self.rows.with_suffix(".tmp")
            tmp.write_text("".join(kept), encoding="utf-8")
            os.replace(tmp, self.rows)

    def _heal_truncated_tail(self) -> None:
        """Cut a half-written last line: what a kill mid-write leaves.

        Only the tail can be cut; every earlier line was written whole. A
        bad line before the tail is real corruption and still raises.
        """
        raw = self.rows.read_bytes()
        if not raw:
            return
        body, _, tail = raw.rpartition(b"\n")
        if not tail:
            # Ends in a newline: the last line is complete, or is a blank
            # line, which json.loads rejects; check the last real line.
            body, _, tail = body.rpartition(b"\n")
            tail_len = len(tail) + 1
        else:
            tail_len = len(tail)
        try:
            json.loads(tail)
            return
        except json.JSONDecodeError:
            pass
        LOG.warning("%s: truncated last line dropped (%d bytes); its pair is redone",
                    self.lang, tail_len)
        tmp = self.rows.with_suffix(".tmp")
        tmp.write_bytes(raw[: len(raw) - tail_len])
        os.replace(tmp, self.rows)

    def key(self, skill: str, intent: str) -> str:
        return f"{skill}\t{intent}"

    def is_done(self, skill: str, intent: str) -> bool:
        return self.key(skill, intent) in self.data["done"]

    def commit(self, skill: str, intent: str, rows: list[dict], stats: dict) -> None:
        # Rows first, then the marker, so a kill between the two leaves a
        # pair unmarked and redone rather than marked and half-written.
        with self.rows.open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        self.data["done"][self.key(skill, intent)] = stats
        tmp = self.ckpt.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.ckpt)

    def committed_rows(self) -> list[dict]:
        """Rows of every marked pair, each sentence once per pair.

        A state dir written before orphan purging existed can hold a pair
        twice (a half-written copy and the redo); the model is deterministic,
        so the copies are identical and collapse here.
        """
        keys = set(self.data["done"])
        seen: set[tuple] = set()
        out = []
        if self.rows.exists():
            with self.rows.open(encoding="utf-8") as f:
                for line in f:
                    r = json.loads(line)
                    k = (r["domain"], r["intent"], r["sentence"])
                    if self.key(r["domain"], r["intent"]) in keys and k not in seen:
                        seen.add(k)
                        out.append(r)
        return out


def plan(sources, published, locales):
    """Per locale: gaps, of which done (published), and remaining."""
    table = {}
    for lang in locales:
        gaps = [k for k, v in sources.items() if lang not in v["have"]]
        pub = published.get(lang, {})
        done = [k for k in gaps if pub.get(k, 0) > 0]
        remaining = [k for k in gaps if pub.get(k, 0) == 0]
        superseded = [k for k in pub if k in sources and k not in gaps]
        stale = [k for k in pub if k not in sources]
        table[lang] = {
            "intents_en": len(sources),
            "published_intents": len(pub),
            "published_superseded_by_human": len(superseded),
            "published_stale_not_in_en_US": len(stale),
            "published_rows_superseded": sum(pub[k] for k in superseded),
            "published_rows_stale": sum(pub[k] for k in stale),
            "human_locale_intents": len(sources) - len(gaps),
            "gap_intents": len(gaps),
            "published_gap_intents": len(done),
            "published_rows": sum(pub.values()),
            "remaining_intents": len(remaining),
            "remaining_templates": sum(len(sources[k]["lines"]) for k in remaining),
            "_remaining": remaining,
            "_gaps": gaps,
        }
    return table


def run_locale(tx, lang, sources, remaining, state: State, log_every=25):
    tgt = lang.split("-")[0].lower()
    try:
        route = tx.route("en", tgt)
    except Exception as exc:
        LOG.warning("no route en -> %s: %s; skipping %s", tgt, exc, lang)
        return None
    LOG.info("%s route: %s", lang, " | ".join(f"{h.model_id}:{h.src}->{h.tgt}" for h in route.hops))

    # Templates across intents share many literal fragments ("tell me",
    # "what is"); one model call per distinct fragment per locale.
    memo: dict[tuple, str] = {}

    def translate_fn(text, s, t):
        key = (text, s, t)
        if key not in memo:
            memo[key] = tx.translate(text, src=s, tgt=t)
        return memo[key]

    todo = [k for k in remaining if not state.is_done(*k)]
    LOG.info("%s: %d remaining intents, %d already checkpointed", lang, len(todo),
             len(remaining) - len(todo))
    t0 = time.time()
    for i, (skill, intent) in enumerate(todo, 1):
        lines = sources[(skill, intent)]["lines"]
        out_lines, reasons, needs_manual = [], Counter(), []
        for line in lines:
            try:
                translated, reason = _translate_line(translate_fn, line, "en", tgt)
            except DecodeError as exc:
                # One input the model cannot decode (special tokens only)
                # stops one template, not the locale. The template is
                # recorded for a human to translate.
                LOG.warning("%s %s/%s: decode error on %r: %s; needs manual translation",
                            lang, skill, intent, line, exc)
                needs_manual.append({"template": line, "error": str(exc)})
                reasons["decode_error"] += 1
                continue
            if translated is not None:
                out_lines.append(translated)
            else:
                reasons[reason or "unknown"] += 1
        sentences = expand(out_lines)
        rows = [{"lang": lang, "domain": skill, "intent": intent, "sentence": s} for s in sentences]
        stats = {
            "templates_in": len(lines),
            "templates_out": len(out_lines),
            "dropped": dict(reasons),
            "sentences_out": len(rows),
            "sentences_en": len(expand(lines)),
            "needs_manual": needs_manual,
        }
        state.commit(skill, intent, rows, stats)
        if i % log_every == 0 or i == len(todo):
            LOG.info("%s: %d/%d intents, %.0fs", lang, i, len(todo), time.time() - t0)
    return True


def locale_summary(state: State) -> dict:
    done = state.data["done"]
    return {
        "intents_filled": len(done),
        "templates_in": sum(d["templates_in"] for d in done.values()),
        "templates_out": sum(d["templates_out"] for d in done.values()),
        "templates_dropped": sum(d["templates_in"] - d["templates_out"] for d in done.values()),
        "sentences_en": sum(d["sentences_en"] for d in done.values()),
        "sentences_out": sum(d["sentences_out"] for d in done.values()),
        "intents_empty": sum(1 for d in done.values() if d["sentences_out"] == 0),
        # Older checkpoints predate the key.
        "templates_needs_manual": sum(len(d.get("needs_manual", ())) for d in done.values()),
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--skills-dir", default=str(REPO_ROOT / "data" / "skills"))
    p.add_argument("--published", help="published ovos_localize_intents_translated.csv")
    p.add_argument("--state-dir", required=True, help="checkpoint dir under your own ~/tmp")
    p.add_argument("--out", help="staging dir for csv + manifest (written by --export)")
    p.add_argument("--lang", action="append", help="target locale(s); default all 31")
    p.add_argument("--status", action="store_true", help="print the plan and stop")
    p.add_argument("--export", action="store_true", help="write the staged csv and manifest")
    p.add_argument("--prefer", default="dedicated")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    sources = load_sources(Path(args.skills_dir))
    published = load_published(Path(args.published) if args.published else None)
    locales = args.lang or TARGET_LOCALES
    table = plan(sources, published, locales)
    state_dir = Path(args.state_dir)

    if args.status:
        print(f"en-US intents: {len(sources)}, templates: {sum(len(v['lines']) for v in sources.values())}")
        for lang in locales:
            t = table[lang]
            st = State(state_dir, lang)
            print(f"{lang}: gaps={t['gap_intents']} published={t['published_gap_intents']} "
                  f"({t['published_rows']} rows) remaining={t['remaining_intents']} "
                  f"templates={t['remaining_templates']} checkpointed={len(st.data['done'])}")
        return 0

    if not args.export:
        os.environ.setdefault("LINGUONNX_CACHE", os.path.expanduser("~/tmp/linguonnx-cache"))
        from linguonnx import load_translator
        tx = load_translator(prefer=args.prefer)
        # Smallest backlog first, so finished locales land early.
        locales = sorted(locales, key=lambda l: table[l]["remaining_templates"])
        for lang in locales:
            st = State(state_dir, lang)
            run_locale(tx, lang, sources, table[lang]["_remaining"], st)
        return 0

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"source_dev_sha": None, "locales": {}, "totals": Counter()}
    csv_path = out / "ovos_localize_intents_translated.csv"
    n_pub = n_new = 0
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLUMNS)
        # A row is kept only while its (locale, skill, intent) is still a
        # gap in the current tree. A row whose intent now has a human
        # locale, or whose intent left en-US, is dropped: the human rows
        # ship in ovos-localize-intents, and a stale intent trains nothing.
        # The same filter applies to published rows and to rows this
        # driver committed: a human translation can land mid-run.
        keep = {lang: set(table[lang]["_remaining"]) | {k for k in table[lang]["_gaps"]}
                for lang in locales}
        n_new_dropped = 0
        if args.published:
            with Path(args.published).open(newline="", encoding="utf-8") as pf:
                for row in csv.DictReader(pf):
                    if (row["domain"], row["intent"]) in keep.get(row["lang"], ()):
                        w.writerow([row[c] for c in CSV_COLUMNS])
                        n_pub += 1
        for lang in locales:
            st = State(state_dir, lang)
            rows = st.committed_rows()
            kept = [r for r in rows if (r["domain"], r["intent"]) in keep[lang]]
            for r in kept:
                w.writerow([r[c] for c in CSV_COLUMNS])
            n_new += len(kept)
            n_new_dropped += len(rows) - len(kept)
            t = {k: v for k, v in table[lang].items() if not k.startswith("_")}
            t.update(locale_summary(st))
            t["new_rows_superseded"] = len(rows) - len(kept)
            t["remaining_after_run"] = t["remaining_intents"] - t["intents_filled"]
            manifest["locales"][lang] = t
    manifest["source_dev_sha"] = os.popen(f"git -C {REPO_ROOT} rev-parse HEAD").read().strip()
    manifest["totals"] = {"published_rows_kept": n_pub, "new_rows": n_new,
                          "new_rows_superseded": n_new_dropped, "rows": n_pub + n_new}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {csv_path} ({n_pub} published + {n_new} new rows, "
          f"{n_new_dropped} new rows superseded by a human locale) and manifest.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
