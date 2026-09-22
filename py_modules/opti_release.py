import functools
import hashlib
import json
import logging
import os
import re
import shutil
import ssl
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

import opti_paths as paths

log = logging.getLogger("optiscaler.release")

# Tags here are not version numbers and an asset can be replaced in place, so
# the cache is keyed on the asset's sha256.
REPO = "justradical/Sloptiscaler"
RELEASE_URL = f"https://github.com/{REPO}/releases/latest"
API_ROOT = "https://api.github.com"
USER_AGENT = "OptiScaler-decky/1.0 (+https://github.com/justradical/Sloptiscaler)"

# Upstream names it like OptiScaler-SGSR2-arm64ec-727b8dd.zip, but a release
# that names its zip anything else is still the build we want.
ASSET_PATTERN = re.compile(r"arm64ec.*\.zip$", re.IGNORECASE)
_HASH_IN_NAME = re.compile(r"-([0-9a-f]{7,40})\.zip$", re.IGNORECASE)

# Only these come out of the zip, so a crafted path cannot escape the build dir.
WANTED_FILES = ("OptiScaler.dll", "OptiScaler.ini", "README.md")
WANTED_DIRS = ("licenses/",)

DLL_NAME = "OptiScaler.dll"
INI_NAME = "OptiScaler.ini"

# An optional ASI plugin that patches games gating DLSS behind their own checks.
# Published to a rolling tag as one unversioned .asi, so also keyed on sha256.
PATCHER_REPO = "optiscaler/OptiPatcher"
PATCHER_TAG = "rolling"
PATCHER_NAME = "OptiPatcher.asi"
PATCHER_URL = f"https://github.com/{PATCHER_REPO}/releases/tag/{PATCHER_TAG}"
_BASE_VERSION = re.compile(r"Base version:\**\s*(v[\d.]+)", re.IGNORECASE)
_BUILD_COMMIT = re.compile(r"Build commit:\**\s*([0-9a-f]{7,40})", re.IGNORECASE)


class ReleaseError(Exception):
    pass


# --------------------------------------------------------------------------
# TLS trust
# --------------------------------------------------------------------------

# Where distributions keep their CA bundle. Checked in order.
# Decky's loader is a PyInstaller bundle whose OpenSSL looks for CA certs at
# the build distro's paths, so the default context can come up empty here.
_CA_BUNDLES = (
    "/etc/ssl/certs/ca-certificates.crt",                        # Debian, Arch, SteamOS
    "/etc/pki/tls/certs/ca-bundle.crt",                          # Fedora, RHEL
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",         # Fedora, ostree
    "/etc/ssl/cert.pem",                                         # BSD, some musl
    "/etc/ssl/ca-bundle.pem",                                    # SUSE
)
_CA_DIRS = ("/etc/ssl/certs", "/etc/pki/tls/certs")


@functools.lru_cache(maxsize=1)
def ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    if _has_roots(context):
        log.debug("TLS: using the interpreter's default trust store")
        return context

    override = os.environ.get("SSL_CERT_FILE")
    candidates = ([override] if override else []) + list(_CA_BUNDLES)
    for candidate in candidates:
        if not candidate or not os.path.isfile(candidate):
            continue
        try:
            context.load_verify_locations(cafile=candidate)
        except (OSError, ssl.SSLError):
            continue
        if _has_roots(context):
            log.info("TLS: loaded CA bundle from %s", candidate)
            return context

    for directory in _CA_DIRS:
        if not os.path.isdir(directory):
            continue
        try:
            context.load_verify_locations(capath=directory)
        except (OSError, ssl.SSLError):
            continue
        if _has_roots(context):
            log.info("TLS: loaded CA certificates from %s", directory)
            return context

    try:
        import certifi  # noqa: PLC0415 - optional, only worth importing here
        context.load_verify_locations(cafile=certifi.where())
        if _has_roots(context):
            log.info("TLS: loaded CA bundle from certifi")
            return context
    except Exception:  # noqa: BLE001 - certifi is a nicety, not a requirement
        pass

    log.warning("TLS: no CA bundle found; HTTPS requests will probably fail")
    return context


