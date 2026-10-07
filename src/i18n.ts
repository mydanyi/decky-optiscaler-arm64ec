// Simplified-Chinese i18n for the OptiScaler Decky plugin.
//
// No external dependencies: tests/i18n.test.mjs transpiles and imports this
// file directly, so it stays a plain ES module. English is the source of
// truth — untranslated strings fall back to the original text and English is
// never rewritten.

export type Locale = "en" | "zh-CN";

export interface LocaleOptions {
  /** Steam's current UI language, e.g. "schinese" or "english". */
  steamLanguage?: string | null;
  /** Decky's requested locales (window.LocalizationManager.m_rgLocalesToUse). */
  deckyLocales?: ReadonlyArray<string | null | undefined> | null;
  /** navigator.languages / navigator.language. */
  browserLanguages?: ReadonlyArray<string | null | undefined> | null;
}

export type TranslateParams = Record<string, string | number>;

export type Translator = (englishSource: string, params?: TranslateParams) => string;

// English source -> Simplified Chinese. Only the fixed wording lives here;
// dynamic strings keep their {placeholders} and are filled by translate().
export const translations: Record<string, string> = {
  // Build section.
  "OptiScaler build": "OptiScaler 构建",
  Version: "版本",
  "Not downloaded yet": "尚未下载",
  "{version}, update available ({remoteVersion})": "{version}，有可用更新（{remoteVersion}）",
  ", up to date": "，已是最新版本",
  ", update available": "，有可用更新",
  "Check for updates": "检查更新",
  "Download update": "下载更新",
  "Download OptiScaler": "下载 OptiScaler",
  "Re-copy this build into the {count} game{plural} you have set up.":
    "将此构建重新复制到你已配置的 {count} 个游戏中。",
  "Update installed games": "更新已安装到游戏中的构建",

  // Per-game setup.
  "Per-game setup": "按游戏配置",
  "Something went wrong": "出错了",
  Retry: "重试",
  "No games found": "未找到游戏",
  "No installed Steam games were detected.": "未检测到已安装的 Steam 游戏。",
  Game: "游戏",
  "Choose a game": "选择一个游戏",
  Status: "状态",
  "Installed as {dll} (build {version})": "已安装为 {dll}（构建 {version}）",
  "Not installed": "未安装",
  "Loader DLL": "加载用 DLL",
  "The filename OptiScaler is installed as. Change it if another mod already uses this name.":
    "OptiScaler 安装时使用的文件名。如果该名称已被其他 MOD 占用，可在此更改。",
  "NVIDIA spoofing": "伪装为 NVIDIA 显卡",
  "Report an NVIDIA GPU so games will offer DLSS for OptiScaler to intercept.":
    "向游戏报告为 NVIDIA 显卡，让游戏提供 DLSS 选项，再由 OptiScaler 接管。",
  "Load OptiPatcher": "加载 OptiPatcher",
  "Adds OptiPatcher as an OptiScaler plugin. It patches games that gate DLSS behind their own checks, so OptiScaler has something to intercept.":
    "作为 OptiScaler 插件加载 OptiPatcher，用于修补那些用自身检查限制 DLSS 的游戏，让 OptiScaler 能够接管。",
  "Install locations": "安装位置",
  "Game root": "游戏根目录",
  "Previously installed": "先前的安装目录",
  "Download the OptiScaler build first.": "请先下载 OptiScaler 构建。",
  "Copies the DLL and config, then sets the launch options for you.":
    "复制 DLL 和配置，并为你设置启动参数。",
  Reinstall: "重新安装",
  "Install into this game": "安装到此游戏",
  "Restores any files that were replaced and clears the launch options.":
    "还原被替换的文件并清除启动参数。",
  "Remove from this game": "从此游戏移除",
  "Defaults for new games": "新游戏默认设置",
  "Default loader DLL": "默认加载用 DLL",

  // In-game direct controls. These command the running core only; they never
  // imply that frame generation or upscaling was switched on.
  "In-game controls": "游戏内控制",
  "Open OptiScaler settings panel": "打开 OptiScaler 设置面板",
  "Close OptiScaler settings panel": "关闭 OptiScaler 设置面板",
  "Show OptiScaler performance stats": "显示 OptiScaler 性能统计",
  "Hide OptiScaler performance stats": "隐藏 OptiScaler 性能统计",
  "Start the game with the direct-control build first.": "请先用直接控制版构建启动游戏。",
  "OptiScaler settings panel opened.": "OptiScaler 设置面板已打开。",
  "OptiScaler settings panel closed.": "OptiScaler 设置面板已关闭。",
  "OptiScaler performance stats shown.": "已显示 OptiScaler 性能统计。",
  "OptiScaler performance stats hidden.": "已隐藏 OptiScaler 性能统计。",

  // Overlay backend errors (main.py) shown through the same toast path.
  "No installed Steam game matches this app id.": "没有已安装的游戏与此 App ID 匹配。",
  "The OptiScaler core did not confirm the change. Try again while the game is running.":
    "OptiScaler 核心未确认此更改。请在游戏运行时重试。",
  "Unsupported OptiScaler control request.": "不支持的 OptiScaler 控制请求。",

  // Toasts / dynamic templates.
  "Installed as {dll} in {count} folder{plural}. Launch options set.":
    "已在 {count} 个文件夹中安装为 {dll}，并设置启动参数。",
  "Removed from {count} folder{plural}.": "已从 {count} 个文件夹中移除。",
  "Now loading as {dll}.": "现在以 {dll} 加载。",
  "Build {version} ready.": "构建 {version} 已就绪。",
  "Update available: {version}": "有可用更新：{version}",
  "You are on the latest build.": "当前已是最新构建。",
  "Updated {count} game{plural}, {failed} failed.": "已更新 {count} 个游戏，{failed} 个失败。",
  "Updated {count} game{plural}.": "已更新 {count} 个游戏。",
  "Steam refused the launch options change": "Steam 未能应用启动参数更改",

  // Real loader DLL labels (py_modules/opti_install.py DLL_CHOICES). The file
  // name inside every label is preserved.
  "dxgi.dll (default, most DX11/DX12 games)": "dxgi.dll（默认，适用于大多数 DX11/DX12 游戏）",
  "winmm.dll (when dxgi clashes with another mod)": "winmm.dll（dxgi 与其他 MOD 冲突时使用）",
  "version.dll (common alternative)": "version.dll（常见替代）",
  "dbghelp.dll (for games that reject the others)": "dbghelp.dll（游戏拒绝其他 DLL 时使用）",
  "d3d12.dll (DX12 only)": "d3d12.dll（仅 DX12）",
  "wininet.dll (last resort)": "wininet.dll（最后备选）",
  "winhttp.dll (last resort)": "winhttp.dll（最后备选）",
};

