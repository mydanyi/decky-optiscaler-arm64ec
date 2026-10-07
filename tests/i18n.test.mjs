// Tests for the Simplified Chinese i18n layer (src/i18n.ts).
//
// This suite loads the *real* src/i18n.ts (transpiled with the repo's existing
// TypeScript devDependency, no new deps) and asserts the Chinese behaviour the
// plugin ships. The implementation file is never imported at module scope, so
// a broken implementation fails one clear assertion per test instead of
// crashing the whole runner.
//
// Run with: node --test tests/i18n.test.mjs

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "..");
const implFile = path.join(repoRoot, "src", "i18n.ts");
const relImpl = path.relative(repoRoot, implFile);

let modulePromise;

// Shared loader: assert the implementation exists, transpile the single file
// in memory, then import it from a data: URL. transpileModule does no type
// checking, which is all we need for behaviour tests. The module is never
// mocked — tests always exercise the real resolveLocale/translate/translations.
function loadI18n() {
  if (!modulePromise) {
    modulePromise = (async () => {
      assert.ok(
        existsSync(implFile),
        `expected implementation ${relImpl} to exist`,
      );

      const ts = require("typescript");
      const source = readFileSync(implFile, "utf8");
      const { outputText } = ts.transpileModule(source, {
        compilerOptions: {
          module: ts.ModuleKind.ESNext,
          target: ts.ScriptTarget.ES2020,
        },
        fileName: relImpl,
      });

      const href =
        "data:text/javascript;base64," + Buffer.from(outputText, "utf8").toString("base64");
      const mod = await import(href);

      assert.equal(typeof mod.resolveLocale, "function", "resolveLocale(options) must be exported");
      assert.equal(
        typeof mod.translate,
        "function",
        "translate(locale, englishSource, params?) must be exported",
      );
      assert.ok(
        mod.translations && typeof mod.translations === "object",
        "translations map must be exported",
      );

      return mod;
    })();
  }
  return modulePromise;
}

// The fixed wording the plugin ships. English source -> Simplified Chinese.
// Entries may contain {placeholder} tokens.
const FIXED = [
  ["Per-game setup", "按游戏配置"],
  ["Defaults for new games", "新游戏默认设置"],
  ["Loader DLL", "加载用 DLL"],
  ["Install into this game", "安装到此游戏"],
  ["NVIDIA spoofing", "伪装为 NVIDIA 显卡"],
  ["Load OptiPatcher", "加载 OptiPatcher"],
  ["Game root", "游戏根目录"],
  ["Previously installed", "先前的安装目录"],
  ["dxgi.dll (default, most DX11/DX12 games)", "dxgi.dll（默认，适用于大多数 DX11/DX12 游戏）"],
  ["Installed as {dll} (build {version})", "已安装为 {dll}（构建 {version}）"],
  [
    "Installed as {dll} in {count} folder{plural}. Launch options set.",
    "已在 {count} 个文件夹中安装为 {dll}，并设置启动参数。",
  ],
  ["Not installed", "未安装"],
  ["Steam refused the launch options change", "Steam 未能应用启动参数更改"],
];

// Strings with no interpolatable tokens: translate(locale, source) must return
// the fixed Chinese verbatim.
const PLAIN = FIXED.filter(([en]) => !en.includes("{"));

test("translations map holds every fixed English source with its Chinese wording", async () => {
  const { translations } = await loadI18n();
  for (const [en, zh] of FIXED) {
    assert.equal(translations[en], zh, `translations[${JSON.stringify(en)}]`);
  }
});

test("translate('en', ...) keeps the English source verbatim", async () => {
  const { translate } = await loadI18n();
  for (const [en] of FIXED) {
    assert.equal(translate("en", en), en, `en source ${JSON.stringify(en)}`);
  }
  assert.equal(translate("en", "Some untranslated error"), "Some untranslated error");
});

