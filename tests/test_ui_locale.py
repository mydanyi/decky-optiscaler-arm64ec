"""Stand-alone tests for the interface-language preference in decky/main.py.

This file is self-contained: it loads the *real* ``main.py`` with a minimal
in-test ``decky`` stub module (Decky itself is not importable here) and uses a
real ``OPTISCALER_HOME`` temporary directory for every path, so the tests
exercise the real ``Plugin.set_ui_locale`` against real files. The five
``TestUiLocale`` assertions match the ones from the combined change; an extra
preservation test pins that unrelated settings files are left alone.

It depends on nothing else in ``tests/`` - no ``test_overlay_backend`` and no
``py_modules/opti_control.py``. Only the standard library is used.

Run with: python -m unittest tests.test_ui_locale
      or: python tests/test_ui_locale.py
"""

import asyncio
import importlib
import logging
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent            # decky/
PY_MODULES = PLUGIN_ROOT / "py_modules"
for entry in (str(PLUGIN_ROOT), str(PY_MODULES)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def _install_decky_stub():
    """main.py does ``import decky`` at import time; supply a minimal stand-in."""
    if "decky" in sys.modules:
        return sys.modules["decky"]
    decky = types.ModuleType("decky")
    decky.logger = logging.getLogger("optiscaler.test")
    # Only a fallback: OPTISCALER_HOME (set per test) drives every real path.
    scratch = tempfile.gettempdir()
    decky.DECKY_PLUGIN_DIR = str(PLUGIN_ROOT)
    decky.DECKY_USER_HOME = scratch
    decky.HOME = scratch
    decky.DECKY_PLUGIN_RUNTIME_DIR = scratch
    decky.DECKY_PLUGIN_SETTINGS_DIR = scratch
    sys.modules["decky"] = decky
    return decky


def _load_main():
    _install_decky_stub()
    return importlib.import_module("main")


try:
    main = _load_main()
    LOAD_ERROR = None
except Exception as exc:  # pragma: no cover - only until main.py imports
    main = None
    LOAD_ERROR = exc


class UiLocaleTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="opti-ui-locale-")
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)

        self._prev_home = os.environ.get("OPTISCALER_HOME")
        os.environ["OPTISCALER_HOME"] = str(self.home)
        self.addCleanup(self._restore_home)

        # A single loop per test: the write runs on a worker thread, and a loop
        # must not be recycled between tests.
        self.loop = asyncio.new_event_loop()
        self.addCleanup(self.loop.close)

        self.plugin = self._new_plugin()

    def _restore_home(self):
        if self._prev_home is None:
            os.environ.pop("OPTISCALER_HOME", None)
        else:
            os.environ["OPTISCALER_HOME"] = self._prev_home

    # -- environment helpers ----------------------------------------------

    def _new_plugin(self):
        self.assertIsNotNone(main, f"main.py must import cleanly ({LOAD_ERROR!r})")
        cls = getattr(main, "Plugin", None)
        self.assertIsNotNone(cls, "main.Plugin must exist")
        return cls()

    @property
    def paths(self):
        return main.paths

    def run_async(self, coro):
        return self.loop.run_until_complete(coro)

    def _api(self, name):
        self.assertIsNotNone(main, f"main.py must import cleanly ({LOAD_ERROR!r})")
        method = getattr(self.plugin, name, None)
        self.assertTrue(
            callable(method),
            f"Plugin.{name} must exist as an async method (ui locale not implemented)",
        )
        return method

    def set_ui_locale(self, language):
        return self.run_async(self._api("set_ui_locale")(language))

    def _preference(self):
        path = self.paths.data_home() / "ui-language"
        self.assertTrue(path.is_file(), f"preference file must exist at {path}")
        return path.read_text(encoding="utf-8").strip()


class TestUiLocale(UiLocaleTestCase):
    """set_ui_locale writes exactly one plain-text preference, never Chinese-by-default."""

    def test_chinese_selection_is_stored_as_zh_cn(self):
        self.set_ui_locale("zh-CN")
        self.assertEqual(self._preference(), "zh-CN")

    def test_english_selection_is_stored_as_en(self):
        self.set_ui_locale("en")
        self.assertEqual(self._preference(), "en")

    def test_non_chinese_players_are_never_forced_into_chinese(self):
        for language in ("fr", "de", "", "ja"):
            self.set_ui_locale(language)
            self.assertEqual(
                self._preference(), "en",
                f"{language!r} must normalise to English, never to Chinese",
            )

    def test_only_the_preference_file_is_written(self):
        self.set_ui_locale("zh-CN")
        files = {p.name for p in self.paths.data_home().iterdir() if p.is_file()}
        self.assertEqual(files, {"ui-language"})

    def test_overlapping_startup_and_qam_locale_writes_stay_consistent(self):
        """Startup and QAM both set the language, so the writes can overlap."""
        set_ui_locale = self._api("set_ui_locale")
        languages = ["zh-CN" if index % 2 == 0 else "en" for index in range(24)]

        async def overlapping():
            return await asyncio.gather(
                *[set_ui_locale(language) for language in languages]
            )

        results = self.run_async(overlapping())

        self.assertEqual(len(results), len(languages),
                         "every overlapping call must produce a result")
        for result in results:
            self.assertTrue(result["ok"], f"a concurrent call failed: {result!r}")
        self.assertIn(
            self._preference(), ("en", "zh-CN"),
            "the stored language must be exactly one of the two supported tags",
        )
        leftovers = sorted(
            p.name for p in self.paths.data_home().glob(".ui-language.*.tmp")
        )
        self.assertEqual(leftovers, [],
                         "an overlapping write must not leave a temp file behind")


class TestPreservation(UiLocaleTestCase):
    def test_existing_game_and_settings_files_are_left_alone(self):
        home = Path(self.paths.data_home())
        home.mkdir(parents=True, exist_ok=True)
        keeper = home / "keep.txt"
        keeper.write_text("keep", encoding="utf-8")

        settings = Path(self.paths.settings_dir())
        settings.mkdir(parents=True, exist_ok=True)
        games_json = settings / "games.json"
        games_json.write_text('{"1": {"dll": "dxgi.dll"}}', encoding="utf-8")
        defaults_json = settings / "defaults.json"
        defaults_json.write_text('{"default_dll": "dxgi.dll"}', encoding="utf-8")

        self.set_ui_locale("zh-CN")

        self.assertEqual(self._preference(), "zh-CN")
        self.assertEqual(keeper.read_text(encoding="utf-8"), "keep")
        self.assertEqual(games_json.read_text(encoding="utf-8"), '{"1": {"dll": "dxgi.dll"}}')
        self.assertEqual(defaults_json.read_text(encoding="utf-8"), '{"default_dll": "dxgi.dll"}')


if __name__ == "__main__":
    unittest.main(verbosity=2)
