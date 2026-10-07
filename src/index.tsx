import {
  ButtonItem,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  Router,
  Spinner,
  ToggleField,
  staticClasses,
} from "@decky/ui";
import { definePlugin, toaster, useQuickAccessVisible } from "@decky/api";
import { useCallback, useEffect, useMemo, useState } from "react";
import { FaExpandArrowsAlt } from "react-icons/fa";

import {
  BuildStatus,
  DllChoice,
  PatcherStatus,
  Game,
  GameDetails,
  OverlayState,
  PluginState,
  Target,
  checkForUpdates,
  computeLaunchOptions,
  downloadBuild,
  getGameDetails,
  getOverlayState,
  getState,
  installGame,
  listGames,
  logFrontend,
  refreshInstalls,
  setDefaults,
  setOverlayState,
  uninstallGame,
  updateGameSettings,
} from "./api";
import { readLaunchOptions, writeLaunchOptions } from "./steam";

// Decky tears the panel down whenever a menu takes the foreground, so state
// held in the component does not survive opening a dropdown.
interface PanelCache {
  state: PluginState | null;
  games: Game[];
  appid: string;
  details: GameDetails | null;
  dll: string;
  spoof: boolean;
  optipatcher: boolean;
  selected: string[];
  lastGameScan: number;
  // The core's last reported visibility state for the selected game. Null
  // means "not read yet", never "off".
  overlay: OverlayState | null;
}

const cache: PanelCache = {
  state: null,
  games: [],
  appid: "",
  details: null,
  dll: "dxgi.dll",
  spoof: false,
  optipatcher: false,
  selected: [],
  lastGameScan: 0,
  overlay: null,
};

// Read __optiscaler.mounts in the Steam console: a climbing count means the
// panel is still being torn down.
let mountCount = 0;

const RESCAN_AFTER_MS = 30_000;

function useCached<K extends keyof PanelCache>(key: K) {
  const [value, setValue] = useState<PanelCache[K]>(cache[key]);
  const update = useCallback(
    (next: PanelCache[K]) => {
      cache[key] = next;
      setValue(next);
    },
    [key],
  );
  return [value, update] as const;
}

const notify = (title: string, body: string) =>
  toaster.toast({ title, body, duration: 4000 });

function report(label: string, error: unknown): void {
  const message = error instanceof Error ? error.message : String(error);
  void logFrontend(`${label}: ${message}`);
  notify("OptiScaler", message);
}

// The direct controls act on the game's own overlay, so the panel steps out of
// the way once a command is on its way. If the API is missing the panel simply
// stays open.
function closeQuickAccessMenu(): void {
  try {
    Router.CloseSideMenus();
  } catch {
    /* the quick access menu may already be closing */
  }
}

// Merge rules live in the backend where they are tested. This only supplies
// the live value and writes the result back.
async function syncLaunchOptions(appid: string, enable: boolean): Promise<void> {
  const numericAppid = Number(appid);
  const live = await readLaunchOptions(numericAppid);
  const result = await computeLaunchOptions(appid, live ?? "", enable);
  if (!result.ok) throw new Error(result.error);
  if (result.changed && !writeLaunchOptions(numericAppid, result.launch_options)) {
    throw new Error("Steam refused the launch options change");
  }
}