test("translate('zh-CN', ...) returns Simplified Chinese for known UI strings", async () => {
  const { translate } = await loadI18n();
  for (const [en, zh] of PLAIN) {
    assert.equal(translate("zh-CN", en), zh, `zh for ${JSON.stringify(en)}`);
  }
});

test("translate interpolates {dll} and {version} in the status line", async () => {
  const { translate } = await loadI18n();
  const src = "Installed as {dll} (build {version})";

  const zh = translate("zh-CN", src, { dll: "dxgi.dll", version: "1.2.3" });
  assert.equal(zh, "已安装为 dxgi.dll（构建 1.2.3）");
  assert.ok(!zh.includes("{"), "no placeholder braces may survive in Chinese output");

  const en = translate("en", src, { dll: "dxgi.dll", version: "1.2.3" });
  assert.equal(en, "Installed as dxgi.dll (build 1.2.3)");
});

test("translate drops the English {plural} placeholder from the Chinese install toast", async () => {
  const { translate } = await loadI18n();
  const src = "Installed as {dll} in {count} folder{plural}. Launch options set.";

  const zhTwo = translate("zh-CN", src, { dll: "dxgi.dll", count: 2, plural: "s" });
  assert.equal(zhTwo, "已在 2 个文件夹中安装为 dxgi.dll，并设置启动参数。");
  assert.ok(!zhTwo.includes("{"), "no placeholders may survive in Chinese output");
  assert.ok(!/folder/i.test(zhTwo), "the English plural stem must not leak into Chinese");

  const zhOne = translate("zh-CN", src, { dll: "dxgi.dll", count: 1, plural: "" });
  assert.equal(zhOne, "已在 1 个文件夹中安装为 dxgi.dll，并设置启动参数。");

  // English keeps the original plural behaviour.
  assert.equal(
    translate("en", src, { dll: "dxgi.dll", count: 2, plural: "s" }),
    "Installed as dxgi.dll in 2 folders. Launch options set.",
  );
  assert.equal(
    translate("en", src, { dll: "dxgi.dll", count: 1, plural: "" }),
    "Installed as dxgi.dll in 1 folder. Launch options set.",
  );
});

test("translate replaces a placeholder every time it appears", async () => {
  const { translate } = await loadI18n();
  assert.equal(
    translate("zh-CN", "{dll} and also {dll}", { dll: "winmm.dll" }),
    "winmm.dll and also winmm.dll",
  );
  assert.equal(translate("en", "{name}/{name}", { name: "ab" }), "ab/ab");
});

test("translate falls back to the original text for unknown sources and raw errors", async () => {
  const { translate } = await loadI18n();
  const rawError = "EPERM: operation not permitted, open '/home/deck/.steam/registry.vdf'";
  assert.equal(translate("zh-CN", rawError), rawError);
  assert.equal(translate("en", rawError), rawError);
  assert.equal(translate("zh-CN", "Unexpected token < in JSON at position 0"), "Unexpected token < in JSON at position 0");
});

test("translate leaves paths, DLL filenames and game names untouched", async () => {
  const { translate } = await loadI18n();
  const untouched = [
    "dxgi.dll",
    "winmm.dll",
    "/home/deck/.steam/steam/steamapps/common/Half-Life 2/bin/win64/dxgi.dll",
    "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Portal 2\\winmm.dll",
    "Half-Life 2",
    "Portal 2",
  ];
  for (const value of untouched) {
    assert.equal(translate("zh-CN", value), value, `unchanged: ${JSON.stringify(value)}`);
  }
});

test("real DLL option labels are translated but keep the DLL file name", async () => {
  const { translate } = await loadI18n();
  assert.equal(
    translate("zh-CN", "dxgi.dll (default, most DX11/DX12 games)"),
    "dxgi.dll（默认，适用于大多数 DX11/DX12 游戏）",
  );
  // The remaining DLL labels are translated too, but the file name inside them
  // must always survive translation.
  const winmm = translate("zh-CN", "winmm.dll (when dxgi clashes with another mod)");
  assert.ok(winmm.includes("winmm.dll"), "the DLL file name must be preserved");
});

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
