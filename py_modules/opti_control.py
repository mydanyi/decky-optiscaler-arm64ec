"""Decky-side controller for the OptiScaler in-game mailbox.

The plugin and the in-game core talk through two small ``key=value`` files in
the game's OptiScaler runtime directory (``overlay.request`` out, ``overlay.state``
back). Protocol version 1: the plugin writes ``version``, ``session`` (the
per-launch nonce the core published), a fresh ``request`` nonce, ``action`` and
``value``; the core mirrors session/request back into the state with
``ready=1`` only once it has applied the change. The actions are ``menu`` and
``fps`` (``0``/``1``) plus ``language`` (``en``/``zh-CN``). Standard library
only: no sockets, processes, keyboards or external services are involved.
"""

from __future__ import annotations

import os
import re
import secrets
import time
from pathlib import Path

CONTROL_DIR_NAME = "OptiScaler"
REQUEST_NAME = "overlay.request"
STATE_NAME = "overlay.state"
PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 4096
MAX_STATE_BYTES = 4096

# A state adopted for a ``session=None`` controller must be this fresh; an
# older one belongs to a previous launch and cannot be trusted.
STATE_MAX_AGE_SECONDS = 5.0

DEFAULT_TIMEOUT = 2.0
DEFAULT_INTERVAL = 0.05

LANGUAGES = ("en", "zh-CN")

_ACTION_VALUES = {
    "menu": ("0", "1"),
    "fps": ("0", "1"),
    "language": LANGUAGES,
}
_STATE_KEYS = ("version", "session", "request", "menu", "fps", "language", "ready")
_HEX_RE = re.compile(r"^[0-9a-f]+$")


class ControlError(Exception):
    """Base error for mailbox-control failures."""


class InvalidRequest(ControlError):
    """The caller asked for an action/value pair the protocol does not allow."""


def _is_hex(value, *, min_len: int = 16, max_len: int = 64) -> bool:
    """True for a lowercase hex token of the documented length."""
    return (
        isinstance(value, str)
        and min_len <= len(value) <= max_len
        and _HEX_RE.match(value) is not None
    )


def new_token() -> str:
    """A fresh 32-character lowercase hex nonce."""
    return secrets.token_hex(16)


def new_session() -> str:
    """Alias of :func:`new_token` for callers that name it a session."""
    return new_token()


def resolve_control_dir(game_root, leaf=CONTROL_DIR_NAME, *, must_exist: bool = False) -> Path:
    """Return ``game_root/leaf`` resolved, guaranteed to stay inside the root.

    Rejects an absolute leaf, a leaf that escapes through ``..``, and a leaf
    that is (or resolves through) a symlink pointing outside the game root.
    """
    root = Path(game_root).resolve()
    part = Path(leaf)
    if part.is_absolute():
        raise ControlError(f"control directory must be relative to the game root: {leaf!r}")

    target = root / part
    if target.is_symlink():
        raise ControlError(f"control directory must not be a symlink: {target}")

    resolved = target.resolve()
    if resolved.parent != root:
        raise ControlError(f"control directory escapes the game root: {leaf!r}")

    if must_exist and not resolved.is_dir():
        raise ControlError(f"control directory does not exist: {resolved}")
    return resolved


def parse_state(text):
    """Parse a state document; return a dict of strings or ``None`` if malformed.

    Accepts exactly the seven documented keys once each with protocol-valid
    values. ``request`` is the one value that may be empty (initial state).
    """
    if text is None:
        return None
    if len(text) > MAX_STATE_BYTES:
        return None

    state = {}
    for line in text.splitlines():
        if not line:
            continue
        if "=" not in line:
            return None
        key, _, value = line.partition("=")
        if not key or key in state:
            return None
        state[key] = value

    if set(state) != set(_STATE_KEYS):
        return None
    if state["version"] != str(PROTOCOL_VERSION):
        return None
    if not _is_hex(state["session"]):
        return None
    if state["request"] and not _is_hex(state["request"]):
        return None
    if state["menu"] not in ("0", "1"):
        return None
    if state["fps"] not in ("0", "1"):
        return None
    if state["ready"] not in ("0", "1"):
        return None
    if state["language"] not in LANGUAGES:
        return None
    return state


def read_state(path, max_age=None):
    """Read a state file, or return ``None``.

    Missing, unreadable, symlinked, malformed, oversized or stale files all
    count as absent. ``max_age`` (seconds) rejects a file older than that; the
    default ``None`` performs no freshness check.
    """
    path = Path(path)
    if path.is_symlink():
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    if max_age is not None and (time.time() - stat.st_mtime) > max_age:
        return None
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_STATE_BYTES + 1)
    except OSError:
        return None
    if len(raw) > MAX_STATE_BYTES:
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return parse_state(text)


