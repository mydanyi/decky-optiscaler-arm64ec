import { callable } from "@decky/api";

export interface Result {
  ok: boolean;
  error: string;
}

export interface BuildStatus {
  installed: boolean;
  local_version: string;
  local_sha256: string;
  asset_name: string;
  source: string;
  release_url: string;
  update_available: boolean;
  remote_version: string;
  remote_published?: string;
  error: string;
}

export interface DllChoice {
  name: string;
  label: string;
}

export interface Defaults {
  default_dll: string;
  default_spoof: boolean;
  default_optipatcher: boolean;
}

export interface PatcherStatus {
  installed: boolean;
  local_version: string;
  local_build: string;
  update_available: boolean;
  remote_version: string;
  remote_build: string;
  release_url: string;
  error: string;
}

export interface PluginState extends Result {
  build: BuildStatus;
  patcher: PatcherStatus;
  defaults: Defaults;
  dll_choices: DllChoice[];
  launch_script: string;
  script_ready: boolean;
  managed_count: number;
}

export interface Game {
  appid: string;
  name: string;
  install_dir: string;
  library: string;
  size_on_disk: number;
  managed: boolean;
}

export interface Target {
  path: string;
  reason: string;
  exe: string;
  primary: boolean;
  installed: boolean;
  selected: boolean;
}

export interface GameSettings {
  appid: string;
  dll: string;
  spoof_nvidia: boolean;
  optipatcher: boolean;
  enabled: boolean;
  directories: string[];
  version: string;
}

export interface InstallManifest {
  appid: string;
  dll: string;
  spoof_nvidia: boolean;
  optipatcher: boolean;
  version: string;
  directories: string[];
  failed: { path: string; error: string }[];
}

export interface GameDetails extends Result {
  game: Game;
  targets: Target[];
  settings: GameSettings;
  manifest: InstallManifest | null;
  installed: boolean;
}

export const getState = callable<[], PluginState>("get_state");
export const checkForUpdates =
  callable<[], Result & { build: BuildStatus; patcher: PatcherStatus }>("check_for_updates");
export const downloadBuild =
  callable<[], Result & { build: BuildStatus; patcher: PatcherStatus; version: string }>(
    "download_build",
  );
export const listGames = callable<[], Result & { games: Game[] }>("list_games");
export const getGameDetails = callable<[appid: string], GameDetails>("get_game_details");

export const installGame = callable<
  [appid: string, dll: string, spoofNvidia: boolean, directories: string[], optipatcher: boolean],
  Result & { manifest: InstallManifest; settings: GameSettings }
>("install_game");

export const uninstallGame = callable<
  [appid: string],
  Result & { removed: string[]; not_found: string[] }
>("uninstall_game");

export const updateGameSettings = callable<
  [appid: string, dll: string, spoofNvidia: boolean, optipatcher: boolean],
  Result & { settings: GameSettings; manifest: InstallManifest | null }
>("update_game_settings");

export const refreshInstalls = callable<
  [],
  Result & { updated: string[]; failed: { appid: string; error: string }[]; version: string }
>("refresh_installs");

export const setDefaults = callable<
  [dll: string, spoofNvidia: boolean, optipatcher: boolean],
  Result & { defaults: Defaults }
>("set_defaults");

export const computeLaunchOptions = callable<
  [appid: string, existing: string, enable: boolean],
  Result & { launch_options: string; previous: string; changed: boolean }
>("compute_launch_options");

export const logFrontend = callable<[message: string], void>("log_frontend");

// --------------------------------------------------------------------------
// In-game overlay control (settings panel visibility / performance stats).
// The backend reports only real, freshly-read core values; `available` is
// false until a direct-control core is actually running for the game.
// --------------------------------------------------------------------------

export type OverlayAction = "menu" | "fps" | "language";
export type OverlayValue = boolean | "en" | "zh-CN";

export interface OverlayState extends Result {
  available: boolean;
  menu: boolean;
  fps: boolean;
  language: "en" | "zh-CN";
  /** Present on set_overlay_state only: the core confirmed the change. */
  ack?: boolean;
}

export const getOverlayState = callable<[appid: string], OverlayState>("get_overlay_state");

export const setOverlayState = callable<
  [appid: string, action: OverlayAction, value: OverlayValue],
  OverlayState
>("set_overlay_state");
