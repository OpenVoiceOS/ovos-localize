"""Unit tests for scripts/translate_agentpipe.py — low-resource language guard.

Loaded by file path (scripts/ is not a package) rather than sys.path
manipulation, to avoid polluting other tests' import state.
"""

import argparse
import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).parents[2] / "scripts" / "translate_agentpipe.py"
_spec = importlib.util.spec_from_file_location("translate_agentpipe", _MODULE_PATH)
translate_agentpipe = importlib.util.module_from_spec(_spec)
sys.modules["translate_agentpipe"] = translate_agentpipe
_spec.loader.exec_module(translate_agentpipe)


class TestLowResourceLangs:
    def test_kabyle_is_low_resource(self):
        assert "kab" in translate_agentpipe.LOW_RESOURCE_LANGS

    def test_low_resource_langs_excluded_from_lang_labels(self):
        # A low-resource language must never also appear in LANG_LABELS —
        # that would silently re-enable MT for it via the default
        # (--lang omitted) code path in main_async.
        assert not (translate_agentpipe.LOW_RESOURCE_LANGS & set(translate_agentpipe.LANG_LABELS))

    def test_cli_accepts_low_resource_lang_as_a_choice(self):
        # --lang kab must reach the friendly guard in main_async, not
        # argparse's generic "invalid choice" error — so it must be a
        # valid choice value even though it's never translated.
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--lang",
            choices=list(translate_agentpipe.LANG_LABELS) + list(translate_agentpipe.LOW_RESOURCE_LANGS),
        )
        args = parser.parse_args(["--lang", "kab"])
        assert args.lang == "kab"


class TestLowResourceGuard:
    def test_main_async_exits_for_low_resource_lang(self, tmp_path, capsys):
        args = argparse.Namespace(
            lang="kab", data_dir=str(tmp_path), status=False,
            upload=False, dry_run=True, concurrency=1,
        )
        with pytest.raises(SystemExit) as exc:
            asyncio.run(translate_agentpipe.main_async(args))
        assert "kab" in str(exc.value)
        assert "human-first" in str(exc.value)

    def test_default_target_langs_never_include_low_resource(self):
        target_langs = [l for l in translate_agentpipe.LANG_LABELS if l != "en-US"]
        assert not (translate_agentpipe.LOW_RESOURCE_LANGS & set(target_langs))
