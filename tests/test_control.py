"""Behaviour tests for the Decky-side direct-control module.

These tests load the *real* ``py_modules/opti_control.py`` this branch ships and
assert the behaviour its docstring promises: the protocol v1 mailbox, the
session/nonce handshake and the acknowledgement rules. If the module is missing
or does not import the tests fail with one clear message instead of a
collection error.

Everything here is real I/O against temporary directories. A small in-test
thread plays the in-game core: it reads ``overlay.request`` and writes
``overlay.state`` exactly like the C++ bridge, so the controller is exercised
end to end. Nothing touches ``/proc`` and no keyboard backend is involved.

Run with: python -m unittest tests.test_control
      or: python tests/test_control.py
"""

import importlib
import importlib.util
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))


def _load_module():
    path = PLUGIN_ROOT / "py_modules" / "opti_control.py"
    if not path.exists():
        raise FileNotFoundError(
            f"expected implementation {path} to exist; it is added by the control change"
        )
    try:
        return importlib.import_module("py_modules.opti_control")
    except Exception:
        spec = importlib.util.spec_from_file_location("opti_control", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["opti_control"] = module
        spec.loader.exec_module(module)
        return module


try:
    opti_control = _load_module()
    LOAD_ERROR = None
except Exception as exc:  # pragma: no cover - only until the module exists
    opti_control = None
    LOAD_ERROR = exc


SESSION = "0123456789abcdef0123456789abcdef"

STATE_TEMPLATE = (
    "version=1\n"
    "session={session}\n"
    "request={request}\n"
    "menu={menu}\n"
    "fps={fps}\n"
    "language={language}\n"
    "ready={ready}\n"
)


def _parse(text):
    """Tiny key=value parser mirroring the on-disk state format."""
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


def _atomic_write(path, text):
    path = Path(path)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _write_state(directory, state):
    _atomic_write(Path(directory) / opti_control.STATE_NAME, STATE_TEMPLATE.format(**state))


def _state_text(**overrides):
    """Build a well-formed state document, letting callers corrupt one field."""
    fields = {
        "version": "1",
        "session": SESSION,
        "request": "",
        "menu": "0",
        "fps": "0",
        "language": "en",
        "ready": "0",
    }
    fields.update(overrides)
    return "".join(f"{key}={value}\n" for key, value in fields.items())


class FakeCore(threading.Thread):
    """Plays the in-game bridge: mirrors a request into a state file.

    It keeps the applied UI state across requests, the way a real core does, so
    a later command only changes its own field and the rest of the state stays
    put.
    """

    def __init__(
        self,
        directory,
        session,
        *,
        report_session=None,
        report_nonce=None,
        report_value=None,
        report_ready=None,
        interval=0.005,
    ):
        super().__init__(daemon=True)
        self.directory = Path(directory)
        self.session = session
        self.report_session = report_session
        self.report_nonce = report_nonce
        self.report_value = report_value
        self.report_ready = report_ready
        self.interval = interval
        self.stopped = threading.Event()
        self.wrote = threading.Event()
        self.actual = {"menu": "0", "fps": "0", "language": "en"}

    def run(self):
        request_path = self.directory / opti_control.REQUEST_NAME
        while not self.stopped.is_set():
            try:
                text = request_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                text = None
            except OSError:
                text = None
            request = _parse(text)
            if (
                request
                and request.get("version") == "1"
                and request.get("session") == self.session
                and request.get("action") in ("menu", "fps", "language")
            ):
                nonce = request.get("request", "")
                if self.report_nonce is not None:
                    nonce = self.report_nonce(nonce)
                action = request.get("action")
                value = request.get("value", "")
                if self.report_value is not None:
                    value = self.report_value(action, value)
                if action in self.actual:
                    self.actual[action] = value

                ready = "1"
                if self.report_ready is not None:
                    ready = (
                        self.report_ready(nonce)
                        if callable(self.report_ready)
                        else self.report_ready
                    )

                state = {
                    "session": self.report_session or self.session,
                    "request": nonce,
                    "menu": self.actual["menu"],
                    "fps": self.actual["fps"],
                    "language": self.actual["language"],
                    "ready": ready,
                }
                _write_state(self.directory, state)
                self.wrote.set()
            self.stopped.wait(self.interval)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    def stop(self):
        self.stopped.set()
        self.join(timeout=2.0)


class ControlTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="opti-control-")
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def mod(self):
        self.assertIsNotNone(
            opti_control,
            f"py_modules/opti_control.py must exist and import cleanly ({LOAD_ERROR!r})",
        )
        return opti_control

    # -- helpers -----------------------------------------------------------

    def controller(self, directory=None, session=SESSION):
        self.mod()
        return opti_control.Controller(directory or self.dir, session=session)

    def assert_no_temp_files(self, directory):
        for entry in Path(directory).iterdir():
            self.assertNotIn(
                ".tmp",
                entry.name,
                f"atomic write left a temporary file behind: {entry.name}",
            )


