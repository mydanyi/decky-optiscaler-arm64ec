import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
from typing import Optional

import opti_paths as paths
import opti_release as release

log = logging.getLogger("optiscaler.install")

# Each directory gets a marker listing what we wrote and what we displaced, so
# uninstalling restores it rather than deleting whatever shares a name.
MARKER = ".optiscaler.json"
BACKUP_SUFFIX = ".optiscaler-bak"

# Each is a DLL Wine looks for next to the executable before its own builtin.
DLL_CHOICES = [
    ("dxgi.dll", "dxgi.dll (default, most DX11/DX12 games)"),
    ("winmm.dll", "winmm.dll (when dxgi clashes with another mod)"),
    ("version.dll", "version.dll (common alternative)"),
    ("dbghelp.dll", "dbghelp.dll (for games that reject the others)"),
    ("d3d12.dll", "d3d12.dll (DX12 only)"),
    ("wininet.dll", "wininet.dll (last resort)"),
    ("winhttp.dll", "winhttp.dll (last resort)"),
]
VALID_DLLS = {name for name, _ in DLL_CHOICES}
DEFAULT_DLL = "dxgi.dll"

INI_NAME = "OptiScaler.ini"
FILES_WE_LEAVE = ("OptiScaler.log", "OptiScaler.ini.bak")


class InstallError(Exception):
    pass


# --------------------------------------------------------------------------
# ini editing
# --------------------------------------------------------------------------

# Section-aware: OptiScaler reuses key names across sections, so a global
# replace of `Vulkan=` would corrupt unrelated settings.
def ini_set(text: str, section: str, key: str, value: str) -> str:
    lines = text.splitlines(keepends=True)
    section_header = re.compile(r"^\s*\[([^\]]+)\]")
    key_line = re.compile(rf"^(\s*){re.escape(key)}(\s*)=.*?(\r?\n?)$", re.IGNORECASE)

    current = None
    in_section_at = None
    for index, line in enumerate(lines):
        header = section_header.match(line)
        if header:
            if current is not None and current.lower() == section.lower():
                # Leaving the target section without having found the key.
                break
            current = header.group(1)
            if current.lower() == section.lower():
                in_section_at = index
            continue
        if current is not None and current.lower() == section.lower():
            match = key_line.match(line)
            if match:
                newline = match.group(3) or "\n"
                lines[index] = f"{match.group(1)}{key}={value}{newline}"
                return "".join(lines)

    if in_section_at is None:
        # Section absent entirely, so append it.
        suffix = "" if text.endswith("\n") or not text else "\n"
        return f"{text}{suffix}\n[{section}]\n{key}={value}\n"

    # Section present but key missing: insert right after the header.
    lines.insert(in_section_at + 1, f"{key}={value}\n")
    return "".join(lines)


# Pinned true or false rather than left at auto, so the toggle means the same
# thing on every machine.
def spoof_overrides(enabled: bool) -> list:
    if enabled:
        return [
            ("Spoofing", "Dxgi", "true"),
            ("Spoofing", "Vulkan", "true"),
            ("Spoofing", "VulkanExtensionSpoofing", "true"),
            ("Spoofing", "StreamlineSpoofing", "true"),
            ("Spoofing", "SpoofedVendorId", "auto"),
            ("Spoofing", "SpoofedDeviceId", "auto"),
            ("Spoofing", "SpoofedGPUName", "auto"),
        ]
    return [
        ("Spoofing", "Dxgi", "false"),
        ("Spoofing", "Vulkan", "false"),
        ("Spoofing", "VulkanExtensionSpoofing", "false"),
        ("Spoofing", "StreamlineSpoofing", "false"),
    ]


def render_ini(source_text: str, spoof_nvidia: bool) -> str:
    text = source_text
    for section, key, value in spoof_overrides(spoof_nvidia):
        text = ini_set(text, section, key, value)
    return text


# --------------------------------------------------------------------------
# marker bookkeeping
# --------------------------------------------------------------------------

