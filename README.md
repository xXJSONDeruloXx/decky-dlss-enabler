<p align="center">
   <a href="https://ko-fi.com/B0B71HZTAX" target="_blank" rel="noopener noreferrer">
      <img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Support on Ko-fi"/>
   </a>
</p>

# Decky DLSS Enabler

Decky plugin for per-game DLSS Enabler management on Steam Deck.

## Function

For a selected Steam game, the plugin:

- locates the effective Windows game executable directory
- copies the bundled DLSS Enabler proxy there as the selected DLL name
- backs up an existing stock DLL as `<name>.backup` when present
- writes a managed marker file for deterministic cleanup
- restores the original DLL on unpatch
- replaces Steam launch options while patched with:
  - `WINEDLLOVERRIDES=<method>=n,b`
  - `SteamDeck=0 %command%`
- restores the previous Steam launch options on unpatch
- optionally installs experimental FSR4 INT8 4.0.2b sidecar files (`amd_fidelityfx_dx12.dll`, `amd_fidelityfx_upscaler_dx12.dll`, and `OptiScaler.ini`)

## Methods

- `version`
- `winmm`
- `d3d11`
- `d3d12`
- `dinput8`
- `dxgi`
- `wininet`
- `winhttp`
- `dbghelp`

Default method: `dxgi`

## Marker

Managed marker format:

```text
DLSS_ENABLER_<METHOD>_DLL
```

Legacy versioned markers from older plugin releases are still recognized and upgraded in place.

## Bundled asset

Expected bundled files:

- `bin/version.dll`
- version `4.4.0.2-dev`
- sha256 `7357292a3ced57c194f60bd2cbfc8f3837604b2365af114a2a4bc61508e9d5c6`
- optional experimental FSR4 sidecar bundle:
  - `bin/amd_fidelityfx_dx12.dll`
  - `bin/amd_fidelityfx_upscaler_dx12.dll` (`4.0.2b`)

## Build

```bash
pnpm build
bash .vscode/build.sh
```
