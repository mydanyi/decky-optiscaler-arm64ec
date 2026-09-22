#!/bin/sh
# Steam launch wrapper. Exports the WINEDLLOVERRIDES entry that lets
# OptiScaler's renamed DLL load instead of Wine's builtin, then execs the game.
# Written by the plugin on every load. Never fatal: the game has to start even
# with the plugin's data gone.

set -u

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || script_dir=""
DATA_DIR="${OPTISCALER_DATA_DIR:-$script_dir}"
PROFILE_DIR="$DATA_DIR/profiles"
LOG_FILE="$DATA_DIR/launch.log"

# Steam exports the app id under several names and Proton needs at least one of
# them, so detect it rather than baking it into launch options that get copied
# between games. OPTISCALER_APPID overrides, and covers older installs.
appid=""
appid_source=none
for candidate_var in OPTISCALER_APPID STEAM_COMPAT_APP_ID SteamAppId \
                     STEAM_COMPAT_DATA_PATH SteamGameId; do
    eval "value=\${$candidate_var:-}"
    [ -n "$value" ] || continue
    if [ "$candidate_var" = STEAM_COMPAT_DATA_PATH ]; then
        # .../steamapps/compatdata/<appid>
        value=${value%/}
        value=${value##*/}
    fi
    case "$value" in
        "" | *[!0-9]*) continue ;;
    esac
    appid=$value
    appid_source=$candidate_var
    break
done

log() {
    [ -d "$DATA_DIR" ] || return 0
    # Keep the log from growing without bound on a handheld.
    if [ -f "$LOG_FILE" ]; then
        size=$(wc -c < "$LOG_FILE" 2>/dev/null || echo 0)
        [ "$size" -gt 131072 ] 2>/dev/null && : > "$LOG_FILE"
    fi
    printf '%s [%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "${appid:-?}" "$*" \
        >> "$LOG_FILE" 2>/dev/null || true
}

# A plain key=value file we wrote, so parsing beats sourcing it.
profile_get() {
    [ -f "$profile" ] || return 0
    sed -n "s/^$1=//p" "$profile" 2>/dev/null | tail -n 1
}

# Remove every entry for module $2 from the WINEDLLOVERRIDES string $1. Wine
# lets one entry cover several modules ("d3d11,dxgi=n"), so a matching group is
# rewritten without our module rather than dropped. Matches the "*module" form.
strip_override() {
    _value=$1
    _module=$2
    _out=""
    set -f                      # entries may contain *, which must not glob
    IFS=";"
    for _entry in $_value; do
        [ -n "$_entry" ] || continue
        case "$_entry" in
            *=*) ;;
            *) _out="${_out:+$_out;}$_entry"; continue ;;
        esac
        _lhs=${_entry%%=*}
        _rhs=${_entry#*=}
        _keep=""
        IFS=","
        for _mod in $_lhs; do
            if [ "$_mod" = "$_module" ] || [ "$_mod" = "*$_module" ]; then
                continue
            fi
            _keep="${_keep:+$_keep,}$_mod"
        done
        IFS=";"
        [ -n "$_keep" ] || continue
        _out="${_out:+$_out;}$_keep=$_rhs"
    done
    set +f
    printf '%s' "$_out"
}

profile="$PROFILE_DIR/$appid.conf"

if [ -z "$appid" ]; then
    log "could not work out the app id, passing through"
elif [ ! -f "$profile" ]; then
    log "no profile at $profile, passing through"
else
    enabled=$(profile_get OPTISCALER_ENABLED)
    dll=$(profile_get OPTISCALER_DLL)
    spoof=$(profile_get OPTISCALER_NVIDIA_SPOOF)

    if [ "${enabled:-0}" = "1" ] && [ -n "${dll:-}" ]; then
        base=${dll%.dll}
        override="$base=n,b"

        # Ours has to win. A left-over "dxgi=b" forces Wine's builtin and stops
        # OptiScaler loading, and whoever pasted it months ago has no reason to
        # connect the two. Replacing avoids relying on which duplicate Wine picks.
        previous=${WINEDLLOVERRIDES:-}
        stripped=$(strip_override "$previous" "$base")
        WINEDLLOVERRIDES="${stripped:+$stripped;}$override"
        export WINEDLLOVERRIDES
        # Only when there was a real conflict, not when it already said this.
        if [ "$stripped" != "$previous" ] && [ "$WINEDLLOVERRIDES" != "$previous" ]; then
            log "replaced an existing $base override (was: $previous)"
        fi

        if [ "${spoof:-0}" = "1" ]; then
            # Lets the game's NVIDIA paths initialise. The ini does the rest.
            export PROTON_ENABLE_NVAPI=1
            export DXVK_NVAPI_ALLOW_OTHER_DRIVERS=1
        fi

        log "via=$appid_source dll=$dll spoof=${spoof:-0} WINEDLLOVERRIDES=${WINEDLLOVERRIDES:-}"
    else
        log "profile disabled, passing through"
    fi
fi

if [ "$#" -eq 0 ]; then
    log "nothing to execute"
    exit 0
fi

exec "$@"
