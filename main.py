import asyncio
import logging
import shutil
import stat
from pathlib import Path

import decky

import opti_paths as paths
import opti_release as release
import opti_games as games
import opti_install as installer
import opti_profiles as profiles
import opti_control as control

logging.basicConfig(level=logging.INFO)
log = decky.logger


def _ok(**payload) -> dict:
    return dict(payload, ok=True, error="")


def _fail(message: str, **payload) -> dict:
    log.error("OptiScaler: %s", message)
    return dict(payload, ok=False, error=str(message))


# --------------------------------------------------------------------------
# in-game overlay control
# --------------------------------------------------------------------------

# The mailbox the in-game core watches lives in the game's own install tree.
# Availability is only ever proven by a fresh, real state file; a completed
# install or an INI on disk proves nothing about a running core.
CONTROL_LEAF = control.CONTROL_DIR_NAME

_NO_GAME = "No installed Steam game matches this app id."
_NO_CORE = "Start the game with the direct-control build first."
_NO_ACK = (
    "The OptiScaler core did not confirm the change. "
    "Try again while the game is running."
)
_BAD_REQUEST = "Unsupported OptiScaler control request."


def _overlay_unavailable(message: str, *, ack=None) -> dict:
    """The one shape an unavailable core reports: real fields, no invented state."""
    result = {
        "ok": False,
        "error": str(message),
        "available": False,
        "menu": False,
        "fps": False,
        "language": "en",
    }
    if ack is not None:
        result["ack"] = bool(ack)
    return result


def _overlay_values(state: dict) -> dict:
    return {
        "ok": True,
        "error": "",
        "available": True,
        "menu": state.get("menu") == "1",
        "fps": state.get("fps") == "1",
        "language": state.get("language", "en"),
    }


def _probe(appid: str):
    """Find the live mailbox for ``appid``.

    Returns ``(control_dir, state, reason)``. ``state`` is a fresh, parsed
    mailbox state; when it is ``None`` ``reason`` is a short English
    explanation. A recorded directory is trusted only while it still resolves
    inside the game's install root, and the ``OptiScaler`` leaf may not be a
    symlink - ``opti_control.resolve_control_dir`` enforces both.
    """
    game = games.game_by_appid(appid)
    if not game:
        return None, None, _NO_GAME
    try:
        root = Path(game["install_dir"]).resolve()
    except (OSError, RuntimeError):
        return None, None, _NO_GAME

    manifest = installer.read_install_manifest(appid) or {}
    for raw in manifest.get("directories") or []:
        try:
            directory = Path(str(raw)).resolve()
        except (OSError, RuntimeError):
            continue
        # A hand-edited or stale manifest must never aim the mailbox at some
        # directory outside the game we believe we are controlling.
        if directory != root and root not in directory.parents:
            continue
        try:
            control_dir = control.resolve_control_dir(directory, CONTROL_LEAF)
        except control.ControlError:
            continue
        state = control.read_state(
            control_dir / control.STATE_NAME,
            max_age=control.STATE_MAX_AGE_SECONDS,
        )
        if state is not None:
            return control_dir, state, ""
    return None, None, _NO_CORE


