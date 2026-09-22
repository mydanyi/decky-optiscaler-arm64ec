import json
import logging
import re
import shlex
from pathlib import Path
from typing import Optional

import opti_paths as paths

log = logging.getLogger("optiscaler.profiles")

COMMAND_TOKEN = "%command%"
APPID_VAR = "OPTISCALER_APPID"
SCRIPT_NAME = "optiscaler-launch.sh"

DEFAULTS = {
    "default_dll": "dxgi.dll",
    # Off by default: spoofing changes what every game sees of the GPU, and the
    # games that need it to expose DLSS are the minority. Turn it on per game.
    "default_spoof": False,
    "default_optipatcher": False,
}


# --------------------------------------------------------------------------
# json helpers
# --------------------------------------------------------------------------

def _load_json(path: Path, fallback: dict) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else dict(fallback)
    except (OSError, ValueError):
        return dict(fallback)


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    tmp.replace(path)


def get_defaults() -> dict:
    data = _load_json(paths.defaults_config(), DEFAULTS)
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in data.items() if k in DEFAULTS})
    return merged


def set_defaults(default_dll: Optional[str] = None,
                 default_spoof: Optional[bool] = None,
                 default_optipatcher: Optional[bool] = None) -> dict:
    current = get_defaults()
    if default_dll:
        current["default_dll"] = default_dll
    if default_spoof is not None:
        current["default_spoof"] = bool(default_spoof)
    if default_optipatcher is not None:
        current["default_optipatcher"] = bool(default_optipatcher)
    _save_json(paths.defaults_config(), current)
    return current


def all_games() -> dict:
    return _load_json(paths.games_config(), {})


def get_game(appid: str) -> dict:
    defaults = get_defaults()
    stored = all_games().get(str(appid)) or {}
    return {
        "appid": str(appid),
        "dll": stored.get("dll") or defaults["default_dll"],
        "spoof_nvidia": bool(stored.get("spoof_nvidia", defaults["default_spoof"])),
        "optipatcher": bool(stored.get("optipatcher", defaults["default_optipatcher"])),
        "enabled": bool(stored.get("enabled", False)),
        "directories": list(stored.get("directories") or []),
        "version": stored.get("version", ""),
    }


def set_game(appid: str, **changes) -> dict:
    games = all_games()
    entry = games.get(str(appid)) or {}
    for key in ("dll", "spoof_nvidia", "optipatcher", "enabled", "directories",
                "version"):
        if key in changes and changes[key] is not None:
            entry[key] = changes[key]
    games[str(appid)] = entry
    _save_json(paths.games_config(), games)
    return get_game(appid)


def forget_game(appid: str) -> None:
    games = all_games()
    if str(appid) in games:
        del games[str(appid)]
        _save_json(paths.games_config(), games)


# --------------------------------------------------------------------------
# the file the launch wrapper reads
# --------------------------------------------------------------------------

def write_profile(appid: str, dll: str, spoof_nvidia: bool, enabled: bool) -> Path:
    paths.profiles_dir().mkdir(parents=True, exist_ok=True)
    profile = paths.profiles_dir() / f"{appid}.conf"
    body = (
        "# Written by the OptiScaler Decky plugin. Edits here are overwritten.\n"
        f"OPTISCALER_ENABLED={'1' if enabled else '0'}\n"
        f"OPTISCALER_DLL={dll}\n"
        f"OPTISCALER_NVIDIA_SPOOF={'1' if spoof_nvidia else '0'}\n"
    )
    profile.write_text(body, encoding="utf-8")
    return profile


def remove_profile(appid: str) -> None:
    (paths.profiles_dir() / f"{appid}.conf").unlink(missing_ok=True)


# --------------------------------------------------------------------------
# Steam launch options
# --------------------------------------------------------------------------

_SAFE_TOKEN = re.compile(r"^[\w@%+=:,./-]+$")


def _quote(token: str) -> str:
    return token if _SAFE_TOKEN.match(token) else shlex.quote(token)


def _tokenise(options: str) -> list:
    try:
        return shlex.split(options, posix=True)
    except ValueError:
        # Unbalanced quotes in what the user typed, so fall back to whitespace.
        return options.split()


def _is_ours(token: str) -> bool:
    return token.startswith(f"{APPID_VAR}=") or token.endswith(SCRIPT_NAME)


def strip_ours(options: str) -> list:
    return [t for t in _tokenise(options or "") if not _is_ours(t)]


def _split_leading_env(tokens: list) -> tuple:
    index = 0
    while index < len(tokens) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[index]):
        index += 1
    return tokens[:index], tokens[index:]


# The wrapper goes immediately before %command% so a gamescope or mangohud
# prefix the user already has stays outside it. No app id is written: the
# wrapper detects it, so options copied between games cannot apply the wrong
# profile.
def build_launch_options(existing: str, enable: bool) -> str:
    tokens = strip_ours(existing or "")

    if not enable:
        if tokens == [COMMAND_TOKEN]:
            return ""
        return " ".join(_quote(t) for t in tokens)

    ours = [str(paths.launch_script())]

    if COMMAND_TOKEN in tokens:
        position = tokens.index(COMMAND_TOKEN)
        merged = tokens[:position] + ours + tokens[position:]
    else:
        # No %command%: leading assignments are env vars, the rest are game args.
        env, rest = _split_leading_env(tokens)
        merged = env + ours + [COMMAND_TOKEN] + rest

    return " ".join(_quote(t) for t in merged)


def has_our_wrapper(options: str) -> bool:
    return any(_is_ours(t) for t in _tokenise(options or ""))


# --------------------------------------------------------------------------
# reading Steam's own copy, as a fallback for the frontend
# --------------------------------------------------------------------------

# Steam only flushes this periodically, so the frontend prefers the live
# AppDetails value and falls back here.
def launch_options_from_disk(appid: str) -> str:
    import opti_games as games  # local import: only needed on this path

    root = paths.steam_root()
    userdata = root / "userdata"
    if not userdata.is_dir():
        return ""

    newest_value = ""
    newest_mtime = -1.0
    for config in userdata.glob("*/config/localconfig.vdf"):
        try:
            mtime = config.stat().st_mtime
        except OSError:
            continue
        data = games._read_vdf(config)
        node = data.get("UserLocalConfigStore") or {}
        for key in ("Software", "Valve", "Steam", "apps"):
            if not isinstance(node, dict):
                node = {}
                break
            node = node.get(key) or node.get(key.lower()) or {}
        entry = node.get(str(appid)) if isinstance(node, dict) else None
        if isinstance(entry, dict) and mtime > newest_mtime:
            newest_mtime = mtime
            newest_value = entry.get("LaunchOptions", "") or ""
    return newest_value