def _coerce_value(action, value) -> str:
    """Validate ``action``/``value`` and return the on-wire string."""
    allowed = _ACTION_VALUES.get(action)
    if allowed is None:
        raise InvalidRequest(f"unknown action: {action!r}")
    if value is True:
        text = "1"
    elif value is False:
        text = "0"
    else:
        text = str(value)
    if text not in allowed:
        raise InvalidRequest(f"invalid value for {action}: {value!r}")
    return text


def validate_action_value(action, value) -> str:
    """Validate an ``action``/``value`` pair; return the on-wire string.

    Public entry point for the plugin API, so a bad request is rejected before
    anything touches the mailbox. Raises :class:`InvalidRequest`.
    """
    return _coerce_value(action, value)


def _atomic_write(path: Path, text: str) -> None:
    """Write ``text`` through a unique sibling temp file, then rename it over."""
    path = Path(path)
    tmp = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    try:
        with open(tmp, "wb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        # Only ever remove the temp file this call created.
        try:
            tmp.unlink()
        except OSError:
            pass


class Controller:
    """Issue menu/FPS/language commands and await the core's acknowledgement."""

    def __init__(self, directory, session=None, *, clock=time.monotonic, sleep=time.sleep):
        self._dir = Path(directory)
        # A symlinked mailbox could be re-pointed between the plugin and the
        # core, so a directory reached through a link is refused outright.
        if self._dir.is_symlink():
            raise ControlError(f"control directory must not be a symlink: {self._dir}")
        self._clock = clock
        self._sleep = sleep
        self._last_error = None
        if session is None:
            # Only a fresh, well-formed state proves a live session; an older
            # one belongs to a previous launch and is never adopted.
            state = read_state(self._dir / STATE_NAME, max_age=STATE_MAX_AGE_SECONDS)
            session = state["session"] if state else None
        elif not _is_hex(session):
            # An explicit session the plugin cannot vouch for is a caller bug,
            # not a silently unavailable core.
            raise ControlError(f"invalid control session: {session!r}")
        self._session = session

    @property
    def session(self):
        return self._session

    @property
    def request_path(self) -> Path:
        return self._dir / REQUEST_NAME

    @property
    def state_path(self) -> Path:
        return self._dir / STATE_NAME

    @property
    def last_error(self):
        return self._last_error

    def send(self, action, value, *, timeout=DEFAULT_TIMEOUT, interval=DEFAULT_INTERVAL) -> bool:
        """Ask the core for a change; return ``True`` only on a matching ack."""
        text = _coerce_value(action, value)
        if not self._session:
            # No launch session was ever adopted: nothing to talk to.
            self._last_error = "core-unavailable"
            return False

        # Never read or overwrite a mailbox file that is a symlink: it could
        # point somewhere the game root does not own.
        if self.request_path.is_symlink() or self.state_path.is_symlink():
            raise ControlError("control mailbox files must not be symlinks")

        nonce = new_token()
        body = (
            f"version={PROTOCOL_VERSION}\n"
            f"session={self._session}\n"
            f"request={nonce}\n"
            f"action={action}\n"
            f"value={text}\n"
        )
        _atomic_write(self.request_path, body)

        deadline = self._clock() + max(0.0, timeout)
        saw_state = False
        while True:
            state = read_state(self.state_path)
            if state is not None:
                saw_state = True
                if self._is_ack(state, action, text, nonce):
                    self._last_error = None
                    return True
            now = self._clock()
            if now >= deadline:
                break
            self._sleep(max(0.0, min(interval, deadline - now)))

        self._last_error = "ack-timeout" if saw_state else "core-unavailable"
        return False

    def _is_ack(self, state, action, value, nonce) -> bool:
        return (
            state.get("version") == str(PROTOCOL_VERSION)
            and state.get("session") == self._session
            and state.get("request") == nonce
            and state.get("ready") == "1"
            and state.get(action) == value
        )

    def set_menu(self, visible, **kw) -> bool:
        return self.send("menu", "1" if visible else "0", **kw)

    def set_fps(self, visible, **kw) -> bool:
        return self.send("fps", "1" if visible else "0", **kw)

    def set_language(self, language, **kw) -> bool:
        return self.send("language", language, **kw)
