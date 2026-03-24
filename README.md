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
- updates Steam launch options to include:
  - `WINEDLLOVERRIDES="<method>=n,b"`
  - `SteamDeck=0`

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
DLSS_ENABLER_4_3_1_0_<METHOD>_DLL
```

## Bundled asset

Expected bundled file:

- `bin/version.dll`
- sha256 `a07b82de96e8c278184fe01409d7b4851a67865f7b8fed56332e40028dc3b41f`

## Build

```bash
pnpm build
bash .vscode/build.sh
```
