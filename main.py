import json
import hashlib
import os
import re
import shutil
import subprocess
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import decky

BUNDLED_ASSET_NAME = "version.dll"
KNOWN_DLSS_ENABLER_ASSETS = [
    {
        "version": "4.3.1.0",
        "sha256": "a07b82de96e8c278184fe01409d7b4851a67865f7b8fed56332e40028dc3b41f",
        "release_tag": "bins",
    },
    {
        "version": "4.4.0.2-dev",
        "sha256": "7357292a3ced57c194f60bd2cbfc8f3837604b2365af114a2a4bc61508e9d5c6",
        "release_tag": "bins-dlss-enabler-4.4.0.2-dev",
    },
]
CURRENT_DLSS_ENABLER_VERSION = "4.4.0.2-dev"
KNOWN_DLSS_ENABLER_ASSETS_BY_VERSION = {
    asset["version"]: asset for asset in KNOWN_DLSS_ENABLER_ASSETS
}
DLSS_ENABLER_VERSION = CURRENT_DLSS_ENABLER_VERSION
BUNDLED_ASSET_SHA256 = KNOWN_DLSS_ENABLER_ASSETS_BY_VERSION[DLSS_ENABLER_VERSION]["sha256"]

FSR4_INT8_BUNDLE = {
    "id": "fsr4-int8-4.0.2b-opti-0.7.9",
    "label": "FSR4 INT8 4.0.2b",
    "fsr4_version": "4.0.2b",
    "optiscaler_version": "0.7.9",
    "release_tag": "bins-fsr4-int8-4.0.2b-opti-0.7.9",
    "assets": [
        {
            "asset_name": "amd_fidelityfx_dx12.dll",
            "target_name": "amd_fidelityfx_dx12.dll",
            "sha256": "6bf0d4f89611ff3cf0f15f767eb4c16c7044cba1e83d6272d996add42980b767",
            "kind": "ffx-loader",
        },
        {
            "asset_name": "amd_fidelityfx_upscaler_dx12.dll",
            "target_name": "amd_fidelityfx_upscaler_dx12.dll",
            "sha256": "2604c0b392072d715b400b2f89434274de31995a4b6e68ce38250ebbd3f6c5fc",
            "kind": "fsr4-upscaler",
        },
    ],
}
OPTIPATCHER_PLUGIN = {
    "id": "optipatcher-2026-03-27",
    "label": "OptiPatcher",
    "version": "2026-03-27",
    "release_tag": "bins-optipatcher-3-27-2026",
    "asset_name": "OptiPatcher.asi",
    "target_dirname": "plugins",
    "target_name": "OptiPatcher.asi",
    "sha256": "001b419bf315da6b200b8c29bb69df37117d7efb1341dd77bdd943b22491ab36",
    "kind": "optipatcher-plugin",
}
FSR4_CONFIG_FILENAME = "OptiScaler.ini"
KNOWN_RUNTIME_ARTIFACT_FILENAMES = [
    "dlss-enabler.ini",
    "dlss-enabler.log",
    "dlssg_to_fsr3_amd_is_better.dll",
    "fakenvapi.log",
]
KNOWN_RUNTIME_ARTIFACT_GLOBS = [
    "OptiScaler.ini.unexpected.*",
]
MARKER_PREFIX = "DLSS_ENABLER_"
MARKER_SUFFIX = "_DLL"
BACKUP_SUFFIX = ".backup"


