"""Backend-integration contract tests for the OptiScaler overlay control API.

This spec loads the real ``decky/main.py`` (with a minimal in-test ``decky``
stub module, because Decky itself is not importable here), uses real temporary
files, the real ``py_modules/opti_control.py`` mailbox ``Controller`` and a real
``FakeCore`` thread that plays the in-game bridge exactly like
``tests/test_control.py``.

The API it pins down:

    Plugin.get_overlay_state(appid)                -> state dict
    Plugin.set_overlay_state(appid, action, value) -> state dict + ``ack``

Availability must come from a *fresh, real* mailbox state, never from install or
config presence. Unknown games, escaped/symlinked control directories and stale
or missing state all report ``available == False`` and never write a request.
A missing API is reported as a plain assertion failure, never as a
collection/import error.

Run with: python -m unittest tests.test_overlay_backend
      or: python tests/test_overlay_backend.py
"""

import asyncio
import importlib
import json
import logging
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent            # decky/
PY_MODULES = PLUGIN_ROOT / "py_modules"
for entry in (str(PLUGIN_ROOT), str(PY_MODULES)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

REQUEST_NAME = "overlay.request"
STATE_NAME = "overlay.state"
SESSION = "0123456789abcdef0123456789abcdef"
APPID = "1234560"

STATE_TEMPLATE = (
    "version=1\n"
    "session={session}\n"
    "request={request}\n"
    "menu={menu}\n"
    "fps={fps}\n"
    "language={language}\n"
    "ready={ready}\n"
)


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


def _parse(text):
    """Tiny key=value parser mirroring the on-disk mailbox format."""
    if text is None:
        return None
    out = {}
    for line in text.splitlines():
        if not line:
            continue
        if "=" not in line:
            return None
        key, _, value = line.partition("=")
        if key in out:
            return None
        out[key] = value
    return out


def _write_state_file(path, state):
    path = Path(path)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(STATE_TEMPLATE.format(**state), encoding="utf-8")
    os.replace(tmp, path)


class FakeCore(threading.Thread):
    """Plays the in-game bridge: mirrors a request into an acknowledged state.

    It keeps the applied UI values across requests, the way a real core does, so
    a later command only changes its own field and the rest stays put.
    """

    def __init__(self, directory, session, *, interval=0.005):
        super().__init__(daemon=True)
        self.directory = Path(directory)
        self.session = session
        self.interval = interval
        self.stopped = threading.Event()
        self.actual = {"menu": "0", "fps": "0", "language": "en"}

    def run(self):
        request_path = self.directory / REQUEST_NAME
        while not self.stopped.is_set():
            try:
                request = _parse(request_path.read_text(encoding="utf-8"))
            except OSError:
                request = None
            if (
                request
                and request.get("version") == "1"
                and request.get("session") == self.session
                and request.get("action") in self.actual
            ):
                action = request["action"]
                self.actual[action] = request.get("value", "")
                _write_state_file(self.directory / STATE_NAME, {
                    "session": self.session,
                    "request": request.get("request", ""),
                    "menu": self.actual["menu"],
                    "fps": self.actual["fps"],
                    "language": self.actual["language"],
                    "ready": "1",
                })
            self.stopped.wait(self.interval)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    def stop(self):
        self.stopped.set()
        self.join(timeout=2.0)


class BackendTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="opti-backend-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

        self._prev_home = os.environ.get("OPTISCALER_HOME")
        os.environ["OPTISCALER_HOME"] = str(self.tmp)
        self.addCleanup(self._restore_home)

        # A single loop per test: the backend keeps a per-app lock, and a lock
        # must not be bounced between loops.
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
            f"Plugin.{name} must exist as an async method",
        )
        return method

    def get_overlay_state(self, appid=APPID):
        return self.run_async(self._api("get_overlay_state")(str(appid)))

    def set_overlay_state(self, appid=APPID, action="menu", value=True):
        return self.run_async(self._api("set_overlay_state")(str(appid), action, value))

    # -- fixture builders --------------------------------------------------

    def install_game(self, *, appid=APPID, name="Test Game", installdir="TestGame"):
        """Build a real Steam library so games.game_by_appid finds the game."""
        steamapps = self.tmp / ".steam" / "steam" / "steamapps"
        root = steamapps / "common" / installdir
        root.mkdir(parents=True, exist_ok=True)
        (steamapps / f"appmanifest_{appid}.acf").write_text(
            '"AppState"\n{\n'
            f'    "appid"      "{appid}"\n'
            f'    "name"       "{name}"\n'
            f'    "installdir" "{installdir}"\n'
            '}\n',
            encoding="utf-8",
        )
        return root

    def write_manifest(self, directories, *, appid=APPID):
        installs = Path(self.paths.installs_dir())
        installs.mkdir(parents=True, exist_ok=True)
        (installs / f"{appid}.json").write_text(json.dumps({
            "appid": str(appid),
            "dll": "dxgi.dll",
            "directories": [str(Path(d)) for d in directories],
            "installed_at": int(time.time()),
        }), encoding="utf-8")

    def control_dir(self, game_root):
        return Path(game_root) / "OptiScaler"

    def write_state(self, directory, *, session=SESSION, request="", menu="0",
                    fps="0", language="en", ready="1", age=None):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / STATE_NAME
        path.write_text(STATE_TEMPLATE.format(
            session=session, request=request, menu=menu, fps=fps,
            language=language, ready=ready), encoding="utf-8")
        if age is not None:
            stamp = time.time() - age
            os.utime(path, (stamp, stamp))
        return path

    # -- assertions --------------------------------------------------------

    def assert_overlay_result(self, result, *, with_ack=False):
        self.assertIsInstance(result, dict, "the overlay API must return a dict")
        for key in ("ok", "error", "available", "menu", "fps", "language"):
            self.assertIn(key, result, f"overlay result is missing {key!r}")
        if with_ack:
            self.assertIn("ack", result, "set_overlay_state must report ack")
            self.assertIsInstance(result["ack"], bool, "ack must be a boolean")

    def request_files(self):
        return sorted(self.tmp.rglob(REQUEST_NAME))


