// Authoritative English wording for the plugin's fixed UI text.
//
// Keys are stable semantic identifiers grouped by surface: build, game,
// defaults, controls, common, toast, dll, overlay and errors. Dynamic values
// keep their {placeholders}; proper names (OptiScaler, OptiPatcher, Steam,
// NVIDIA, DLSS), file names and technical values are literal data and are never
// translated.
//
// This module is the root of the locale graph: it imports nothing. The Chinese
// catalogue imports only the TranslationKey type from here, so the dependency
// graph stays acyclic.

const en = {
  // Build section.
  "build.title": "OptiScaler build",
  "build.version": "Version",
  "build.notDownloaded": "Not downloaded yet",
  "build.status.updateAvailable": "{version}, update available ({remoteVersion})",
  "build.status.upToDateSuffix": ", up to date",
  "build.status.updateAvailableSuffix": ", update available",
  "build.check": "Check for updates",
  "build.downloadUpdate": "Download update",
  "build.download": "Download OptiScaler",
  "build.recopy.description": "Re-copy this build into the {count} game{plural} you have set up.",
  "build.recopy.action": "Update installed games",

  // Per-game setup.
  "game.title": "Per-game setup",
  "game.error.title": "Something went wrong",
  "game.none.title": "No games found",
  "game.none.description": "No installed Steam games were detected.",
  "game.label": "Game",
  "game.choose": "Choose a game",
  "game.status.label": "Status",
  "game.status.installed": "Installed as {dll} (build {version})",
  "game.status.notInstalled": "Not installed",
  "game.dll.label": "Loader DLL",
  "game.dll.description":
    "The filename OptiScaler is installed as. Change it if another mod already uses this name.",
  "game.spoof.label": "NVIDIA spoofing",
  "game.spoof.description":
    "Report an NVIDIA GPU so games will offer DLSS for OptiScaler to intercept.",
  "game.optipatcher.label": "Load OptiPatcher",
  "game.optipatcher.description":
    "Adds OptiPatcher as an OptiScaler plugin. It patches games that gate DLSS behind their own checks, so OptiScaler has something to intercept.",
  "game.targets.title": "Install locations",
  "game.targets.root": "Game root",
  "game.targets.previous": "Previously installed",
  "game.install.needsBuild": "Download the OptiScaler build first.",
  "game.install.description": "Copies the DLL and config, then sets the launch options for you.",
  "game.install.reinstall": "Reinstall",
  "game.install.action": "Install into this game",
  "game.uninstall.description":
    "Restores any files that were replaced and clears the launch options.",
  "game.uninstall.action": "Remove from this game",

  // Defaults for new games.
  "defaults.title": "Defaults for new games",
  "defaults.dll.label": "Default loader DLL",

  // In-game direct controls. These command the running core only; they never
  // imply that frame generation or upscaling was switched on. The controls
  // themselves live in the plugin build that ships them, and the wording stays
  // here so it never drifts out of the catalogue.
  "controls.title": "In-game controls",
  "controls.openPanel": "Open OptiScaler settings panel",
  "controls.closePanel": "Close OptiScaler settings panel",
  "controls.showStats": "Show OptiScaler performance stats",
  "controls.hideStats": "Hide OptiScaler performance stats",
  "controls.needsBuild": "Start the game with the direct-control build first.",

  // Shared wording.
  "common.retry": "Retry",

  // Toasts. The static in-game-control toasts first, then the dynamic ones.
  "toast.controls.panelOpened": "OptiScaler settings panel opened.",
  "toast.controls.panelClosed": "OptiScaler settings panel closed.",
  "toast.controls.statsShown": "OptiScaler performance stats shown.",
  "toast.controls.statsHidden": "OptiScaler performance stats hidden.",
  "toast.install.success":
    "Installed as {dll} in {count} folder{plural}. Launch options set.",
  "toast.uninstall.success": "Removed from {count} folder{plural}.",
  "toast.dllChanged": "Now loading as {dll}.",
  "toast.buildReady": "Build {version} ready.",
  "toast.updateAvailable": "Update available: {version}",
  "toast.latest": "You are on the latest build.",
  "toast.refresh.someFailed": "Updated {count} game{plural}, {failed} failed.",
  "toast.refresh.success": "Updated {count} game{plural}.",

  // Real loader DLL labels (py_modules/opti_install.py DLL_CHOICES). The labels
  // come from the backend as English text and are looked up by wording; the file
  // name inside every label is preserved.
  "dll.dxgi": "dxgi.dll (default, most DX11/DX12 games)",
  "dll.winmm": "winmm.dll (when dxgi clashes with another mod)",
  "dll.version": "version.dll (common alternative)",
  "dll.dbghelp": "dbghelp.dll (for games that reject the others)",
  "dll.d3d12": "d3d12.dll (DX12 only)",
  "dll.wininet": "wininet.dll (last resort)",
  "dll.winhttp": "winhttp.dll (last resort)",

  // Overlay backend errors (main.py) shown through the same toast path.
  "overlay.error.noGame": "No installed Steam game matches this app id.",
  "overlay.error.notConfirmed":
    "The OptiScaler core did not confirm the change. Try again while the game is running.",
  "overlay.error.unsupported": "Unsupported OptiScaler control request.",

  // Errors the frontend itself raises and shows raw through the toast path.
  "errors.launchOptionsRefused": "Steam refused the launch options change",
};

// Every semantic key the plugin can ask for, derived from the English catalogue.
export type TranslationKey = keyof typeof en;

export default en;