# urllib wraps the OpenSSL message, which a toast cuts off before the half
# that says what is wrong.
def _reason(exc: urllib.error.URLError) -> str:
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, ssl.SSLCertVerificationError):
        return "no usable CA certificates, so GitHub's certificate cannot be verified"
    if isinstance(reason, ssl.SSLError):
        return f"TLS error ({reason.reason or 'unknown'})"
    if isinstance(reason, TimeoutError):
        return "timed out"
    return str(reason)


def _has_roots(context: ssl.SSLContext) -> bool:
    try:
        return context.cert_store_stats().get("x509_ca", 0) > 0
    except Exception:  # noqa: BLE001
        return False


def trust_source() -> str:
    context = ssl_context()
    return f"{context.cert_store_stats().get('x509_ca', 0)} CA certificates loaded"


# --------------------------------------------------------------------------
# remote
# --------------------------------------------------------------------------

def _api_get(url: str, timeout: float = 20.0):
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    })
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=timeout,
                                context=ssl_context()) as response:
        return json.loads(response.read().decode("utf-8"))


def _pick_asset(release: dict) -> Optional[dict]:
    assets = release.get("assets") or []
    for asset in assets:
        if ASSET_PATTERN.search(asset.get("name", "")):
            return asset
    # Fall back to the only zip on the release. The extract step still checks
    # that it holds OptiScaler.dll, so a wrong guess fails loudly.
    zips = [a for a in assets if a.get("name", "").lower().endswith(".zip")]
    return zips[0] if len(zips) == 1 else None


# The build hash in the asset name if there is one, else the tag. Tags here
# have been things like "yeah", so the hash is preferred when both exist.
def _version_label(asset_name: str, tag: str) -> str:
    match = _HASH_IN_NAME.search(asset_name or "")
    return match.group(1) if match else (tag or "unknown")


def _normalise(release: dict, asset: dict) -> dict:
    digest = (asset.get("digest") or "")
    sha256 = digest.split("sha256:", 1)[1] if "sha256:" in digest else ""
    return {
        "tag": release.get("tag_name") or "",
        "release_name": release.get("name") or "",
        "notes": release.get("body") or "",
        "published_at": release.get("published_at") or release.get("updated_at") or "",
        "asset_name": asset.get("name") or "",
        "asset_url": asset.get("browser_download_url") or "",
        "asset_id": asset.get("id"),
        "size": asset.get("size") or 0,
        "sha256": sha256,
        "version": _version_label(asset.get("name") or "", release.get("tag_name") or ""),
        "html_url": release.get("html_url") or RELEASE_URL,
        "fetched_at": int(time.time()),
    }


# Whatever the newest release happens to hold. No tag is pinned, because the
# tags carry no version meaning and the next build may land under a new one.
def remote_release(timeout: float = 20.0) -> dict:
    try:
        release = _api_get(f"{API_ROOT}/repos/{REPO}/releases/latest", timeout)
        asset = _pick_asset(release)
        if asset:
            return _normalise(release, asset)
        log.warning("latest release has no usable asset, scanning the rest")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise ReleaseError(f"GitHub returned HTTP {exc.code}") from exc
        # A 404 here means every release is a prerelease or a draft.
        log.warning("no published latest release, scanning the rest")
    except urllib.error.URLError as exc:
        raise ReleaseError(f"Could not reach GitHub: {_reason(exc)}") from exc

    try:
        releases = _api_get(f"{API_ROOT}/repos/{REPO}/releases?per_page=30", timeout)
    except urllib.error.URLError as exc:
        raise ReleaseError(f"Could not reach GitHub: {_reason(exc)}") from exc

    for release in releases:
        if release.get("draft"):
            continue
        asset = _pick_asset(release)
        if asset:
            return _normalise(release, asset)
    raise ReleaseError("No OptiScaler build found in any release")


# --------------------------------------------------------------------------
# local cache
# --------------------------------------------------------------------------

def _meta_path() -> Path:
    return paths.cache_dir() / "release.json"