function BuildSection({
  build,
  patcher,
  busy,
  managedCount,
  onCheck,
  onDownload,
  onRefreshInstalls,
}: {
  build: BuildStatus;
  patcher: PatcherStatus;
  busy: string;
  managedCount: number;
  onCheck: () => void;
  onDownload: () => void;
  onRefreshInstalls: () => void;
}) {
  const status = !build.installed
    ? "Not downloaded yet"
    : build.update_available
      ? `${build.local_version}, update available (${build.remote_version})`
      : `${build.local_version}${build.remote_version ? ", up to date" : ""}`;

  return (
    <PanelSection title="OptiScaler build">
      <PanelSectionRow>
        <Field label="Version" focusable={true} bottomSeparator="none">
          {status}
        </Field>
      </PanelSectionRow>

      {patcher.installed && (
        <PanelSectionRow>
          <Field label="OptiPatcher" focusable={true} bottomSeparator="none">
            {/* The base version stays put across rebuilds of the rolling tag,
                so the build id is what tells two releases apart. */}
            {[patcher.local_version, patcher.local_build].filter(Boolean).join(" · ")}
            {patcher.update_available && ", update available"}
          </Field>
        </PanelSectionRow>
      )}

      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy !== ""} onClick={onCheck}>
          {busy === "check" ? <Spinner width={16} height={16} /> : "Check for updates"}
        </ButtonItem>
      </PanelSectionRow>

      {(!build.installed || build.update_available) && (
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy !== ""} onClick={onDownload}>
            {busy === "download" ? (
              <Spinner width={16} height={16} />
            ) : build.installed ? (
              "Download update"
            ) : (
              "Download OptiScaler"
            )}
          </ButtonItem>
        </PanelSectionRow>
      )}

      {build.installed && managedCount > 0 && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            description={`Re-copy this build into the ${managedCount} game${
              managedCount === 1 ? "" : "s"
            } you have set up.`}
            disabled={busy !== ""}
            onClick={onRefreshInstalls}
          >
            {busy === "refresh" ? <Spinner width={16} height={16} /> : "Update installed games"}
          </ButtonItem>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

function TargetList({
  targets,
  selected,
  onToggle,
}: {
  targets: Target[];
  selected: string[];
  onToggle: (path: string, on: boolean) => void;
}) {
  return (
    <>
      {targets.map((target) => (
        <PanelSectionRow key={target.path}>
          <ToggleField
            label={target.primary ? "Game root" : target.reason}
            description={target.exe || target.path}
            checked={selected.includes(target.path)}
            onChange={(on: boolean) => onToggle(target.path, on)}
          />
        </PanelSectionRow>
      ))}
    </>
  );
}

function Content() {
  const visible = useQuickAccessVisible();
  const [state, setState] = useCached("state");
  const [games, setGames] = useCached("games");
  const [appid, setAppid] = useCached("appid");
  const [details, setDetails] = useCached("details");
  const [dll, setDll] = useCached("dll");
  const [spoof, setSpoof] = useCached("spoof");
  const [optipatcher, setOptipatcher] = useCached("optipatcher");
  const [selected, setSelected] = useCached("selected");
  const [overlay, setOverlay] = useCached("overlay");
  const [busy, setBusy] = useState<string>("");
  const [loadError, setLoadError] = useState<string>("");

  const loadState = useCallback(async () => {
    try {
      const next = await getState();
      if (next.ok) {
        setState(next);
        setLoadError("");
      } else {
        setLoadError(next.error);
      }
    } catch (error) {
      setLoadError(String(error));
    }
  }, [setState]);

  const loadGames = useCallback(async () => {
    try {
      const result = await listGames();
      if (!result.ok) {
        setLoadError(result.error);
        return;
      }
      cache.lastGameScan = Date.now();
      setGames(result.games);

      // Keep whatever the user already picked. Only choose for them when the
      // current selection has gone away.
      const current = cache.appid;
      if (current && result.games.some((game) => game.appid === current)) return;
      const running = String((window as any).SteamUIStore?.RunningApps?.[0]?.appid ?? "");
      const pick =
        (running && result.games.find((game) => game.appid === running)) ||
        result.games.find((game) => game.managed) ||
        result.games[0];
      setAppid(pick?.appid ?? "");
    } catch (error) {
      setLoadError(String(error));
    }
  }, [setGames, setAppid]);

  const applyDetails = useCallback(
    (result: GameDetails) => {
      setDetails(result);
      setDll(result.settings.dll);
      setSpoof(result.settings.spoof_nvidia);
      setOptipatcher(result.settings.optipatcher);
      setSelected(result.targets.filter((t) => t.selected).map((t) => t.path));
    },
    [setDetails, setDll, setSpoof, setOptipatcher, setSelected],
  );

  const loadDetails = useCallback(
    async (id: string) => {
      if (!id) {
        setDetails(null);
        return;
      }
      setBusy("details");
      try {
        const result = await getGameDetails(id);
        if (!result.ok) {
          setDetails(null);
          notify("OptiScaler", result.error);
          return;
        }
        applyDetails(result);
      } catch (error) {
        report("get_game_details", error);
      } finally {
        setBusy("");
      }
    },
    [applyDetails, setDetails],
  );

  // The buttons must reflect the core's real, freshly-read state, so this only
  // runs when the panel opens or the selected game changes - never on a timer.
  const loadOverlay = useCallback(
    async (id: string) => {
      if (!id) {
        setOverlay(null);
        return;
      }
      try {
        setOverlay(await getOverlayState(id));
      } catch (error) {
        setOverlay(null);
        report("get_overlay_state", error);
      }
    },
    [setOverlay],
  );

  useEffect(() => {
    mountCount += 1;
    (window as any).__optiscaler = { mounts: mountCount, cache };
  }, []);

  // First mount only: anything already cached is rendered as-is.
  useEffect(() => {
    if (!cache.state) void loadState();
    if (cache.games.length === 0) void loadGames();
  }, [loadState, loadGames]);

  // Re-scan when the panel is reopened, but not on the rapid hide/show a
  // dropdown causes. That churn is what made the panel appear to reload.
  useEffect(() => {
    if (!visible) return;
    if (Date.now() - cache.lastGameScan < RESCAN_AFTER_MS) return;
    void loadGames();
  }, [visible, loadGames]);

  // Read the real core state whenever the panel opens or the game changes.
  useEffect(() => {
    if (!visible) return;
    void loadOverlay(appid);
  }, [visible, appid, loadOverlay]);

  // Only fetch when the selection actually changed.
  useEffect(() => {
    if (!appid) return;
    if (cache.details?.game?.appid === appid) return;
    void loadDetails(appid);
  }, [appid, loadDetails]);

  const runCheck = async () => {
    setBusy("check");
    try {
      const result = await checkForUpdates();
      if (!result.ok) {
        notify("OptiScaler", result.error);
        return;
      }
      if (cache.state) setState({ ...cache.state, build: result.build, patcher: result.patcher });
      notify(
        "OptiScaler",
        result.build.update_available
          ? `Update available: ${result.build.remote_version}`
          : "You are on the latest build.",
      );
    } catch (error) {
      report("check_for_updates", error);
    } finally {
      setBusy("");
    }
  };

  const runDownload = async () => {
    setBusy("download");
    try {
      const result = await downloadBuild();
      if (!result.ok) {
        notify("OptiScaler", result.error);
        return;
      }
      if (cache.state) setState({ ...cache.state, build: result.build, patcher: result.patcher });
      notify("OptiScaler", `Build ${result.version} ready.`);
    } catch (error) {
      report("download_build", error);
    } finally {
      setBusy("");
    }
  };

  const runRefresh = async () => {
    setBusy("refresh");
    try {
      const result = await refreshInstalls();
      if (!result.ok) {
        notify("OptiScaler", result.error);
        return;
      }
      notify(
        "OptiScaler",
        `Updated ${result.updated.length} game${result.updated.length === 1 ? "" : "s"}` +
          (result.failed.length ? `, ${result.failed.length} failed.` : "."),
      );
      await loadDetails(appid);
    } catch (error) {
      report("refresh_installs", error);
    } finally {
      setBusy("");
    }
  };

  const runInstall = async () => {
    if (!appid || selected.length === 0) return;
    setBusy("install");
    try {
      const result = await installGame(appid, dll, spoof, selected, optipatcher);
      if (!result.ok) {
        notify("OptiScaler", result.error);
        return;
      }
      await syncLaunchOptions(appid, true);
      notify(
        "OptiScaler",
        `Installed as ${dll} in ${result.manifest.directories.length} folder${
          result.manifest.directories.length === 1 ? "" : "s"
        }. Launch options set.`,
      );
      await Promise.all([loadDetails(appid), loadGames(), loadState()]);
    } catch (error) {
      report("install_game", error);
    } finally {
      setBusy("");
    }
  };

  const runUninstall = async () => {
    if (!appid) return;
    setBusy("uninstall");
    try {
      // Clear the launch options first: if that fails we have not yet removed
      // the DLL they refer to.
      await syncLaunchOptions(appid, false);
      const result = await uninstallGame(appid);
      if (!result.ok) {
        notify("OptiScaler", result.error);
        return;
      }
      notify(
        "OptiScaler",
        `Removed from ${result.removed.length} folder${result.removed.length === 1 ? "" : "s"}.`,
      );
      await Promise.all([loadDetails(appid), loadGames(), loadState()]);
    } catch (error) {
      report("uninstall_game", error);
    } finally {
      setBusy("");
    }
  };

  const applySettings = async (nextDll: string, nextSpoof: boolean, nextPatcher: boolean) => {
    setDll(nextDll);
    setSpoof(nextSpoof);
    setOptipatcher(nextPatcher);
    if (!appid) return;
    setBusy("settings");
    try {
      const result = await updateGameSettings(appid, nextDll, nextSpoof, nextPatcher);
      if (!result.ok) {
        notify("OptiScaler", result.error);
        return;
      }
      // Patch the cached details in place rather than re-fetching, so the
      // panel does not visibly reset every time a dropdown is used.
      if (cache.details) {
        setDetails({
          ...cache.details,
          settings: result.settings,
          manifest: result.manifest,
          installed: Boolean(result.manifest),
        });
      }
      if (result.manifest) notify("OptiScaler", `Now loading as ${nextDll}.`);
    } catch (error) {
      report("update_game_settings", error);
    } finally {
      setBusy("");
    }
  };

  const saveDefaults = async (nextDll: string, nextSpoof: boolean, nextPatcher: boolean) => {
    try {
      const result = await setDefaults(nextDll, nextSpoof, nextPatcher);
      if (result.ok && cache.state) setState({ ...cache.state, defaults: result.defaults });
    } catch (error) {
      report("set_defaults", error);
    }
  };

  const toggleTarget = (path: string, on: boolean) => {
    const next = selected.filter((entry) => entry !== path);
    if (on) next.push(path);
    setSelected(next);
  };

  // Re-read the actual state, then ask for the explicit opposite. The core has
  // to acknowledge it, so the button never fakes a checked toggle.
  const toggleOverlay = async (action: "menu" | "fps") => {
    if (!appid) return;
    setBusy("overlay");
    try {
      const current = await getOverlayState(appid);
      setOverlay(current);
      if (!current.available) {
        notify(
          "OptiScaler",
          current.error || "Start the game with the direct-control build first.",
        );
        return;
      }
      const next = action === "menu" ? !current.menu : !current.fps;
      const pending = setOverlayState(appid, action, next);
      closeQuickAccessMenu();
      const result = await pending;
      setOverlay(result);
      if (!result.ack) {
        notify(
          "OptiScaler",
          result.error ||
            "The OptiScaler core did not confirm the change. Try again while the game is running.",
        );
        return;
      }
      notify(
        "OptiScaler",
        action === "menu"
          ? result.menu
            ? "OptiScaler settings panel opened."
            : "OptiScaler settings panel closed."
          : result.fps
            ? "OptiScaler performance stats shown."
            : "OptiScaler performance stats hidden.",
      );
    } catch (error) {
      report("set_overlay_state", error);
    } finally {
      setBusy("");
    }
  };

  const gameOptions = useMemo(
    () =>
      games.map((game) => ({
        data: game.appid,
        label: `${game.managed ? "● " : ""}${game.name}`,
      })),
    [games],
  );

  const dllOptions = useMemo(
    () =>
      (state?.dll_choices ?? []).map((choice: DllChoice) => ({
        data: choice.name,
        label: choice.label,
      })),
    [state],
  );

  if (loadError) {
    return (
      <PanelSection title="OptiScaler">
        <PanelSectionRow>
          <Field label="Something went wrong" focusable={true}>
            {loadError}
          </Field>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => void loadState()}>
            Retry
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    );
  }

  if (!state) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <Spinner />
        </PanelSectionRow>
      </PanelSection>
    );
  }

  const installed = Boolean(details?.installed);
  const buildReady = state.build.installed;
  const overlayAvailable = Boolean(overlay?.available);

  return (
    <>
      <BuildSection
        build={state.build}
        patcher={state.patcher}
        busy={busy}
        managedCount={state.managed_count}
        onCheck={runCheck}
        onDownload={runDownload}
        onRefreshInstalls={runRefresh}
      />

      {details && installed && (
        <PanelSection title="In-game controls">
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              disabled={busy !== "" || !overlayAvailable}
              description={
                overlayAvailable
                  ? undefined
                  : "Start the game with the direct-control build first."
              }
              onClick={() => void toggleOverlay("menu")}
            >
              {overlay?.menu
                ? "Close OptiScaler settings panel"
                : "Open OptiScaler settings panel"}
            </ButtonItem>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              disabled={busy !== "" || !overlayAvailable}
              description={
                overlayAvailable
                  ? undefined
                  : "Start the game with the direct-control build first."
              }
              onClick={() => void toggleOverlay("fps")}
            >
              {overlay?.fps
                ? "Hide OptiScaler performance stats"
                : "Show OptiScaler performance stats"}
            </ButtonItem>
          </PanelSectionRow>
        </PanelSection>
      )}

      <PanelSection title="Per-game setup">
        {games.length === 0 ? (
          <PanelSectionRow>
            <Field label="No games found" focusable={true}>
              No installed Steam games were detected.
            </Field>
          </PanelSectionRow>
        ) : (
          <PanelSectionRow>
            <DropdownItem
              label="Game"
              menuLabel="Choose a game"
              rgOptions={gameOptions}
              selectedOption={appid}
              onChange={(option) => setAppid(option.data as string)}
            />
          </PanelSectionRow>
        )}

        {busy === "details" && !details && (
          <PanelSectionRow>
            <Spinner width={16} height={16} />
          </PanelSectionRow>
        )}

        {details && (
          <>
            <PanelSectionRow>
              <Field label="Status" focusable={true} bottomSeparator="none">
                {installed
                  ? `Installed as ${details.manifest?.dll} (build ${
                      details.manifest?.version || "?"
                    })`
                  : "Not installed"}
              </Field>
            </PanelSectionRow>

            <PanelSectionRow>
              <DropdownItem
                label="Loader DLL"
                description="The filename OptiScaler is installed as. Change it if another mod already uses this name."
                menuLabel="Loader DLL"
                rgOptions={dllOptions}
                selectedOption={dll}
                onChange={(option) => void applySettings(option.data as string, spoof, optipatcher)}
              />
            </PanelSectionRow>

            <PanelSectionRow>
              <ToggleField
                label="NVIDIA spoofing"
                description="Report an NVIDIA GPU so games will offer DLSS for OptiScaler to intercept."
                checked={spoof}
                onChange={(on: boolean) => void applySettings(dll, on, optipatcher)}
              />
            </PanelSectionRow>

            <PanelSectionRow>
              <ToggleField
                label="Load OptiPatcher"
                description="Adds OptiPatcher as an OptiScaler plugin. It patches games that gate DLSS behind their own checks, so OptiScaler has something to intercept."
                checked={optipatcher}
                onChange={(on: boolean) => void applySettings(dll, spoof, on)}
              />
            </PanelSectionRow>

            <PanelSectionRow>
              <Field label="Install locations" focusable={true} bottomSeparator="none" />
            </PanelSectionRow>

            <TargetList targets={details.targets} selected={selected} onToggle={toggleTarget} />

            <PanelSectionRow>
              <ButtonItem
                layout="below"
                disabled={busy !== "" || !buildReady || selected.length === 0}
                description={
                  !buildReady
                    ? "Download the OptiScaler build first."
                    : "Copies the DLL and config, then sets the launch options for you."
                }
                onClick={runInstall}
              >
                {busy === "install" ? (
                  <Spinner width={16} height={16} />
                ) : installed ? (
                  "Reinstall"
                ) : (
                  "Install into this game"
                )}
              </ButtonItem>
            </PanelSectionRow>

            {installed && (
              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  disabled={busy !== ""}
                  description="Restores any files that were replaced and clears the launch options."
                  onClick={runUninstall}
                >
                  {busy === "uninstall" ? (
                    <Spinner width={16} height={16} />
                  ) : (
                    "Remove from this game"
                  )}
                </ButtonItem>
              </PanelSectionRow>
            )}
          </>
        )}
      </PanelSection>

      <PanelSection title="Defaults for new games">
        <PanelSectionRow>
          <DropdownItem
            label="Loader DLL"
            menuLabel="Default loader DLL"
            rgOptions={dllOptions}
            selectedOption={state.defaults.default_dll}
            onChange={(option) =>
              void saveDefaults(
                option.data as string,
                state.defaults.default_spoof,
                state.defaults.default_optipatcher,
              )
            }
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="NVIDIA spoofing"
            checked={state.defaults.default_spoof}
            onChange={(on: boolean) =>
              void saveDefaults(state.defaults.default_dll, on, state.defaults.default_optipatcher)
            }
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="Load OptiPatcher"
            checked={state.defaults.default_optipatcher}
            onChange={(on: boolean) =>
              void saveDefaults(state.defaults.default_dll, state.defaults.default_spoof, on)
            }
          />
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

export default definePlugin(() => ({
  name: "OptiScaler",
  titleView: <div className={staticClasses.Title}>OptiScaler (ARM64EC)</div>,
  content: <Content />,
  icon: <FaExpandArrowsAlt />,
  // Keep the panel mounted so opening a dropdown does not tear it down.
  alwaysRender: true,
}));
