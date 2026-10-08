import {
  ButtonItem,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
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
  PluginState,
  Target,
  checkForUpdates,
  computeLaunchOptions,
  downloadBuild,
  getGameDetails,
  getState,
  installGame,
  listGames,
  logFrontend,
  refreshInstalls,
  setDefaults,
  uninstallGame,
  updateGameSettings,
} from "./api";
import { readLaunchOptions, writeLaunchOptions } from "./steam";
// translateText covers the raw English labels/errors the backend sends;
// translateMessage does the same with an explicit locale for the panel itself.
import { translateMessage, translateText } from "./i18n";
import type { Translator } from "./i18n";
import { initializeLocaleSync, useLocale } from "./useLocale";

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
  toaster.toast({ title, body: translateText(body), duration: 4000 });

function report(label: string, error: unknown): void {
  const message = error instanceof Error ? error.message : String(error);
  // The log keeps the original message; only the toast is localized.
  void logFrontend(`${label}: ${message}`);
  notify("OptiScaler", message);
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
  t,
  onCheck,
  onDownload,
  onRefreshInstalls,
}: {
  build: BuildStatus;
  patcher: PatcherStatus;
  busy: string;
  managedCount: number;
  t: Translator;
  onCheck: () => void;
  onDownload: () => void;
  onRefreshInstalls: () => void;
}) {
  const status = !build.installed
    ? t("build.notDownloaded")
    : build.update_available
      ? t("build.status.updateAvailable", {
          version: build.local_version,
          remoteVersion: build.remote_version,
        })
      : `${build.local_version}${build.remote_version ? t("build.status.upToDateSuffix") : ""}`;

  return (
    <PanelSection title={t("build.title")}>
      <PanelSectionRow>
        <Field label={t("build.version")} focusable={true} bottomSeparator="none">
          {status}
        </Field>
      </PanelSectionRow>

      {patcher.installed && (
        <PanelSectionRow>
          <Field label="OptiPatcher" focusable={true} bottomSeparator="none">
            {/* The base version stays put across rebuilds of the rolling tag,
                so the build id is what tells two releases apart. */}
            {[patcher.local_version, patcher.local_build].filter(Boolean).join(" · ")}
            {patcher.update_available && t("build.status.updateAvailableSuffix")}
          </Field>
        </PanelSectionRow>
      )}

      <PanelSectionRow>
        <ButtonItem layout="below" disabled={busy !== ""} onClick={onCheck}>
          {busy === "check" ? <Spinner width={16} height={16} /> : t("build.check")}
        </ButtonItem>
      </PanelSectionRow>

      {(!build.installed || build.update_available) && (
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={busy !== ""} onClick={onDownload}>
            {busy === "download" ? (
              <Spinner width={16} height={16} />
            ) : build.installed ? (
              t("build.downloadUpdate")
            ) : (
              t("build.download")
            )}
          </ButtonItem>
        </PanelSectionRow>
      )}

      {build.installed && managedCount > 0 && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            description={t("build.recopy.description", {
              count: managedCount,
              plural: managedCount === 1 ? "" : "s",
            })}
            disabled={busy !== ""}
            onClick={onRefreshInstalls}
          >
            {busy === "refresh" ? <Spinner width={16} height={16} /> : t("build.recopy.action")}
          </ButtonItem>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

function TargetList({
  targets,
  selected,
  t,
  onToggle,
}: {
  targets: Target[];
  selected: string[];
  t: Translator;
  onToggle: (path: string, on: boolean) => void;
}) {
  return (
    <>
      {targets.map((target) => (
        <PanelSectionRow key={target.path}>
          <ToggleField
            label={
              target.primary
                ? t("game.targets.root")
                : target.reason === "Previously installed"
                  ? t("game.targets.previous")
                  : target.reason
            }
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
  const { locale, t } = useLocale();
  const [state, setState] = useCached("state");
  const [games, setGames] = useCached("games");
  const [appid, setAppid] = useCached("appid");
  const [details, setDetails] = useCached("details");
  const [dll, setDll] = useCached("dll");
  const [spoof, setSpoof] = useCached("spoof");
  const [optipatcher, setOptipatcher] = useCached("optipatcher");
  const [selected, setSelected] = useCached("selected");
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
          ? t("toast.updateAvailable", { version: result.build.remote_version })
          : t("toast.latest"),
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
      notify("OptiScaler", t("toast.buildReady", { version: result.version }));
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
        result.failed.length
          ? t("toast.refresh.someFailed", {
              count: result.updated.length,
              plural: result.updated.length === 1 ? "" : "s",
              failed: result.failed.length,
            })
          : t("toast.refresh.success", {
              count: result.updated.length,
              plural: result.updated.length === 1 ? "" : "s",
            }),
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
        t("toast.install.success", {
          dll,
          count: result.manifest.directories.length,
          plural: result.manifest.directories.length === 1 ? "" : "s",
        }),
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
        t("toast.uninstall.success", {
          count: result.removed.length,
          plural: result.removed.length === 1 ? "" : "s",
        }),
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
      if (result.manifest) notify("OptiScaler", t("toast.dllChanged", { dll: nextDll }));
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

  const gameOptions = useMemo(
    () =>
      games.map((game) => ({
        data: game.appid,
        label: `${game.managed ? "● " : ""}${game.name}`,
      })),
    [games],
  );

  // The DLL labels arrive from the backend as English text, so they go through
  // the raw-message lookup instead of the semantic-key one.
  const dllOptions = useMemo(
    () =>
      (state?.dll_choices ?? []).map((choice: DllChoice) => ({
        data: choice.name,
        label: translateMessage(locale, choice.label),
      })),
    [state, locale],
  );

  if (loadError) {
    return (
      <PanelSection title="OptiScaler">
        <PanelSectionRow>
          <Field label={t("game.error.title")} focusable={true}>
            {translateMessage(locale, loadError)}
          </Field>
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={() => void loadState()}>
            {t("common.retry")}
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

  return (
    <>
      <BuildSection
        build={state.build}
        patcher={state.patcher}
        busy={busy}
        managedCount={state.managed_count}
        t={t}
        onCheck={runCheck}
        onDownload={runDownload}
        onRefreshInstalls={runRefresh}
      />

      <PanelSection title={t("game.title")}>
        {games.length === 0 ? (
          <PanelSectionRow>
            <Field label={t("game.none.title")} focusable={true}>
              {t("game.none.description")}
            </Field>
          </PanelSectionRow>
        ) : (
          <PanelSectionRow>
            <DropdownItem
              label={t("game.label")}
              menuLabel={t("game.choose")}
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
              <Field label={t("game.status.label")} focusable={true} bottomSeparator="none">
                {installed
                  ? t("game.status.installed", {
                      dll: details.manifest?.dll ?? "",
                      version: details.manifest?.version || "?",
                    })
                  : t("game.status.notInstalled")}
              </Field>
            </PanelSectionRow>

            <PanelSectionRow>
              <DropdownItem
                label={t("game.dll.label")}
                description={t("game.dll.description")}
                menuLabel={t("game.dll.label")}
                rgOptions={dllOptions}
                selectedOption={dll}
                onChange={(option) => void applySettings(option.data as string, spoof, optipatcher)}
              />
            </PanelSectionRow>

            <PanelSectionRow>
              <ToggleField
                label={t("game.spoof.label")}
                description={t("game.spoof.description")}
                checked={spoof}
                onChange={(on: boolean) => void applySettings(dll, on, optipatcher)}
              />
            </PanelSectionRow>

            <PanelSectionRow>
              <ToggleField
                label={t("game.optipatcher.label")}
                description={t("game.optipatcher.description")}
                checked={optipatcher}
                onChange={(on: boolean) => void applySettings(dll, spoof, on)}
              />
            </PanelSectionRow>

            <PanelSectionRow>
              <Field label={t("game.targets.title")} focusable={true} bottomSeparator="none" />
            </PanelSectionRow>

            <TargetList
              targets={details.targets}
              selected={selected}
              t={t}
              onToggle={toggleTarget}
            />

            <PanelSectionRow>
              <ButtonItem
                layout="below"
                disabled={busy !== "" || !buildReady || selected.length === 0}
                description={
                  !buildReady
                    ? t("game.install.needsBuild")
                    : t("game.install.description")
                }
                onClick={runInstall}
              >
                {busy === "install" ? (
                  <Spinner width={16} height={16} />
                ) : installed ? (
                  t("game.install.reinstall")
                ) : (
                  t("game.install.action")
                )}
              </ButtonItem>
            </PanelSectionRow>

            {installed && (
              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  disabled={busy !== ""}
                  description={t("game.uninstall.description")}
                  onClick={runUninstall}
                >
                  {busy === "uninstall" ? (
                    <Spinner width={16} height={16} />
                  ) : (
                    t("game.uninstall.action")
                  )}
                </ButtonItem>
              </PanelSectionRow>
            )}
          </>
        )}
      </PanelSection>

      <PanelSection title={t("defaults.title")}>
        <PanelSectionRow>
          <DropdownItem
            label={t("game.dll.label")}
            menuLabel={t("defaults.dll.label")}
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
            label={t("game.spoof.label")}
            checked={state.defaults.default_spoof}
            onChange={(on: boolean) =>
              void saveDefaults(state.defaults.default_dll, on, state.defaults.default_optipatcher)
            }
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label={t("game.optipatcher.label")}
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

export default definePlugin(() => {
  // One-time at load: hand Steam's confirmed language to the native panel.
  initializeLocaleSync();
  return {
    name: "OptiScaler",
    titleView: <div className={staticClasses.Title}>OptiScaler (ARM64EC)</div>,
    content: <Content />,
    icon: <FaExpandArrowsAlt />,
    // Keep the panel mounted so opening a dropdown does not tear it down.
    alwaysRender: true,
  };
});