class Plugin:
    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def _main(self) -> None:
        paths.ensure_dirs()
        self._deploy_launch_script()
        log.info("OptiScaler loaded; data dir %s", paths.runtime_dir())
        try:
            log.info("TLS trust: %s", release.trust_source())
        except Exception as exc:  # noqa: BLE001
            log.error("could not establish TLS trust: %s", exc)

    async def _unload(self) -> None:
        log.info("OptiScaler unloaded")

    # The wrapper stays put: launch options may still name it, and a missing file
    # there stops the game launching at all.
    async def _uninstall(self) -> None:
        try:
            for manifest in paths.installs_dir().glob("*.json"):
                appid = manifest.stem
                try:
                    installer.uninstall_game(appid)
                    profiles.remove_profile(appid)
                except Exception as exc:  # noqa: BLE001
                    log.error("cleanup of %s failed: %s", appid, exc)
        except Exception as exc:  # noqa: BLE001
            log.error("uninstall cleanup failed: %s", exc)

    # Outside the plugin directory, so updating or removing the plugin never
    # invalidates the absolute path already written into Steam.
    def _deploy_launch_script(self) -> None:
        source = paths.plugin_dir() / "assets" / profiles.SCRIPT_NAME
        target = paths.launch_script()
        try:
            if not source.is_file():
                log.error("launch script missing from plugin at %s", source)
                return
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except OSError as exc:
            log.error("could not deploy launch script: %s", exc)

    # ------------------------------------------------------------------
    # the OptiScaler build
    # ------------------------------------------------------------------

    async def get_state(self) -> dict:
        try:
            status = release.status(check_remote=False)
            return _ok(
                build=status,
                patcher=release.patcher_status(check_remote=False),
                defaults=profiles.get_defaults(),
                dll_choices=[{"name": n, "label": l} for n, l in installer.DLL_CHOICES],
                launch_script=str(paths.launch_script()),
                script_ready=paths.launch_script().is_file(),
                managed_count=len(list(paths.installs_dir().glob("*.json"))),
            )
        except Exception as exc:  # noqa: BLE001
            return _fail(f"Could not read plugin state: {exc}")

    async def check_for_updates(self) -> dict:
        try:
            status = await asyncio.to_thread(release.status, True, 20.0)
            patcher = await asyncio.to_thread(release.patcher_status, True, 20.0)
            if status.get("error"):
                return _fail(status["error"], build=status, patcher=patcher)
            return _ok(build=status, patcher=patcher)
        except Exception as exc:  # noqa: BLE001
            return _fail(f"Update check failed: {exc}")

    async def download_build(self) -> dict:
        try:
            def work() -> dict:
                try:
                    meta = release.remote_release()
                except release.ReleaseError as exc:
                    # Offline: a zip in the cache or ~/Downloads still works.
                    adopted = release.adopt_cached_zip()
                    if adopted is None:
                        raise release.ReleaseError(
                            f"{exc}. No local copy found either. Put the release "
                            f"zip in ~/Downloads and try again."
                        ) from exc
                    return adopted
                return release.fetch_release(meta)

            meta = await asyncio.to_thread(work)

            # ensure_patcher keeps the cached copy, so without this an update
            # would never land. Only for users who already have it.
            if release.local_patcher() is not None:
                try:
                    await asyncio.to_thread(release.refresh_patcher)
                except Exception as exc:  # noqa: BLE001 - never fail the build update
                    log.error("OptiPatcher update failed: %s", exc)

            return _ok(build=release.status(check_remote=False),
                       patcher=release.patcher_status(check_remote=False),
                       version=meta.get("version", ""))
        except release.ReleaseError as exc:
            return _fail(str(exc))
        except Exception as exc:  # noqa: BLE001
            return _fail(f"Download failed: {exc}")

    # ------------------------------------------------------------------
    # games
    # ------------------------------------------------------------------

    async def list_games(self) -> dict:
        try:
            found = await asyncio.to_thread(games.list_games)
            managed = {p.stem for p in paths.installs_dir().glob("*.json")}
            for game in found:
                game["managed"] = game["appid"] in managed
            return _ok(games=found)
        except Exception as exc:  # noqa: BLE001
            return _fail(f"Could not list games: {exc}")

    async def get_game_details(self, appid: str) -> dict:
        try:
            appid = str(appid)
            game = await asyncio.to_thread(games.game_by_appid, appid)
            if game is None:
                return _fail("That game is no longer installed")

            targets = await asyncio.to_thread(games.find_targets, game["install_dir"])
            manifest = installer.read_install_manifest(appid)
            chosen = set((manifest or {}).get("directories") or [])

            for target in targets:
                target["installed"] = installer.is_installed(Path(target["path"]))
                target["selected"] = target["path"] in chosen if manifest else True

            # A recorded directory that is no longer detected still needs to be
            # shown, otherwise the user cannot uninstall from it.
            known = {t["path"] for t in targets}
            for extra in chosen - known:
                targets.append({
                    "path": extra,
                    "reason": "Previously installed",
                    "exe": "",
                    "primary": False,
                    "installed": installer.is_installed(Path(extra)),
                    "selected": True,
                })

            settings = profiles.get_game(appid)
            return _ok(
                game=game,
                targets=targets,
                settings=settings,
                manifest=manifest,
                installed=bool(manifest),
            )
        except Exception as exc:  # noqa: BLE001
            return _fail(f"Could not inspect that game: {exc}")

    @staticmethod
    # Fetched before anything is written into a game directory, so a failed
    # download leaves the game untouched.
    async def _patcher_source(enabled: bool):
        if not enabled:
            return None
        meta = await asyncio.to_thread(release.ensure_patcher, True)
        source = release.patcher_file()
        if not source.is_file():
            raise release.ReleaseError("OptiPatcher download did not produce a file")
        log.info("using OptiPatcher %s", meta.get("version", "?"))
        return source

    async def install_game(self, appid: str, dll: str, spoof_nvidia: bool,
                           directories: list, optipatcher: bool = False) -> dict:
        try:
            appid = str(appid)
            if not directories:
                return _fail("No install directories selected")
            if dll not in installer.VALID_DLLS:
                return _fail(f"Unsupported DLL name: {dll}")

            build = await asyncio.to_thread(release.ensure_build, True)
            patcher_src = await self._patcher_source(bool(optipatcher))
            manifest = await asyncio.to_thread(
                installer.install_game, appid, directories, dll,
                bool(spoof_nvidia), build.get("version", ""), patcher_src,
            )

            profiles.write_profile(appid, dll, bool(spoof_nvidia), True)
            profiles.set_game(appid, dll=dll, spoof_nvidia=bool(spoof_nvidia),
                              optipatcher=bool(optipatcher),
                              enabled=True, directories=manifest["directories"],
                              version=build.get("version", ""))
            return _ok(manifest=manifest, settings=profiles.get_game(appid))
        except (installer.InstallError, release.ReleaseError) as exc:
            return _fail(str(exc))
        except Exception as exc:  # noqa: BLE001
            return _fail(f"Install failed: {exc}")

    async def uninstall_game(self, appid: str) -> dict:
        try:
            appid = str(appid)
            result = await asyncio.to_thread(installer.uninstall_game, appid)
            profiles.remove_profile(appid)
            profiles.forget_game(appid)
            return _ok(**result)
        except Exception as exc:  # noqa: BLE001
            return _fail(f"Uninstall failed: {exc}")

    async def update_game_settings(self, appid: str, dll: str,
                                   spoof_nvidia: bool,
                                   optipatcher: bool = False) -> dict:
        try:
            appid = str(appid)
            if dll not in installer.VALID_DLLS:
                return _fail(f"Unsupported DLL name: {dll}")

            manifest = installer.read_install_manifest(appid)
            if manifest:
                build = await asyncio.to_thread(release.ensure_build, True)
                patcher_src = await self._patcher_source(bool(optipatcher))
                manifest = await asyncio.to_thread(
                    installer.install_game, appid, manifest["directories"], dll,
                    bool(spoof_nvidia), build.get("version", ""), patcher_src,
                )
                profiles.write_profile(appid, dll, bool(spoof_nvidia), True)
                profiles.set_game(appid, dll=dll, spoof_nvidia=bool(spoof_nvidia),
                                  optipatcher=bool(optipatcher),
                                  enabled=True, directories=manifest["directories"])
            else:
                profiles.set_game(appid, dll=dll, spoof_nvidia=bool(spoof_nvidia),
                                  optipatcher=bool(optipatcher))

            return _ok(settings=profiles.get_game(appid), manifest=manifest)
        except (installer.InstallError, release.ReleaseError) as exc:
            return _fail(str(exc))
        except Exception as exc:  # noqa: BLE001
            return _fail(f"Could not apply settings: {exc}")

    # Games keep the DLL they were installed with until this runs.
    async def refresh_installs(self) -> dict:
        try:
            build = await asyncio.to_thread(release.ensure_build, True)
            updated, failed = [], []
            for manifest_file in sorted(paths.installs_dir().glob("*.json")):
                appid = manifest_file.stem
                manifest = installer.read_install_manifest(appid)
                if not manifest:
                    continue
                settings = profiles.get_game(appid)
                try:
                    patcher_src = await self._patcher_source(settings["optipatcher"])
                    await asyncio.to_thread(
                        installer.install_game, appid, manifest["directories"],
                        settings["dll"], settings["spoof_nvidia"],
                        build.get("version", ""), patcher_src,
                    )
                    profiles.write_profile(appid, settings["dll"],
                                           settings["spoof_nvidia"], True)
                    profiles.set_game(appid, version=build.get("version", ""))
                    updated.append(appid)
                except Exception as exc:  # noqa: BLE001
                    failed.append({"appid": appid, "error": str(exc)})
            return _ok(updated=updated, failed=failed,
                       version=build.get("version", ""))
        except release.ReleaseError as exc:
            return _fail(str(exc))
        except Exception as exc:  # noqa: BLE001
            return _fail(f"Refresh failed: {exc}")

    # ------------------------------------------------------------------
    # settings and launch options
    # ------------------------------------------------------------------

    async def set_defaults(self, dll: str, spoof_nvidia: bool,
                           optipatcher: bool = False) -> dict:
        try:
            if dll not in installer.VALID_DLLS:
                return _fail(f"Unsupported DLL name: {dll}")
            return _ok(defaults=profiles.set_defaults(
                dll, bool(spoof_nvidia), bool(optipatcher)))
        except Exception as exc:  # noqa: BLE001
            return _fail(f"Could not save defaults: {exc}")

    # The string surgery lives here where it is testable. The frontend only
    # supplies the live value and writes the result back.
    async def compute_launch_options(self, appid: str, existing: str,
                                     enable: bool) -> dict:
        try:
            appid = str(appid)
            current = existing if existing is not None else ""
            if not current:
                current = await asyncio.to_thread(profiles.launch_options_from_disk, appid)
            merged = profiles.build_launch_options(current, bool(enable))
            return _ok(launch_options=merged, previous=current,
                       changed=merged != current)
        except Exception as exc:  # noqa: BLE001
            return _fail(f"Could not build launch options: {exc}")

    # ------------------------------------------------------------------
    # in-game overlay: settings panel and performance stats
    # ------------------------------------------------------------------

    # Reads are cheap and prove nothing on their own, so they never write.
    async def get_overlay_state(self, appid: str) -> dict:
        try:
            appid = str(appid)
            _control_dir, state, reason = await asyncio.to_thread(_probe, appid)
            if state is None:
                return _overlay_unavailable(reason or _NO_CORE)
            return _overlay_values(state)
        except Exception as exc:  # noqa: BLE001
            log.error("OptiScaler: overlay read failed: %s", exc)
            return _overlay_unavailable(f"Could not read the in-game overlay state: {exc}")

    # One mailbox per app, serialised, so two quick taps cannot steal each
    # other's acknowledgement.
    def _overlay_lock(self, appid: str) -> asyncio.Lock:
        locks = getattr(self, "_overlay_locks", None)
        if locks is None:
            locks = {}
            self._overlay_locks = locks
        lock = locks.get(appid)
        if lock is None:
            lock = asyncio.Lock()
            locks[appid] = lock
        return lock

    async def set_overlay_state(self, appid: str, action: str, value) -> dict:
        try:
            appid = str(appid)
            try:
                control.validate_action_value(action, value)
            except control.InvalidRequest:
                return _overlay_unavailable(_BAD_REQUEST, ack=False)

            control_dir, state, reason = await asyncio.to_thread(_probe, appid)
            if state is None:
                return _overlay_unavailable(reason or _NO_CORE, ack=False)

            async with self._overlay_lock(appid):
                return await self._send_overlay(control_dir, action, value)
        except Exception as exc:  # noqa: BLE001
            log.error("OptiScaler: overlay command failed: %s", exc)
            return _overlay_unavailable(_NO_ACK, ack=False)

    async def _send_overlay(self, control_dir, action: str, value) -> dict:
        # Default session: adopt only the launch session the core published in
        # a fresh state. Without one there is nothing to talk to.
        controller = control.Controller(control_dir, session=None)
        if controller.session is None:
            return _overlay_unavailable(_NO_CORE, ack=False)

        # The blocking poll must never stall the event loop; two seconds is the
        # protocol budget.
        acknowledged = await asyncio.to_thread(
            controller.send, action, value, timeout=2.0, interval=0.05)
        if not acknowledged:
            return _overlay_unavailable(_NO_ACK, ack=False)

        # Report what the core actually applied, not what we asked for.
        state = await asyncio.to_thread(
            control.read_state,
            control_dir / control.STATE_NAME,
            control.STATE_MAX_AGE_SECONDS,
        )
        if state is None:
            return _overlay_unavailable(_NO_ACK, ack=False)
        result = _overlay_values(state)
        result["ack"] = True
        return result

    async def log_frontend(self, message: str) -> None:
        log.info("OptiScaler frontend: %s", message)
