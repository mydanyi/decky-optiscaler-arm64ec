import { useCallback, useEffect, useState } from "react";
import { useQuickAccessVisible } from "@decky/api";

import { setUiLocale } from "./api";
import { getCurrentLocale, resolveLocale, setCurrentLocale, translate } from "./i18n";
import type { Locale, LocaleOptions, Translator } from "./i18n";

// Once Steam has confirmed a language, a later panel opening must not let the
// browser's Chinese override a confirmed English during the async window.
let steamSettled = false;

function readDeckyLocales(): string[] {
  try {
    const manager = (window as any)?.LocalizationManager;
    const locales = manager?.m_rgLocalesToUse;
    if (Array.isArray(locales)) {
      return locales.filter((value): value is string => typeof value === "string");
    }
  } catch {
    /* Decky not available */
  }
  return [];
}

function readBrowserLanguages(): string[] {
  try {
    const nav = typeof navigator === "undefined" ? undefined : navigator;
    if (nav && Array.isArray(nav.languages) && nav.languages.length > 0) {
      return Array.from(nav.languages);
    }
    if (nav?.language) return [nav.language];
  } catch {
    /* ignore */
  }
  return [];
}

// SteamClient.Settings.GetCurrentLanguage() may be sync or promise-like. Any
// failure resolves to null so the environment fallback stands.
function readSteamLanguage(): Promise<string | null> {
  try {
    const settings = (window as any)?.SteamClient?.Settings;
    if (settings && typeof settings.GetCurrentLanguage === "function") {
      return Promise.resolve(settings.GetCurrentLanguage()).then(
        (value: unknown) => (typeof value === "string" ? value : null),
        () => null,
      );
    }
  } catch {
    /* ignore */
  }
  return Promise.resolve(null);
}

export interface LocaleTools {
  locale: Locale;
  t: Translator;
}

// The native in-game panel reads the same preference from disk. A failure here
// only means the panel keeps its previous language, so it is never surfaced.
function publishUiLocale(locale: Locale): void {
  try {
    void setUiLocale(locale).catch(() => undefined);
  } catch {
    /* api not ready yet */
  }
}

let localeSyncInitialised = false;

// Called once from the plugin's initializer. Steam's confirmed language is
// what the native panel must match; an unknown language stays English, so a
// browser or Decky Chinese never forces Chinese onto a Steam player who is
// not using it.
export function initializeLocaleSync(): void {
  if (localeSyncInitialised) return;
  localeSyncInitialised = true;
  void readSteamLanguage().then((steamLanguage) => {
    const confirmed = typeof steamLanguage === "string" && steamLanguage.trim().length > 0;
    publishUiLocale(confirmed ? resolveLocale({ steamLanguage }) : "en");
  });
}

export function useLocale(): LocaleTools {
  const visible = useQuickAccessVisible();
  const [locale, setLocaleState] = useState<Locale>(() => getCurrentLocale());

  const apply = useCallback((next: Locale) => {
    setCurrentLocale(next);
    setLocaleState(next);
  }, []);

  // Re-detect each time the panel opens. The effect already only re-runs when
  // `visible` changes, so it is once-per-open without a separate guard; a guard
  // would wrongly skip detection after a React StrictMode cleanup re-runs it.
  useEffect(() => {
    if (!visible) return;

    let cancelled = false;
    const options: LocaleOptions = {
      deckyLocales: readDeckyLocales(),
      browserLanguages: readBrowserLanguages(),
    };

    // Render the environment guess immediately, but only until Steam has
    // confirmed a language once.
    if (!steamSettled) {
      apply(resolveLocale(options));
    }

    void readSteamLanguage().then((steamLanguage) => {
      // The component may have unmounted while we waited.
      if (cancelled) return;
      // Only a non-empty Steam language counts as confirmed. A failed or null
      // read keeps a previously confirmed locale instead of falling back to the
      // browser's Chinese; the environment fallback runs only when Steam was
      // never confirmed.
      if (typeof steamLanguage === "string" && steamLanguage.trim().length > 0) {
        steamSettled = true;
        const confirmed = resolveLocale({ ...options, steamLanguage });
        apply(confirmed);
        // Steam's language is authoritative, so re-publish it to the native
        // panel whenever the panel is reopened with a confirmed value.
        publishUiLocale(confirmed);
      } else if (!steamSettled) {
        apply(resolveLocale({ ...options, steamLanguage }));
      }
    });

    return () => {
      cancelled = true;
    };
  }, [visible, apply]);

  // The panel asks for wording by semantic key; the hook binds that key to the
  // locale it detected.
  const t = useCallback<Translator>(
    (key, params) => translate(locale, key, params),
    [locale],
  );

  return { locale, t };
}
