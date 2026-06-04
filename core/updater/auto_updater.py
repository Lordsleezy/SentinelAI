"""Production auto-updater — GitHub Releases, semver, verify, install, rollback."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.updater.semver import normalize_version, version_meets_minimum, version_newer

logger = logging.getLogger("sentinel.updater")

_ROOT = Path(__file__).resolve().parents[2]
_STATE_DIR = _ROOT / "data" / "updates"
_ARCHIVE_DIR = _STATE_DIR / "archive"
_MANIFEST_PATH = _STATE_DIR / "update_state.json"
_UPDATE_MANIFEST_PATH = _ROOT / "data" / "release" / "update_manifest.json"
_DEFAULT_REPO = os.environ.get("SENTINEL_GITHUB_REPO", "Lordsleezy/SentinelAI")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _current_version() -> str:
    try:
        import build_info as bi
        return getattr(bi, "BUILD_VERSION", "0.0.0")
    except ImportError:
        return "0.0.0"


def _build_type() -> str:
    try:
        import build_info as bi
        return getattr(bi, "BUILD_TYPE", "dev")
    except ImportError:
        return "dev"


def load_update_manifest() -> Dict[str, Any]:
    if _UPDATE_MANIFEST_PATH.is_file():
        try:
            return json.loads(_UPDATE_MANIFEST_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_update_manifest(manifest: Dict[str, Any]) -> None:
    _UPDATE_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _UPDATE_MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


class AutoUpdater:
    def __init__(self, repo: str = _DEFAULT_REPO) -> None:
        self.repo = repo
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        self._channel = self._load_state().get("channel", "beta")
        self._lock = threading.Lock()
        self._download_thread: Optional[threading.Thread] = None

    def _load_state(self) -> Dict[str, Any]:
        if _MANIFEST_PATH.is_file():
            try:
                return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_state(self, state: Dict[str, Any]) -> None:
        with self._lock:
            _MANIFEST_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def _touch_state(self, **fields: Any) -> Dict[str, Any]:
        state = self._load_state()
        state.update(fields)
        self._save_state(state)
        return state

    def _updates_disabled(self) -> bool:
        m = load_update_manifest()
        if m.get("updates_disabled"):
            return True
        if m.get("kill_switch"):
            return True
        return os.environ.get("SENTINEL_UPDATES_DISABLED", "").lower() in ("1", "true", "yes")

    def _record_failure(self, error: str) -> None:
        self._touch_state(
            last_failure={"at": _utc(), "error": error[:500]},
            update_status="failed",
        )

    def _github_headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "SentinelAI-Updater"}
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def test_github_connectivity(self) -> Dict[str, Any]:
        import httpx
        owner, name = self.repo.split("/", 1)
        url = f"https://api.github.com/repos/{owner}/{name}"
        try:
            with httpx.Client(timeout=12.0) as client:
                r = client.get(url, headers=self._github_headers())
                ok = r.status_code == 200
                self._touch_state(
                    github_connectivity={"ok": ok, "status_code": r.status_code, "checked_at": _utc()},
                )
                return {"ok": ok, "status_code": r.status_code}
        except Exception as e:
            self._touch_state(
                github_connectivity={"ok": False, "error": str(e)[:200], "checked_at": _utc()},
            )
            return {"ok": False, "error": str(e)}

    def status(self) -> Dict[str, Any]:
        state = self._load_state()
        manifest = load_update_manifest()
        avail = state.get("available") or {}
        latest = (avail.get("version") or "").lstrip("v") if avail else None
        return {
            "current_version": _current_version(),
            "latest_version": latest,
            "build_type": _build_type(),
            "channel": self._channel,
            "last_check": state.get("last_check"),
            "last_download": state.get("last_download"),
            "last_install": state.get("last_install"),
            "last_failure": state.get("last_failure"),
            "last_update": state.get("last_update"),
            "github_connectivity": state.get("github_connectivity"),
            "update_status": state.get("update_status", "idle"),
            "electron_update": state.get("electron_update"),
            "available_update": avail,
            "pending_download": state.get("pending_download"),
            "rollback_version": state.get("rollback_version"),
            "rollback_artifact": state.get("rollback_artifact"),
            "can_rollback": bool(state.get("rollback_artifact", {}).get("path")),
            "repo": self.repo,
            "updates_disabled": self._updates_disabled(),
            "force_update": bool(manifest.get("force_update")),
            "minimum_supported_version": manifest.get("minimum_supported_version"),
            "manifest": manifest,
        }

    def diagnostics(self) -> Dict[str, Any]:
        st = self.status()
        gh = st.get("github_connectivity") or {}
        return {
            "current_version": st.get("current_version"),
            "latest_version": st.get("latest_version") or "—",
            "update_channel": st.get("channel"),
            "last_check": st.get("last_check") or "—",
            "last_download": (st.get("last_download") or {}).get("at") if isinstance(st.get("last_download"), dict) else st.get("last_download") or "—",
            "last_install": (st.get("last_install") or {}).get("at") if isinstance(st.get("last_install"), dict) else st.get("last_install") or "—",
            "last_failure": st.get("last_failure") or "—",
            "github_connectivity": "OK" if gh.get("ok") else (gh.get("error") or f"HTTP {gh.get('status_code', '?')}"),
            "update_status": st.get("update_status", "idle"),
            "pending_download": st.get("pending_download"),
            "rollback_version": st.get("rollback_version"),
            "can_rollback": st.get("can_rollback"),
            "updates_disabled": st.get("updates_disabled"),
            "force_update": st.get("force_update"),
        }

    def set_channel(self, channel: str) -> Dict[str, Any]:
        if channel not in ("beta", "stable"):
            return {"ok": False, "error": "channel must be beta or stable"}
        self._channel = channel
        manifest = load_update_manifest()
        manifest["channel"] = channel
        save_update_manifest(manifest)
        self._touch_state(channel=channel)
        return {"ok": True, "channel": channel}

    def record_electron_event(self, phase: str, detail: Optional[Dict[str, Any]] = None) -> None:
        """Merge electron-updater lifecycle into shared state."""
        state = self._load_state()
        state["electron_update"] = {
            "phase": phase,
            "detail": detail or {},
            "at": _utc(),
        }
        if phase == "error":
            state["last_failure"] = {"at": _utc(), "error": str((detail or {}).get("message", phase))[:500]}
            state["update_status"] = "failed"
        elif phase == "update-downloaded":
            state["update_status"] = "ready_to_install"
            ver = (detail or {}).get("version")
            if ver:
                state["available"] = state.get("available") or {}
                state["available"]["version"] = ver
        elif phase == "checking":
            state["update_status"] = "checking"
        self._save_state(state)

    def check_for_updates(self) -> Dict[str, Any]:
        if self._updates_disabled():
            return {"ok": False, "error": "updates disabled by manifest or environment"}

        manifest = load_update_manifest()
        current = _current_version()
        min_ver = manifest.get("minimum_supported_version") or "0.0.0"
        if not version_meets_minimum(current, min_ver):
            self._record_failure(f"current {current} below minimum {min_ver}")
            return {"ok": False, "error": "below_minimum_supported_version", "minimum": min_ver}

        gh = self.test_github_connectivity()
        if not gh.get("ok"):
            return {"ok": False, "error": gh.get("error", "github unreachable")}

        import httpx
        owner, name = self.repo.split("/", 1)
        url = f"https://api.github.com/repos/{owner}/{name}/releases"
        try:
            with httpx.Client(timeout=20.0) as client:
                r = client.get(url, headers=self._github_headers())
                r.raise_for_status()
                releases = r.json()
        except Exception as e:
            logger.warning("update check failed: %s", e)
            self._record_failure(str(e))
            return {"ok": False, "error": str(e)}

        chosen = self._select_release(releases, current)
        state = self._load_state()
        state["last_check"] = _utc()
        state["update_status"] = "checked"
        if chosen:
            tag = chosen.get("tag_name") or ""
            asset = self._pick_asset(chosen.get("assets", []))
            state["available"] = {
                "version": tag,
                "name": chosen.get("name"),
                "published_at": chosen.get("published_at"),
                "asset": asset,
                "body": (chosen.get("body") or "")[:2000],
                "prerelease": bool(chosen.get("prerelease")),
            }
            state["latest_version"] = tag.lstrip("v")
        else:
            state["available"] = None
        self._save_state(state)
        return {
            "ok": True,
            "current": current,
            "available": state.get("available"),
            "force_update": bool(manifest.get("force_update")),
        }

    def _select_release(self, releases: List[Dict[str, Any]], current: str) -> Optional[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        for rel in releases:
            if rel.get("draft"):
                continue
            tag = (rel.get("tag_name") or "").lstrip("v")
            prerelease = bool(rel.get("prerelease"))
            if self._channel == "stable" and prerelease:
                continue
            if not version_newer(tag, current):
                continue
            candidates.append(rel)
        if not candidates:
            return None
        # GitHub returns newest first; pick highest semver among candidates
        best = candidates[0]
        best_tag = (best.get("tag_name") or "").lstrip("v")
        for rel in candidates[1:]:
            tag = (rel.get("tag_name") or "").lstrip("v")
            if version_newer(tag, best_tag):
                best = rel
                best_tag = tag
        return best

    def _pick_asset(self, assets: list) -> Optional[Dict[str, Any]]:
        preferred = ("sentinelaisetup", "sentinel ai setup", "setup.exe", ".exe")
        sorted_assets = sorted(assets, key=lambda a: (a.get("name") or "").lower())
        for key in preferred:
            for a in sorted_assets:
                name = (a.get("name") or "").lower()
                if key in name or name.endswith(key):
                    return {
                        "name": a.get("name"),
                        "url": a.get("browser_download_url"),
                        "size": a.get("size"),
                    }
        for a in sorted_assets:
            name = (a.get("name") or "").lower()
            if name.endswith(".exe") or name.endswith(".msi") or name.endswith(".zip"):
                return {
                    "name": a.get("name"),
                    "url": a.get("browser_download_url"),
                    "size": a.get("size"),
                }
        if assets:
            a = assets[0]
            return {"name": a.get("name"), "url": a.get("browser_download_url"), "size": a.get("size")}
        return None

    def download_update(self, *, background: bool = True) -> Dict[str, Any]:
        if self._updates_disabled():
            return {"ok": False, "error": "updates disabled"}
        state = self._load_state()
        avail = state.get("available")
        if not avail or not avail.get("asset", {}).get("url"):
            return {"ok": False, "error": "no update available"}
        if background:
            if self._download_thread and self._download_thread.is_alive():
                return {"ok": True, "message": "download already in progress"}
            self._download_thread = threading.Thread(
                target=self._download_worker,
                args=(avail,),
                daemon=True,
                name="sentinel-updater-download",
            )
            self._download_thread.start()
            return {"ok": True, "message": "background download started"}
        return self._download_worker(avail)

    def _download_worker(self, avail: Dict[str, Any]) -> Dict[str, Any]:
        import httpx
        asset = avail["asset"]
        version_tag = (avail.get("version") or "unknown").replace("/", "_")
        dest = _STATE_DIR / f"pending_{version_tag}_{asset['name']}"
        partial = dest.with_suffix(dest.suffix + ".part")
        if partial.is_file():
            partial.unlink(missing_ok=True)
        if dest.is_file():
            dest.unlink(missing_ok=True)

        self._touch_state(update_status="downloading")
        try:
            with httpx.Client(timeout=300.0, follow_redirects=True) as client:
                with client.stream("GET", asset["url"]) as r:
                    r.raise_for_status()
                    h = hashlib.sha256()
                    with open(partial, "wb") as f:
                        for chunk in r.iter_bytes(65536):
                            f.write(chunk)
                            h.update(chunk)
            digest = h.hexdigest()
            expected = self._expected_checksum(avail, asset.get("name", ""))
            if expected and digest != expected:
                partial.unlink(missing_ok=True)
                self._record_failure("checksum mismatch")
                return {"ok": False, "error": "checksum mismatch"}
            if not expected:
                logger.warning("No SHA-256 published for %s — download accepted without hash verify", asset.get("name"))

            shutil.move(str(partial), str(dest))
            self._archive_installer(_current_version(), None)

            state = self._load_state()
            state["rollback_version"] = _current_version()
            state["pending_download"] = {
                "path": str(dest),
                "version": avail.get("version"),
                "sha256": digest,
                "downloaded_at": _utc(),
                "expected_checksum": expected,
            }
            state["last_download"] = {"at": _utc(), "version": avail.get("version"), "path": str(dest)}
            state["last_update"] = _utc()
            state["update_status"] = "downloaded"
            state["last_failure"] = None
            self._save_state(state)
            logger.info("Update downloaded: %s", dest)
            return {"ok": True, "path": str(dest), "sha256": digest, "checksum_verified": bool(expected)}
        except Exception as e:
            partial.unlink(missing_ok=True)
            logger.exception("download failed")
            self._record_failure(str(e))
            return {"ok": False, "error": str(e)}

    def _expected_checksum(self, avail: Dict[str, Any], asset_name: str) -> Optional[str]:
        body = avail.get("body") or ""
        for line in body.splitlines():
            low = line.lower()
            if asset_name.lower() in low and "sha" in low:
                for token in line.replace(":", " ").split():
                    t = token.strip().lower()
                    if len(t) == 64 and all(c in "0123456789abcdef" for c in t):
                        return t
            if asset_name in line and len(line.split()) >= 2:
                token = line.split()[-1].strip().lower()
                if len(token) == 64 and all(c in "0123456789abcdef" for c in token):
                    return token
        sidecar = _STATE_DIR / f"{asset_name}.sha256"
        if sidecar.is_file():
            return sidecar.read_text(encoding="utf-8").split()[0].lower()
        manifest_sidecar = _ROOT / "data" / "release" / f"{asset_name}.sha256"
        if manifest_sidecar.is_file():
            return manifest_sidecar.read_text(encoding="utf-8").split()[0].lower()
        return None

    def _archive_installer(self, version: str, path: Optional[Path]) -> None:
        """Keep last known installer per version for rollback."""
        if path and path.is_file():
            dest = _ARCHIVE_DIR / f"SentinelAISetup_{normalize_version(version)}.exe"
            try:
                shutil.copy2(path, dest)
            except Exception as e:
                logger.debug("archive copy failed: %s", e)

    def install_pending(self) -> Dict[str, Any]:
        """Launch silent NSIS installer for pending download (Windows)."""
        state = self._load_state()
        pending = state.get("pending_download")
        if not pending or not pending.get("path"):
            return {"ok": False, "error": "no pending download"}

        installer = Path(pending["path"])
        if not installer.is_file():
            self._record_failure("pending installer missing")
            return {"ok": False, "error": "installer file missing"}

        if pending.get("sha256"):
            digest = hashlib.sha256(installer.read_bytes()).hexdigest()
            if digest != pending["sha256"]:
                self._record_failure("pending installer corrupt")
                installer.unlink(missing_ok=True)
                return {"ok": False, "error": "pending installer failed validation"}

        rollback_from = _current_version()
        self._archive_installer(rollback_from, None)

        launched = self._launch_installer(installer)
        if not launched.get("ok"):
            self._record_failure(launched.get("error", "install launch failed"))
            return launched

        state = self._load_state()
        state["rollback_version"] = rollback_from
        state["rollback_artifact"] = {
            "version": rollback_from,
            "archived_at": _utc(),
            "note": "Reinstall from archive or GitHub if rollback needed",
        }
        state["last_install"] = {
            "at": _utc(),
            "version": pending.get("version"),
            "path": str(installer),
            "method": "nsis_silent",
        }
        state["update_status"] = "install_launched"
        state["installed_target_version"] = pending.get("version")
        self._save_state(state)
        return {
            "ok": True,
            "restart_required": True,
            "path": str(installer),
            "version": pending.get("version"),
            "message": "Installer started. Sentinel will restart to complete the update.",
        }

    def _launch_installer(self, installer: Path) -> Dict[str, Any]:
        if platform.system() != "Windows":
            return {"ok": False, "error": "silent install supported on Windows only"}
        try:
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen(
                [str(installer), "/S"],
                close_fds=True,
                creationflags=creationflags,
            )
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def apply_pending_notification(self) -> Dict[str, Any]:
        pending = self._load_state().get("pending_download")
        if not pending:
            return {"ok": False, "error": "no pending download"}
        return self.install_pending()

    def rollback_info(self) -> Dict[str, Any]:
        state = self._load_state()
        rb = state.get("rollback_artifact") or {}
        ver = state.get("rollback_version")
        archived = _ARCHIVE_DIR / f"SentinelAISetup_{normalize_version(ver)}.exe" if ver else None
        has_archive = bool(archived and archived.is_file())
        return {
            "rollback_version": ver,
            "can_rollback": bool(ver),
            "archived_installer": str(archived) if has_archive else None,
            "has_archived_installer": has_archive,
            "pending": state.get("pending_download"),
            "rollback_artifact": rb,
        }

    def trigger_rollback(self) -> Dict[str, Any]:
        """Resolve rollback installer (archive → GitHub re-download)."""
        info = self.rollback_info()
        ver = info.get("rollback_version")
        if not ver:
            return {"ok": False, "error": "no rollback version recorded"}

        archived = _ARCHIVE_DIR / f"SentinelAISetup_{normalize_version(ver)}.exe"
        if archived.is_file():
            digest = hashlib.sha256(archived.read_bytes()).hexdigest()
            state = self._touch_state(
                rollback_pending={
                    "path": str(archived),
                    "version": ver,
                    "sha256": digest,
                    "source": "archive",
                },
                update_status="rollback_ready",
            )
            return {"ok": True, "source": "archive", "path": str(archived), "version": ver}

        fetched = self._fetch_release_installer(ver)
        if not fetched.get("ok"):
            self._record_failure(fetched.get("error", "rollback fetch failed"))
            return fetched

        state = self._touch_state(
            rollback_pending=fetched,
            update_status="rollback_ready",
        )
        return {"ok": True, **fetched}

    def execute_rollback(self) -> Dict[str, Any]:
        """Validate and launch rollback installer."""
        state = self._load_state()
        rb = state.get("rollback_pending")
        if not rb:
            triggered = self.trigger_rollback()
            if not triggered.get("ok"):
                return triggered
            state = self._load_state()
            rb = state.get("rollback_pending")
        if not rb or not rb.get("path"):
            return {"ok": False, "error": "rollback artifact not available"}

        installer = Path(rb["path"])
        if not installer.is_file():
            return {"ok": False, "error": "rollback installer missing on disk"}

        if rb.get("sha256"):
            digest = hashlib.sha256(installer.read_bytes()).hexdigest()
            if digest != rb["sha256"]:
                self._record_failure("rollback checksum failed")
                return {"ok": False, "error": "rollback installer corrupt"}

        launched = self._launch_installer(installer)
        if not launched.get("ok"):
            self._record_failure(launched.get("error", "rollback launch failed"))
            return launched

        self._touch_state(
            last_install={"at": _utc(), "version": rb.get("version"), "method": "rollback"},
            update_status="rollback_launched",
        )
        return {
            "ok": True,
            "message": f"Rollback to {rb.get('version')} started. Restart Sentinel to complete.",
            "version": rb.get("version"),
        }

    def _fetch_release_installer(self, version: str) -> Dict[str, Any]:
        import httpx
        owner, name = self.repo.split("/", 1)
        tag = version if version.startswith("v") else f"v{version}"
        url = f"https://api.github.com/repos/{owner}/{name}/releases/tags/{tag}"
        try:
            with httpx.Client(timeout=20.0) as client:
                r = client.get(url, headers=self._github_headers())
                if r.status_code == 404:
                    return {"ok": False, "error": f"release {tag} not found"}
                r.raise_for_status()
                rel = r.json()
        except Exception as e:
            return {"ok": False, "error": str(e)}

        asset = self._pick_asset(rel.get("assets", []))
        if not asset or not asset.get("url"):
            return {"ok": False, "error": "no installer asset on release"}

        avail = {"version": rel.get("tag_name"), "body": rel.get("body"), "asset": asset}
        dest = _ARCHIVE_DIR / f"SentinelAISetup_{normalize_version(version)}.exe"
        if dest.is_file():
            dest.unlink(missing_ok=True)

        import httpx as hx
        try:
            with hx.Client(timeout=300.0, follow_redirects=True) as client:
                data = client.get(asset["url"]).content
            digest = hashlib.sha256(data).hexdigest()
            expected = self._expected_checksum(avail, asset.get("name", ""))
            if expected and digest != expected:
                return {"ok": False, "error": "rollback download checksum mismatch"}
            dest.write_bytes(data)
            return {
                "ok": True,
                "path": str(dest),
                "version": version,
                "sha256": digest,
                "source": "github",
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}


_updater: Optional[AutoUpdater] = None


def get_auto_updater() -> AutoUpdater:
    global _updater
    if _updater is None:
        _updater = AutoUpdater()
    return _updater