class TestLayout(ControlTestCase):
    def test_module_exposes_the_documented_surface(self):
        mod = self.mod()
        self.assertEqual(mod.PROTOCOL_VERSION, 1)
        self.assertGreaterEqual(mod.MAX_REQUEST_BYTES, 4096)
        for attr in ("ControlError", "InvalidRequest", "resolve_control_dir", "read_state"):
            self.assertTrue(hasattr(mod, attr), f"{attr} must be exported")

    def test_new_token_is_fresh_unique_hex(self):
        mod = self.mod()
        tokens = {mod.new_token() for _ in range(64)}
        self.assertEqual(len(tokens), 64, "tokens must be unique")
        for token in tokens:
            self.assertRegex(token, r"^[0-9a-f]+$", "tokens must be lowercase hex")
            self.assertGreaterEqual(len(token), 16)

    def test_resolve_control_dir_stays_inside_the_game_root(self):
        mod = self.mod()
        root = self.dir.resolve()
        resolved = mod.resolve_control_dir(self.dir)
        self.assertEqual(resolved.parent, root, "the control dir must sit directly under the game root")
        self.assertEqual(resolved.name, mod.CONTROL_DIR_NAME)

    def test_resolve_control_dir_rejects_parent_escape(self):
        mod = self.mod()
        with self.assertRaises(mod.ControlError):
            mod.resolve_control_dir(self.dir, "../escape")

    def test_resolve_control_dir_rejects_symlink_escape(self):
        mod = self.mod()
        outside = Path(tempfile.mkdtemp(prefix="opti-outside-"))
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        link = self.dir / "linked"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable on this platform: {exc}")
        with self.assertRaises(mod.ControlError):
            mod.resolve_control_dir(self.dir, "linked")


class TestSendSuccess(ControlTestCase):
    def test_menu_command_succeeds_only_on_matching_ack(self):
        mod = self.mod()
        ctrl = self.controller()
        with FakeCore(self.dir, SESSION):
            self.assertTrue(ctrl.set_menu(True, timeout=2.0, interval=0.01))
        state = mod.read_state(ctrl.state_path)
        self.assertIsNotNone(state)
        self.assertEqual(state["menu"], "1")
        self.assertEqual(state["ready"], "1")
        self.assertEqual(state["session"], SESSION)
        self.assert_no_temp_files(self.dir)

    def test_fps_and_language_round_trip(self):
        mod = self.mod()
        ctrl = self.controller()
        with FakeCore(self.dir, SESSION):
            self.assertTrue(ctrl.set_fps(True, timeout=2.0, interval=0.01))
            self.assertTrue(ctrl.set_language("zh-CN", timeout=2.0, interval=0.01))
        state = mod.read_state(ctrl.state_path)
        self.assertEqual(state["fps"], "1")
        self.assertEqual(state["language"], "zh-CN")

    def test_language_change_never_touches_menu_or_fps(self):
        mod = self.mod()
        ctrl = self.controller()
        with FakeCore(self.dir, SESSION):
            self.assertTrue(ctrl.set_language("zh-CN", timeout=2.0, interval=0.01))
        state = mod.read_state(ctrl.state_path)
        self.assertEqual(state["menu"], "0")
        self.assertEqual(state["fps"], "0")

    def test_each_send_uses_a_fresh_request_token(self):
        mod = self.mod()
        ctrl = self.controller()
        nonces = []
        with FakeCore(self.dir, SESSION):
            for visible in (True, False):
                self.assertTrue(ctrl.set_menu(visible, timeout=2.0, interval=0.01))
                nonces.append(
                    _parse((self.dir / mod.REQUEST_NAME).read_text(encoding="utf-8"))["request"]
                )
        self.assertEqual(len(set(nonces)), 2, "every command needs a unique nonce")

    def test_other_files_are_preserved(self):
        mod = self.mod()
        ctrl = self.controller()
        notes = self.dir / "notes.txt"
        notes.write_text("do not touch", encoding="utf-8")
        with FakeCore(self.dir, SESSION):
            self.assertTrue(ctrl.set_menu(True, timeout=2.0, interval=0.01))
        self.assertEqual(notes.read_text(encoding="utf-8"), "do not touch")
        # Only the two protocol files may exist.
        names = {p.name for p in self.dir.iterdir()}
        self.assertLessEqual({mod.REQUEST_NAME, mod.STATE_NAME, "notes.txt"}, names)


