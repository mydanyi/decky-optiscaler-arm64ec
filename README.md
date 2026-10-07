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

## In-game controls

With a game set up, the panel shows an **In-game controls** section between the
build section and **Per-game setup**. It holds two buttons that act on the
game's own overlay: open or close the OptiScaler settings panel, and show or
hide the OptiScaler performance stats. Each tap re-reads the core's live state,
asks for the opposite, and closes the quick access menu while the command is on
its way; the label only changes once the core has confirmed the new value, so it
never reports a change the game did not make.

There are no controller mappings. These two buttons are the only input the
plugin adds, and no keyboard, timer or Steam Input binding is involved.

The buttons need a core running inside the game that speaks companion protocol
version 1 - the plugin writes `overlay.request` in the game's `OptiScaler`
directory and waits for the matching `overlay.state`. Until such a core is
running, both buttons stay disabled and say the game has to be started with the
direct-control build first. A core for other OptiScaler builds is not included
here, and nothing in this plugin promises that a stock Sloptiscaler or
OptiScaler release already provides it.

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
