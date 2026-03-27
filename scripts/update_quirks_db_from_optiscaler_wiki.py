#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unicodedata
from pathlib import Path

WIKI_GIT_URL = "https://github.com/optiscaler/OptiScaler.wiki.git"
QUIRKS_DB_PATH = Path(__file__).resolve().parent.parent / "py_modules" / "quirks_db.json"
SUPPORTED_METHODS = {
    "version",
    "winmm",
    "d3d11",
    "d3d12",
    "dinput8",
    "dxgi",
    "wininet",
    "winhttp",
    "dbghelp",
}
SKIP_PAGE_STEMS = {
    "CL-Template",
    "Home",
    "Known-Issues",
    "Manual-Installation",
    "Legacy-Installation",
    "Frame-Generation-Options",
    "Fakenvapi",
    "Hudfix-incompatible",
    "Update-OptiScaler-when-using-DLSS-Enabler",
}


def _normalize_name(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.lower().replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _slug_to_display_name(slug: str) -> str:
    return slug.replace("-", " ")


def _clean_note_text(value: str) -> str:
    value = value.replace(" +", " ").replace("+", " ")
    value = re.sub(r"https?://\S+\[(.*?)\]", r"\1", value)
    value = re.sub(r"\[(.*?)\]\([^)]*\)", r"\1", value)
    value = value.replace("`", "")
    value = value.replace("**", "")
    value = value.replace("*", "")
    value = re.sub(r"\s+", " ", value)
    return value.strip(" -")


def _parse_asciidoc_table_cells(text: str) -> dict[str, str]:
    lines = text.splitlines()
    cells: dict[str, str] = {}
    index = 0
    while index < len(lines):
        match = re.match(r"^\|\*\*(.+?)\*\*\s*$", lines[index].rstrip())
        if not match:
            index += 1
            continue

        key = match.group(1).strip()
        index += 1
        if index >= len(lines):
            break

        line = lines[index]
        buffer: list[str] = []
        if line.startswith("a|"):
            remainder = line[2:]
            if remainder:
                buffer.append(remainder)
            index += 1
            while index < len(lines):
                next_line = lines[index].rstrip()
                if re.match(r"^\|\*\*.+?\*\*\s*$", next_line) or next_line == "|===":
                    break
                buffer.append(lines[index])
                index += 1
        elif line.startswith("|"):
            buffer.append(line[1:])
            index += 1
        else:
            index += 1

        cells[key] = "\n".join(buffer).strip()

    return cells


def _extract_bullets(block: str) -> list[str]:
    bullets: list[str] = []
    current: str | None = None

    for raw_line in block.splitlines():
        line = raw_line.rstrip()
        if not line or line.startswith(".For example:"):
            continue

        stripped = line.lstrip()
        if stripped.startswith("* "):
            if current:
                cleaned = _clean_note_text(current)
                if cleaned:
                    bullets.append(cleaned)
            current = stripped[2:].strip()
        elif stripped.startswith("** "):
            continuation = stripped[3:].strip()
            current = continuation if current is None else f"{current} {continuation}"
        elif current is not None:
            current = f"{current} {stripped.strip()}"

    if current:
        cleaned = _clean_note_text(current)
        if cleaned:
            bullets.append(cleaned)

    deduped: list[str] = []
    seen = set()
    for bullet in bullets:
        key = bullet.lower()
        if key not in seen:
            deduped.append(bullet)
            seen.add(key)
    return deduped


def _parse_page(path: Path) -> dict | None:
    if path.stem in SKIP_PAGE_STEMS:
        return None

    cells = _parse_asciidoc_table_cells(path.read_text(encoding="utf-8", errors="replace"))
    filename_cell = cells.get("Filename")
    if not filename_cell:
        return None

    methods = sorted(
        {
            match.group(1).lower()
            for match in re.finditer(r"([A-Za-z0-9_]+)\.dll", filename_cell, re.IGNORECASE)
            if match.group(1).lower() in SUPPORTED_METHODS
        }
    )
    if not methods:
        return None

    notes = _extract_bullets(cells.get("Notes", ""))
    known_issues = _extract_bullets(cells.get("Known Issues", ""))

    if len(methods) > 1:
        notes = [
            f"OptiScaler wiki lists multiple compatible DLL names: {', '.join(f'{method}.dll' for method in methods)}."
        ] + notes

    notes.extend(known_issues)

    return {
        "steam_name": _slug_to_display_name(path.stem),
        "steam_appids": [],
        "wiki_slug": path.stem,
        "source": "OptiScaler wiki",
        "source_url": f"https://github.com/optiscaler/OptiScaler/wiki/{path.stem}",
        "recommended_method": methods[0] if len(methods) == 1 else None,
        "recommended_methods": methods,
        "recommended_optiscaler_ini_overrides": {},
        "notes": notes,
    }


def _load_existing_db() -> dict:
    if not QUIRKS_DB_PATH.exists():
        return {"version": 1, "games": {}}
    return json.loads(QUIRKS_DB_PATH.read_text(encoding="utf-8"))


def _existing_entries_by_slug(existing_games: dict) -> dict[str, tuple[str, dict]]:
    by_slug: dict[str, tuple[str, dict]] = {}
    for key, value in existing_games.items():
        if not isinstance(value, dict):
            continue
        slug = str(value.get("wiki_slug") or "").strip()
        if slug:
            by_slug[slug] = (key, value)
    return by_slug


def _merged_entry(parsed_entry: dict, existing_entry: dict | None) -> dict:
    merged = dict(parsed_entry)
    if not existing_entry:
        return merged

    for field in [
        "steam_name",
        "steam_appids",
        "aliases",
        "recommended_optiscaler_ini_overrides",
        "notes",
        "recommended_method",
        "recommended_methods",
    ]:
        if existing_entry.get(field):
            merged[field] = existing_entry[field]

    return merged


def main() -> None:
    with tempfile.TemporaryDirectory() as tempdir:
        wiki_dir = Path(tempdir) / "wiki"
        subprocess.run(
            ["git", "clone", "--depth", "1", WIKI_GIT_URL, str(wiki_dir)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        parsed_entries = [entry for path in sorted(wiki_dir.glob("*.asciidoc")) if (entry := _parse_page(path))]

    existing_db = _load_existing_db()
    existing_games = existing_db.get("games") if isinstance(existing_db.get("games"), dict) else {}
    existing_by_slug = _existing_entries_by_slug(existing_games)

    merged_games: dict[str, dict] = {}
    matched_existing_keys: set[str] = set()

    for parsed_entry in parsed_entries:
        slug = parsed_entry["wiki_slug"]
        existing_key, existing_entry = existing_by_slug.get(slug, (slug, None))
        merged_games[existing_key] = _merged_entry(parsed_entry, existing_entry)
        matched_existing_keys.add(existing_key)

    for key, value in existing_games.items():
        if key not in matched_existing_keys and isinstance(value, dict):
            merged_games[key] = value

    output = {
        "version": 1,
        "games": dict(sorted(merged_games.items(), key=lambda item: (_normalize_name(item[1].get("steam_name") or item[0]), item[0]))),
    }
    QUIRKS_DB_PATH.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {QUIRKS_DB_PATH}")
    print(f"entries: {len(output['games'])}")


if __name__ == "__main__":
    main()
