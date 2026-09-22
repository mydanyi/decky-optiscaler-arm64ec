import logging
import os
import re
from pathlib import Path
from typing import Iterable, Optional

import opti_paths as paths

log = logging.getLogger("optiscaler.games")

# Depots that are not games.
SKIP_APPIDS = {"228980", "1070560", "1391110", "1493710", "1628350", "2180100"}
SKIP_NAME_PATTERNS = ("proton", "steam linux runtime", "steamworks common",
                      "steam controller", "proton experimental")

# Directory names that never hold the game's renderer.
SKIP_DIRS = {
    "_commonredist", "commonredist", "redist", "redistributable", "redistributables",
    "directx", "dotnet", "dotnetfx", "vcredist", "__installer", "installer",
    "easyanticheat", "easyanticheat_eos", "battleye", "anticheat",
    "支持", "support", "tools", "sdk", "docs", "documentation",
    "crashreportclient", "crashpad", "dxsetup", "openvr", "steamvr",
    "_backup", "backup", "mods", "saves", "savegames", "screenshots",
    "node_modules", ".git",
}

# Present in nearly every Proton title and never the renderer.
SKIP_EXE_PATTERNS = re.compile(
    r"(unins|setup|vcredist|dxsetup|dotnet|oalinst|directx|redist"
    r"|crashhandler|crashreport|crashpad|sendreport|errorreport"
    r"|easyanticheat|battleye|beservice|anticheat"
    r"|cefsubprocess|subprocess|helper|webhelper|touchup"
    r"|nvngx|python|perl|7z|quicksfv|dokan)",
    re.IGNORECASE,
)

# The usual homes of a 64-bit game binary.
PREFERRED_FRAGMENTS = (
    ("binaries/win64", 100),
    ("binaries/wingdk", 90),
    ("bin/x64", 80),
    ("bin64", 80),
    ("win64", 60),
    ("x64", 50),
    ("bin", 30),
)

MACHINE_AMD64 = 0x8664
MACHINE_ARM64 = 0xAA64
MACHINE_I386 = 0x14C

MIN_EXE_SIZE = 192 * 1024
MAX_WALK_ENTRIES = 40000
DEFAULT_MAX_TARGETS = 4


# --------------------------------------------------------------------------
# VDF / ACF
# --------------------------------------------------------------------------

_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')


# Tolerant on purpose: a malformed appmanifest should cost one game, not the
# whole listing.
def parse_vdf(text: str) -> dict:
    root: dict = {}
    stack = [root]
    pending: Optional[str] = None
    for match in _TOKEN.finditer(text):
        quoted, brace = match.group(1), match.group(2)
        if brace == "{":
            child: dict = {}
            if pending is not None:
                stack[-1][pending] = child
                pending = None
            stack.append(child)
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
        else:
            value = quoted.replace("\\\\", "\\").replace('\\"', '"')
            if pending is None:
                pending = value
            else:
                stack[-1][pending] = value
                pending = None
    return root


