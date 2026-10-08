// Tests for the Simplified-Chinese i18n layer (src/i18n.ts) after the approved
// locale-file refactor:
//
//   * wording is addressed by semantic translation keys, not by the English
//     source text;
//   * English and Chinese live in two separate default-export dictionaries,
//     src/locales/en.ts and src/locales/zh-CN.ts;
//   * English is the per-key fallback when the Chinese dictionary has no entry
//     for a key;
//   * translate(locale, key, params?) is the key-based API, while
//     translateMessage(locale, rawMessage, params?) handles the English labels
//     and errors the Python backend sends; anything unknown stays verbatim.
//
// The suite loads the *real* modules (transpiled with the repo's existing
// TypeScript devDependency — no new deps, no mocks, no production test hooks).
// A relative specifier cannot be resolved from a data: URL, so the loader walks
// the TypeScript sources, rewrites their relative imports to data: URLs
// recursively and caches one module instance per file path. That cache is what
// lets a test import src/locales/zh-CN.ts and observe the very dictionary
// instance src/i18n.ts uses.
//
// Before the refactor these tests fail by assertion, not by a loader crash:
// src/i18n.ts still loads, but translate("en", "build.title") returns the key
// "build.title" instead of "OptiScaler build", translateMessage does not exist
// yet, and src/locales/*.ts are missing (asserted explicitly).
//
// Run with: node --test tests/i18n.test.mjs

import assert from "node:assert/strict";
import { existsSync, readFileSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "..");
const implFile = path.join(repoRoot, "src", "i18n.ts");
const localesDir = path.join(repoRoot, "src", "locales");

function rel(file) {
  return path.relative(repoRoot, file) || file;
}

// File path -> Promise<data: URL>. Cached so a module (and every module that
// imports it) is instantiated exactly once per test process.
const moduleCache = new Map();

// Resolve a relative specifier from a TypeScript module to a real file on disk.
// The refactored modules may write "./locales/en", "./locales/en.ts" or the
// NodeNext style "./locales/en.js"; all three must resolve to the .ts source.
function resolveSpecifier(fromFile, spec) {
  const base = path.resolve(path.dirname(fromFile), spec);
  const candidates = [
    base,
    `${base}.ts`,
    base.replace(/\.js$/, ".ts"),
    `${base}.tsx`,
    path.join(base, "index.ts"),
  ];
  for (const candidate of candidates) {
    if (existsSync(candidate) && statSync(candidate).isFile()) return candidate;
  }
  return base;
}