function normalizeTag(raw: unknown): string {
  return String(raw ?? "")
    .trim()
    .toLowerCase()
    .replace(/_/g, "-");
}

// Simplified-Chinese identifiers seen from Steam, Decky and browsers. A
// Traditional tag such as zh-Hant or a traditional region (tw/hk/mo) must
// never match.
function isSimplifiedChinese(raw: unknown): boolean {
  const tag = normalizeTag(raw);
  if (!tag) return false;
  if (tag === "schinese" || tag === "steamchina-schinese") return true;
  if (tag === "zh") return true; // bare "zh" only
  if (!tag.startsWith("zh-")) return false;

  const parts = tag.split("-").slice(1);
  if (parts.includes("hant")) return false;
  if (parts.includes("hans")) return true;
  // Only explicitly Simplified regions count; an unknown zh-XX variant is not
  // assumed Simplified.
  return parts.includes("cn") || parts.includes("sg");
}

function firstMeaningful(
  list: ReadonlyArray<string | null | undefined> | null | undefined,
): string {
  if (!Array.isArray(list)) return "";
  for (const entry of list) {
    if (normalizeTag(entry)) return String(entry);
  }
  return "";
}

export function resolveLocale(options: LocaleOptions = {}): Locale {
  // A real Steam language is authoritative: it decides Chinese vs English and
  // is never overridden by Decky or the browser, even for a Traditional tag.
  if (normalizeTag(options.steamLanguage)) {
    return isSimplifiedChinese(options.steamLanguage) ? "zh-CN" : "en";
  }

  // Steam is unavailable: Decky's first locale decides, then the browser's.
  const decky = firstMeaningful(options.deckyLocales);
  if (decky) return isSimplifiedChinese(decky) ? "zh-CN" : "en";

  const browser = firstMeaningful(options.browserLanguages);
  if (browser) return isSimplifiedChinese(browser) ? "zh-CN" : "en";

  return "en";
}

function interpolate(template: string, params?: TranslateParams | null): string {
  if (!params) return template;
  // A replacer callback keeps parameter values literal, so a value containing
  // "$&" or "$1" is never treated as a replacement pattern. The global regex
  // replaces every occurrence of a repeated placeholder.
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : match,
  );
}

export function translate(
  locale: Locale,
  englishSource: string,
  params?: TranslateParams | null,
): string {
  // Own keys only: lookups never hit Object.prototype (toString, __proto__, …).
  const template =
    locale !== "en" && Object.prototype.hasOwnProperty.call(translations, englishSource)
      ? translations[englishSource]
      : englishSource;
  return interpolate(template, params);
}

// Small display helpers for code outside React components (notify/report).
let currentLocale: Locale = "en";

export function setCurrentLocale(locale: Locale): void {
  currentLocale = locale;
}

export function getCurrentLocale(): Locale {
  return currentLocale;
}

export function t(englishSource: string, params?: TranslateParams): string {
  return translate(currentLocale, englishSource, params);
}