def read_marker(directory: Path) -> Optional[dict]:
    try:
        with open(directory / MARKER, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _write_marker(directory: Path, data: dict) -> None:
    with open(directory / MARKER, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)


def _back_up(target: Path, marker: Optional[dict], backups: dict) -> None:
    if not target.exists():
        return
    previously_ours = marker is not None and target.name in (marker.get("files") or [])
    if previously_ours:
        target.unlink()
        return
    backup = target.with_name(target.name + BACKUP_SUFFIX)
    if backup.exists():
        # An earlier backup is the real original, so never clobber it.
        target.unlink()
        return
    target.rename(backup)
    backups[target.name] = backup.name
    log.info("backed up existing %s", target)


def install_into(directory: Path, build: Path, dll_name: str,
                 spoof_nvidia: bool, version: str) -> dict:
    if dll_name not in VALID_DLLS:
        raise InstallError(f"Unsupported DLL name: {dll_name}")
    if not directory.is_dir():
        raise InstallError(f"Not a directory: {directory}")
    if not os.access(directory, os.W_OK):
        raise InstallError(f"No write access to {directory}")

    source_dll = build / release.DLL_NAME
    source_ini = build / release.INI_NAME
    if not source_dll.is_file():
        raise InstallError("Cached OptiScaler build is incomplete")

    marker = read_marker(directory)
    backups = dict((marker or {}).get("backups") or {})
    created = []

    # A DLL name change leaves the old one behind, so clear it first.
    if marker:
        stale = marker.get("dll")
        if stale and stale != dll_name:
            _restore_one(directory, stale, marker)

    dll_target = directory / dll_name
    _back_up(dll_target, marker, backups)
    shutil.copy2(source_dll, dll_target)
    created.append(dll_name)

    ini_target = directory / INI_NAME
    _back_up(ini_target, marker, backups)
    ini_text = source_ini.read_text(encoding="utf-8", errors="replace") \
        if source_ini.is_file() else "[Spoofing]\n"
    ini_target.write_text(render_ini(ini_text, spoof_nvidia), encoding="utf-8")
    created.append(INI_NAME)

    record = {
        "plugin": "OptiScaler",
        "version": version,
        "dll": dll_name,
        "spoof_nvidia": bool(spoof_nvidia),
        "files": created,
        "backups": backups,
        "installed_at": int(time.time()),
    }
    _write_marker(directory, record)
    return record


def _restore_one(directory: Path, filename: str, marker: dict) -> None:
    target = directory / filename
    if target.exists():
        target.unlink()
    backup_name = (marker.get("backups") or {}).get(filename)
    if backup_name:
        backup = directory / backup_name
        if backup.exists():
            backup.rename(target)
            log.info("restored %s", target)


def uninstall_from(directory: Path) -> bool:
    marker = read_marker(directory)
    if marker is None:
        return False
    for filename in list(marker.get("files") or []):
        _restore_one(directory, filename, marker)
    for leftover in FILES_WE_LEAVE:
        (directory / leftover).unlink(missing_ok=True)
    (directory / MARKER).unlink(missing_ok=True)
    return True


def is_installed(directory: Path) -> bool:
    marker = read_marker(directory)
    if marker is None:
        return False
    return (directory / marker.get("dll", "")).is_file()


# --------------------------------------------------------------------------
# whole-game operations
# --------------------------------------------------------------------------

def _manifest_path(appid: str) -> Path:
    return paths.installs_dir() / f"{appid}.json"


def read_install_manifest(appid: str) -> Optional[dict]:
    try:
        with open(_manifest_path(appid), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def install_game(appid: str, target_dirs: list, dll_name: str,
                 spoof_nvidia: bool, version: str) -> dict:
    build = paths.build_dir()
    paths.installs_dir().mkdir(parents=True, exist_ok=True)

    installed, failed = [], []
    for raw in target_dirs:
        directory = Path(raw)
        try:
            install_into(directory, build, dll_name, spoof_nvidia, version)
            installed.append(str(directory))
        except (InstallError, OSError) as exc:
            log.error("install into %s failed: %s", directory, exc)
            failed.append({"path": str(directory), "error": str(exc)})

    if not installed:
        raise InstallError(failed[0]["error"] if failed else "No directories to install into")

    manifest = {
        "appid": str(appid),
        "dll": dll_name,
        "spoof_nvidia": bool(spoof_nvidia),
        "version": version,
        "directories": installed,
        "failed": failed,
        "installed_at": int(time.time()),
    }
    tmp = _manifest_path(appid).with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    tmp.replace(_manifest_path(appid))
    return manifest


def uninstall_game(appid: str, extra_dirs: Optional[list] = None) -> dict:
    manifest = read_install_manifest(appid) or {}
    directories = list(manifest.get("directories") or [])
    for extra in extra_dirs or []:
        if extra not in directories:
            directories.append(extra)

    removed, missed = [], []
    for raw in directories:
        directory = Path(raw)
        try:
            if uninstall_from(directory):
                removed.append(str(directory))
            else:
                missed.append(str(directory))
        except OSError as exc:
            log.error("uninstall from %s failed: %s", directory, exc)
            missed.append(str(directory))

    _manifest_path(appid).unlink(missing_ok=True)
    return {"removed": removed, "not_found": missed}
