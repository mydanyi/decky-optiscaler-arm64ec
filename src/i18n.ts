// Simplified-Chinese i18n for the OptiScaler Decky plugin.
//
// No external dependencies: tests/i18n.test.mjs transpiles and imports this
// file directly, so it stays a plain ES module. English is the source of
// truth: every fixed string is addressed by a semantic translation key, the
// English catalogue owns the wording and is also the per-key fallback, so a
// partial Chinese catalogue never shows a key and English is never rewritten.

import en from "./locales/en";
import zhCN from "./locales/zh-CN";
// Type-only: erased when the sources are transpiled, so the runtime module graph
// stays acyclic — en.ts imports nothing, zh-CN.ts imports only this type.
import type { TranslationKey } from "./locales/en";

export type { TranslationKey };

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

// Keys are derived from the English catalogue, so a caller can only ask for
// wording that exists. The Chinese entry for a key is optional.
export type Translator = (key: TranslationKey, params?: TranslateParams) => string;

// The two independent catalogue modules. English is authoritative; Simplified
// Chinese is partial and falls back per key.
const catalogues: Record<Locale, object> = {
  en,
  "zh-CN": zhCN,
};

// Own keys only: lookups never hit Object.prototype (toString, __proto__, …).
function hasOwn(catalog: object, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(catalog, key);
}

function entry(catalog: object, key: string): string | undefined {
  if (!hasOwn(catalog, key)) return undefined;
  const value = (catalog as Record<string, string | undefined>)[key];
  return typeof value === "string" ? value : undefined;
}

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
  key: string,
  params?: TranslateParams | null,
): string {
  // A semantic key resolves through the locale's own catalogue first, then
  // through the English wording for that key. Anything that is not a key — a
  // raw path, a DLL file name, a game name or an unknown identifier — is
  // returned verbatim rather than invented.
  const template = entry(catalogues[locale], key) ?? entry(catalogues.en, key) ?? key;
  return interpolate(template, params);
}

// The Python backend sends fixed English labels and errors, never keys. Rather
// than keeping a second, hand-maintained message table, the semantic key is
// recovered from the English catalogue that already owns the wording.
function keyForMessage(rawMessage: string): TranslationKey | undefined {
  for (const key of Object.keys(en) as TranslationKey[]) {
    if (en[key] === rawMessage) return key;
  }
  return undefined;
}

export function translateMessage(
  locale: Locale,
  rawMessage: string,
  params?: TranslateParams | null,
): string {
  const key = keyForMessage(rawMessage);
  // Unknown text — an error, a path, a file name, a game name — stays as it was
  // received; only text the catalogue knows is translated.
  return key === undefined ? rawMessage : translate(locale, key, params);
}

// Small display helpers for code outside React components (notify/report).
let currentLocale: Locale = "en";

export function setCurrentLocale(locale: Locale): void {
  currentLocale = locale;
}

export function getCurrentLocale(): Locale {
  return currentLocale;
}

// Current locale, semantic key: the function components get from useLocale().
export function t(key: TranslationKey, params?: TranslateParams): string {
  return translate(currentLocale, key, params);
}

// Current locale, raw English message: the convenience wrapper for the labels
// and errors the backend sends through the toast path.
export function translateText(rawMessage: string, params?: TranslateParams): string {
  return translateMessage(currentLocale, rawMessage, params);
}