def _version_token(version: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", version).strip("_").upper()


KNOWN_DLSS_ENABLER_ASSETS_BY_SHA256 = {
    asset["sha256"].lower(): asset for asset in KNOWN_DLSS_ENABLER_ASSETS
}
KNOWN_DLSS_ENABLER_ASSETS_BY_TOKEN = {
    _version_token(asset["version"]): asset for asset in KNOWN_DLSS_ENABLER_ASSETS
}

SUPPORTED_METHODS = [
    "version",
    "winmm",
    "d3d11",
    "d3d12",
    "dinput8",
    "dxgi",
    "wininet",
    "winhttp",
    "dbghelp",
]

UNREAL_HINTS = [
    "/binaries/win64/",
    "-win64-shipping.exe",
    "shipping.exe",
]

BAD_EXE_SUBSTRINGS = [
    "crashreport",
    "crashreportclient",
    "eac",
    "easyanticheat",
    "beclient",
    "eosbootstrap",
    "benchmark",
    "uninstall",
    "setup",
    "launcher",
    "updater",
    "bootstrap",
    "_redist",
    "prereq",
]


class Plugin:
    def _log(self, message: str) -> None:
        decky.logger.info(f"[DLSS Enabler] {message}")

    async def _main(self):
        self._log("plugin loaded")

    async def _unload(self):
        self._log("plugin unloaded")

    async def _uninstall(self):
        self._log("plugin uninstalled")

    async def _migration(self):
        pass

    def _home_path(self) -> Path:
        try:
            return Path(decky.HOME)
        except TypeError:
            return Path(str(decky.HOME))

    def _plugin_bin_dir(self) -> Path:
        return Path(decky.DECKY_PLUGIN_DIR) / "bin"

    def _bundled_asset_path(self) -> Path:
        return self._plugin_bin_dir() / BUNDLED_ASSET_NAME

    def _bundled_sidecar_asset_path(self, asset_name: str) -> Path:
        return self._plugin_bin_dir() / asset_name

    def _quirks_db_path(self) -> Path:
        return Path(__file__).parent / "py_modules" / "quirks_db.json"

    def _load_quirks_db(self) -> dict:
        return self._read_json_file(self._quirks_db_path())

    def _normalized_optiscaler_ini_overrides(self, overrides: dict | None) -> dict[str, dict[str, str]]:
        normalized: dict[str, dict[str, str]] = {}
        if not isinstance(overrides, dict):
            return normalized

        for section_name, section_values in overrides.items():
            normalized_section = str(section_name).strip().strip("[]")
            if not normalized_section or not isinstance(section_values, dict):
                continue

            normalized_values: dict[str, str] = {}
            for key, value in section_values.items():
                normalized_key = str(key).strip()
                if not normalized_key:
                    continue
                normalized_values[normalized_key] = str(value).strip()

            if normalized_values:
                normalized[normalized_section] = normalized_values

        return normalized

    def _normalize_game_name(self, name: str | None) -> str:
        normalized = unicodedata.normalize("NFKD", str(name or ""))
        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        normalized = normalized.lower().replace("&", " and ")
        normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
        return " ".join(normalized.split())

    def _entry_game_name_candidates(self, entry_key: str, entry: dict) -> list[str]:
        candidates: list[str] = []
        for value in [entry.get("steam_name"), entry.get("wiki_slug")]:
            if value:
                candidates.append(str(value).replace("-", " "))

        for alias in entry.get("aliases") or []:
            if alias:
                candidates.append(str(alias))

        if entry_key and not str(entry_key).isdigit():
            candidates.append(str(entry_key).replace("-", " "))

        normalized_candidates: list[str] = []
        seen = set()
        for candidate in candidates:
            normalized = self._normalize_game_name(candidate)
            if normalized and normalized not in seen:
                normalized_candidates.append(normalized)
                seen.add(normalized)
        return normalized_candidates

    def _entry_steam_appids(self, entry: dict) -> set[str]:
        appids: set[str] = set()
        for value in entry.get("steam_appids") or []:
            normalized = str(value).strip()
            if normalized:
                appids.add(normalized)
        return appids

    def _game_quirks(self, appid: str, game_name: str | None = None) -> dict | None:
        quirks_db = self._load_quirks_db()
        games = quirks_db.get("games") if isinstance(quirks_db, dict) else None
        if not isinstance(games, dict):
            return None

        normalized_appid = str(appid).strip()
        entry = games.get(normalized_appid)
        if isinstance(entry, dict):
            return entry

        for entry_value in games.values():
            if not isinstance(entry_value, dict):
                continue
            if normalized_appid and normalized_appid in self._entry_steam_appids(entry_value):
                return entry_value

        normalized_game_name = self._normalize_game_name(game_name)
        if not normalized_game_name:
            return None

        for entry_key, entry_value in games.items():
            if not isinstance(entry_value, dict):
                continue
            if normalized_game_name in self._entry_game_name_candidates(str(entry_key), entry_value):
                return entry_value

        return None

    def _game_quirks_payload(self, appid: str, game_name: str | None = None) -> dict:
        entry = self._game_quirks(appid, game_name)
        if not entry:
            return {
                "recommended_method": None,
                "recommended_optipatcher": False,
                "recommendation_source": None,
                "recommendation_wiki_url": None,
                "recommendation_notes": [],
                "recommended_optiscaler_ini_overrides": {},
            }

        recommended_method = None
        try:
            if entry.get("recommended_method"):
                recommended_method = self._normalize_method(str(entry.get("recommended_method")))
        except Exception:
            recommended_method = None

        notes = [
            str(note).strip()
            for note in (entry.get("notes") or [])
            if str(note).strip()
        ]

        return {
            "recommended_method": recommended_method,
            "recommended_optipatcher": bool(entry.get("recommended_optipatcher")),
            "recommendation_source": str(entry.get("source") or "") or None,
            "recommendation_wiki_url": str(entry.get("source_url") or "") or None,
            "recommendation_notes": notes,
            "recommended_optiscaler_ini_overrides": self._normalized_optiscaler_ini_overrides(
                entry.get("recommended_optiscaler_ini_overrides")
            ),
        }

    def _managed_optiscaler_config_contents(
        self,
        *,
        enable_fsr4: bool = False,
        enable_optipatcher: bool = False,
        overrides: dict[str, dict[str, str]] | None = None,
    ) -> str:
        sections: dict[str, dict[str, str]] = {}
        if enable_fsr4:
            sections.update(
                {
                    "FSR": {
                        "Fsr4Update": "true",
                        "FsrAgilitySDKUpgrade": "auto",
                    },
                    "Upscalers": {
                        "Dx12Upscaler": "fsr31",
                    },
                    "FrameGen": {
                        "FGType": "Nukems",
                    },
                }
            )

        if enable_optipatcher:
            sections.setdefault("Plugins", {})["LoadAsiPlugins"] = "true"

        for section_name, section_values in self._normalized_optiscaler_ini_overrides(overrides).items():
            sections.setdefault(section_name, {}).update(section_values)

        lines = ["; Managed by Decky DLSS Enabler"]
        if enable_fsr4:
            lines.append("; Experimental FSR4 INT8 sidecar support")
        if enable_optipatcher:
            lines.append("; OptiPatcher ASI plugin enabled")
        lines.append("")

        for section_name, section_values in sections.items():
            lines.append(f"[{section_name}]")
            for key, value in section_values.items():
                lines.append(f"{key}={value}")
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    def _bytes_sha256(self, payload: bytes) -> str:
        digest = hashlib.sha256()
        digest.update(payload)
        return digest.hexdigest()

    def _file_sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _safe_sha256(self, path: Path) -> str | None:
        try:
            if path.exists() and path.is_file() and not path.is_symlink():
                return self._file_sha256(path)
        except Exception:
            return None
        return None

    def _verify_bundled_asset(self) -> Path:
        asset_path = self._bundled_asset_path()
        if not asset_path.exists():
            raise FileNotFoundError(f"Bundled asset missing: {asset_path}")

        asset_hash = self._file_sha256(asset_path)
        self._log(f"verify bundled asset: path={asset_path} sha256={asset_hash}")
        if asset_hash.lower() != BUNDLED_ASSET_SHA256.lower():
            raise RuntimeError(
                f"Bundled asset hash mismatch for {asset_path.name}: expected {BUNDLED_ASSET_SHA256}, got {asset_hash}"
            )
        return asset_path

    def _verify_fsr4_bundle_assets(self) -> list[dict]:
        verified_assets: list[dict] = []
        for asset in FSR4_INT8_BUNDLE["assets"]:
            asset_path = self._bundled_sidecar_asset_path(asset["asset_name"])
            if not asset_path.exists():
                raise FileNotFoundError(f"Bundled FSR4 sidecar asset missing: {asset_path}")

            asset_hash = self._file_sha256(asset_path)
            self._log(f"verify fsr4 asset: path={asset_path} sha256={asset_hash}")
            if asset_hash.lower() != asset["sha256"].lower():
                raise RuntimeError(
                    f"Bundled FSR4 sidecar hash mismatch for {asset_path.name}: expected {asset['sha256']}, got {asset_hash}"
                )

            verified_assets.append({**asset, "path": asset_path})
        return verified_assets

    def _verify_optipatcher_asset(self) -> dict:
        asset_path = self._bundled_sidecar_asset_path(OPTIPATCHER_PLUGIN["asset_name"])
        if not asset_path.exists():
            raise FileNotFoundError(f"Bundled OptiPatcher asset missing: {asset_path}")

        asset_hash = self._file_sha256(asset_path)
        self._log(f"verify optipatcher asset: path={asset_path} sha256={asset_hash}")
        if asset_hash.lower() != OPTIPATCHER_PLUGIN["sha256"].lower():
            raise RuntimeError(
                f"Bundled OptiPatcher hash mismatch for {asset_path.name}: expected {OPTIPATCHER_PLUGIN['sha256']}, got {asset_hash}"
            )

        return {**OPTIPATCHER_PLUGIN, "path": asset_path}

    def _read_json_file(self, path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as file:
                parsed = json.load(file)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _write_json_file(self, path: Path, payload: dict) -> None:
        with open(path, "w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, sort_keys=True)

    def _normalize_method(self, method: str | None) -> str:
        normalized = (method or "version").replace(".dll", "").strip().lower()
        if normalized not in SUPPORTED_METHODS:
            raise ValueError(f"Unsupported injection method '{method}'")
        return normalized

    def _marker_filename(self, method: str) -> str:
        return f"{MARKER_PREFIX}{self._normalize_method(method).upper()}{MARKER_SUFFIX}"

    def _legacy_marker_filename(self, method: str, version: str) -> str:
        normalized_method = self._normalize_method(method).upper()
        return f"{MARKER_PREFIX}{_version_token(version)}_{normalized_method}{MARKER_SUFFIX}"

    def _parse_marker_name(self, marker_name: str) -> dict | None:
        stable_pattern = rf"^{re.escape(MARKER_PREFIX)}([A-Z0-9]+){re.escape(MARKER_SUFFIX)}$"
        stable_match = re.match(stable_pattern, marker_name)
        if stable_match:
            parsed_method = stable_match.group(1).lower()
            if parsed_method in SUPPORTED_METHODS:
                return {
                    "method": parsed_method,
                    "asset_version": None,
                    "asset_version_token": None,
                    "marker_format": "stable",
                }

        legacy_pattern = rf"^{re.escape(MARKER_PREFIX)}([A-Z0-9_-]+)_([A-Z0-9]+){re.escape(MARKER_SUFFIX)}$"
        legacy_match = re.match(legacy_pattern, marker_name)
        if not legacy_match:
            return None

        asset_version_token = legacy_match.group(1).upper()
        parsed_method = legacy_match.group(2).lower()
        if parsed_method not in SUPPORTED_METHODS:
            return None

        known_asset = KNOWN_DLSS_ENABLER_ASSETS_BY_TOKEN.get(asset_version_token)
        return {
            "method": parsed_method,
            "asset_version": known_asset["version"] if known_asset else None,
            "asset_version_token": asset_version_token,
            "marker_format": "legacy",
        }

    def _marker_method_from_name(self, marker_name: str) -> str | None:
        parsed = self._parse_marker_name(marker_name)
        return parsed.get("method") if parsed else None

    def _asset_info_for_version(self, version: str | None) -> dict | None:
        if not version:
            return None
        return KNOWN_DLSS_ENABLER_ASSETS_BY_VERSION.get(str(version))

    def _asset_info_for_sha256(self, sha256: str | None) -> dict | None:
        if not sha256:
            return None
        return KNOWN_DLSS_ENABLER_ASSETS_BY_SHA256.get(str(sha256).lower())

    def _steam_root_candidates(self) -> list[Path]:
        home = self._home_path()
        candidates = [
            home / ".local" / "share" / "Steam",
            home / ".steam" / "steam",
            home / ".steam" / "root",
            home / ".var" / "app" / "com.valvesoftware.Steam" / "home" / ".local" / "share" / "Steam",
            home / ".var" / "app" / "com.valvesoftware.Steam" / "home" / ".steam" / "steam",
        ]

        unique: list[Path] = []
        seen = set()
        for candidate in candidates:
            key = str(candidate)
            if key not in seen:
                unique.append(candidate)
                seen.add(key)
        return unique

    def _steam_library_paths(self) -> list[Path]:
        library_paths: list[Path] = []
        seen = set()

        for steam_root in self._steam_root_candidates():
            if steam_root.exists():
                key = str(steam_root)
                if key not in seen:
                    library_paths.append(steam_root)
                    seen.add(key)

            library_file = steam_root / "steamapps" / "libraryfolders.vdf"
            if not library_file.exists():
                continue

            try:
                with open(library_file, "r", encoding="utf-8", errors="replace") as file:
                    for line in file:
                        if '"path"' not in line:
                            continue
                        path = line.split('"path"', 1)[1].strip().strip('"').replace("\\\\", "/")
                        candidate = Path(path)
                        key = str(candidate)
                        if key not in seen:
                            library_paths.append(candidate)
                            seen.add(key)
            except Exception as exc:
                self._log(f"failed to parse libraryfolders: {library_file} error={exc}")

        return library_paths

    def _find_installed_games(self, appid: str | None = None) -> list[dict]:
        games: list[dict] = []

        for library_path in self._steam_library_paths():
            steamapps_path = library_path / "steamapps"
            if not steamapps_path.exists():
                continue

            for appmanifest in steamapps_path.glob("appmanifest_*.acf"):
                game_info = {
                    "appid": "",
                    "name": "",
                    "library_path": str(library_path),
                    "install_path": "",
                }
                install_dir = ""
                try:
                    with open(appmanifest, "r", encoding="utf-8", errors="replace") as file:
                        for line in file:
                            if '"appid"' in line:
                                game_info["appid"] = line.split('"appid"', 1)[1].strip().strip('"')
                            elif '"name"' in line:
                                game_info["name"] = line.split('"name"', 1)[1].strip().strip('"')
                            elif '"installdir"' in line:
                                install_dir = line.split('"installdir"', 1)[1].strip().strip('"')
                except Exception as exc:
                    self._log(f"skipping manifest {appmanifest}: {exc}")
                    continue

                if not game_info["appid"] or not game_info["name"]:
                    continue
                if "Proton" in game_info["name"] or "Steam Linux Runtime" in game_info["name"]:
                    continue

                install_path = steamapps_path / "common" / install_dir if install_dir else Path()
                game_info["install_path"] = str(install_path)

                if appid is None or str(game_info["appid"]) == str(appid):
                    games.append(game_info)

        deduped: dict[str, dict] = {}
        for game in games:
            deduped[str(game["appid"])] = game
        return sorted(deduped.values(), key=lambda entry: entry["name"].lower())

    def _compatdata_dirs_for_appid(self, appid: str) -> list[Path]:
        matches: list[Path] = []
        for library in self._steam_library_paths():
            compatdata_dir = library / "steamapps" / "compatdata" / str(appid)
            if compatdata_dir.exists():
                matches.append(compatdata_dir)
        return matches

    def _game_record(self, appid: str) -> dict | None:
        matches = self._find_installed_games(appid)
        return matches[0] if matches else None

    def _normalized_path_string(self, value: str) -> str:
        normalized = value.lower().replace("\\", "/")
        normalized = normalized.replace("z:/", "/")
        normalized = normalized.replace("//", "/")
        return normalized

    def _candidate_executables(self, install_root: Path) -> list[Path]:
        if not install_root.exists():
            return []

        candidates: list[Path] = []
        try:
            for exe in install_root.rglob("*.exe"):
                if not exe.is_file():
                    continue
                candidates.append(exe)
        except Exception as exc:
            self._log(f"candidate exe scan failed for {install_root}: {exc}")
        return candidates

    def _exe_score(self, exe: Path, install_root: Path, game_name: str) -> int:
        normalized = self._normalized_path_string(str(exe))
        name = exe.name.lower()
        score = 0

        if normalized.endswith("-win64-shipping.exe"):
            score += 300
        if "shipping.exe" in name:
            score += 220
        if "/binaries/win64/" in normalized:
            score += 200
        if "/win64/" in normalized:
            score += 80
        if exe.parent == install_root:
            score += 20

        sanitized_game = re.sub(r"[^a-z0-9]", "", game_name.lower())
        sanitized_name = re.sub(r"[^a-z0-9]", "", exe.stem.lower())
        sanitized_root = re.sub(r"[^a-z0-9]", "", install_root.name.lower())
        if sanitized_game and sanitized_game in sanitized_name:
            score += 120
        if sanitized_root and sanitized_root in sanitized_name:
            score += 90

        for bad in BAD_EXE_SUBSTRINGS:
            if bad in normalized:
                score -= 200

        score -= len(exe.parts)
        return score

    def _best_running_executable(self, candidates: list[Path]) -> Path | None:
        if not candidates:
            return None

        try:
            result = subprocess.run(["ps", "-eo", "args="], capture_output=True, text=True, check=False)
            process_lines = result.stdout.splitlines()
        except Exception as exc:
            self._log(f"running executable scan failed: {exc}")
            return None

        normalized_candidates = [(exe, self._normalized_path_string(str(exe))) for exe in candidates]
        matches: list[tuple[int, Path]] = []
        for line in process_lines:
            normalized_line = self._normalized_path_string(line)
            for exe, normalized_exe in normalized_candidates:
                if normalized_exe in normalized_line:
                    matches.append((len(normalized_exe), exe))

        if not matches:
            return None
        matches.sort(key=lambda item: item[0], reverse=True)
        return matches[0][1]

    def _guess_patch_target(self, game_info: dict) -> tuple[Path, Path | None]:
        install_root = Path(game_info["install_path"])
        candidates = self._candidate_executables(install_root)
        if not candidates:
            return install_root, None

        running_exe = self._best_running_executable(candidates)
        if running_exe:
            return running_exe.parent, running_exe

        best = max(candidates, key=lambda exe: self._exe_score(exe, install_root, game_info["name"]))
        return best.parent, best

    def _find_markers_under_install_root(self, install_root: Path) -> list[Path]:
        if not install_root.exists():
            return []

        markers: list[Path] = []
        try:
            for marker in install_root.rglob(f"{MARKER_PREFIX}*{MARKER_SUFFIX}"):
                parsed = self._parse_marker_name(marker.name)
                if marker.is_file() and parsed and parsed.get("method"):
                    markers.append(marker)
        except Exception as exc:
            self._log(f"marker scan failed under {install_root}: {exc}")

        return sorted(markers, key=lambda path: path.stat().st_mtime, reverse=True)

    def _read_marker_metadata(self, marker_path: Path) -> dict:
        parsed_name = self._parse_marker_name(marker_path.name) or {}
        metadata = {
            "marker_name": marker_path.name,
            "marker_format": parsed_name.get("marker_format"),
            "method": parsed_name.get("method"),
            "asset_version": parsed_name.get("asset_version"),
            "asset_version_token": parsed_name.get("asset_version_token"),
            "original_launch_options": "",
            "backup_created": False,
            "fsr4_enabled": False,
            "fsr4_bundle_id": None,
            "optipatcher_enabled": False,
            "optipatcher_id": None,
            "managed_files": [],
        }
        try:
            parsed = self._read_json_file(marker_path)
            if parsed:
                metadata.update(parsed)
        except Exception:
            pass

        if not metadata.get("method"):
            metadata["method"] = parsed_name.get("method")
        if not metadata.get("marker_format"):
            metadata["marker_format"] = parsed_name.get("marker_format")
        if not metadata.get("asset_version"):
            metadata["asset_version"] = parsed_name.get("asset_version")
        if not metadata.get("asset_version_token"):
            metadata["asset_version_token"] = parsed_name.get("asset_version_token")

        asset_from_version = self._asset_info_for_version(metadata.get("asset_version"))
        if not metadata.get("asset_sha256") and asset_from_version:
            metadata["asset_sha256"] = asset_from_version["sha256"]
        if not metadata.get("release_tag") and asset_from_version:
            metadata["release_tag"] = asset_from_version.get("release_tag")

        return metadata

    def _write_marker_metadata(
        self,
        marker_path: Path,
        *,
        appid: str,
        game_name: str,
        method: str,
        target_dir: Path,
        target_exe: Path | None,
        original_launch_options: str,
        backup_created: bool,
        fsr4_enabled: bool = False,
        fsr4_bundle_id: str | None = None,
        optipatcher_enabled: bool = False,
        optipatcher_id: str | None = None,
        managed_files: list[dict] | None = None,
    ) -> None:
        payload = {
            "appid": str(appid),
            "game_name": game_name,
            "marker_format": "stable",
            "method": self._normalize_method(method),
            "proxy_filename": f"{self._normalize_method(method)}.dll",
            "asset_name": BUNDLED_ASSET_NAME,
            "asset_sha256": BUNDLED_ASSET_SHA256,
            "asset_version": DLSS_ENABLER_VERSION,
            "release_tag": KNOWN_DLSS_ENABLER_ASSETS_BY_VERSION[DLSS_ENABLER_VERSION].get("release_tag"),
            "target_dir": str(target_dir),
            "target_exe": str(target_exe) if target_exe else "",
            "original_launch_options": original_launch_options,
            "backup_created": bool(backup_created),
            "fsr4_enabled": bool(fsr4_enabled),
            "fsr4_bundle_id": fsr4_bundle_id if fsr4_enabled else None,
            "optipatcher_enabled": bool(optipatcher_enabled),
            "optipatcher_id": optipatcher_id if optipatcher_enabled else None,
            "managed_files": managed_files or [],
            "patched_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write_json_file(marker_path, payload)

    def _describe_path(self, path: Path) -> dict:
        exists = path.exists() or path.is_symlink()
        description = {
            "path": str(path),
            "exists": exists,
            "is_symlink": path.is_symlink(),
        }
        if not exists:
            return description

        try:
            stat_result = path.lstat() if path.is_symlink() else path.stat()
            description["size"] = stat_result.st_size
        except Exception:
            pass

        if path.is_symlink():
            try:
                description["symlink_target"] = os.readlink(path)
            except Exception:
                pass
        else:
            sha = self._safe_sha256(path)
            if sha:
                description["sha256"] = sha
        return description

    def _log_target_state(self, prefix: str, target_dir: Path, method: str) -> None:
        normalized_method = self._normalize_method(method)
        proxy_filename = f"{normalized_method}.dll"
        proxy_path = target_dir / proxy_filename
        backup_path = target_dir / f"{proxy_filename}{BACKUP_SUFFIX}"
        marker_path = target_dir / self._marker_filename(normalized_method)
        self._log(
            f"{prefix}: proxy={json.dumps(self._describe_path(proxy_path), sort_keys=True)} "
            f"backup={json.dumps(self._describe_path(backup_path), sort_keys=True)} "
            f"marker={json.dumps(self._describe_path(marker_path), sort_keys=True)}"
        )

    def _is_bundled_proxy_file(self, path: Path) -> bool:
        try:
            return path.is_file() and self._file_sha256(path).lower() == BUNDLED_ASSET_SHA256.lower()
        except Exception:
            return False

    def _installed_asset_state(self, proxy_path: Path, metadata: dict) -> dict:
        marker_asset_sha256 = str(metadata.get("asset_sha256") or "") or None
        marker_asset_version = str(metadata.get("asset_version") or "") or None
        proxy_sha256 = self._safe_sha256(proxy_path)
        proxy_asset = self._asset_info_for_sha256(proxy_sha256) if proxy_sha256 else None
        marker_asset = self._asset_info_for_version(marker_asset_version) or self._asset_info_for_sha256(marker_asset_sha256)

        installed_asset_version = None
        if proxy_asset:
            installed_asset_version = proxy_asset["version"]
        elif marker_asset:
            installed_asset_version = marker_asset["version"]

        integrity_ok = None
        if proxy_sha256 and marker_asset_sha256:
            integrity_ok = proxy_sha256.lower() == marker_asset_sha256.lower()

        upgrade_available = False
        if proxy_sha256 and proxy_sha256.lower() != BUNDLED_ASSET_SHA256.lower() and proxy_asset:
            upgrade_available = True
        elif marker_asset_sha256 and marker_asset_sha256.lower() != BUNDLED_ASSET_SHA256.lower() and marker_asset:
            upgrade_available = True

        reinstall_recommended = bool(proxy_sha256 and integrity_ok is False)

        return {
            "marker_asset_version": marker_asset["version"] if marker_asset else marker_asset_version,
            "marker_asset_sha256": marker_asset["sha256"] if marker_asset else marker_asset_sha256,
            "installed_asset_version": installed_asset_version,
            "installed_asset_sha256": proxy_sha256 or marker_asset_sha256,
            "proxy_sha256": proxy_sha256,
            "bundled_asset_version": DLSS_ENABLER_VERSION,
            "bundled_asset_sha256": BUNDLED_ASSET_SHA256,
            "upgrade_available": upgrade_available,
            "reinstall_recommended": reinstall_recommended,
            "integrity_ok": integrity_ok,
        }

    def _managed_feature_file_state(self, expected_files: list[dict]) -> dict:
        installed_files: list[dict] = []
        integrity_values: list[bool] = []

        for managed_file in expected_files:
            target_path_value = managed_file.get("target_path") or managed_file.get("path")
            if not target_path_value:
                continue
            target_path = Path(str(target_path_value))
            expected_sha256 = str(managed_file.get("sha256") or "") or None
            actual_sha256 = self._safe_sha256(target_path)
            exists = target_path.exists() or target_path.is_symlink()
            integrity_ok = None
            if actual_sha256 and expected_sha256:
                integrity_ok = actual_sha256.lower() == expected_sha256.lower()
                integrity_values.append(integrity_ok)
            installed_files.append(
                {
                    "name": managed_file.get("target_name") or target_path.name,
                    "target_path": str(target_path),
                    "expected_sha256": expected_sha256,
                    "actual_sha256": actual_sha256,
                    "exists": exists,
                    "integrity_ok": integrity_ok,
                }
            )

        return {
            "files": installed_files,
            "files_present": any(entry["exists"] for entry in installed_files),
            "files_complete": bool(installed_files) and all(entry["exists"] for entry in installed_files),
            "integrity_ok": None if not installed_files else all(value is not False for value in integrity_values),
            "reinstall_recommended": any(value is False for value in integrity_values),
        }

    def _fsr4_bundle_state(self, target_dir: Path, metadata: dict) -> dict:
        expected_bundle_id = metadata.get("fsr4_bundle_id")
        expected_files = [
            managed_file
            for managed_file in (metadata.get("managed_files") or [])
            if managed_file.get("kind") in {"ffx-loader", "fsr4-upscaler", "optiscaler-config"}
        ]
        feature_state = self._managed_feature_file_state(expected_files)
        fsr4_enabled = bool(metadata.get("fsr4_enabled") or expected_bundle_id)

        return {
            "fsr4_enabled": fsr4_enabled,
            "fsr4_bundle_id": expected_bundle_id,
            "fsr4_label": FSR4_INT8_BUNDLE["label"] if fsr4_enabled else None,
            "fsr4_optiscaler_version": FSR4_INT8_BUNDLE["optiscaler_version"] if fsr4_enabled else None,
            "fsr4_files_present": feature_state["files_present"],
            "fsr4_files_complete": feature_state["files_complete"],
            "fsr4_integrity_ok": feature_state["integrity_ok"],
            "fsr4_reinstall_recommended": feature_state["reinstall_recommended"],
            "fsr4_managed_files": feature_state["files"],
        }

    def _optipatcher_state(self, target_dir: Path, metadata: dict) -> dict:
        expected_plugin_id = metadata.get("optipatcher_id")
        expected_files = [
            managed_file
            for managed_file in (metadata.get("managed_files") or [])
            if managed_file.get("kind") in {"optipatcher-plugin", "optiscaler-config"}
        ]
        feature_state = self._managed_feature_file_state(expected_files)
        optipatcher_enabled = bool(metadata.get("optipatcher_enabled") or expected_plugin_id)

        return {
            "optipatcher_enabled": optipatcher_enabled,
            "optipatcher_id": expected_plugin_id,
            "optipatcher_label": OPTIPATCHER_PLUGIN["label"] if optipatcher_enabled else None,
            "optipatcher_files_present": feature_state["files_present"],
            "optipatcher_files_complete": feature_state["files_complete"],
            "optipatcher_integrity_ok": feature_state["integrity_ok"],
            "optipatcher_reinstall_recommended": feature_state["reinstall_recommended"],
            "optipatcher_managed_files": feature_state["files"],
        }

    def _install_managed_optiscaler_support(
        self,
        target_dir: Path,
        *,
        enable_fsr4: bool = False,
        enable_optipatcher: bool = False,
        config_overrides: dict[str, dict[str, str]] | None = None,
    ) -> list[dict]:
        managed_files: list[dict] = []

        if enable_fsr4:
            verified_assets = self._verify_fsr4_bundle_assets()
            for asset in verified_assets:
                target_path = target_dir / asset["target_name"]
                backup_created = self._prepare_managed_file(target_path, asset["sha256"])
                shutil.copy2(asset["path"], target_path)
                copied_hash = self._file_sha256(target_path)
                if copied_hash.lower() != asset["sha256"].lower():
                    raise RuntimeError(
                        f"Copied FSR4 sidecar hash mismatch for {target_path.name}: expected {asset['sha256']}, got {copied_hash}"
                    )
                managed_files.append(
                    {
                        "kind": asset["kind"],
                        "asset_name": asset["asset_name"],
                        "target_name": asset["target_name"],
                        "target_path": str(target_path),
                        "sha256": asset["sha256"],
                        "backup_created": backup_created,
                    }
                )

        if enable_optipatcher:
            verified_optipatcher = self._verify_optipatcher_asset()
            plugins_dir = target_dir / verified_optipatcher["target_dirname"]
            plugins_dir.mkdir(parents=True, exist_ok=True)
            target_path = plugins_dir / verified_optipatcher["target_name"]
            backup_created = self._prepare_managed_file(target_path, verified_optipatcher["sha256"])
            shutil.copy2(verified_optipatcher["path"], target_path)
            copied_hash = self._file_sha256(target_path)
            if copied_hash.lower() != verified_optipatcher["sha256"].lower():
                raise RuntimeError(
                    f"Copied OptiPatcher hash mismatch for {target_path.name}: expected {verified_optipatcher['sha256']}, got {copied_hash}"
                )
            managed_files.append(
                {
                    "kind": verified_optipatcher["kind"],
                    "asset_name": verified_optipatcher["asset_name"],
                    "target_name": verified_optipatcher["target_name"],
                    "target_path": str(target_path),
                    "sha256": verified_optipatcher["sha256"],
                    "backup_created": backup_created,
                }
            )

        if enable_fsr4 or enable_optipatcher:
            config_path = target_dir / FSR4_CONFIG_FILENAME
            config_text = self._managed_optiscaler_config_contents(
                enable_fsr4=enable_fsr4,
                enable_optipatcher=enable_optipatcher,
                overrides=config_overrides,
            )
            config_bytes = config_text.encode("utf-8")
            config_sha256 = self._bytes_sha256(config_bytes)
            config_backup_created = self._prepare_managed_file(config_path, config_sha256)
            config_path.write_text(config_text, encoding="utf-8")
            written_config_sha256 = self._file_sha256(config_path)
            if written_config_sha256.lower() != config_sha256.lower():
                raise RuntimeError(
                    f"Copied managed OptiScaler config hash mismatch for {config_path.name}: expected {config_sha256}, got {written_config_sha256}"
                )
            managed_files.append(
                {
                    "kind": "optiscaler-config",
                    "asset_name": FSR4_CONFIG_FILENAME,
                    "target_name": FSR4_CONFIG_FILENAME,
                    "target_path": str(config_path),
                    "sha256": config_sha256,
                    "backup_created": config_backup_created,
                }
            )

        return managed_files

    def _unique_stash_path(self, path: Path, label: str) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        base = path.with_name(f"{path.name}.{label}.{timestamp}")
        candidate = base
        counter = 1
        while candidate.exists():
            candidate = path.with_name(f"{base.name}.{counter}")
            counter += 1
        return candidate

    def _remove_path(self, path: Path) -> None:
        if not path.exists() and not path.is_symlink():
            return
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()

    def _is_managed_file_sha(self, path: Path, expected_sha256: str | None) -> bool:
        if not expected_sha256:
            return False
        try:
            return path.is_file() and self._file_sha256(path).lower() == expected_sha256.lower()
        except Exception:
            return False

    def _prepare_managed_file(self, target_path: Path, expected_sha256: str | None) -> bool:
        backup_path = target_path.with_name(f"{target_path.name}{BACKUP_SUFFIX}")
        backup_created = False

        if backup_path.exists() or backup_path.is_symlink():
            stashed_backup = self._unique_stash_path(backup_path, "preexisting-backup")
            backup_path.rename(stashed_backup)
            self._log(f"prepare managed file stashed preexisting backup to {stashed_backup}")

        if target_path.exists() or target_path.is_symlink():
            if self._is_managed_file_sha(target_path, expected_sha256):
                self._remove_path(target_path)
                self._log(f"prepare managed file removed existing managed file {target_path}")
            else:
                target_path.rename(backup_path)
                backup_created = True
                self._log(f"prepare managed file moved existing file to backup {backup_path}")

        return backup_created

    def _restore_managed_file(
        self,
        target_path: Path,
        expected_sha256: str | None,
        *,
        remove_if_unexpected: bool = False,
    ) -> list[str]:
        notes: list[str] = []
        filename = target_path.name
        backup_path = target_path.with_name(f"{filename}{BACKUP_SUFFIX}")

        backup_exists = backup_path.exists() or backup_path.is_symlink()
        file_exists = target_path.exists() or target_path.is_symlink()

        if backup_exists:
            if file_exists:
                if self._is_managed_file_sha(target_path, expected_sha256):
                    self._remove_path(target_path)
                elif remove_if_unexpected:
                    self._remove_path(target_path)
                    notes.append(f"Removed modified {filename}")
                else:
                    stashed_path = self._unique_stash_path(target_path, "unexpected")
                    target_path.rename(stashed_path)
                    notes.append(f"Stashed unexpected {filename} to {stashed_path.name}")
            backup_path.rename(target_path)
            notes.append(f"Restored original {filename}")
        elif file_exists:
            if self._is_managed_file_sha(target_path, expected_sha256):
                self._remove_path(target_path)
                notes.append(f"Removed managed {filename}")
            elif remove_if_unexpected:
                self._remove_path(target_path)
                notes.append(f"Removed modified {filename}")
            else:
                stashed_path = self._unique_stash_path(target_path, "unexpected")
                target_path.rename(stashed_path)
                notes.append(f"Stashed unexpected {filename} to {stashed_path.name}")

        return notes

    def _restore_method_in_dir(self, target_dir: Path, method: str) -> list[str]:
        proxy_filename = f"{self._normalize_method(method)}.dll"
        proxy_path = target_dir / proxy_filename
        return self._restore_managed_file(proxy_path, BUNDLED_ASSET_SHA256)

    def _cleanup_known_runtime_artifacts(self, target_dir: Path) -> list[str]:
        notes: list[str] = []

        for filename in KNOWN_RUNTIME_ARTIFACT_FILENAMES:
            artifact_path = target_dir / filename
            if artifact_path.exists() or artifact_path.is_symlink():
                self._remove_path(artifact_path)
                notes.append(f"Removed runtime artifact {filename}")

        for pattern in KNOWN_RUNTIME_ARTIFACT_GLOBS:
            for artifact_path in sorted(target_dir.glob(pattern)):
                self._remove_path(artifact_path)
                notes.append(f"Removed runtime artifact {artifact_path.name}")

        return notes

    def _cleanup_empty_plugins_dir(self, target_dir: Path) -> list[str]:
        notes: list[str] = []
        plugins_dir = target_dir / OPTIPATCHER_PLUGIN["target_dirname"]
        try:
            if plugins_dir.exists() and plugins_dir.is_dir() and not any(plugins_dir.iterdir()):
                plugins_dir.rmdir()
                notes.append(f"Removed empty {plugins_dir.name} directory")
        except Exception as exc:
            self._log(f"failed to clean empty plugins dir {plugins_dir}: {exc}")
        return notes

    def _cleanup_install_root(self, install_root: Path) -> dict:
        marker_paths = self._find_markers_under_install_root(install_root)
        notes: list[str] = []
        original_launch_options = ""
        cleaned_methods: list[str] = []

        self._log(f"cleanup install root: install_root={install_root} markers={[marker.name for marker in marker_paths]}")
        for marker_path in marker_paths:
            metadata = self._read_marker_metadata(marker_path)
            method = metadata.get("method")
            if not method:
                continue
            if not original_launch_options:
                original_launch_options = str(metadata.get("original_launch_options") or "")

            target_dir = marker_path.parent
            self._log(f"cleanup marker metadata: {json.dumps(metadata, sort_keys=True)}")
            self._log_target_state("cleanup before restore", target_dir, method)

            for managed_file in metadata.get("managed_files") or []:
                target_path_value = managed_file.get("target_path") or managed_file.get("path")
                expected_sha256 = managed_file.get("sha256")
                if not target_path_value:
                    continue
                remove_if_unexpected = managed_file.get("kind") == "optiscaler-config"
                notes.extend(
                    self._restore_managed_file(
                        Path(str(target_path_value)),
                        expected_sha256,
                        remove_if_unexpected=remove_if_unexpected,
                    )
                )

            notes.extend(self._restore_method_in_dir(target_dir, method))
            notes.extend(self._cleanup_known_runtime_artifacts(target_dir))
            notes.extend(self._cleanup_empty_plugins_dir(target_dir))
            cleaned_methods.append(method)
            self._log_target_state("cleanup after restore", target_dir, method)
            try:
                marker_path.unlink()
                self._log(f"cleanup removed marker: {marker_path}")
            except FileNotFoundError:
                pass

        result = {
            "notes": notes,
            "original_launch_options": original_launch_options,
            "cleaned_methods": cleaned_methods,
        }
        self._log(f"cleanup result: {json.dumps(result, sort_keys=True)}")
        return result

    def _prepare_target_proxy(self, target_dir: Path, method: str) -> bool:
        method = self._normalize_method(method)
        proxy_filename = f"{method}.dll"
        proxy_path = target_dir / proxy_filename

        self._log_target_state("prepare before", target_dir, method)
        self._log(
            f"prepare target proxy: target_dir={target_dir} method={method} "
            f"proxy_is_bundled={self._is_bundled_proxy_file(proxy_path)}"
        )

        backup_created = self._prepare_managed_file(proxy_path, BUNDLED_ASSET_SHA256)

        self._log_target_state("prepare after", target_dir, method)
        return backup_created

    def _managed_launch_options(self, method: str) -> str:
        normalized_method = self._normalize_method(method)
        return f"WINEDLLOVERRIDES={normalized_method}=n,b SteamDeck=0 %command%"

    def _is_managed_launch_options(self, raw_command: str) -> bool:
        if not raw_command or not raw_command.strip():
            return False

        normalized_command = " ".join(raw_command.strip().split())
        managed_commands = {self._managed_launch_options(method) for method in SUPPORTED_METHODS}
        legacy_managed_commands = {f"WINEDLLOVERRIDES={method}=n,b" for method in SUPPORTED_METHODS}
        return normalized_command in managed_commands or normalized_command in legacy_managed_commands

    def _original_launch_options_to_restore(self, current_launch_options: str, cleanup_original_launch_options: str = "") -> str:
        if cleanup_original_launch_options and not self._is_managed_launch_options(cleanup_original_launch_options):
            return cleanup_original_launch_options
        if self._is_managed_launch_options(current_launch_options):
            return ""
        return current_launch_options or ""

    def _build_managed_launch_options(self, method: str) -> str:
        return self._managed_launch_options(method)

    def _is_game_running(self, game_info: dict) -> bool:
        install_root = Path(game_info["install_path"])
        candidates = self._candidate_executables(install_root)
        return self._best_running_executable(candidates) is not None

    async def list_installed_games(self) -> dict:
        try:
            games = []
            for game in self._find_installed_games():
                install_root = Path(game["install_path"])
                games.append(
                    {
                        "appid": str(game["appid"]),
                        "name": game["name"],
                        "prefix_exists": install_root.exists(),
                    }
                )
            return {"status": "success", "games": games}
        except Exception as exc:
            self._log(f"list_installed_games failed: {exc}")
            return {"status": "error", "message": str(exc), "games": []}

    async def get_game_status(self, appid: str) -> dict:
        try:
            self._log(f"get_game_status start: appid={appid}")
            game_info = self._game_record(str(appid))
            game_name = game_info["name"] if game_info else str(appid)
            quirks = self._game_quirks_payload(str(appid), game_name)
            if not game_info:
                return {
                    "status": "success",
                    "appid": str(appid),
                    "name": game_name,
                    "prefix_exists": False,
                    "patched": False,
                    "method": None,
                    "proxy_filename": None,
                    "fsr4_enabled": False,
                    "optipatcher_enabled": False,
                    "message": "Game install path could not be resolved.",
                    **quirks,
                }

            install_root = Path(game_info["install_path"])
            if not install_root.exists():
                return {
                    "status": "success",
                    "appid": str(appid),
                    "name": game_name,
                    "prefix_exists": False,
                    "patched": False,
                    "method": None,
                    "proxy_filename": None,
                    "fsr4_enabled": False,
                    "optipatcher_enabled": False,
                    "message": "Game install directory does not exist.",
                    "paths": {
                        "install_root": str(install_root),
                    },
                    **quirks,
                }

            target_dir, target_exe = self._guess_patch_target(game_info)
            markers = self._find_markers_under_install_root(install_root)
            if not markers:
                return {
                    "status": "success",
                    "appid": str(appid),
                    "name": game_name,
                    "prefix_exists": True,
                    "patched": False,
                    "method": None,
                    "proxy_filename": None,
                    "fsr4_enabled": False,
                    "optipatcher_enabled": False,
                    "message": "This game is not currently patched.",
                    "paths": {
                        "install_root": str(install_root),
                        "target_dir": str(target_dir),
                        "target_exe": str(target_exe) if target_exe else "",
                    },
                    **quirks,
                }

            marker = markers[0]
            metadata = self._read_marker_metadata(marker)
            method = self._normalize_method(metadata.get("method") or "version")
            proxy_filename = f"{method}.dll"
            target_dir = marker.parent
            proxy_path = target_dir / proxy_filename
            patched = proxy_path.exists() or proxy_path.is_symlink()
            asset_state = self._installed_asset_state(proxy_path, metadata)
            fsr4_state = self._fsr4_bundle_state(target_dir, metadata)
            optipatcher_state = self._optipatcher_state(target_dir, metadata)
            self._log(f"get_game_status marker metadata: {json.dumps(metadata, sort_keys=True)}")
            self._log(f"get_game_status asset state: {json.dumps(asset_state, sort_keys=True)}")
            self._log(f"get_game_status fsr4 state: {json.dumps(fsr4_state, sort_keys=True)}")
            self._log(f"get_game_status optipatcher state: {json.dumps(optipatcher_state, sort_keys=True)}")
            self._log_target_state("get_game_status", target_dir, method)

            if not patched:
                message = f"Managed marker found for {proxy_filename}, but the proxy DLL is missing."
            elif asset_state["reinstall_recommended"]:
                message = f"Patched using {proxy_filename}, but the on-disk DLL does not match the recorded managed asset. Reinstall recommended."
            elif asset_state["upgrade_available"]:
                installed_version = asset_state.get("installed_asset_version") or asset_state.get("marker_asset_version") or "older version"
                message = (
                    f"Patched using {proxy_filename}. Upgrade available: {installed_version} → {DLSS_ENABLER_VERSION}."
                )
            elif optipatcher_state["optipatcher_reinstall_recommended"]:
                message = f"Patched using {proxy_filename}, but the managed OptiPatcher files do not match the recorded assets. Reinstall recommended."
            else:
                installed_version = asset_state.get("installed_asset_version") or asset_state.get("marker_asset_version")
                message = (
                    f"Patched using {proxy_filename} ({installed_version})."
                    if installed_version
                    else f"Patched using {proxy_filename}."
                )

            return {
                "status": "success",
                "appid": str(appid),
                "name": game_name,
                "prefix_exists": True,
                "patched": patched,
                "method": method,
                "proxy_filename": proxy_filename,
                "marker_name": marker.name,
                "marker_format": metadata.get("marker_format"),
                "message": message,
                "bundled_asset_version": asset_state["bundled_asset_version"],
                "bundled_asset_sha256": asset_state["bundled_asset_sha256"],
                "marker_asset_version": asset_state["marker_asset_version"],
                "marker_asset_sha256": asset_state["marker_asset_sha256"],
                "installed_asset_version": asset_state["installed_asset_version"],
                "installed_asset_sha256": asset_state["installed_asset_sha256"],
                "proxy_sha256": asset_state["proxy_sha256"],
                "upgrade_available": asset_state["upgrade_available"],
                "reinstall_recommended": asset_state["reinstall_recommended"],
                "integrity_ok": asset_state["integrity_ok"],
                "fsr4_enabled": fsr4_state["fsr4_enabled"],
                "fsr4_bundle_id": fsr4_state["fsr4_bundle_id"],
                "fsr4_label": fsr4_state["fsr4_label"],
                "fsr4_optiscaler_version": fsr4_state["fsr4_optiscaler_version"],
                "fsr4_files_present": fsr4_state["fsr4_files_present"],
                "fsr4_files_complete": fsr4_state["fsr4_files_complete"],
                "fsr4_integrity_ok": fsr4_state["fsr4_integrity_ok"],
                "fsr4_reinstall_recommended": fsr4_state["fsr4_reinstall_recommended"],
                "optipatcher_enabled": optipatcher_state["optipatcher_enabled"],
                "optipatcher_id": optipatcher_state["optipatcher_id"],
                "optipatcher_label": optipatcher_state["optipatcher_label"],
                "optipatcher_files_present": optipatcher_state["optipatcher_files_present"],
                "optipatcher_files_complete": optipatcher_state["optipatcher_files_complete"],
                "optipatcher_integrity_ok": optipatcher_state["optipatcher_integrity_ok"],
                "optipatcher_reinstall_recommended": optipatcher_state["optipatcher_reinstall_recommended"],
                "paths": {
                    "install_root": str(install_root),
                    "target_dir": str(target_dir),
                    "target_exe": str(metadata.get("target_exe") or ""),
                },
                **quirks,
            }
        except Exception as exc:
            self._log(f"get_game_status failed for {appid}: {exc}")
            return {"status": "error", "message": str(exc)}

    async def patch_game(
        self,
        appid: str,
        method: str,
        current_launch_options: str = "",
        enable_fsr4: bool = False,
        apply_recommendations: bool = False,
        enable_optipatcher: bool = False,
    ) -> dict:
        try:
            requested_method = self._normalize_method(method)
            asset_path = self._verify_bundled_asset()
            game_info = self._game_record(str(appid))
            if not game_info:
                return {"status": "error", "message": "Game install path could not be resolved."}

            quirks = self._game_quirks_payload(str(appid), game_info["name"])
            effective_method = requested_method
            if apply_recommendations and quirks.get("recommended_method"):
                effective_method = self._normalize_method(str(quirks.get("recommended_method")))
            effective_optipatcher = bool(enable_optipatcher or (apply_recommendations and quirks.get("recommended_optipatcher")))

            self._log(
                f"patch_game start: appid={appid} requested_method={requested_method} effective_method={effective_method} "
                f"enable_fsr4={enable_fsr4} enable_optipatcher={effective_optipatcher} apply_recommendations={apply_recommendations} "
                f"original_launch_options={json.dumps(current_launch_options)}"
            )

            if self._is_game_running(game_info):
                return {"status": "error", "message": "Close the game before patching."}

            install_root = Path(game_info["install_path"])
            if not install_root.exists():
                return {"status": "error", "message": "Game install directory does not exist."}

            target_dir, target_exe = self._guess_patch_target(game_info)
            target_dir.mkdir(parents=True, exist_ok=True)
            self._log(
                f"patch_game target selection: install_root={install_root} target_dir={target_dir} target_exe={target_exe}"
            )
            self._log_target_state("patch before cleanup", target_dir, effective_method)

            cleanup_result = self._cleanup_install_root(install_root)
            original_launch_options = self._original_launch_options_to_restore(
                current_launch_options or "",
                str(cleanup_result.get("original_launch_options") or ""),
            )
            self._log(
                f"patch after cleanup: original_launch_options={json.dumps(original_launch_options)} cleanup_result={json.dumps(cleanup_result, sort_keys=True)}"
            )

            backup_created = self._prepare_target_proxy(target_dir, effective_method)
            target_proxy_path = target_dir / f"{effective_method}.dll"
            self._log(f"patch copy start: source={asset_path} target={target_proxy_path}")
            shutil.copy2(asset_path, target_proxy_path)
            self._log_target_state("patch after copy", target_dir, effective_method)

            copied_hash = self._file_sha256(target_proxy_path)
            if copied_hash.lower() != BUNDLED_ASSET_SHA256.lower():
                raise RuntimeError(
                    f"Copied proxy hash mismatch for {target_proxy_path.name}: expected {BUNDLED_ASSET_SHA256}, got {copied_hash}"
                )

            managed_files: list[dict] = []
            config_overrides = quirks.get("recommended_optiscaler_ini_overrides") if apply_recommendations else None
            if enable_fsr4 or effective_optipatcher:
                managed_files = self._install_managed_optiscaler_support(
                    target_dir,
                    enable_fsr4=enable_fsr4,
                    enable_optipatcher=effective_optipatcher,
                    config_overrides=config_overrides,
                )
                self._log(f"patch installed managed OptiScaler support: {json.dumps(managed_files, sort_keys=True)}")

            marker_path = target_dir / self._marker_filename(effective_method)
            self._write_marker_metadata(
                marker_path,
                appid=str(appid),
                game_name=game_info["name"],
                method=effective_method,
                target_dir=target_dir,
                target_exe=target_exe,
                original_launch_options=original_launch_options,
                backup_created=backup_created,
                fsr4_enabled=enable_fsr4,
                fsr4_bundle_id=FSR4_INT8_BUNDLE["id"] if enable_fsr4 else None,
                optipatcher_enabled=effective_optipatcher,
                optipatcher_id=OPTIPATCHER_PLUGIN["id"] if effective_optipatcher else None,
                managed_files=managed_files,
            )
            self._log(f"patch wrote marker: {json.dumps(self._read_marker_metadata(marker_path), sort_keys=True)}")

            managed_launch_options = self._build_managed_launch_options(effective_method)
            self._log(f"patch managed launch options: {json.dumps(managed_launch_options)}")

            result = {
                "status": "success",
                "appid": str(appid),
                "name": game_info["name"],
                "method": effective_method,
                "proxy_filename": f"{effective_method}.dll",
                "marker_name": marker_path.name,
                "bundled_asset_version": DLSS_ENABLER_VERSION,
                "bundled_asset_sha256": BUNDLED_ASSET_SHA256,
                "fsr4_enabled": enable_fsr4,
                "fsr4_bundle_id": FSR4_INT8_BUNDLE["id"] if enable_fsr4 else None,
                "fsr4_label": FSR4_INT8_BUNDLE["label"] if enable_fsr4 else None,
                "optipatcher_enabled": effective_optipatcher,
                "optipatcher_id": OPTIPATCHER_PLUGIN["id"] if effective_optipatcher else None,
                "optipatcher_label": OPTIPATCHER_PLUGIN["label"] if effective_optipatcher else None,
                "launch_options": managed_launch_options,
                "original_launch_options": original_launch_options,
                "message": (
                    f"Patched {game_info['name']} using {effective_method}.dll"
                    + (
                        " with "
                        + ", ".join(
                            component
                            for component in [
                                FSR4_INT8_BUNDLE["label"] if enable_fsr4 else "",
                                OPTIPATCHER_PLUGIN["label"] if effective_optipatcher else "",
                            ]
                            if component
                        )
                        if (enable_fsr4 or effective_optipatcher)
                        else ""
                    )
                    + "."
                ),
                "paths": {
                    "install_root": str(install_root),
                    "target_dir": str(target_dir),
                    "target_exe": str(target_exe) if target_exe else "",
                    "proxy": str(target_proxy_path),
                    "marker": str(marker_path),
                },
            }
            self._log_target_state("patch success final state", target_dir, effective_method)
            self._log(f"patch success: {json.dumps(result, sort_keys=True)}")
            return result
        except Exception as exc:
            decky.logger.error(f"[DLSS Enabler] patch_game failed for {appid}: {exc}")
            return {"status": "error", "message": str(exc)}

    async def unpatch_game(self, appid: str) -> dict:
        try:
            self._log(f"unpatch_game start: appid={appid}")
            game_info = self._game_record(str(appid))
            if not game_info:
                return {"status": "success", "appid": str(appid), "launch_options": "", "message": "Game install path could not be resolved."}

            if self._is_game_running(game_info):
                return {"status": "error", "message": "Close the game before unpatching."}

            install_root = Path(game_info["install_path"])
            if not install_root.exists():
                return {
                    "status": "success",
                    "appid": str(appid),
                    "name": game_info["name"],
                    "launch_options": "",
                    "message": "Game install directory does not exist.",
                }

            markers = self._find_markers_under_install_root(install_root)
            self._log(f"unpatch markers: {[marker.name for marker in markers]}")
            for marker in markers:
                marker_method = self._marker_method_from_name(marker.name)
                if marker_method:
                    self._log_target_state("unpatch before cleanup", marker.parent, marker_method)

            if not markers:
                return {
                    "status": "success",
                    "appid": str(appid),
                    "name": game_info["name"],
                    "launch_options": "",
                    "message": "No managed DLSS Enabler marker was found for this game.",
                    "paths": {
                        "install_root": str(install_root),
                    },
                }

            cleanup_result = self._cleanup_install_root(install_root)
            restored_launch_options = str(cleanup_result.get("original_launch_options") or "")
            if self._is_managed_launch_options(restored_launch_options):
                restored_launch_options = ""

            cleaned_methods = cleanup_result.get("cleaned_methods") or []
            methods_display = ", ".join(f"{method}.dll" for method in cleaned_methods) if cleaned_methods else "managed proxy"
            result = {
                "status": "success",
                "appid": str(appid),
                "name": game_info["name"],
                "launch_options": restored_launch_options,
                "message": f"Unpatched {game_info['name']} and restored {methods_display}.",
                "paths": {
                    "install_root": str(install_root),
                },
                "notes": cleanup_result.get("notes") or [],
            }
            self._log(f"unpatch success: {json.dumps(result, sort_keys=True)}")
            return result
        except Exception as exc:
            decky.logger.error(f"[DLSS Enabler] unpatch_game failed for {appid}: {exc}")
            return {"status": "error", "message": str(exc)}