class TestStateParsing(ControlTestCase):
    """parse_state/read_state reject anything outside the documented protocol."""

    def parse(self, text):
        mod = self.mod()
        return mod.parse_state(text)

    def test_accepts_the_documented_shape(self):
        state = self.parse(_state_text(request="", ready="0"))
        self.assertIsInstance(state, dict)
        self.assertEqual(
            set(state),
            {"version", "session", "request", "menu", "fps", "language", "ready"},
        )

    def test_initial_state_may_have_an_empty_request(self):
        state = self.parse(_state_text(request=""))
        self.assertIsNotNone(state)
        self.assertEqual(state["request"], "")

    def test_rejects_wrong_protocol_version(self):
        self.assertIsNone(self.parse(_state_text(version="2")))

    def test_rejects_missing_field(self):
        self.assertIsNone(self.parse(_state_text().replace("ready=0\n", "")))

    def test_rejects_unknown_field(self):
        self.assertIsNone(self.parse(_state_text() + "extra=1\n"))

    def test_rejects_duplicate_field(self):
        self.assertIsNone(self.parse(_state_text() + "ready=1\n"))

    def test_rejects_non_hex_session(self):
        self.assertIsNone(self.parse(_state_text(session="not-hex")))

    def test_rejects_non_hex_request(self):
        self.assertIsNone(self.parse(_state_text(request="zz")))

    def test_rejects_invalid_booleans(self):
        self.assertIsNone(self.parse(_state_text(menu="2")))
        self.assertIsNone(self.parse(_state_text(ready="maybe")))

    def test_rejects_invalid_locale(self):
        self.assertIsNone(self.parse(_state_text(language="fr")))

    def test_rejects_line_without_equals(self):
        self.assertIsNone(self.parse("version=1\nsession=" + SESSION + "\nbroken\n"))

    def test_rejects_oversized_state(self):
        big = _state_text() + ("x" * (self.mod().MAX_REQUEST_BYTES + 1))
        self.assertIsNone(self.parse(big))

    def test_read_state_returns_none_for_missing_file(self):
        mod = self.mod()
        self.assertIsNone(mod.read_state(self.dir / mod.STATE_NAME))

    def test_read_state_drops_state_older_than_max_age(self):
        mod = self.mod()
        _write_state(
            self.dir,
            {
                "session": SESSION,
                "request": "",
                "menu": "1",
                "fps": "0",
                "language": "en",
                "ready": "1",
            },
        )
        path = self.dir / mod.STATE_NAME
        old = time.time() - 3600
        os.utime(path, (old, old))
        self.assertIsNone(mod.read_state(path, max_age=5))
        # The default keeps the plain behaviour and a generous age still accepts it.
        self.assertIsNotNone(mod.read_state(path))
        self.assertIsNotNone(mod.read_state(path, max_age=7200))