class TestApiSurface(BackendTestCase):
    def test_plugin_exposes_the_overlay_api(self):
        for name in ("get_overlay_state", "set_overlay_state"):
            self.assertTrue(
                callable(getattr(self.plugin, name, None)),
                f"Plugin.{name} must exist",
            )


class TestUnavailableStates(BackendTestCase):
    """No fresh core state -> available is False, and nothing is written."""

    def test_unknown_game_is_unavailable(self):
        result = self.get_overlay_state("9999999")
        self.assert_overlay_result(result)
        self.assertFalse(result["available"], "an unknown game has no overlay core")
        self.assertEqual(self.request_files(), [], "no request may be written for an unknown game")

    def test_recorded_directory_outside_the_game_root_is_rejected(self):
        game_root = self.install_game()          # the game itself exists and is found
        outside = self.tmp / "outside"
        self.write_state(self.control_dir(outside))   # a fresh, valid mailbox, but...
        self.write_manifest([outside])                # ...recorded outside the game root

        result = self.get_overlay_state()
        self.assert_overlay_result(result)
        self.assertFalse(result["available"],
                         "a recorded directory escaping the game root must never be trusted")

        set_result = self.set_overlay_state(action="menu", value=True)
        self.assert_overlay_result(set_result, with_ack=True)
        self.assertFalse(set_result["ack"])
        self.assertEqual(self.request_files(), [],
                         "no request may be written into an escaped directory")
        self.assertTrue(game_root.is_dir())

    def test_missing_state_is_unavailable_even_when_installed(self):
        game_root = self.install_game()
        self.write_manifest([game_root])
        # Install config exists, but nothing proves a running core right now.
        result = self.get_overlay_state()
        self.assert_overlay_result(result)
        self.assertFalse(result["available"],
                         "availability must not be faked from install/config alone")

        set_result = self.set_overlay_state(action="menu", value=True)
        self.assert_overlay_result(set_result, with_ack=True)
        self.assertFalse(set_result["ack"])
        self.assertEqual(self.request_files(), [],
                         "no request may be written when no core session is known")

    def test_state_older_than_five_seconds_is_unavailable(self):
        game_root = self.install_game()
        self.write_manifest([game_root])
        self.write_state(self.control_dir(game_root), menu="1", ready="1", age=3600)
        result = self.get_overlay_state()
        self.assert_overlay_result(result)
        self.assertFalse(result["available"], "a state from a previous launch is not usable")

    def test_symlinked_control_directory_is_rejected(self):
        game_root = self.install_game()
        self.write_manifest([game_root])
        outside = self.tmp / "elsewhere"
        self.write_state(self.control_dir(outside))       # fresh mailbox behind the link
        link = self.control_dir(game_root)
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable on this platform: {exc}")

        result = self.get_overlay_state()
        self.assert_overlay_result(result)
        self.assertFalse(result["available"], "a symlinked control dir must be refused")