// Relative import specifiers, as they appear in the emitted JavaScript:
//   import en from "./locales/en";
//   export { x } from "./locales/x";
//   import "./side-effect";
const RELATIVE_IMPORT_PATTERNS = [
  /\bfrom\s*(["'])(\.[^"'\n]*)\1/g,
  /\bimport\s*(["'])(\.[^"'\n]*)\1/g,
];

async function rewriteRelativeImports(source, file) {
  let out = source;
  for (const pattern of RELATIVE_IMPORT_PATTERNS) {
    // A fresh RegExp per pattern, per invocation: these patterns are shared by
    // every recursively awaited import, and lastIndex is mutable state on the
    // instance, so a shared one would be re-entered with a stale cursor.
    const matcher = new RegExp(pattern.source, pattern.flags);
    let rewritten = "";
    let cursor = 0;
    let match;
    while ((match = matcher.exec(out)) !== null) {
      const spec = match[2];
      // Position of the opening quote of the specifier inside the match.
      const quote = match.index + match[0].length - spec.length - 2;
      const url = await moduleUrl(resolveSpecifier(file, spec));
      rewritten += out.slice(cursor, quote) + JSON.stringify(url);
      cursor = quote + spec.length + 2;
    }
    out = rewritten + out.slice(cursor);
  }
  return out;
}

function moduleUrl(file) {
  if (moduleCache.has(file)) return moduleCache.get(file);
  // The cache entry is published before any dependency is resolved, so a
  // circular import resolves to the same module instance instead of recursing.
  let resolveUrl;
  let rejectUrl;
  const urlPromise = new Promise((resolve, reject) => {
    resolveUrl = resolve;
    rejectUrl = reject;
  });
  moduleCache.set(file, urlPromise);
  (async () => {
    assert.ok(existsSync(file), `expected module ${rel(file)} to exist`);
    const ts = require("typescript");
    const source = readFileSync(file, "utf8");
    // Transpile first: only after type erasure is the emitted JavaScript free
    // of `import type` statements, so the rewriting below only ever sees real
    // runtime imports. transpileModule does no type checking, which is all a
    // behaviour test needs, and it keeps the ESNext imports.
    const { outputText } = ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.ESNext,
        target: ts.ScriptTarget.ES2020,
      },
      fileName: rel(file),
    });
    const rewritten = await rewriteRelativeImports(outputText, file);
    return "data:text/javascript;base64," + Buffer.from(rewritten, "utf8").toString("base64");
  })().then(resolveUrl, rejectUrl);
  return urlPromise;
}

let implPromise;

// Shared loader for the real translator module. The implementation is never
// mocked: every assertion runs against src/i18n.ts and the locale modules it
// imports.
function loadI18n() {
  if (!implPromise) {
    implPromise = (async () => {
      assert.ok(
        existsSync(implFile),
        `expected implementation ${rel(implFile)} to exist`,
      );
      const href = await moduleUrl(implFile);
      const mod = await import(href);

      assert.equal(typeof mod.resolveLocale, "function", "resolveLocale(options) must be exported");
      assert.equal(
        typeof mod.translate,
        "function",
        "translate(locale, key, params?) must be exported",
      );
      assert.equal(
        typeof mod.translateMessage,
        "function",
        "translateMessage(locale, rawMessage, params?) must be exported",
      );
      return mod;
    })();
  }
  return implPromise;
}

// Load one production dictionary module. The default export must be the
// dictionary object itself.
async function loadLocaleDict(name) {
  const file = path.join(localesDir, `${name}.ts`);
  assert.ok(
    existsSync(file),
    `expected locale module ${rel(file)} to exist (English and Chinese dictionaries must be separate default-export modules)`,
  );
  const href = await moduleUrl(file);
  const mod = await import(href);
  const dict = mod.default;
  assert.ok(
    dict && typeof dict === "object",
    `${rel(file)} must default-export its dictionary object`,
  );
  return dict;
}

// The pinned keys and wording for this refactor. Both columns are literals the
// tests check independently: the English wording is what the plugin ships
// today, the Chinese wording is the shipped translation (unchanged wording).
const PINNED = [
  { key: "build.title", en: "OptiScaler build", zh: "OptiScaler 构建" },
  { key: "common.retry", en: "Retry", zh: "重试" },
  {
    key: "game.status.installed",
    en: "Installed as {dll} (build {version})",
    zh: "已安装为 {dll}（构建 {version}）",
  },
  {
    key: "toast.install.success",
    en: "Installed as {dll} in {count} folder{plural}. Launch options set.",
    zh: "已在 {count} 个文件夹中安装为 {dll}，并设置启动参数。",
  },
  {
    key: "dll.dxgi",
    en: "dxgi.dll (default, most DX11/DX12 games)",
    zh: "dxgi.dll（默认，适用于大多数 DX11/DX12 游戏）",
  },
  {
    key: "errors.launchOptionsRefused",
    en: "Steam refused the launch options change",
    zh: "Steam 未能应用启动参数更改",
  },
];

// Pinned keys with no {placeholder} token.
const PINNED_PLAIN = PINNED.filter((entry) => !entry.en.includes("{"));

function pinnedByKey(key) {
  const entry = PINNED.find((candidate) => candidate.key === key);
  assert.ok(entry, `pinned fixture for ${key} is missing`);
  return entry;
}

// ---------------------------------------------------------------------------
// Dictionaries: two standalone modules, keyed by the semantic key namespace.
// ---------------------------------------------------------------------------

test("the English dictionary is a separate module mapping pinned keys to English wording", async () => {
  const en = await loadLocaleDict("en");
  for (const { key, en: english } of PINNED) {
    assert.equal(en[key], english, `en dictionary entry for ${key}`);
  }
  assert.equal(en["build.title"], "OptiScaler build");
});

test("the Chinese dictionary is a separate module mapping pinned keys to Chinese wording", async () => {
  const en = await loadLocaleDict("en");
  const zh = await loadLocaleDict("zh-CN");
  assert.notEqual(en, zh, "en and zh-CN must be two separate dictionaries");

  for (const { key, zh: chinese } of PINNED) {
    assert.equal(zh[key], chinese, `zh-CN dictionary entry for ${key}`);
  }
  assert.equal(zh["build.title"], "OptiScaler 构建");
});

test("translate('en', key) returns the English wording for every pinned key", async () => {
  const { translate } = await loadI18n();
  for (const { key, en: english } of PINNED) {
    assert.equal(translate("en", key), english, `en lookup for ${key}`);
  }
});

test("translate('zh-CN', key) returns the pinned Simplified Chinese wording", async () => {
  const { translate } = await loadI18n();
  for (const { key, zh: chinese } of PINNED_PLAIN) {
    assert.equal(translate("zh-CN", key), chinese, `zh lookup for ${key}`);
  }
});

// ---------------------------------------------------------------------------
// Interpolation, retained from the English-source API.
// ---------------------------------------------------------------------------

test("translate interpolates {dll} and {version} through the status key", async () => {
  const { translate } = await loadI18n();
  const key = "game.status.installed";

  const zh = translate("zh-CN", key, { dll: "dxgi.dll", version: "1.2.3" });
  assert.equal(zh, "已安装为 dxgi.dll（构建 1.2.3）");
  assert.ok(!zh.includes("{"), "no placeholder braces may survive in Chinese output");

  const en = translate("en", key, { dll: "dxgi.dll", version: "1.2.3" });
  assert.equal(en, "Installed as dxgi.dll (build 1.2.3)");
});

test("translate drops the English {plural} placeholder from the Chinese install toast", async () => {
  const { translate } = await loadI18n();
  const key = "toast.install.success";

  const zhTwo = translate("zh-CN", key, { dll: "dxgi.dll", count: 2, plural: "s" });
  assert.equal(zhTwo, "已在 2 个文件夹中安装为 dxgi.dll，并设置启动参数。");
  assert.ok(!zhTwo.includes("{"), "no placeholders may survive in Chinese output");
  assert.ok(!/folder/i.test(zhTwo), "the English plural stem must not leak into Chinese");

  const zhOne = translate("zh-CN", key, { dll: "dxgi.dll", count: 1, plural: "" });
  assert.equal(zhOne, "已在 1 个文件夹中安装为 dxgi.dll，并设置启动参数。");

  // English keeps the original plural behaviour.
  assert.equal(
    translate("en", key, { dll: "dxgi.dll", count: 2, plural: "s" }),
    "Installed as dxgi.dll in 2 folders. Launch options set.",
  );
  assert.equal(
    translate("en", key, { dll: "dxgi.dll", count: 1, plural: "" }),
    "Installed as dxgi.dll in 1 folder. Launch options set.",
  );
});

test("translate inserts parameter values literally, never as replacement patterns", async () => {
  const { translate } = await loadI18n();
  const key = "game.status.installed";

  assert.equal(
    translate("zh-CN", key, { dll: "$&", version: "$1" }),
    "已安装为 $&（构建 $1）",
    "a value containing $& or $1 must be inserted verbatim",
  );
  assert.equal(
    translate("en", key, { dll: "$`", version: "$'" }),
    "Installed as $` (build $')",
    "the $` and $' replacement patterns are literal data here",
  );
});

test("translate replaces a repeated placeholder every time it appears", async () => {
  const { translate } = await loadI18n();
  const key = "game.status.installed";

  // The shipped wording has no key whose template repeats a placeholder, so the
  // imported dictionaries are given a repeated-placeholder fixture for the
  // duration of this test (restored in finally). Only the template is
  // temporary; lookup, fallback and interpolation are the real implementation.
  const en = await loadLocaleDict("en");
  const zh = await loadLocaleDict("zh-CN");
  const savedEn = en[key];
  const savedZh = zh[key];
  try {
    en[key] = "{dll} and {dll} (build {version})";
    assert.equal(
      translate("en", key, { dll: "winmm.dll", version: "1.2.3" }),
      "winmm.dll and winmm.dll (build 1.2.3)",
    );

    zh[key] = "{dll} 与 {dll}（构建 {version}）";
    assert.equal(
      translate("zh-CN", key, { dll: "winmm.dll", version: "1.2.3" }),
      "winmm.dll 与 winmm.dll（构建 1.2.3）",
    );
  } finally {
    en[key] = savedEn;
    zh[key] = savedZh;
  }
});

test("a key missing from the Chinese dictionary falls back to English and still interpolates", async () => {
  const { translate } = await loadI18n();
  const key = "game.status.installed";
  const params = { dll: "dxgi.dll", version: "1.2.3" };

  // Guard: the key really is translated before the Chinese entry is removed.
  assert.equal(translate("zh-CN", key, params), "已安装为 dxgi.dll（构建 1.2.3）");

  const zh = await loadLocaleDict("zh-CN");
  assert.ok(
    Object.prototype.hasOwnProperty.call(zh, key),
    `zh-CN dictionary must really contain ${key} before the partial-dictionary test`,
  );
  const saved = zh[key];
  try {
    delete zh[key];
    assert.equal(
      translate("zh-CN", key, params),
      "Installed as dxgi.dll (build 1.2.3)",
      "an absent Chinese entry must fall back to the English wording, with its placeholders filled",
    );
    // Only the removed key is affected; the rest of the Chinese dictionary is
    // still used.
    assert.equal(translate("zh-CN", "common.retry"), "重试");
  } finally {
    zh[key] = saved;
  }

  assert.equal(
    translate("zh-CN", key, params),
    "已安装为 dxgi.dll（构建 1.2.3）",
    "the dictionary must be restored after the partial-dictionary test",
  );
});

// ---------------------------------------------------------------------------
// Key-based lookup, raw passthrough.
// ---------------------------------------------------------------------------

test("keys are the lookup path: raw English wording and unknown keys pass through", async () => {
  const { translate } = await loadI18n();

  // The English source strings are no longer the lookup keys, so they are
  // returned as they were given.
  const rawEnglish = [
    "OptiScaler build",
    "Retry",
    "Per-game setup",
    "Installed as {dll} (build {version})",
    "Steam refused the launch options change",
  ];
  for (const value of rawEnglish) {
    assert.equal(translate("zh-CN", value), value, `raw English wording: ${JSON.stringify(value)}`);
    assert.equal(translate("en", value), value, `raw English wording (en): ${JSON.stringify(value)}`);
  }

  // Keys are opaque strings: an unknown key is not invented from anywhere.
  assert.equal(translate("zh-CN", "some.unknown.key"), "some.unknown.key");
  assert.equal(translate("en", "some.unknown.key"), "some.unknown.key");
  assert.equal(translate("en", "Some untranslated error"), "Some untranslated error");
});

test("raw errors, paths, DLL filenames and game names stay untouched", async () => {
  const { translate, translateMessage } = await loadI18n();
  const untouched = [
    "dxgi.dll",
    "winmm.dll",
    "/home/deck/.steam/steam/steamapps/common/Half-Life 2/bin/win64/dxgi.dll",
    "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Portal 2\\winmm.dll",
    "Half-Life 2",
    "Portal 2",
    "EPERM: operation not permitted, open '/home/deck/.steam/registry.vdf'",
    "Unexpected token < in JSON at position 0",
  ];
  for (const value of untouched) {
    assert.equal(translate("zh-CN", value), value, `translate unchanged: ${JSON.stringify(value)}`);
    assert.equal(translate("en", value), value, `translate (en) unchanged: ${JSON.stringify(value)}`);
    assert.equal(
      translateMessage("zh-CN", value),
      value,
      `translateMessage unchanged: ${JSON.stringify(value)}`,
    );
  }
});

// ---------------------------------------------------------------------------
// translateMessage: the English labels/errors the Python backend sends.
// ---------------------------------------------------------------------------

test("translateMessage translates the pinned backend label and backend error", async () => {
  const { translateMessage } = await loadI18n();

  const dll = pinnedByKey("dll.dxgi");
  assert.equal(translateMessage("zh-CN", dll.en), dll.zh);
  assert.equal(translateMessage("en", dll.en), dll.en, "English stays the source of truth");

  const refused = pinnedByKey("errors.launchOptionsRefused");
  assert.equal(translateMessage("zh-CN", refused.en), refused.zh);
  assert.equal(translateMessage("en", refused.en), refused.en);

  // The same English text is *not* a translation key, so the key-based API
  // leaves it alone while the raw-message API translates it.
  const { translate } = await loadI18n();
  assert.equal(translate("zh-CN", refused.en), refused.en);
  assert.equal(translate("zh-CN", dll.en), dll.en);
});

test("translateMessage translates the real backend DLL labels and keeps the file name", async () => {
  const { translateMessage } = await loadI18n();
  const labels = [
    ["winmm.dll (when dxgi clashes with another mod)", "winmm.dll（dxgi 与其他 MOD 冲突时使用）", "winmm.dll"],
    ["version.dll (common alternative)", "version.dll（常见替代）", "version.dll"],
    ["dbghelp.dll (for games that reject the others)", "dbghelp.dll（游戏拒绝其他 DLL 时使用）", "dbghelp.dll"],
    ["d3d12.dll (DX12 only)", "d3d12.dll（仅 DX12）", "d3d12.dll"],
    ["wininet.dll (last resort)", "wininet.dll（最后备选）", "wininet.dll"],
    ["winhttp.dll (last resort)", "winhttp.dll（最后备选）", "winhttp.dll"],
  ];
  for (const [raw, chinese, fileName] of labels) {
    const translated = translateMessage("zh-CN", raw);
    assert.equal(translated, chinese, `zh label for ${JSON.stringify(raw)}`);
    assert.ok(translated.includes(fileName), `the DLL file name ${fileName} must be preserved`);
    assert.equal(translateMessage("en", raw), raw, `en label for ${JSON.stringify(raw)}`);
  }
});

test("translateMessage translates the overlay backend errors", async () => {
  const { translateMessage } = await loadI18n();
  const errors = [
    ["No installed Steam game matches this app id.", "没有已安装的游戏与此 App ID 匹配。"],
    [
      "The OptiScaler core did not confirm the change. Try again while the game is running.",
      "OptiScaler 核心未确认此更改。请在游戏运行时重试。",
    ],
    ["Unsupported OptiScaler control request.", "不支持的 OptiScaler 控制请求。"],
  ];
  for (const [raw, chinese] of errors) {
    assert.equal(translateMessage("zh-CN", raw), chinese, `zh error for ${JSON.stringify(raw)}`);
    assert.equal(translateMessage("en", raw), raw, `en error for ${JSON.stringify(raw)}`);
  }
});

test("unknown backend text is never replaced by a dictionary key", async () => {
  const { translateMessage } = await loadI18n();
  const unknown = [
    "Some unknown backend text",
    "Game {name} could not be installed (code 42).",
    "Installed as dxgi.dll (build 1.2.3)",
    "winmm.dll failed to load from C:\\Games\\Foo\\winmm.dll",
    "OPTISCALER_DEBUG=1",
  ];
  for (const value of unknown) {
    assert.equal(
      translateMessage("zh-CN", value),
      value,
      `unknown backend text must stay verbatim: ${JSON.stringify(value)}`,
    );
    assert.equal(translateMessage("en", value), value, `unknown backend text (en): ${JSON.stringify(value)}`);
  }
});

// ---------------------------------------------------------------------------
// Locale selection: unchanged by the refactor, retained case for case.
// ---------------------------------------------------------------------------

test("resolveLocale: Steam Simplified Chinese identifiers resolve to zh-CN", async () => {
  const { resolveLocale } = await loadI18n();
  const simplified = [
    "schinese",
    "SteamChina_SChinese",
    "SCHINESE",
    "steamchina_schinese",
    "zh",
    "zh-CN",
    "zh_cn",
    "ZH-CN",
    "zh-Hans",
    "zh_hans",
    "zh-SG",
    "zh-Hans-CN",
  ];
  for (const value of simplified) {
    assert.equal(resolveLocale({ steamLanguage: value }), "zh-CN", `steamLanguage=${value}`);
  }
});

test("resolveLocale: zh-Hant-CN is Traditional Chinese, never Simplified", async () => {
  const { resolveLocale } = await loadI18n();
  assert.equal(resolveLocale({ steamLanguage: "zh-Hant-CN" }), "en");
  assert.equal(
    resolveLocale({ steamLanguage: "zh-Hant-CN", browserLanguages: ["zh-CN"] }),
    "en",
    "browser Chinese must not rescue a Traditional Steam language",
  );
});

test("resolveLocale: a non-empty Steam language wins over Decky and browser Chinese", async () => {
  const { resolveLocale } = await loadI18n();
  const steamLanguages = ["english", "tchinese", "zh-TW", "zh-Hant", "japanese", "klingon"];
  for (const value of steamLanguages) {
    const locale = resolveLocale({
      steamLanguage: value,
      deckyLocales: ["zh-CN"],
      browserLanguages: ["zh-CN"],
    });
    assert.equal(locale, "en", `steamLanguage=${value} must not fall back to Chinese`);
  }
});

test("resolveLocale: blank or missing Steam language falls back to Decky locales", async () => {
  const { resolveLocale } = await loadI18n();
  assert.equal(
    resolveLocale({ steamLanguage: "", deckyLocales: ["zh-CN"], browserLanguages: ["en-US"] }),
    "zh-CN",
  );
  assert.equal(
    resolveLocale({ steamLanguage: "   ", deckyLocales: ["schinese"], browserLanguages: ["en-US"] }),
    "zh-CN",
    "whitespace-only Steam language counts as unavailable",
  );
  assert.equal(resolveLocale({ steamLanguage: undefined, deckyLocales: ["zh-CN"] }), "zh-CN");
});

test("resolveLocale: only the first Decky entry matters, browser is the last resort", async () => {
  const { resolveLocale } = await loadI18n();
  // Decky's first entry is English -> en, even though a later entry and the
  // browser are Chinese.
  assert.equal(
    resolveLocale({ deckyLocales: ["en-US", "zh-CN"], browserLanguages: ["zh-CN"] }),
    "en",
  );
  // Decky's first entry is a non-Chinese language -> en; browser is not consulted.
  assert.equal(resolveLocale({ deckyLocales: ["fr"], browserLanguages: ["zh-CN"] }), "en");
  // No Decky entries at all -> browser's first entry decides.
  assert.equal(resolveLocale({ deckyLocales: [], browserLanguages: ["schinese"] }), "zh-CN");
  assert.equal(resolveLocale({ deckyLocales: [], browserLanguages: ["zh-Hans"] }), "zh-CN");
});

test("resolveLocale: defaults to en and only ever returns en or zh-CN", async () => {
  const { resolveLocale } = await loadI18n();
  const cases = [
    {},
    { steamLanguage: undefined, deckyLocales: [], browserLanguages: [] },
    { steamLanguage: "" },
    { deckyLocales: [] },
    { browserLanguages: [] },
    { steamLanguage: "english" },
    { steamLanguage: "schinese" },
    { steamLanguage: "fr", deckyLocales: ["de"], browserLanguages: ["es"] },
  ];
  for (const options of cases) {
    const locale = resolveLocale(options);
    assert.ok(
      locale === "en" || locale === "zh-CN",
      `unexpected locale ${JSON.stringify(locale)} for ${JSON.stringify(options)}`,
    );
  }
  assert.equal(resolveLocale({}), "en");
  assert.equal(
    resolveLocale({ steamLanguage: undefined, deckyLocales: [], browserLanguages: [] }),
    "en",
  );
});
