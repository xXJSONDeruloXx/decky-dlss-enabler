#!/usr/bin/env bash
set -euo pipefail

CLI_LOCATION="$(pwd)/cli/decky"
PLUGIN_DIR="$(pwd)"
OUTPUT_DIR="$PLUGIN_DIR/out"
TMP_OUTPUT_DIR="$PLUGIN_DIR/.decky-tmp"
ENGINE="docker"

echo "Building plugin in $PLUGIN_DIR"

if ! test -x "$CLI_LOCATION"; then
  echo "Decky CLI not found at $CLI_LOCATION"
  echo "Run: bash .vscode/setup.sh"
  exit 1
fi

mkdir -p "$OUTPUT_DIR" "$TMP_OUTPUT_DIR"

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  ENGINE="docker"
elif command -v podman >/dev/null 2>&1; then
  if ! podman info >/dev/null 2>&1; then
    echo "Starting podman machine..."
    podman machine start >/dev/null
  fi
  ENGINE="podman"
else
  echo "Neither a working docker daemon nor podman is available."
  exit 1
fi

"$CLI_LOCATION" plugin build -e "$ENGINE" -t "$TMP_OUTPUT_DIR" -o "$OUTPUT_DIR" "$PLUGIN_DIR"
