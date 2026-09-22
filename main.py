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

logging.basicConfig(level=logging.INFO)
log = decky.logger


def _ok(**payload) -> dict:
    return dict(payload, ok=True, error="")


def _fail(message: str, **payload) -> dict:
    log.error("OptiScaler: %s", message)
    return dict(payload, ok=False, error=str(message))


class Plugin:
    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def _main(self) -> None:
        paths.ensure_dirs()
        self._deploy_launch_script()
        log.info("OptiScaler loaded; data dir %s", paths.runtime_dir())

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
            if status.get("error"):
                return _fail(status["error"], build=status)
            return _ok(build=status)
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
            return _ok(build=release.status(check_remote=False), version=meta.get("version", ""))
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

    async def install_game(self, appid: str, dll: str, spoof_nvidia: bool,
                           directories: list) -> dict:
        try:
            appid = str(appid)
            if not directories:
                return _fail("No install directories selected")
            if dll not in installer.VALID_DLLS:
                return _fail(f"Unsupported DLL name: {dll}")

            build = await asyncio.to_thread(release.ensure_build, True)
            manifest = await asyncio.to_thread(
                installer.install_game, appid, directories, dll,
                bool(spoof_nvidia), build.get("version", ""),
            )

            profiles.write_profile(appid, dll, bool(spoof_nvidia), True)
            profiles.set_game(appid, dll=dll, spoof_nvidia=bool(spoof_nvidia),
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
                                   spoof_nvidia: bool) -> dict:
        try:
            appid = str(appid)
            if dll not in installer.VALID_DLLS:
                return _fail(f"Unsupported DLL name: {dll}")

            manifest = installer.read_install_manifest(appid)
            if manifest:
                build = await asyncio.to_thread(release.ensure_build, True)
                manifest = await asyncio.to_thread(
                    installer.install_game, appid, manifest["directories"], dll,
                    bool(spoof_nvidia), build.get("version", ""),
                )
                profiles.write_profile(appid, dll, bool(spoof_nvidia), True)
                profiles.set_game(appid, dll=dll, spoof_nvidia=bool(spoof_nvidia),
                                  enabled=True, directories=manifest["directories"])
            else:
                profiles.set_game(appid, dll=dll, spoof_nvidia=bool(spoof_nvidia))

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
                    await asyncio.to_thread(
                        installer.install_game, appid, manifest["directories"],
                        settings["dll"], settings["spoof_nvidia"],
                        build.get("version", ""),
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

    async def set_defaults(self, dll: str, spoof_nvidia: bool) -> dict:
        try:
            if dll not in installer.VALID_DLLS:
                return _fail(f"Unsupported DLL name: {dll}")
            return _ok(defaults=profiles.set_defaults(dll, bool(spoof_nvidia)))
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

    async def log_frontend(self, message: str) -> None:
        log.info("OptiScaler frontend: %s", message)
