# Decky DLSS Enabler

Decky plugin for managing a bundled DLSS Enabler proxy inside a game's Proton prefix.

## What it does

For each selected Steam game, the plugin can:

- detect whether the game's prefix is patched
- show which DLL name is currently being used
- back up the stock `system32/<proxy>.dll` when present
- copy the bundled DLSS Enabler proxy into `system32` using the selected DLL name
- create a managed marker file so patch state is deterministic
- restore the original DLL on unpatch
- preserve and restore the game's original Steam launch options
- apply `WINEDLLOVERRIDES="<proxy>=n,b"` automatically when patching

## Supported injection methods

- `version`
- `winmm`
- `d3d11`
- `d3d12`
- `dinput8`
- `dxgi`
- `wininet`
- `winhttp`
- `dbghelp`

## Managed marker format

The plugin writes a marker like:

```text
DLSS_ENABLER_4_3_1_0_VERSION_DLL
```

That marker lets the plugin know which DLL name it owns and how to cleanly restore the original prefix state.

## Bundled asset

The plugin expects this static asset to be bundled into `bin/` by Decky build tooling:

- `version.dll`
- sha256 `a07b82de96e8c278184fe01409d7b4851a67865f7b8fed56332e40028dc3b41f`

## Local build

```bash
pnpm install
pnpm build
```

## Zip build

```bash
bash .vscode/build.sh
```
