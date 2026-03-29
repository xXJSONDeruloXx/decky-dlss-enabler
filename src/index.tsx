import {
  ButtonItem,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  ToggleField,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";
import { useCallback, useEffect, useMemo, useState } from "react";
import { FaPlug } from "react-icons/fa";

type GameInfo = {
  appid: string;
  name: string;
  prefix_exists: boolean;
};

type GameListResponse = {
  status: "success" | "error";
  message?: string;
  games: GameInfo[];
};

type GameStatusResponse = {
  status: "success" | "error";
  message?: string;
  appid?: string;
  name?: string;
  prefix_exists?: boolean;
  patched?: boolean;
  method?: string | null;
  proxy_filename?: string | null;
  marker_name?: string;
  marker_format?: string | null;
  bundled_asset_version?: string;
  bundled_asset_sha256?: string;
  marker_asset_version?: string | null;
  marker_asset_sha256?: string | null;
  installed_asset_version?: string | null;
  installed_asset_sha256?: string | null;
  proxy_sha256?: string | null;
  upgrade_available?: boolean;
  reinstall_recommended?: boolean;
  integrity_ok?: boolean | null;
  fsr_profile_id?: string | null;
  fsr_profile_label?: string | null;
  fsr_profile_family?: string | null;
  fsr4_enabled?: boolean;
  fsr4_bundle_id?: string | null;
  fsr4_label?: string | null;
  fsr4_optiscaler_version?: string | null;
  fsr4_files_present?: boolean;
  fsr4_files_complete?: boolean;
  fsr4_integrity_ok?: boolean | null;
  fsr4_reinstall_recommended?: boolean;
  optipatcher_enabled?: boolean;
  optipatcher_id?: string | null;
  optipatcher_label?: string | null;
  optipatcher_files_present?: boolean;
  optipatcher_files_complete?: boolean;
  optipatcher_integrity_ok?: boolean | null;
  optipatcher_reinstall_recommended?: boolean;
  recommended_method?: string | null;
  recommended_optipatcher?: boolean;
  recommendation_source?: string | null;
  recommendation_wiki_url?: string | null;
  recommendation_notes?: string[];
  recommended_optiscaler_ini_overrides?: Record<string, Record<string, string>>;
  paths?: {
    install_root?: string;
    target_dir?: string;
    target_exe?: string;
  };
};

type PatchResponse = {
  status: "success" | "error";
  message?: string;
  appid?: string;
  name?: string;
  method?: string;
  proxy_filename?: string;
  marker_name?: string;
  bundled_asset_version?: string;
  bundled_asset_sha256?: string;
  fsr_profile_id?: string | null;
  fsr_profile_label?: string | null;
  fsr4_enabled?: boolean;
  fsr4_bundle_id?: string | null;
  fsr4_label?: string | null;
  optipatcher_enabled?: boolean;
  optipatcher_id?: string | null;
  optipatcher_label?: string | null;
  launch_options?: string;
  original_launch_options?: string;
  paths?: {
    install_root?: string;
    target_dir?: string;
    target_exe?: string;
    proxy?: string;
    marker?: string;
  };
};

type UnpatchResponse = {
  status: "success" | "error";
  message?: string;
  launch_options?: string;
  paths?: {
    install_root?: string;
    target_dir?: string;
    target_exe?: string;
  };
  notes?: string[];
};

const METHOD_OPTIONS = [
  { value: "version", label: "version.dll", hint: "Default for most games." },
  { value: "winmm", label: "winmm.dll", hint: "Good fallback when a game already uses version.dll." },
  { value: "d3d11", label: "d3d11.dll", hint: "Use for DirectX 11 games." },
  { value: "d3d12", label: "d3d12.dll", hint: "Use for DirectX 12 games." },
  { value: "dinput8", label: "dinput8.dll", hint: "Use for DirectInput hook paths." },
  { value: "dxgi", label: "dxgi.dll", hint: "Use for DXGI-based hook paths." },
  { value: "wininet", label: "wininet.dll", hint: "Use for games that respond to WinINet hooking." },
  { value: "winhttp", label: "winhttp.dll", hint: "Use for games that respond to WinHTTP hooking." },
  { value: "dbghelp", label: "dbghelp.dll", hint: "Use for Debug Help Library hook paths." },
] as const;

const FSR_PROFILE_OPTIONS = [
  { value: "disabled", label: "Disabled", hint: "Do not install managed FSR sidecar files." },
  { value: "fsr4-int8-4.0.2b-opti-0.7.9", label: "FSR4 INT8 4.0.2b (RDNA2&3)", hint: "Community INT8 build for older RDNA2 and RDNA3 GPUs." },
  { value: "fsr4-official-4.1.0-rdna4", label: "FSR4 4.1.0 official (RDNA4)", hint: "Installs AMD loader, upscaler, and amdxcffx64.dll for the official RDNA4 path." },
] as const;

const listInstalledGames = callable<[], GameListResponse>("list_installed_games");
const getGameStatus = callable<[appid: string], GameStatusResponse>("get_game_status");
const patchGame = callable<
  [appid: string, method: string, currentLaunchOptions: string, fsrProfileId: string | null, applyRecommendations: boolean, enableOptiPatcher: boolean],
  PatchResponse
>("patch_game");
const unpatchGame = callable<[appid: string], UnpatchResponse>("unpatch_game");

const getMethodHint = (method: string) =>
  METHOD_OPTIONS.find((entry) => entry.value === method)?.hint ?? "";

const getAppLaunchOptions = (appid: number): Promise<string> =>
  new Promise((resolve, reject) => {
    let settled = false;
    let unregister = () => undefined;

    const timeout = window.setTimeout(() => {
      if (settled) return;
      settled = true;
      unregister();
      reject(new Error("Timed out while loading the current launch options."));
    }, 5000);

    const registration = SteamClient.Apps.RegisterForAppDetails(appid, (details: { strLaunchOptions?: string }) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      unregister();
      resolve(details?.strLaunchOptions ?? "");
    });

    unregister = registration.unregister;
  });

