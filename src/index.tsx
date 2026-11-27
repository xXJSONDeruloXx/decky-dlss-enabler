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
import { L } from "./i18n";

type GameInfo = {
  appid: string;
  name: string;
  prefix_exists: boolean;
  is_shortcut?: boolean;
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
  { value: "version", label: "version.dll", hint: () => L("Default for most games.", "多數遊戲的預設選項。") },
  { value: "winmm", label: "winmm.dll", hint: () => L("Good fallback when a game already uses version.dll.", "當遊戲本身已使用 version.dll 時的理想備援。") },
  { value: "d3d11", label: "d3d11.dll", hint: () => L("Use for DirectX 11 games.", "適用於 DirectX 11 遊戲。") },
  { value: "d3d12", label: "d3d12.dll", hint: () => L("Use for DirectX 12 games.", "適用於 DirectX 12 遊戲。") },
  { value: "dinput8", label: "dinput8.dll", hint: () => L("Use for DirectInput hook paths.", "適用於 DirectInput 掛鉤路徑。") },
  { value: "dxgi", label: "dxgi.dll", hint: () => L("Use for DXGI-based hook paths.", "適用於 DXGI 掛鉤路徑。") },
  { value: "wininet", label: "wininet.dll", hint: () => L("Use for games that respond to WinINet hooking.", "適用於支援 WinINet 掛鉤的遊戲。") },
  { value: "winhttp", label: "winhttp.dll", hint: () => L("Use for games that respond to WinHTTP hooking.", "適用於支援 WinHTTP 掛鉤的遊戲。") },
  { value: "dbghelp", label: "dbghelp.dll", hint: () => L("Use for Debug Help Library hook paths.", "適用於 Debug Help 函式庫掛鉤路徑。") },
] as const;

const listInstalledGames = callable<[], GameListResponse>("list_installed_games");
const getGameStatus = callable<[appid: string], GameStatusResponse>("get_game_status");
const patchGame = callable<
  [appid: string, method: string, currentLaunchOptions: string, enableFsr4: boolean, applyRecommendations: boolean, enableOptiPatcher: boolean],
  PatchResponse
>("patch_game");
const unpatchGame = callable<[appid: string], UnpatchResponse>("unpatch_game");

const getMethodHint = (method: string) =>
  METHOD_OPTIONS.find((entry) => entry.value === method)?.hint() ?? "";

