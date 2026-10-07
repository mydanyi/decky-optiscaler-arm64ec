# OptiScaler

Decky plugin that installs the ARM64EC
[OptiScaler/SGSR2 build](https://github.com/justradical/Sloptiscaler/releases)
into Steam games, for Adreno handhelds running Windows games under Proton
Experimental (ARM64).

## What it does

- Downloads whatever the newest release holds, checked against the sha256 that
  GitHub publishes, and caches it. A zip already in `~/Downloads` is used when
  there is no network.
- Installs the DLL into the game root and into every directory holding a
  64-bit executable, because Wine resolves it per directory.
- Per-game loader DLL name, NVIDIA spoofing and OptiPatcher, each off or
  defaulted until you change it.
- Sets the game's launch options to run a wrapper that exports
  `WINEDLLOVERRIDES`, so nothing has to be edited by hand.
- Backs up any file it replaces and restores it on uninstall.

## Using it

Open the Decky menu, pick **OptiScaler**, download the build once, then choose
a game and install. Turn on DLSS, FSR or XeSS in the game's own graphics
settings. OptiScaler replaces whichever one the game asks for, so native or TAA
leaves it nothing to hook. `Shift+F2` opens its overlay.

## Localization

The plugin follows Steam's own language. With **Simplified Chinese** selected
(`schinese`) the panel, its labels and its status and toast messages are shown
in Chinese; every other Steam language, including Traditional Chinese, keeps
the original English wording. The same preference is stored as a single
`ui-language` token that the launch wrapper passes to compatible native cores,
so their in-game panel can follow it too. This change only translates this
plugin's own interface: translating the native overlay's own strings and
bundling a CJK font are separate core companion changes and are not included
here. Not every language is translated - only Simplified Chinese has a
translation, and everything else falls back to the original English.

## Building

```bash
make build      # pnpm install and rollup
make package    # writes build/OptiScaler.zip
make install    # copies into ~/homebrew/plugins and restarts Decky, needs sudo
```

## Layout

Cached builds and install manifests live in `~/homebrew/data/OptiScaler`, and
settings in `~/homebrew/settings/OptiScaler`. The launch wrapper and the
per-game profiles live in `~/.local/share/optiscaler`, outside `~/homebrew`,
because Steam records the wrapper by absolute path and it has to outlive the
plugin.

## Licence

BSD-3-Clause. OptiScaler is downloaded at runtime rather than bundled. It is
GPL-3.0 and SGSR2 is BSD-3-Clause, and their licences ship inside the release
zip.
