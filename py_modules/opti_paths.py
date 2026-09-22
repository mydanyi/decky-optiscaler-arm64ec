import os
from pathlib import Path

PLUGIN_NAME = "OptiScaler"

try:
    import decky
except ImportError:  # running outside Decky (tests, manual invocation)
    decky = None


def _decky_attr(name: str, default) -> str:
    value = getattr(decky, name, None) if decky is not None else None
    return value or str(default)


def user_home() -> Path:
    # Never root's home, even when Decky runs the plugin as root.
    override = os.environ.get("OPTISCALER_HOME")
    if override:
        return Path(override)
    return Path(_decky_attr("DECKY_USER_HOME", _decky_attr("HOME", Path.home())))


def plugin_dir() -> Path:
    return Path(_decky_attr("DECKY_PLUGIN_DIR", Path(__file__).resolve().parent.parent))


def runtime_dir() -> Path:
    if os.environ.get("OPTISCALER_HOME"):
        return user_home() / "homebrew" / "data" / PLUGIN_NAME
    return Path(_decky_attr("DECKY_PLUGIN_RUNTIME_DIR",
                            user_home() / "homebrew" / "data" / PLUGIN_NAME))


def settings_dir() -> Path:
    if os.environ.get("OPTISCALER_HOME"):
        return user_home() / "homebrew" / "settings" / PLUGIN_NAME
    return Path(_decky_attr("DECKY_PLUGIN_SETTINGS_DIR",
                            user_home() / "homebrew" / "settings" / PLUGIN_NAME))


def cache_dir() -> Path:
    return runtime_dir() / "cache"


def build_dir() -> Path:
    return cache_dir() / "current"


def data_home() -> Path:
    # Outside ~/homebrew: Steam records the wrapper by absolute path, so it has
    # to outlive the plugin. Gone, a game still naming it stops launching.
    override = os.environ.get("OPTISCALER_HOME")
    if override:
        return Path(override) / ".local" / "share" / "optiscaler"
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg and os.path.isabs(xdg) else user_home() / ".local" / "share"
    return base / "optiscaler"


def profiles_dir() -> Path:
    return data_home() / "profiles"


def installs_dir() -> Path:
    return runtime_dir() / "installs"


def launch_script() -> Path:
    return data_home() / "optiscaler-launch.sh"


def games_config() -> Path:
    return settings_dir() / "games.json"


def defaults_config() -> Path:
    return settings_dir() / "defaults.json"


def steam_root() -> Path:
    # First root that actually exists. The ~/.steam symlink is the usual one.
    home = user_home()
    candidates = [
        home / ".steam" / "steam",
        home / ".local" / "share" / "Steam",
        home / ".steam" / "root",
        home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
    ]
    for candidate in candidates:
        if (candidate / "steamapps").is_dir():
            return candidate
    return candidates[0]


def ensure_dirs() -> None:
    for directory in (runtime_dir(), settings_dir(), cache_dir(),
                      data_home(), profiles_dir(), installs_dir()):
        directory.mkdir(parents=True, exist_ok=True)