class TestFailureModes(ControlTestCase):
    def test_unavailable_core_does_not_report_success(self):
        mod = self.mod()
        ctrl = self.controller()
        self.assertFalse(ctrl.set_menu(True, timeout=0.3, interval=0.01))
        self.assertEqual(ctrl.last_error, "core-unavailable")

    def test_stale_state_is_not_success(self):
        mod = self.mod()
        ctrl = self.controller()
        # A state left over from some earlier request/session.
        _write_state(
            self.dir,
            {
                "session": "ffffffffffffffffffffffffffffffff",
                "request": "deadbeefdeadbeefdeadbeefdeadbeef",
                "menu": "1",
                "fps": "0",
                "language": "en",
                "ready": "1",
            },
        )
        self.assertFalse(ctrl.set_menu(True, timeout=0.3, interval=0.01))
        self.assertEqual(ctrl.last_error, "ack-timeout")

    def test_wrong_nonce_is_not_success(self):
        mod = self.mod()
        ctrl = self.controller()
        with FakeCore(self.dir, SESSION, report_nonce=lambda _n: "0" * 32):
            self.assertFalse(ctrl.set_menu(True, timeout=0.4, interval=0.01))
        self.assertEqual(ctrl.last_error, "ack-timeout")

    def test_wrong_session_ack_is_not_success(self):
        mod = self.mod()
        ctrl = self.controller()
        with FakeCore(self.dir, SESSION, report_session="f" * 32):
            self.assertFalse(ctrl.set_menu(True, timeout=0.4, interval=0.01))

    def test_value_mismatch_is_not_success(self):
        mod = self.mod()
        ctrl = self.controller()
        # The core claims to have applied the opposite of what we asked.
        with FakeCore(self.dir, SESSION, report_value=lambda _a, v: "0" if v == "1" else "1"):
            self.assertFalse(ctrl.set_menu(True, timeout=0.4, interval=0.01))

    def test_writer_ready_zero_is_not_success(self):
        mod = self.mod()
        ctrl = self.controller()
        # The core echoed our session/nonce/value but has not finished applying
        # it, so its state carries ready=0 and must not count as an ack.
        with FakeCore(self.dir, SESSION, report_ready="0"):
            self.assertFalse(ctrl.set_menu(True, timeout=0.4, interval=0.01))
        self.assertEqual(ctrl.last_error, "ack-timeout")

    def test_invalid_action_and_value_raise(self):
        mod = self.mod()
        ctrl = self.controller()
        with self.assertRaises(mod.InvalidRequest):
            ctrl.send("volume", "1", timeout=0.1)
        with self.assertRaises(mod.InvalidRequest):
            ctrl.send("menu", "2", timeout=0.1)
        with self.assertRaises(mod.InvalidRequest):
            ctrl.set_language("fr", timeout=0.1)


class TestDefaultSession(ControlTestCase):
    """``Controller(session=None)`` adopts the launch session the core published.

    The plugin never invents a session: when no fresh state exists there is
    nothing to talk to and the controller stays unavailable rather than
    fabricating a nonce.
    """

    def test_adopts_the_published_session(self):
        mod = self.mod()
        self.controller()  # ensure the module loaded for a clear failure reason
        _write_state(self.dir, {
            "session": SESSION,
            "request": "",
            "menu": "0",
            "fps": "0",
            "language": "en",
            "ready": "1",
        })
        ctrl = opti_control.Controller(self.dir, session=None)
        self.assertEqual(ctrl.session, SESSION)

    def test_without_state_there_is_no_session_and_no_request(self):
        mod = self.mod()
        ctrl = opti_control.Controller(self.dir, session=None)
        self.assertIsNone(ctrl.session)
        self.assertFalse(ctrl.set_menu(True, timeout=0.2, interval=0.01))
        self.assertEqual(ctrl.last_error, "core-unavailable")
        self.assertFalse(
            (self.dir / mod.REQUEST_NAME).exists(),
            "no session must never be invented, so no request may be written",
        )

    def test_a_stale_session_is_not_adopted(self):
        mod = self.mod()
        self.controller()
        _write_state(self.dir, {
            "session": SESSION,
            "request": "",
            "menu": "0",
            "fps": "0",
            "language": "en",
            "ready": "1",
        })
        path = self.dir / mod.STATE_NAME
        old = time.time() - (mod.STATE_MAX_AGE_SECONDS + 60)
        os.utime(path, (old, old))
        ctrl = opti_control.Controller(self.dir, session=None)
        self.assertIsNone(ctrl.session, "a state from a previous launch is too old to adopt")


if __name__ == "__main__":
    unittest.main(verbosity=2)