const getAppLaunchOptions = (appid: number): Promise<string> =>
  new Promise((resolve, reject) => {
    let settled = false;
    let unregister = () => undefined;

    const timeout = window.setTimeout(() => {
      if (settled) return;
      settled = true;
      unregister();
      reject(new Error(L("Timed out while loading the current launch options.", "讀取目前啟動選項逾時。")));
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
let lastSelectedFsr4 = "disabled";
let lastSelectedOptiPatcher = "disabled";
let lastApplyRecommendations = "disabled";

function Content() {
  const [games, setGames] = useState<GameInfo[]>([]);
  const [gamesLoading, setGamesLoading] = useState(true);
  const [selectedAppId, setSelectedAppId] = useState<string>(() => lastSelectedAppId);
  const [selectedMethod, setSelectedMethod] = useState<string>(() => lastSelectedMethod);
  const [selectedFsr4, setSelectedFsr4] = useState<string>(() => lastSelectedFsr4);
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
        throw new Error(result.message || L("Failed to load installed games.", "無法載入已安裝的遊戲。"));
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
      const message = error instanceof Error ? error.message : L("Failed to load installed games.", "無法載入已安裝的遊戲。");
      setResultMessage(L(`Error: ${message}`, `錯誤：${message}`));
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
        const nextFsr4 = result.fsr4_enabled ? "enabled" : "disabled";
        lastSelectedFsr4 = nextFsr4;
        setSelectedFsr4(nextFsr4);
        const nextOptiPatcher = result.optipatcher_enabled ? "enabled" : "disabled";
        lastSelectedOptiPatcher = nextOptiPatcher;
        setSelectedOptiPatcher(nextOptiPatcher);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : L("Failed to load game status.", "無法載入遊戲狀態。");
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
      label: entry.value === status?.recommended_method ? `${entry.label} ${L("(recommended)", "（建議）")}` : entry.label,
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
  const injectionMethodDescription = useMemo(() => {
    if (applyRecommendationsEnabled && status?.recommended_method) {
      return L(
        `Using ${effectiveMethodLabel} (recommended). Turn recommendations off to choose manually.`,
        `使用 ${effectiveMethodLabel}（建議）。若要手動選擇請關閉遊戲建議設定。`,
      );
    }
    return getMethodHint(selectedMethod);
  }, [applyRecommendationsEnabled, effectiveMethodLabel, selectedMethod, status?.recommended_method]);
  const optiPatcherDescription = useMemo(() => {
    if (optiPatcherRecommended) {
      return L(
        "Using OptiPatcher (recommended). Turn recommendations off to choose manually.",
        "使用 OptiPatcher（建議）。若要手動選擇請關閉遊戲建議設定。",
      );
    }
    return L(
      "Installs plugins/OptiPatcher.asi and enables [Plugins] LoadAsiPlugins=true in OptiScaler.ini.",
      "安裝 plugins/OptiPatcher.asi 並在 OptiScaler.ini 中啟用 [Plugins] LoadAsiPlugins=true。",
    );
  }, [optiPatcherRecommended]);

  const canPatch = Boolean(selectedGame && status?.status === "success" && status.prefix_exists && !busyAction);
  const canUnpatch = Boolean(selectedGame && status?.status === "success" && status.marker_name && !busyAction);

  const patchButtonLabel = useMemo(() => {
    const selectedComponents = [
      selectedFsr4 === "enabled" ? "FSR4 INT8 4.0.2b" : null,
      effectiveOptiPatcherEnabled ? "OptiPatcher" : null,
    ].filter(Boolean);
    const suffix = selectedComponents.length ? ` + ${selectedComponents.join(" + ")}` : "";
    if (busyAction === "patch") return L("Patching...", "正在套用修補...");
    if (!selectedGame) return L("Patch selected game", "修補所選遊戲");
    if (!status?.prefix_exists) return L("Patch target not found", "找不到修補目標");
    if (status?.method && status.method !== effectiveMethod) return L(`Switch to ${effectiveMethodLabel}${suffix}`, `切換為 ${effectiveMethodLabel}${suffix}`);
    if (status?.reinstall_recommended || status?.fsr4_reinstall_recommended || status?.optipatcher_reinstall_recommended) return L(`Reinstall ${effectiveMethodLabel}${suffix}`, `重新安裝 ${effectiveMethodLabel}${suffix}`);
    if (status?.upgrade_available) return L(`Upgrade to ${status.bundled_asset_version ?? effectiveMethodLabel}`, `升級至 ${status.bundled_asset_version ?? effectiveMethodLabel}`);
    if (status?.marker_name) return L(`Reinstall ${effectiveMethodLabel}${suffix}`, `重新安裝 ${effectiveMethodLabel}${suffix}`);
    return L(`Patch with ${effectiveMethodLabel}${suffix}`, `以 ${effectiveMethodLabel}${suffix} 修補`);
  }, [busyAction, effectiveMethod, effectiveMethodLabel, effectiveOptiPatcherEnabled, selectedFsr4, selectedGame, status]);

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
        selectedFsr4 === "enabled",
        applyRecommendationsEnabled,
        selectedOptiPatcher === "enabled",
      );
      if (result.status !== "success") {
        throw new Error(result.message || L("Patch failed.", "修補失敗。"));
      }

      setAppLaunchOptions(Number(selectedAppId), result.launch_options || "");
      setResultMessage(result.message || L(`Patched ${selectedGame.name} using ${effectiveMethodLabel}.`, `已使用 ${effectiveMethodLabel} 修補 ${selectedGame.name}。`));
      toaster.toast({
        title: "DLSS Enabler",
        body: result.message || L(`Patched ${selectedGame.name} using ${effectiveMethodLabel}.`, `已使用 ${effectiveMethodLabel} 修補 ${selectedGame.name}。`),
      });
      await loadStatus(selectedAppId);
    } catch (error) {
      const message = error instanceof Error ? error.message : L("Patch failed.", "修補失敗。");
      setResultMessage(L(`Error: ${message}`, `錯誤：${message}`));
      toaster.toast({ title: "DLSS Enabler", body: message });
    } finally {
      setBusyAction(null);
    }
  }, [applyRecommendationsEnabled, effectiveMethodLabel, loadStatus, selectedAppId, selectedFsr4, selectedGame, selectedMethod, selectedOptiPatcher]);

  const handleUnpatch = useCallback(async () => {
    if (!selectedGame || !selectedAppId) return;

    setBusyAction("unpatch");
    setResultMessage("");
    try {
      const result = await unpatchGame(selectedAppId);
      if (result.status !== "success") {
        throw new Error(result.message || L("Unpatch failed.", "還原修補失敗。"));
      }

      setAppLaunchOptions(Number(selectedAppId), result.launch_options || "");
      setResultMessage(result.message || L(`Unpatched ${selectedGame.name}.`, `已還原 ${selectedGame.name} 的修補。`));
      toaster.toast({
        title: "DLSS Enabler",
        body: result.message || L(`Unpatched ${selectedGame.name}.`, `已還原 ${selectedGame.name} 的修補。`),
      });
      await loadStatus(selectedAppId);
    } catch (error) {
      const message = error instanceof Error ? error.message : L("Unpatch failed.", "還原修補失敗。");
      setResultMessage(L(`Error: ${message}`, `錯誤：${message}`));
      toaster.toast({ title: "DLSS Enabler", body: message });
    } finally {
      setBusyAction(null);
    }
  }, [loadStatus, selectedAppId, selectedGame]);

  const versionDisplay = useMemo(() => {
    if (!selectedGame || status?.status !== "success" || !status.patched) {
      return { text: "—", color: undefined as string | undefined };
    }

    const text = status.installed_asset_version || status.marker_asset_version || L("Unknown", "未知");
    if (status.reinstall_recommended) {
      return { text, color: "#ff7b72" };
    }
    if (status.upgrade_available) {
      return { text, color: "#ffd866" };
    }
    return { text, color: "#3fb950" };
  }, [selectedGame, status]);

  const fsr4Display = useMemo(() => {
    if (!selectedGame || status?.status !== "success") {
      return { text: "—", color: undefined as string | undefined };
    }
    if (!status.fsr4_enabled) {
      return { text: L("Disabled", "已停用"), color: undefined as string | undefined };
    }
    const text = status.fsr4_label || "FSR4 INT8 4.0.2b";
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
      return { text: L("Disabled", "已停用"), color: undefined as string | undefined };
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
    if (!selectedGame) return L("Choose a game to manage its patch state.", "請選擇一款遊戲以管理修補狀態。");
    if (statusLoading) return L("Loading patch status...", "正在載入修補狀態...");
    if (!status) return L("No status loaded yet.", "尚未載入狀態。");
    if (status.status === "error") return L(`Error: ${status.message || "Failed to load status."}`, `錯誤：${status.message || "無法載入狀態。"}`);
    if (!status.prefix_exists) return status.message || L("Patch target not found.", "找不到修補目標。");
    if (!status.patched) return status.message || L("This game is not currently patched.", "此遊戲目前尚未修補。");
    if (status.reinstall_recommended || status.upgrade_available || status.fsr4_reinstall_recommended || status.optipatcher_reinstall_recommended) {
      return status.message || L("An update is available.", "有可用的更新。");
    }
    if (status.fsr4_enabled && !status.fsr4_files_complete) {
      return L("FSR4 sidecar files are expected but incomplete. Reinstall recommended.", "FSR4 輔助檔案預期存在但不完整，建議重新安裝。");
    }
    if (status.optipatcher_enabled && !status.optipatcher_files_complete) {
      return L("OptiPatcher files are expected but incomplete. Reinstall recommended.", "OptiPatcher 檔案預期存在但不完整，建議重新安裝。");
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
          label={L("Target game", "目標遊戲")}
          menuLabel={L("Installed games", "已安裝的遊戲")}
          strDefaultLabel={gamesLoading ? L("Loading installed games...", "正在載入已安裝遊戲...") : L("Choose a game", "選擇遊戲")}
          disabled={gamesLoading || games.length === 0}
          selectedOption={selectedAppId}
          rgOptions={games.map((game) => {
            const suffix = game.is_shortcut ? L(" [Non-Steam]", " [非 Steam]") : "";
            const notFound = game.prefix_exists ? "" : L(" (target not found)", "（找不到目標）");
            return { data: game.appid, label: `${game.name}${notFound}${suffix}` };
          })}
          onChange={(option) => {
            const nextAppId = String(option.data);
            lastSelectedAppId = nextAppId;
            setSelectedAppId(nextAppId);
            setResultMessage("");
          }}
        />
      </PanelSectionRow>

      <PanelSectionRow>
        <Field {...focusableFieldProps} label={L("Game", "遊戲名稱")}>{selectedGame?.name ?? "—"}</Field>
      </PanelSectionRow>

      <PanelSectionRow>
        <Field {...focusableFieldProps} label="App ID">{selectedGame?.appid ?? "—"}</Field>
      </PanelSectionRow>

      <PanelSectionRow>
        <Field {...focusableFieldProps} label={L("Target ready", "目標就緒")}>
          {selectedGame && status?.status === "success" ? (status.prefix_exists ? L("Yes", "是") : L("No", "否")) : "—"}
        </Field>
      </PanelSectionRow>

      <PanelSectionRow>
        <Field {...focusableFieldProps} label={L("Patched", "已修補")}>
          {selectedGame && status?.status === "success" ? (status.patched ? L("Yes", "是") : L("No", "否")) : "—"}
        </Field>
      </PanelSectionRow>

      <PanelSectionRow>
        <Field {...focusableFieldProps} label={L("Current DLL name", "目前 DLL 名稱")}>
          {selectedGame && status?.status === "success" && status.method
            ? (status.proxy_filename || `${status.method}.dll`)
            : "—"}
        </Field>
      </PanelSectionRow>

      {hasRecommendationNotes ? (
        <PanelSectionRow>
          <Field {...focusableFieldProps} label={L("Recommendation notes", "建議備註")}>
            <div>
              {status?.recommendation_notes?.map((note, index) => (
                <div key={`${note}-${index}`}>• {note}</div>
              ))}
            </div>
          </Field>
        </PanelSectionRow>
      ) : null}

      <PanelSectionRow>
        <Field {...focusableFieldProps} label={L("DLSS Enabler version", "DLSS Enabler 版本")}>
          {versionDisplay.color ? (
            <span style={{ color: versionDisplay.color, fontWeight: 600 }}>{versionDisplay.text}</span>
          ) : versionDisplay.text}
        </Field>
      </PanelSectionRow>

      <PanelSectionRow>
        <Field {...focusableFieldProps} label={L("Bundled version", "隨附版本")}>
          {selectedGame && status?.status === "success"
            ? (status.bundled_asset_version || "—")
            : "—"}
        </Field>
      </PanelSectionRow>

      <PanelSectionRow>
        <Field {...focusableFieldProps} label={L("FSR4 sidecar", "FSR4 輔助檔案")}>
          {fsr4Display.color ? (
            <span style={{ color: fsr4Display.color, fontWeight: 600 }}>{fsr4Display.text}</span>
          ) : fsr4Display.text}
        </Field>
      </PanelSectionRow>

      <PanelSectionRow>
        <Field {...focusableFieldProps} label={L("OptiPatcher plugin", "OptiPatcher 插件")}>
          {optiPatcherDisplay.color ? (
            <span style={{ color: optiPatcherDisplay.color, fontWeight: 600 }}>{optiPatcherDisplay.text}</span>
          ) : optiPatcherDisplay.text}
        </Field>
      </PanelSectionRow>

      <PanelSectionRow>
        <Field {...focusableFieldProps} label={L("OptiScaler base", "OptiScaler 基底")}>
          {selectedGame && status?.status === "success"
            ? (status.fsr4_enabled ? (status.fsr4_optiscaler_version || "0.7.9") : "—")
            : "—"}
        </Field>
      </PanelSectionRow>

      {statusMessage ? (
        <PanelSectionRow>
          <Field {...focusableFieldProps} label={L("Status", "狀態")}>{statusMessage}</Field>
        </PanelSectionRow>
      ) : null}

      <PanelSectionRow>
        <DropdownItem
          label={L("Injection method", "注入方式")}
          description={injectionMethodDescription}
          menuLabel={L("Injection method", "注入方式")}
          strDefaultLabel={L("Choose DLL name", "選擇 DLL 名稱")}
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
            label={L("Apply game recommendations", "套用遊戲建議設定")}
            description={L(
              "Automatically use the recommended DLL name, OptiPatcher plugin, and any game-specific OptiScaler.ini overrides.",
              "自動使用建議的 DLL 名稱、OptiPatcher 插件與特定遊戲的 OptiScaler.ini 覆寫設定。",
            )}
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

      {applyRecommendationsEnabled && selectedFsr4 === "enabled" && effectiveIniOverrideLines.length ? (
        <PanelSectionRow>
          <Field {...focusableFieldProps} label={L("Additional OptiScaler.ini overrides", "額外 OptiScaler.ini 覆寫")}>
            <div>
              {effectiveIniOverrideLines.map((line, index) => (
                <div key={`${line}-${index}`}>• {line}</div>
              ))}
            </div>
          </Field>
        </PanelSectionRow>
      ) : null}

      <PanelSectionRow>
        <ToggleField
          label={L("FSR4 INT8 sidecar", "FSR4 INT8 輔助檔案")}
          description={L(
            "Experimental: installs OptiScaler 0.7.9 FFX sidecar files plus FSR4 INT8 4.0.2b.",
            "實驗性：安裝 OptiScaler 0.7.9 FFX 輔助檔案與 FSR4 INT8 4.0.2b。",
          )}
          checked={selectedFsr4 === "enabled"}
          onChange={(checked) => {
            const nextValue = checked ? "enabled" : "disabled";
            lastSelectedFsr4 = nextValue;
            setSelectedFsr4(nextValue);
          }}
          disabled={!selectedGame || busyAction !== null}
        />
      </PanelSectionRow>

      <PanelSectionRow>
        <ToggleField
          label={L("OptiPatcher plugin", "OptiPatcher 插件")}
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
          {busyAction === "unpatch" ? L("Unpatching...", "正在還原修補...") : L("Unpatch selected game", "還原所選遊戲修補")}
        </ButtonItem>
      </PanelSectionRow>

      <PanelSectionRow>
        <ButtonItem layout="below" onClick={() => selectedAppId && void loadStatus(selectedAppId)} disabled={!selectedAppId || busyAction !== null || statusLoading}>
          {statusLoading ? L("Refreshing...", "正在重新整理...") : L("Refresh selected game status", "重新整理所選遊戲狀態")}
        </ButtonItem>
      </PanelSectionRow>

      {resultMessage ? (
        <PanelSectionRow>
          <Field {...focusableFieldProps} label={L("Last action", "最近操作")}>
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