def local_release() -> Optional[dict]:
    build = paths.build_dir()
    if not (build / DLL_NAME).is_file() or not (build / INI_NAME).is_file():
        return None
    try:
        with open(_meta_path(), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        # Build is there but we lost the metadata. Still usable, just unlabelled.
        return {"version": "unknown", "asset_name": "", "sha256": "", "tag": ""}


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


# Also finds a copy downloaded by hand, so a fresh install works offline.
def _candidate_zips(asset_name: str = "") -> list:
    seen = []
    search_dirs = [
        paths.cache_dir(),
        paths.runtime_dir() / "import",
        paths.user_home() / "Downloads",
        paths.user_home() / "Desktop",
    ]
    for directory in search_dirs:
        try:
            entries = sorted(directory.glob("*.zip"),
                             key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            continue
        for entry in entries:
            if entry.name == asset_name or ASSET_PATTERN.search(entry.name):
                seen.append(entry)
    return seen


def _extract(zip_path: Path, build: Path) -> None:
    staging = Path(tempfile.mkdtemp(dir=str(build.parent), prefix=".unpack-"))
    try:
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            if DLL_NAME not in names:
                raise ReleaseError(f"{zip_path.name} does not contain {DLL_NAME}")
            for name in names:
                if name.endswith("/"):
                    continue
                wanted = name in WANTED_FILES or name.startswith(WANTED_DIRS)
                if not wanted:
                    continue
                # name is matched against a fixed whitelist above, so it cannot
                # contain traversal, but resolve and re-check anyway.
                destination = (staging / name).resolve()
                if not str(destination).startswith(str(staging.resolve())):
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as source, open(destination, "wb") as target:
                    shutil.copyfileobj(source, target)

        previous = build.with_name(build.name + ".old")
        if previous.exists():
            shutil.rmtree(previous, ignore_errors=True)
        if build.exists():
            build.rename(previous)
        staging.rename(build)
        shutil.rmtree(previous, ignore_errors=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _write_meta(meta: dict) -> None:
    paths.cache_dir().mkdir(parents=True, exist_ok=True)
    tmp = _meta_path().with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2)
    tmp.replace(_meta_path())


def _download(url: str, destination: Path, expected_sha: str, expected_size: int,
              progress: Optional[Callable[[int, int], None]] = None) -> None:
    partial = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(request, timeout=60,
                                    context=ssl_context()) as response:
            total = int(response.headers.get("Content-Length") or expected_size or 0)
            done = 0
            with open(partial, "wb") as handle:
                while True:
                    block = response.read(1 << 18)
                    if not block:
                        break
                    handle.write(block)
                    digest.update(block)
                    done += len(block)
                    if progress:
                        progress(done, total)
    except urllib.error.URLError as exc:
        partial.unlink(missing_ok=True)
        raise ReleaseError(f"Download failed: {_reason(exc)}") from exc

    if expected_sha and digest.hexdigest() != expected_sha:
        partial.unlink(missing_ok=True)
        raise ReleaseError("Downloaded file failed its sha256 check")
    partial.replace(destination)


def _prune_cache(keep: Path) -> None:
    for entry in paths.cache_dir().glob("*.zip"):
        if entry != keep:
            entry.unlink(missing_ok=True)


def install_from_zip(zip_path: Path, meta: dict) -> dict:
    paths.cache_dir().mkdir(parents=True, exist_ok=True)
    cached = paths.cache_dir() / (meta.get("asset_name") or zip_path.name)
    if zip_path.resolve() != cached.resolve():
        shutil.copy2(zip_path, cached)
    _extract(cached, paths.build_dir())
    meta = dict(meta)
    meta.setdefault("sha256", sha256_of(cached))
    meta.setdefault("version", _version_label(cached.name, ""))
    meta["installed_at"] = int(time.time())
    meta["source"] = meta.get("source") or "local"
    _write_meta(meta)
    _prune_cache(cached)
    return meta


def adopt_cached_zip() -> Optional[dict]:
    for candidate in _candidate_zips():
        try:
            with zipfile.ZipFile(candidate) as archive:
                if DLL_NAME not in archive.namelist():
                    continue
        except (OSError, zipfile.BadZipFile):
            continue
        log.info("adopting locally cached build %s", candidate)
        return install_from_zip(candidate, {
            "tag": "",
            "asset_name": candidate.name,
            "version": _version_label(candidate.name, ""),
            "source": "local",
            "html_url": RELEASE_URL,
        })
    return None


def fetch_release(meta: dict,
                  progress: Optional[Callable[[int, int], None]] = None) -> dict:
    paths.cache_dir().mkdir(parents=True, exist_ok=True)
    destination = paths.cache_dir() / meta["asset_name"]

    reusable = None
    for candidate in _candidate_zips(meta["asset_name"]):
        if meta.get("sha256"):
            if sha256_of(candidate) == meta["sha256"]:
                reusable = candidate
                break
        elif candidate.name == meta["asset_name"]:
            reusable = candidate
            break

    if reusable is not None:
        log.info("reusing locally cached %s", reusable)
        meta = dict(meta, source="cache")
        return install_from_zip(reusable, meta)

    if not meta.get("asset_url"):
        raise ReleaseError("No download URL for this release")
    log.info("downloading %s", meta["asset_url"])
    _download(meta["asset_url"], destination, meta.get("sha256", ""),
              meta.get("size", 0), progress)
    return install_from_zip(destination, dict(meta, source="download"))


def status(check_remote: bool = False, timeout: float = 20.0) -> dict:
    local = local_release()
    result = {
        "installed": local is not None,
        "local_version": (local or {}).get("version", ""),
        "local_sha256": (local or {}).get("sha256", ""),
        "asset_name": (local or {}).get("asset_name", ""),
        "source": (local or {}).get("source", ""),
        "release_url": RELEASE_URL,
        "update_available": False,
        "remote_version": "",
        "remote": None,
        "error": "",
    }
    if not check_remote:
        return result

    try:
        remote = remote_release(timeout)
    except ReleaseError as exc:
        result["error"] = str(exc)
        return result
    except Exception as exc:  # noqa: BLE001 - never let an update check crash the panel
        result["error"] = f"Update check failed: {exc}"
        return result

    result["remote"] = remote
    result["remote_version"] = remote["version"]
    result["remote_published"] = remote.get("published_at", "")
    if local is None:
        result["update_available"] = True
    elif remote.get("sha256") and local.get("sha256"):
        result["update_available"] = remote["sha256"] != local["sha256"]
    else:
        result["update_available"] = remote["version"] != local.get("version")
    return result


def ensure_build(allow_network: bool = True) -> dict:
    local = local_release()
    if local is not None:
        return local
    adopted = adopt_cached_zip()
    if adopted is not None:
        return adopted
    if not allow_network:
        raise ReleaseError("No OptiScaler build cached and network use not allowed")
    return fetch_release(remote_release())


# --------------------------------------------------------------------------
# OptiPatcher
# --------------------------------------------------------------------------

def patcher_dir() -> Path:
    return paths.cache_dir() / "optipatcher"


def _patcher_meta_path() -> Path:
    return patcher_dir() / "release.json"


def patcher_file() -> Path:
    return patcher_dir() / PATCHER_NAME


def remote_patcher(timeout: float = 20.0) -> dict:
    try:
        release = _api_get(f"{API_ROOT}/repos/{PATCHER_REPO}/releases/tags/{PATCHER_TAG}",
                           timeout)
    except urllib.error.HTTPError as exc:
        raise ReleaseError(f"GitHub returned HTTP {exc.code} for OptiPatcher") from exc
    except urllib.error.URLError as exc:
        raise ReleaseError(f"Could not reach GitHub: {_reason(exc)}") from exc

    asset = None
    for candidate in release.get("assets") or []:
        if candidate.get("name") == PATCHER_NAME:
            asset = candidate
            break
    if asset is None:
        raise ReleaseError(f"No {PATCHER_NAME} in the OptiPatcher release")

    digest = asset.get("digest") or ""
    sha256 = digest.split("sha256:", 1)[1] if "sha256:" in digest else ""
    body = release.get("body") or ""
    base = _BASE_VERSION.search(body)
    commit = _BUILD_COMMIT.search(body)
    # The base version stays put across rebuilds, so alone it reads as
    # "v0.41 - update available (v0.41)". The build commit is what moves.
    return {
        "asset_name": PATCHER_NAME,
        "asset_url": asset.get("browser_download_url") or "",
        "size": asset.get("size") or 0,
        "sha256": sha256,
        "version": base.group(1) if base else (sha256[:7] or PATCHER_TAG),
        "build": (commit.group(1)[:7] if commit else sha256[:7]),
        "published_at": release.get("published_at") or release.get("updated_at") or "",
        "html_url": release.get("html_url") or PATCHER_URL,
        "fetched_at": int(time.time()),
    }


def local_patcher() -> Optional[dict]:
    if not patcher_file().is_file():
        return None
    try:
        with open(_patcher_meta_path(), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {"version": "unknown", "build": "", "sha256": "",
                "asset_name": PATCHER_NAME}


def _adopt_local_patcher() -> Optional[dict]:
    for directory in (patcher_dir(), paths.runtime_dir() / "import",
                      paths.user_home() / "Downloads", paths.user_home() / "Desktop"):
        candidate = directory / PATCHER_NAME
        if not candidate.is_file():
            continue
        patcher_dir().mkdir(parents=True, exist_ok=True)
        if candidate.resolve() != patcher_file().resolve():
            shutil.copy2(candidate, patcher_file())
        digest = sha256_of(patcher_file())
        meta = {"asset_name": PATCHER_NAME, "sha256": digest,
                "version": digest[:7], "build": digest[:7], "source": "local",
                "html_url": PATCHER_URL, "installed_at": int(time.time())}
        _write_patcher_meta(meta)
        return meta
    return None


def _write_patcher_meta(meta: dict) -> None:
    patcher_dir().mkdir(parents=True, exist_ok=True)
    tmp = _patcher_meta_path().with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2)
    tmp.replace(_patcher_meta_path())


def fetch_patcher(meta: dict,
                  progress: Optional[Callable[[int, int], None]] = None) -> dict:
    patcher_dir().mkdir(parents=True, exist_ok=True)
    cached = local_patcher()
    if cached and meta.get("sha256") and cached.get("sha256") == meta["sha256"]:
        return cached
    if not meta.get("asset_url"):
        raise ReleaseError("No download URL for OptiPatcher")
    _download(meta["asset_url"], patcher_file(), meta.get("sha256", ""),
              meta.get("size", 0), progress)
    stored = dict(meta, source="download", installed_at=int(time.time()))
    _write_patcher_meta(stored)
    return stored


def ensure_patcher(allow_network: bool = True) -> dict:
    local = local_patcher()
    if local is not None:
        return local
    adopted = _adopt_local_patcher()
    if adopted is not None:
        return adopted
    if not allow_network:
        raise ReleaseError("OptiPatcher is not cached and network use not allowed")
    return fetch_patcher(remote_patcher())


def patcher_status(check_remote: bool = False, timeout: float = 20.0) -> dict:
    local = local_patcher()
    result = {
        "installed": local is not None,
        "local_version": (local or {}).get("version", ""),
        "local_build": (local or {}).get("build", ""),
        "local_sha256": (local or {}).get("sha256", ""),
        "update_available": False,
        "remote_version": "",
        "remote_build": "",
        "release_url": PATCHER_URL,
        "error": "",
    }
    if not check_remote:
        return result
    try:
        remote = remote_patcher(timeout)
    except ReleaseError as exc:
        result["error"] = str(exc)
        return result
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"OptiPatcher update check failed: {exc}"
        return result

    result["remote_version"] = remote["version"]
    result["remote_build"] = remote.get("build", "")
    if local is None:
        result["update_available"] = True
    elif remote.get("sha256") and local.get("sha256"):
        result["update_available"] = remote["sha256"] != local["sha256"]
    return result


# ensure_patcher keeps whatever is cached so installing a game never becomes
# a surprise download. Updating is therefore explicit.
def refresh_patcher(progress: Optional[Callable[[int, int], None]] = None) -> dict:
    return fetch_patcher(remote_patcher(), progress)