class TestLiveCore(BackendTestCase):
    """A fresh mailbox state is read verbatim; commands need a real ack."""

    def test_fresh_state_reports_the_actual_core_values(self):
        game_root = self.install_game()
        self.write_manifest([game_root])
        self.write_state(self.control_dir(game_root), menu="1", fps="0",
                         language="zh-CN", ready="1")

        result = self.get_overlay_state()
        self.assert_overlay_result(result)
        self.assertTrue(result["available"])
        self.assertTrue(result["menu"])
        self.assertFalse(result["fps"])
        self.assertEqual(result["language"], "zh-CN")

    def test_toggle_menu_waits_for_a_real_ack(self):
        game_root = self.install_game()
        self.write_manifest([game_root])
        control = self.control_dir(game_root)
        self.write_state(control, session=SESSION, ready="0")  # running bridge, session adoptable

        core = FakeCore(control, SESSION)
        with core:
            result = self.set_overlay_state(action="menu", value=True)

        self.assert_overlay_result(result, with_ack=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["ack"], "the command must be acknowledged by the core")
        self.assertTrue(result["menu"])
        self.assertEqual(core.actual["menu"], "1")

    def test_fps_and_language_do_not_touch_other_fields(self):
        game_root = self.install_game()
        self.write_manifest([game_root])
        control = self.control_dir(game_root)
        self.write_state(control, session=SESSION, ready="0")

        core = FakeCore(control, SESSION)
        with core:
            fps = self.set_overlay_state(action="fps", value=True)
            language = self.set_overlay_state(action="language", value="zh-CN")

        self.assertTrue(fps["ack"])
        self.assertTrue(language["ack"])

        result = self.get_overlay_state()
        self.assertTrue(result["available"])
        self.assertTrue(result["fps"])
        self.assertEqual(result["language"], "zh-CN")
        self.assertFalse(result["menu"], "fps/language must not flip the menu")
        self.assertEqual(core.actual["menu"], "0")

    def test_overlapping_requests_keep_their_acks(self):
        game_root = self.install_game()
        self.write_manifest([game_root])
        control = self.control_dir(game_root)
        self.write_state(control, session=SESSION, ready="0")
        set_overlay_state = self._api("set_overlay_state")

        async def overlapping():
            return await asyncio.gather(
                set_overlay_state(str(APPID), "menu", True),
                set_overlay_state(str(APPID), "fps", True),
            )

        with FakeCore(control, SESSION):
            menu_result, fps_result = self.run_async(overlapping())

        self.assertTrue(menu_result["ack"], "two overlapping commands must not lose an ack")
        self.assertTrue(fps_result["ack"], "two overlapping commands must not lose an ack")


class TestPreservation(BackendTestCase):
    def test_other_game_and_user_files_are_left_alone(self):
        game_root = self.install_game()
        self.write_manifest([game_root])
        control = self.control_dir(game_root)
        self.write_state(control, session=SESSION, ready="0")
        notes = control / "notes.txt"
        notes.write_text("do not touch", encoding="utf-8")

        home = Path(self.paths.data_home())
        home.mkdir(parents=True, exist_ok=True)
        keeper = home / "keep.txt"
        keeper.write_text("keep", encoding="utf-8")

        settings = Path(self.paths.settings_dir())
        settings.mkdir(parents=True, exist_ok=True)
        games_json = settings / "games.json"
        games_json.write_text('{"1": {"dll": "dxgi.dll"}}', encoding="utf-8")

        with FakeCore(control, SESSION):
            self.set_overlay_state(action="menu", value=True)

        self.assertEqual(notes.read_text(encoding="utf-8"), "do not touch")
        self.assertEqual(keeper.read_text(encoding="utf-8"), "keep")
        self.assertEqual(games_json.read_text(encoding="utf-8"), '{"1": {"dll": "dxgi.dll"}}')

        names = {p.name for p in control.iterdir()}
        self.assertTrue({REQUEST_NAME, STATE_NAME, "notes.txt"} <= names,
                        f"unexpected control-directory contents: {names}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