const setAppLaunchOptions = (appid: number, launchOptions: string) => {
  SteamClient.Apps.SetAppLaunchOptions(appid, launchOptions);
};

let lastSelectedAppId = "";
let lastSelectedMethod = "dxgi";
let lastSelectedFsrProfile = "disabled";
let lastSelectedOptiPatcher = "disabled";
let lastApplyRecommendations = "disabled";

function Content() {
  const [games, setGames] = useState<GameInfo[]>([]);
  const [gamesLoading, setGamesLoading] = useState(true);
  const [selectedAppId, setSelectedAppId] = useState<string>(() => lastSelectedAppId);
  const [selectedMethod, setSelectedMethod] = useState<string>(() => lastSelectedMethod);
  const [selectedFsrProfile, setSelectedFsrProfile] = useState<string>(() => lastSelectedFsrProfile);
  const [selectedOptiPatcher, setSelectedOptiPatcher] = useState<string>(() => lastSelectedOptiPatcher);
  const [applyRecommendations, setApplyRecommendations] = useState<string>(() => lastApplyRecommendations);
  const [status, setStatus] = useState<GameStatusResponse | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [busyAction, setBusyAction] = useState<"patch" | "unpatch" | null>(null);
  const [resultMessage, setResultMessage] = useState<string>("");

  const loadGames = useCallback(async () => {
    setGamesLoading(true);
    setResultMessage("");
    try {
      const result = await listInstalledGames();
      if (result.status !== "success") {
        throw new Error(result.message || "Failed to load installed games.");
      }

      setGames(result.games);
      if (!result.games.length) {
        lastSelectedAppId = "";
        setSelectedAppId("");
        setStatus(null);
        return;
      }

      setSelectedAppId((current) => {
        const nextAppId = current && result.games.some((game) => game.appid === current)
          ? current
          : result.games[0].appid;
        lastSelectedAppId = nextAppId;
        return nextAppId;
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to load installed games.";
      setResultMessage(`Error: ${message}`);
      toaster.toast({ title: "DLSS Enabler", body: message });
    } finally {
      setGamesLoading(false);
    }
  }, []);

  const loadStatus = useCallback(async (appid: string) => {
    if (!appid) {
      setStatus(null);
      return;
    }

    setStatusLoading(true);
    try {
      const result = await getGameStatus(appid);
      setStatus(result);
      if (result.status === "success" && result.method) {
        lastSelectedMethod = result.method;
        setSelectedMethod(result.method);
      }
      if (result.status === "success") {
        const nextFsrProfile = result.fsr_profile_id || "disabled";
        lastSelectedFsrProfile = nextFsrProfile;
        setSelectedFsrProfile(nextFsrProfile);
        const nextOptiPatcher = result.optipatcher_enabled ? "enabled" : "disabled";
        lastSelectedOptiPatcher = nextOptiPatcher;
        setSelectedOptiPatcher(nextOptiPatcher);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to load game status.";
      setStatus({ status: "error", message });
    } finally {
      setStatusLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadGames();
  }, [loadGames]);

  useEffect(() => {
    if (!selectedAppId) {
      setStatus(null);
      return;
    }
    void loadStatus(selectedAppId);
  }, [selectedAppId, loadStatus]);

  const selectedGame = useMemo(
    () => games.find((game) => game.appid === selectedAppId) ?? null,
    [games, selectedAppId],
  );

  const methodDropdownOptions = useMemo(
    () => METHOD_OPTIONS.map((entry) => ({
      data: entry.value,
      label: entry.value === status?.recommended_method ? `${entry.label} (recommended)` : entry.label,
    })),
    [status?.recommended_method],
  );
  const hasRecommendationNotes = Boolean(status?.recommendation_notes && status.recommendation_notes.length);
  const hasApplicableRecommendations = Boolean(
    status?.recommended_method ||
    status?.recommended_optipatcher ||
    (status?.recommended_optiscaler_ini_overrides && Object.keys(status.recommended_optiscaler_ini_overrides).length),
  );
  const applyRecommendationsEnabled = applyRecommendations === "enabled" && hasApplicableRecommendations;
  const effectiveMethod = applyRecommendationsEnabled && status?.recommended_method
    ? status.recommended_method
    : selectedMethod;
  const optiPatcherRecommended = applyRecommendationsEnabled && Boolean(status?.recommended_optipatcher);
  const effectiveOptiPatcherEnabled = selectedOptiPatcher === "enabled" || optiPatcherRecommended;
  const effectiveMethodLabel = useMemo(
    () => METHOD_OPTIONS.find((entry) => entry.value === effectiveMethod)?.label ?? `${effectiveMethod}.dll`,
    [effectiveMethod],
  );
  const effectiveIniOverrides = useMemo(
    () => (applyRecommendationsEnabled ? (status?.recommended_optiscaler_ini_overrides ?? {}) : {}),
    [applyRecommendationsEnabled, status?.recommended_optiscaler_ini_overrides],
  );
  const effectiveIniOverrideLines = useMemo(
    () => Object.entries(effectiveIniOverrides).flatMap(([section, values]) =>
      Object.entries(values).map(([key, value]) => `[${section}] ${key}=${value}`),
    ),
    [effectiveIniOverrides],
  );
  const selectedFsrProfileOption = useMemo(
    () => FSR_PROFILE_OPTIONS.find((entry) => entry.value === selectedFsrProfile) ?? FSR_PROFILE_OPTIONS[0],
    [selectedFsrProfile],
  );
  const injectionMethodDescription = useMemo(() => {
    if (applyRecommendationsEnabled && status?.recommended_method) {
      return `Using ${effectiveMethodLabel} (recommended). Turn recommendations off to choose manually.`;
    }
    return getMethodHint(selectedMethod);
  }, [applyRecommendationsEnabled, effectiveMethodLabel, selectedMethod, status?.recommended_method]);
  const optiPatcherDescription = useMemo(() => {
    if (optiPatcherRecommended) {
      return "Using OptiPatcher (recommended). Turn recommendations off to choose manually.";
    }
    return "Installs plugins/OptiPatcher.asi and enables [Plugins] LoadAsiPlugins=true in OptiScaler.ini.";
  }, [optiPatcherRecommended]);

  const canPatch = Boolean(selectedGame && status?.status === "success" && status.prefix_exists && !busyAction);
  const canUnpatch = Boolean(selectedGame && status?.status === "success" && status.marker_name && !busyAction);

  const patchButtonLabel = useMemo(() => {
    const selectedComponents = [
      selectedFsrProfileOption.value !== "disabled" ? selectedFsrProfileOption.label : null,
      effectiveOptiPatcherEnabled ? "OptiPatcher" : null,
    ].filter(Boolean);
    const suffix = selectedComponents.length ? ` + ${selectedComponents.join(" + ")}` : "";
    if (busyAction === "patch") return "Patching...";
    if (!selectedGame) return "Patch selected game";
    if (!status?.prefix_exists) return "Patch target not found";
    if (status?.method && status.method !== effectiveMethod) return `Switch to ${effectiveMethodLabel}${suffix}`;
    if (status?.reinstall_recommended || status?.fsr4_reinstall_recommended || status?.optipatcher_reinstall_recommended) return `Reinstall ${effectiveMethodLabel}${suffix}`;
    if (status?.upgrade_available) return `Upgrade to ${status.bundled_asset_version ?? effectiveMethodLabel}`;
    if (status?.marker_name) return `Reinstall ${effectiveMethodLabel}${suffix}`;
    return `Patch with ${effectiveMethodLabel}${suffix}`;
  }, [busyAction, effectiveMethod, effectiveMethodLabel, effectiveOptiPatcherEnabled, selectedFsrProfileOption, selectedGame, status]);

  const handlePatch = useCallback(async () => {
    if (!selectedGame || !selectedAppId) return;

    setBusyAction("patch");
    setResultMessage("");
    try {
      const currentLaunchOptions = await getAppLaunchOptions(Number(selectedAppId));
      const result = await patchGame(
        selectedAppId,
        selectedMethod,
        currentLaunchOptions,
        selectedFsrProfile === "disabled" ? null : selectedFsrProfile,
        applyRecommendationsEnabled,
        selectedOptiPatcher === "enabled",
      );
      if (result.status !== "success") {
        throw new Error(result.message || "Patch failed.");
      }

      setAppLaunchOptions(Number(selectedAppId), result.launch_options || "");
      setResultMessage(result.message || `Patched ${selectedGame.name} using ${effectiveMethodLabel}.`);
      toaster.toast({
        title: "DLSS Enabler",
        body: result.message || `Patched ${selectedGame.name} using ${effectiveMethodLabel}.`,
      });
      await loadStatus(selectedAppId);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Patch failed.";
      setResultMessage(`Error: ${message}`);
      toaster.toast({ title: "DLSS Enabler", body: message });
    } finally {
      setBusyAction(null);
    }
  }, [applyRecommendationsEnabled, effectiveMethodLabel, loadStatus, selectedAppId, selectedFsrProfile, selectedGame, selectedMethod, selectedOptiPatcher]);

  const handleUnpatch = useCallback(async () => {
    if (!selectedGame || !selectedAppId) return;

    setBusyAction("unpatch");
    setResultMessage("");
    try {
      const result = await unpatchGame(selectedAppId);
      if (result.status !== "success") {
        throw new Error(result.message || "Unpatch failed.");
      }

      setAppLaunchOptions(Number(selectedAppId), result.launch_options || "");
      setResultMessage(result.message || `Unpatched ${selectedGame.name}.`);
      toaster.toast({
        title: "DLSS Enabler",
        body: result.message || `Unpatched ${selectedGame.name}.`,
      });
      await loadStatus(selectedAppId);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unpatch failed.";
      setResultMessage(`Error: ${message}`);
      toaster.toast({ title: "DLSS Enabler", body: message });
    } finally {
      setBusyAction(null);
    }
  }, [loadStatus, selectedAppId, selectedGame]);

  const versionDisplay = useMemo(() => {
    if (!selectedGame || status?.status !== "success" || !status.patched) {
      return { text: "—", color: undefined as string | undefined };
    }

    const text = status.installed_asset_version || status.marker_asset_version || "Unknown";
    if (status.reinstall_recommended) {
      return { text, color: "#ff7b72" };
    }
    if (status.upgrade_available) {
      return { text, color: "#ffd866" };
    }
    return { text, color: "#3fb950" };
  }, [selectedGame, status]);

  const fsrProfileDisplay = useMemo(() => {
    if (!selectedGame || status?.status !== "success") {
      return { text: "—", color: undefined as string | undefined };
    }
    if (!status.fsr_profile_id) {
      return { text: "Disabled", color: undefined as string | undefined };
    }
    const text = status.fsr_profile_label || status.fsr4_label || status.fsr_profile_id;
    if (status.fsr4_reinstall_recommended) {
      return { text, color: "#ff7b72" };
    }
    if (!status.fsr4_files_complete) {
      return { text, color: "#ffd866" };
    }
    return { text, color: "#3fb950" };
  }, [selectedGame, status]);

  const optiPatcherDisplay = useMemo(() => {
    if (!selectedGame || status?.status !== "success") {
      return { text: "—", color: undefined as string | undefined };
    }
    if (!status.optipatcher_enabled) {
      return { text: "Disabled", color: undefined as string | undefined };
    }
    const text = status.optipatcher_label || "OptiPatcher";
    if (status.optipatcher_reinstall_recommended) {
      return { text, color: "#ff7b72" };
    }
    if (!status.optipatcher_files_complete) {
      return { text, color: "#ffd866" };
    }
    return { text, color: "#3fb950" };
  }, [selectedGame, status]);

  const statusMessage = useMemo(() => {
    if (!selectedGame) return "Choose a game to manage its patch state.";
    if (statusLoading) return "Loading patch status...";
    if (!status) return "No status loaded yet.";
    if (status.status === "error") return `Error: ${status.message || "Failed to load status."}`;
    if (!status.prefix_exists) return status.message || "Patch target not found.";
    if (!status.patched) return status.message || "This game is not currently patched.";
    if (status.reinstall_recommended || status.upgrade_available || status.fsr4_reinstall_recommended || status.optipatcher_reinstall_recommended) {
      return status.message || "An update is available.";
    }
    if (status.fsr_profile_id && !status.fsr4_files_complete) {
      return "Managed FSR profile files are expected but incomplete. Reinstall recommended.";
    }
    if (status.optipatcher_enabled && !status.optipatcher_files_complete) {
      return "OptiPatcher files are expected but incomplete. Reinstall recommended.";
    }
    return "";
  }, [selectedGame, status, statusLoading]);

  const focusableFieldProps = {
    focusable: true,
    highlightOnFocus: true,
  } as const;

  return (
    <PanelSection>
      <PanelSectionRow>
        <DropdownItem
          label="Target game"
          menuLabel="Installed Steam games"
          strDefaultLabel={gamesLoading ? "Loading installed games..." : "Choose a game"}
          disabled={gamesLoading || games.length === 0}
          selectedOption={selectedAppId}
          rgOptions={games.map((game) => ({
            data: game.appid,
            label: game.prefix_exists ? game.name : `${game.name} (target not found)`,
          }))}
          onChange={(option) => {
            const nextAppId = String(option.data);
            lastSelectedAppId = nextAppId;
            setSelectedAppId(nextAppId);
            setResultMessage("");
          }}
        />
      </PanelSectionRow>

      <PanelSectionRow>
        <Field {...focusableFieldProps} label="Game">{selectedGame?.name ?? "—"}</Field>
      </PanelSectionRow>

      <PanelSectionRow>
        <Field {...focusableFieldProps} label="App ID">{selectedGame?.appid ?? "—"}</Field>
      </PanelSectionRow>

      <PanelSectionRow>
        <Field {...focusableFieldProps} label="Target ready">
          {selectedGame && status?.status === "success" ? (status.prefix_exists ? "Yes" : "No") : "—"}
        </Field>
      </PanelSectionRow>

      <PanelSectionRow>
        <Field {...focusableFieldProps} label="Patched">
          {selectedGame && status?.status === "success" ? (status.patched ? "Yes" : "No") : "—"}
        </Field>
      </PanelSectionRow>

      <PanelSectionRow>
        <Field {...focusableFieldProps} label="Current DLL name">
          {selectedGame && status?.status === "success" && status.method
            ? (status.proxy_filename || `${status.method}.dll`)
            : "—"}
        </Field>
      </PanelSectionRow>

      {hasRecommendationNotes ? (
        <PanelSectionRow>
          <Field {...focusableFieldProps} label="Recommendation notes">
            <div>
              {status?.recommendation_notes?.map((note, index) => (
                <div key={`${note}-${index}`}>• {note}</div>
              ))}
            </div>
          </Field>
        </PanelSectionRow>
      ) : null}

      <PanelSectionRow>
        <Field {...focusableFieldProps} label="DLSS Enabler version">
          {versionDisplay.color ? (
            <span style={{ color: versionDisplay.color, fontWeight: 600 }}>{versionDisplay.text}</span>
          ) : versionDisplay.text}
        </Field>
      </PanelSectionRow>

      <PanelSectionRow>
        <Field {...focusableFieldProps} label="Bundled version">
          {selectedGame && status?.status === "success"
            ? (status.bundled_asset_version || "—")
            : "—"}
        </Field>
      </PanelSectionRow>

      <PanelSectionRow>
        <Field {...focusableFieldProps} label="Managed FSR profile">
          {fsrProfileDisplay.color ? (
            <span style={{ color: fsrProfileDisplay.color, fontWeight: 600 }}>{fsrProfileDisplay.text}</span>
          ) : fsrProfileDisplay.text}
        </Field>
      </PanelSectionRow>

      <PanelSectionRow>
        <Field {...focusableFieldProps} label="OptiPatcher plugin">
          {optiPatcherDisplay.color ? (
            <span style={{ color: optiPatcherDisplay.color, fontWeight: 600 }}>{optiPatcherDisplay.text}</span>
          ) : optiPatcherDisplay.text}
        </Field>
      </PanelSectionRow>

      <PanelSectionRow>
        <Field {...focusableFieldProps} label="OptiScaler base">
          {selectedGame && status?.status === "success"
            ? ((status.fsr_profile_id || status.optipatcher_enabled) ? (status.fsr4_optiscaler_version || "0.7.9") : "—")
            : "—"}
        </Field>
      </PanelSectionRow>

      {statusMessage ? (
        <PanelSectionRow>
          <Field {...focusableFieldProps} label="Status">{statusMessage}</Field>
        </PanelSectionRow>
      ) : null}

      <PanelSectionRow>
        <DropdownItem
          label="Injection method"
          description={injectionMethodDescription}
          menuLabel="Injection method"
          strDefaultLabel="Choose DLL name"
          selectedOption={effectiveMethod}
          rgOptions={methodDropdownOptions}
          onChange={(option) => {
            const nextMethod = String(option.data);
            lastSelectedMethod = nextMethod;
            setSelectedMethod(nextMethod);
          }}
          disabled={!selectedGame || busyAction !== null || applyRecommendationsEnabled}
        />
      </PanelSectionRow>

      {hasApplicableRecommendations ? (
        <PanelSectionRow>
          <ToggleField
            label="Apply game recommendations"
            description="Automatically use the recommended DLL name, OptiPatcher plugin, and any game-specific OptiScaler.ini overrides."
            checked={applyRecommendationsEnabled}
            onChange={(checked) => {
              const nextValue = checked ? "enabled" : "disabled";
              lastApplyRecommendations = nextValue;
              setApplyRecommendations(nextValue);
            }}
            disabled={!selectedGame || busyAction !== null}
          />
        </PanelSectionRow>
      ) : null}

      {applyRecommendationsEnabled && (selectedFsrProfile !== "disabled" || effectiveOptiPatcherEnabled) && effectiveIniOverrideLines.length ? (
        <PanelSectionRow>
          <Field {...focusableFieldProps} label="Additional OptiScaler.ini overrides">
            <div>
              {effectiveIniOverrideLines.map((line, index) => (
                <div key={`${line}-${index}`}>• {line}</div>
              ))}
            </div>
          </Field>
        </PanelSectionRow>
      ) : null}

      <PanelSectionRow>
        <DropdownItem
          label="Managed FSR profile"
          description={selectedFsrProfileOption.hint}
          menuLabel="Managed FSR profile"
          strDefaultLabel="Choose FSR profile"
          selectedOption={selectedFsrProfile}
          rgOptions={FSR_PROFILE_OPTIONS.map((entry) => ({ data: entry.value, label: entry.label }))}
          onChange={(option) => {
            const nextValue = String(option.data);
            lastSelectedFsrProfile = nextValue;
            setSelectedFsrProfile(nextValue);
          }}
          disabled={!selectedGame || busyAction !== null}
        />
      </PanelSectionRow>

      <PanelSectionRow>
        <ToggleField
          label="OptiPatcher plugin"
          description={optiPatcherDescription}
          checked={effectiveOptiPatcherEnabled}
          onChange={(checked) => {
            const nextValue = checked ? "enabled" : "disabled";
            lastSelectedOptiPatcher = nextValue;
            setSelectedOptiPatcher(nextValue);
          }}
          disabled={!selectedGame || busyAction !== null || optiPatcherRecommended}
        />
      </PanelSectionRow>

      <PanelSectionRow>
        <ButtonItem layout="below" onClick={handlePatch} disabled={!canPatch}>
          {patchButtonLabel}
        </ButtonItem>
      </PanelSectionRow>

      <PanelSectionRow>
        <ButtonItem layout="below" onClick={handleUnpatch} disabled={!canUnpatch}>
          {busyAction === "unpatch" ? "Unpatching..." : "Unpatch selected game"}
        </ButtonItem>
      </PanelSectionRow>

      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => selectedAppId && void loadStatus(selectedAppId)} disabled={!selectedAppId || busyAction !== null || statusLoading}>
          {statusLoading ? "Refreshing..." : "Refresh selected game status"}
        </ButtonItem>
      </PanelSectionRow>

      {resultMessage ? (
        <PanelSectionRow>
          <Field {...focusableFieldProps} label="Last action">
            <div>
              {resultMessage.split("\n").map((line, index) => (
                <div key={`${line}-${index}`}>{line || "\u00A0"}</div>
              ))}
            </div>
          </Field>
        </PanelSectionRow>
      ) : null}
    </PanelSection>
  );
}

export default definePlugin(() => {
  console.log("DLSS Enabler frontend loaded");

  return {
    name: "DLSS Enabler",
    titleView: <div className={staticClasses.Title}>DLSS Enabler</div>,
    content: <Content />,
    alwaysRender: true,
    icon: <FaPlug />,
    onDismount() {
      console.log("DLSS Enabler frontend unloaded");
    },
  };
});