def _read_vdf(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return parse_vdf(handle.read())
    except OSError as exc:
        log.warning("could not read %s: %s", path, exc)
        return {}


def library_paths() -> list:
    root = paths.steam_root()
    found = []

    def add(candidate) -> None:
        try:
            resolved = Path(candidate).expanduser()
        except (TypeError, ValueError):
            return
        if (resolved / "steamapps").is_dir() and resolved not in found:
            found.append(resolved)

    add(root)
    data = _read_vdf(root / "steamapps" / "libraryfolders.vdf")
    folders = data.get("libraryfolders") or data.get("LibraryFolders") or {}
    for key, entry in folders.items():
        if isinstance(entry, dict):
            add(entry.get("path", ""))
        elif key.isdigit():  # pre-2021 format: "1" "/path"
            add(entry)
    return found


# --------------------------------------------------------------------------
# game listing
# --------------------------------------------------------------------------

def _is_real_game(appid: str, name: str) -> bool:
    if appid in SKIP_APPIDS:
        return False
    lowered = name.lower()
    return not any(pattern in lowered for pattern in SKIP_NAME_PATTERNS)


def list_games() -> list:
    games = []
    seen = set()
    for library in library_paths():
        steamapps = library / "steamapps"
        for manifest in sorted(steamapps.glob("appmanifest_*.acf")):
            state = (_read_vdf(manifest).get("AppState") or {})
            appid = state.get("appid", "").strip()
            name = state.get("name", "").strip()
            installdir = state.get("installdir", "").strip()
            if not appid or not installdir or appid in seen:
                continue
            if not _is_real_game(appid, name):
                continue
            install_path = steamapps / "common" / installdir
            if not install_path.is_dir():
                continue
            seen.add(appid)
            games.append({
                "appid": appid,
                "name": name or installdir,
                "install_dir": str(install_path),
                "library": str(library),
                "size_on_disk": int(state.get("SizeOnDisk", "0") or 0),
            })
    games.sort(key=lambda game: game["name"].lower())
    return games


def game_by_appid(appid: str) -> Optional[dict]:
    appid = str(appid)
    for game in list_games():
        if game["appid"] == appid:
            return game
    return None


# --------------------------------------------------------------------------
# executable detection
# --------------------------------------------------------------------------

# ARM64EC images report AMD64 too, so this only rules out 32-bit binaries,
# which can never load the DLL.
def pe_machine(path: Path) -> Optional[int]:
    try:
        with open(path, "rb") as handle:
            if handle.read(2) != b"MZ":
                return None
            handle.seek(0x3C)
            offset_bytes = handle.read(4)
            if len(offset_bytes) != 4:
                return None
            handle.seek(int.from_bytes(offset_bytes, "little"))
            if handle.read(4) != b"PE\0\0":
                return None
            machine = handle.read(2)
            return int.from_bytes(machine, "little") if len(machine) == 2 else None
    except OSError:
        return None


def _score(exe: Path, root: Path, size: int) -> int:
    try:
        relative = exe.parent.relative_to(root).as_posix().lower()
    except ValueError:
        relative = ""
    score = 0
    for fragment, points in PREFERRED_FRAGMENTS:
        if fragment in relative:
            score += points
            break
    # Shipping binaries dwarf helper executables, so size is a fair tiebreak.
    score += min(size // (1024 * 1024), 60)
    # A binary named after its folder is usually the real one.
    if exe.stem.lower() in root.name.lower() or root.name.lower() in exe.stem.lower():
        score += 25
    if relative == "":
        score += 15
    return score


def _walk_executables(root: Path) -> Iterable[Path]:
    budget = MAX_WALK_ENTRIES
    for current, dirnames, filenames in os.walk(root, topdown=True):
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS
                       and not d.startswith(".")]
        budget -= len(filenames)
        if budget <= 0:
            log.warning("stopped scanning %s after %d entries", root, MAX_WALK_ENTRIES)
            return
        for filename in filenames:
            if filename.lower().endswith(".exe"):
                yield Path(current) / filename


# The install root is always a target. Loading is per-directory and a game's
# renderer often sits several levels down, so guessing wrong costs nothing.
def find_targets(install_dir: str, max_targets: int = DEFAULT_MAX_TARGETS) -> list:
    root = Path(install_dir)
    targets = [{
        "path": str(root),
        "reason": "Game root",
        "exe": "",
        "primary": True,
    }]
    if not root.is_dir():
        return targets

    candidates = {}
    for exe in _walk_executables(root):
        if SKIP_EXE_PATTERNS.search(exe.name):
            continue
        try:
            size = exe.stat().st_size
        except OSError:
            continue
        if size < MIN_EXE_SIZE:
            continue
        if pe_machine(exe) not in (MACHINE_AMD64, MACHINE_ARM64):
            continue
        score = _score(exe, root, size)
        existing = candidates.get(exe.parent)
        if existing is None or score > existing[0]:
            candidates[exe.parent] = (score, exe)

    ranked = sorted(candidates.items(), key=lambda item: item[1][0], reverse=True)
    for directory, (_score_value, exe) in ranked:
        if len(targets) >= max_targets + 1:
            break
        if directory == root:
            targets[0]["exe"] = exe.name
            continue
        try:
            relative = directory.relative_to(root).as_posix()
        except ValueError:
            relative = str(directory)
        targets.append({
            "path": str(directory),
            "reason": relative,
            "exe": exe.name,
            "primary": False,
        })
    return targets
