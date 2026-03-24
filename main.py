import json
import hashlib
import os
import re
import shlex
import shutil
from datetime import datetime, timezone
from pathlib import Path

import decky

PLUGIN_NAME = "decky-dlss-enabler"
BUNDLED_ASSET_NAME = "version.dll"
BUNDLED_ASSET_SHA256 = "a07b82de96e8c278184fe01409d7b4851a67865f7b8fed56332e40028dc3b41f"
DLSS_ENABLER_VERSION = "4.3.1.0"
DLSS_ENABLER_VERSION_TOKEN = DLSS_ENABLER_VERSION.replace(".", "_")
MARKER_PREFIX = f"DLSS_ENABLER_{DLSS_ENABLER_VERSION_TOKEN}_"
MARKER_SUFFIX = "_DLL"
BACKUP_SUFFIX = ".backup"

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


class Plugin:
    async def _main(self):
        decky.logger.info("DLSS Enabler plugin loaded")

    async def _unload(self):
        decky.logger.info("DLSS Enabler plugin unloaded")

    async def _uninstall(self):
        decky.logger.info("DLSS Enabler plugin uninstalled")

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

    def _file_sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _verify_bundled_asset(self) -> Path:
        asset_path = self._bundled_asset_path()
        if not asset_path.exists():
            raise FileNotFoundError(f"Bundled asset missing: {asset_path}")

        asset_hash = self._file_sha256(asset_path)
        if asset_hash.lower() != BUNDLED_ASSET_SHA256.lower():
            raise RuntimeError(
                f"Bundled asset hash mismatch for {asset_path.name}: expected {BUNDLED_ASSET_SHA256}, got {asset_hash}"
            )
        return asset_path

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
                decky.logger.error(f"Failed to parse {library_file}: {exc}")

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
                }
                try:
                    with open(appmanifest, "r", encoding="utf-8", errors="replace") as file:
                        for line in file:
                            if '"appid"' in line:
                                game_info["appid"] = line.split('"appid"', 1)[1].strip().strip('"')
                            if '"name"' in line:
                                game_info["name"] = line.split('"name"', 1)[1].strip().strip('"')
                except Exception as exc:
                    decky.logger.error(f"Skipping {appmanifest}: {exc}")
                    continue

                if not game_info["appid"] or not game_info["name"]:
                    continue
                if "Proton" in game_info["name"] or "Steam Linux Runtime" in game_info["name"]:
                    continue
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

    def _prefix_paths_for_appid(self, appid: str) -> dict | None:
        compatdata_dirs = self._compatdata_dirs_for_appid(str(appid))
        if not compatdata_dirs:
            return None

        compatdata_dir = compatdata_dirs[0]
        system32 = compatdata_dir / "pfx" / "drive_c" / "windows" / "system32"
        return {
            "compatdata_dir": compatdata_dir,
            "system32": system32,
        }

    def _normalize_method(self, method: str | None) -> str:
        normalized = (method or "version").replace(".dll", "").strip().lower()
        if normalized not in SUPPORTED_METHODS:
            raise ValueError(f"Unsupported injection method '{method}'")
        return normalized

    def _marker_filename(self, method: str) -> str:
        return f"{MARKER_PREFIX}{self._normalize_method(method).upper()}{MARKER_SUFFIX}"

    def _marker_method_from_name(self, marker_name: str) -> str | None:
        pattern = rf"^{re.escape(MARKER_PREFIX)}([A-Z0-9]+){re.escape(MARKER_SUFFIX)}$"
        match = re.match(pattern, marker_name)
        if not match:
            return None
        parsed = match.group(1).lower()
        return parsed if parsed in SUPPORTED_METHODS else None

    def _marker_paths(self, system32: Path) -> list[Path]:
        if not system32.exists():
            return []

        markers: list[Path] = []
        for entry in system32.iterdir():
            if not entry.is_file():
                continue
            if self._marker_method_from_name(entry.name):
                markers.append(entry)

        return sorted(markers, key=lambda path: path.stat().st_mtime, reverse=True)

    def _read_marker_metadata(self, marker_path: Path) -> dict:
        metadata = {
            "marker_name": marker_path.name,
            "method": self._marker_method_from_name(marker_path.name),
            "original_launch_options": "",
            "backup_created": False,
        }

        try:
            with open(marker_path, "r", encoding="utf-8", errors="replace") as file:
                raw = file.read().strip()
            if raw:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    metadata.update(parsed)
        except Exception:
            pass

        if not metadata.get("method"):
            metadata["method"] = self._marker_method_from_name(marker_path.name)

        return metadata

    def _write_marker_metadata(
        self,
        marker_path: Path,
        *,
        appid: str,
        game_name: str,
        method: str,
        original_launch_options: str,
        backup_created: bool,
    ) -> None:
        payload = {
            "appid": str(appid),
            "game_name": game_name,
            "method": self._normalize_method(method),
            "proxy_filename": f"{self._normalize_method(method)}.dll",
            "asset_name": BUNDLED_ASSET_NAME,
            "asset_sha256": BUNDLED_ASSET_SHA256,
            "asset_version": DLSS_ENABLER_VERSION,
            "original_launch_options": original_launch_options,
            "backup_created": bool(backup_created),
            "patched_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(marker_path, "w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, sort_keys=True)

    def _is_bundled_proxy_file(self, path: Path) -> bool:
        try:
            return path.is_file() and self._file_sha256(path).lower() == BUNDLED_ASSET_SHA256.lower()
        except Exception:
            return False

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

    def _restore_method(self, system32: Path, method: str) -> list[str]:
        notes: list[str] = []
        proxy_filename = f"{self._normalize_method(method)}.dll"
        proxy_path = system32 / proxy_filename
        backup_path = system32 / f"{proxy_filename}{BACKUP_SUFFIX}"

        backup_exists = backup_path.exists() or backup_path.is_symlink()
        proxy_exists = proxy_path.exists() or proxy_path.is_symlink()

        if backup_exists:
            if proxy_exists:
                if self._is_bundled_proxy_file(proxy_path):
                    self._remove_path(proxy_path)
                else:
                    stashed_path = self._unique_stash_path(proxy_path, "unexpected")
                    proxy_path.rename(stashed_path)
                    notes.append(f"Stashed unexpected {proxy_filename} to {stashed_path.name}")
            backup_path.rename(proxy_path)
            notes.append(f"Restored original {proxy_filename}")
        elif proxy_exists:
            if self._is_bundled_proxy_file(proxy_path):
                self._remove_path(proxy_path)
                notes.append(f"Removed managed {proxy_filename}")
            else:
                stashed_path = self._unique_stash_path(proxy_path, "unexpected")
                proxy_path.rename(stashed_path)
                notes.append(f"Stashed unexpected {proxy_filename} to {stashed_path.name}")

        return notes

    def _cleanup_managed_state(self, system32: Path) -> dict:
        marker_paths = self._marker_paths(system32)
        notes: list[str] = []
        original_launch_options = ""
        cleaned_methods: list[str] = []

        for marker_path in marker_paths:
            metadata = self._read_marker_metadata(marker_path)
            method = metadata.get("method")
            if not method:
                continue
            if not original_launch_options:
                original_launch_options = str(metadata.get("original_launch_options") or "")
            notes.extend(self._restore_method(system32, method))
            cleaned_methods.append(method)
            try:
                marker_path.unlink()
            except FileNotFoundError:
                pass

        return {
            "notes": notes,
            "original_launch_options": original_launch_options,
            "cleaned_methods": cleaned_methods,
        }

    def _prepare_target_proxy(self, system32: Path, method: str) -> bool:
        method = self._normalize_method(method)
        proxy_filename = f"{method}.dll"
        proxy_path = system32 / proxy_filename
        backup_path = system32 / f"{proxy_filename}{BACKUP_SUFFIX}"
        backup_created = False

        marker_for_method = system32 / self._marker_filename(method)
        same_method_already_managed = marker_for_method.exists()

        if backup_path.exists() or backup_path.is_symlink():
            if not same_method_already_managed:
                stashed_backup = self._unique_stash_path(backup_path, "preexisting-backup")
                backup_path.rename(stashed_backup)

        if proxy_path.exists() or proxy_path.is_symlink():
            if same_method_already_managed and self._is_bundled_proxy_file(proxy_path):
                self._remove_path(proxy_path)
            elif self._is_bundled_proxy_file(proxy_path):
                self._remove_path(proxy_path)
            else:
                proxy_path.rename(backup_path)
                backup_created = True

        return backup_created

    def _is_env_assignment(self, token: str) -> bool:
        if "=" not in token or token.startswith("-"):
            return False
        key_part = token.split("=", 1)[0]
        return "/" not in key_part

    def _parse_launch_option(self, raw_command: str) -> dict:
        if not raw_command or not raw_command.strip():
            return {"env_pairs": [], "prefix": [], "suffix": []}

        try:
            parts = shlex.split(raw_command)
        except ValueError:
            parts = raw_command.split()

        try:
            command_idx = parts.index("%command%")
            left_parts = parts[:command_idx]
            right_parts = parts[command_idx + 1 :]
        except ValueError:
            temp_left: list[str] = []
            temp_right: list[str] = []

            for index, part in enumerate(parts):
                if self._is_env_assignment(part):
                    temp_left.append(part)
                    continue

                if part.startswith("-") or part.startswith("+"):
                    temp_right.append(part)
                    temp_right.extend(parts[index + 1 :])
                    break

                temp_left.append(part)

            left_parts = temp_left
            right_parts = temp_right

        env_pairs: list[tuple[str, str]] = []
        prefix: list[str] = []

        for part in left_parts:
            if self._is_env_assignment(part):
                key, value = part.split("=", 1)
                env_pairs.append((key, value))
            else:
                prefix.append(part)

        return {
            "env_pairs": env_pairs,
            "prefix": right_or_default(prefix),
            "suffix": right_or_default(right_parts),
        }

    def _merge_winedlloverrides(self, existing_value: str, method: str) -> str:
        method = self._normalize_method(method)
        desired_entry = f"{method}=n,b"
        entries = [entry.strip() for entry in (existing_value or "").split(";") if entry.strip()]
        filtered = [entry for entry in entries if not entry.lower().startswith(f"{method.lower()}=")]
        filtered.append(desired_entry)
        return ";".join(filtered)

    def _build_managed_launch_options(self, original_launch_options: str, method: str) -> str:
        parsed = self._parse_launch_option(original_launch_options)
        env_pairs = list(parsed["env_pairs"])
        prefix = list(parsed["prefix"])
        suffix = list(parsed["suffix"])

        existing_winedlloverrides = ""
        other_env_pairs: list[tuple[str, str]] = []
        for key, value in env_pairs:
            if key == "WINEDLLOVERRIDES":
                existing_winedlloverrides = value
            else:
                other_env_pairs.append((key, value))

        merged_env_pairs = [("WINEDLLOVERRIDES", self._merge_winedlloverrides(existing_winedlloverrides, method))]
        merged_env_pairs.extend(other_env_pairs)

        parts = [f"{key}={value}" for key, value in merged_env_pairs]
        parts.extend(prefix)
        parts.append("%command%")
        parts.extend(suffix)
        return shlex.join(parts)

    async def list_installed_games(self) -> dict:
        try:
            games = []
            for game in self._find_installed_games():
                paths = self._prefix_paths_for_appid(str(game["appid"]))
                prefix_exists = bool(paths and paths["system32"].exists())
                games.append(
                    {
                        "appid": str(game["appid"]),
                        "name": game["name"],
                        "prefix_exists": prefix_exists,
                    }
                )

            return {"status": "success", "games": games}
        except Exception as exc:
            decky.logger.error(f"list_installed_games failed: {exc}")
            return {"status": "error", "message": str(exc), "games": []}

    async def get_game_status(self, appid: str) -> dict:
        try:
            paths = self._prefix_paths_for_appid(str(appid))
            installed_game = self._find_installed_games(str(appid))
            game_name = installed_game[0]["name"] if installed_game else str(appid)

            if not paths:
                return {
                    "status": "success",
                    "appid": str(appid),
                    "name": game_name,
                    "prefix_exists": False,
                    "patched": False,
                    "method": None,
                    "proxy_filename": None,
                    "message": "No compatdata prefix found for this game yet. Launch it once with Proton first.",
                }

            system32 = paths["system32"]
            if not system32.exists():
                return {
                    "status": "success",
                    "appid": str(appid),
                    "name": game_name,
                    "prefix_exists": False,
                    "patched": False,
                    "method": None,
                    "proxy_filename": None,
                    "message": "The Proton prefix has not been created yet. Launch the game once first.",
                    "paths": {
                        "compatdata": str(paths["compatdata_dir"]),
                        "system32": str(system32),
                    },
                }

            markers = self._marker_paths(system32)
            if not markers:
                return {
                    "status": "success",
                    "appid": str(appid),
                    "name": game_name,
                    "prefix_exists": True,
                    "patched": False,
                    "method": None,
                    "proxy_filename": None,
                    "message": "This game is not currently patched.",
                    "paths": {
                        "compatdata": str(paths["compatdata_dir"]),
                        "system32": str(system32),
                    },
                }

            marker = markers[0]
            metadata = self._read_marker_metadata(marker)
            method = self._normalize_method(metadata.get("method") or "version")
            proxy_filename = f"{method}.dll"
            proxy_path = system32 / proxy_filename
            patched = proxy_path.exists() or proxy_path.is_symlink()

            if patched:
                message = f"Patched using {proxy_filename}."
            else:
                message = f"Managed marker found for {proxy_filename}, but the proxy DLL is missing. Patch again to repair or unpatch to clean up."

            return {
                "status": "success",
                "appid": str(appid),
                "name": game_name,
                "prefix_exists": True,
                "patched": patched,
                "method": method,
                "proxy_filename": proxy_filename,
                "marker_name": marker.name,
                "message": message,
                "paths": {
                    "compatdata": str(paths["compatdata_dir"]),
                    "system32": str(system32),
                },
            }
        except Exception as exc:
            decky.logger.error(f"get_game_status failed for {appid}: {exc}")
            return {"status": "error", "message": str(exc)}

    async def patch_game(self, appid: str, method: str, current_launch_options: str = "") -> dict:
        try:
            normalized_method = self._normalize_method(method)
            asset_path = self._verify_bundled_asset()
            paths = self._prefix_paths_for_appid(str(appid))
            installed_game = self._find_installed_games(str(appid))
            game_name = installed_game[0]["name"] if installed_game else str(appid)

            if not paths or not paths["system32"].exists():
                return {
                    "status": "error",
                    "message": "No Proton prefix found for this game yet. Launch it once with Proton first.",
                }

            system32 = paths["system32"]
            system32.mkdir(parents=True, exist_ok=True)

            preserved_launch_options = current_launch_options or ""
            cleanup_result = self._cleanup_managed_state(system32)
            if cleanup_result["original_launch_options"]:
                preserved_launch_options = cleanup_result["original_launch_options"]

            backup_created = self._prepare_target_proxy(system32, normalized_method)
            target_proxy_path = system32 / f"{normalized_method}.dll"
            shutil.copy2(asset_path, target_proxy_path)

            copied_hash = self._file_sha256(target_proxy_path)
            if copied_hash.lower() != BUNDLED_ASSET_SHA256.lower():
                raise RuntimeError(
                    f"Copied proxy hash mismatch for {target_proxy_path.name}: expected {BUNDLED_ASSET_SHA256}, got {copied_hash}"
                )

            marker_path = system32 / self._marker_filename(normalized_method)
            self._write_marker_metadata(
                marker_path,
                appid=str(appid),
                game_name=game_name,
                method=normalized_method,
                original_launch_options=preserved_launch_options,
                backup_created=backup_created,
            )

            managed_launch_options = self._build_managed_launch_options(preserved_launch_options, normalized_method)
            cleanup_notes = cleanup_result.get("notes") or []
            message = f"Patched {game_name} using {normalized_method}.dll."
            if cleanup_notes:
                message = f"{message} Cleaned previous managed state first."

            return {
                "status": "success",
                "appid": str(appid),
                "name": game_name,
                "method": normalized_method,
                "proxy_filename": f"{normalized_method}.dll",
                "marker_name": marker_path.name,
                "launch_options": managed_launch_options,
                "original_launch_options": preserved_launch_options,
                "message": message,
                "paths": {
                    "compatdata": str(paths["compatdata_dir"]),
                    "system32": str(system32),
                    "proxy": str(target_proxy_path),
                    "marker": str(marker_path),
                },
            }
        except Exception as exc:
            decky.logger.error(f"patch_game failed for {appid}: {exc}")
            return {"status": "error", "message": str(exc)}

    async def unpatch_game(self, appid: str) -> dict:
        try:
            paths = self._prefix_paths_for_appid(str(appid))
            installed_game = self._find_installed_games(str(appid))
            game_name = installed_game[0]["name"] if installed_game else str(appid)

            if not paths or not paths["system32"].exists():
                return {
                    "status": "success",
                    "appid": str(appid),
                    "name": game_name,
                    "launch_options": "",
                    "message": "No Proton prefix found for this game, so there is nothing to clean up in the prefix.",
                }

            system32 = paths["system32"]
            markers = self._marker_paths(system32)
            if not markers:
                return {
                    "status": "success",
                    "appid": str(appid),
                    "name": game_name,
                    "launch_options": "",
                    "message": "No managed DLSS Enabler marker was found for this game.",
                    "paths": {
                        "compatdata": str(paths["compatdata_dir"]),
                        "system32": str(system32),
                    },
                }

            cleanup_result = self._cleanup_managed_state(system32)
            cleaned_methods = cleanup_result.get("cleaned_methods") or []
            methods_display = ", ".join(f"{method}.dll" for method in cleaned_methods) if cleaned_methods else "managed proxy"

            return {
                "status": "success",
                "appid": str(appid),
                "name": game_name,
                "launch_options": cleanup_result.get("original_launch_options") or "",
                "message": f"Unpatched {game_name} and restored {methods_display}.",
                "paths": {
                    "compatdata": str(paths["compatdata_dir"]),
                    "system32": str(system32),
                },
                "notes": cleanup_result.get("notes") or [],
            }
        except Exception as exc:
            decky.logger.error(f"unpatch_game failed for {appid}: {exc}")
            return {"status": "error", "message": str(exc)}


def right_or_default(values: list[str]) -> list[str]:
    return values if values else []
