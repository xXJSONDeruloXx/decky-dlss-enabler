#!/usr/bin/env python3
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests

QUIRKS_DB_PATH = Path(__file__).resolve().parents[1] / "py_modules" / "quirks_db.json"
STEAM_SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
USER_AGENT = "Mozilla/5.0 (Decky DLSS Enabler quirks DB updater)"

# Entries that are not useful for Steam-appid lookup in this plugin.
DROP_KEYS = {
    "Alan-Wake-II",
    "Arknights-Endfield",
    "Capcom-RE-engine-games",
    "Escape-from-Tarkov-(SPT)",
    "Luma-Unreal-Engine-Luma-UE",
    "Minecraft-RTX",
    "Minecraft-RTX-(Minecraft-Education)",
    "RTX-Remix-Games",
    "Zenless-Zone-Zero",
}

# Hard mappings for tricky pages, mods, or titles where Steam search is inconsistent.
MANUAL_APPIDS = {
    "171": [1269370],
    "3489700": [3489700],
    "Avatar-Frontiers-of-Pandora": [2840770],
    "Diablo-II-Resurrected": [2536520],
    "Dragon-Age-The-Veilguard": [1845910],
    "Dying-Light-The-Beast": [3008130],
    "Elden-Ring-(ERSS‐FG)": [1245620],
    "Epic-Mickey-Rebrushed": [1522160],
    "Guardians-of-the-Galaxy": [1088850],
    "HITMAN-3-World-of-Assassination": [1659040],
    "Horizon-Forbidden-West-Complete-Edition": [2420110],
    "Horizon-Zero-Dawn": [1151640],
    "Horizon-Zero-Dawn-Remastered": [2561580],
    "Immortals-of-Aveum": [2009100],
    "Metro-Exodus-Enhanced-Edition": [412020],
    "Need-For-Speed-Unbound": [1846380],
    "Prey-Luma-Remastered-mod": [480490],
    "Returnal": [1649240],
    "Rise-of-the-Tomb-Raider": [391220],
    "Robocop-Rogue-City": [1681430],
    "Robocop-Rogue-City-‐-Unfinished-Business": [3527760],
    "STALKER-Enhanced-Editions": [2427410, 2427420, 2427430],
    "STAR-WARS-Jedi-Fallen-Order": [1172380],
    "STAR-WARS-Jedi-Survivor": [1774580],
    "Sackboy-‐-A-Big-Adventure": [1599660],
    "SekiroTSR": [814380],
    "Skyrim-SE": [489830],
    "The-Callisto-Protocol": [1544020],
    "The-Last-of-Us-Part-I": [1888930],
    "The-Last-of-Us-Part-II-Remastered": [2531310],
    "The-Outer-Worlds-Spacers-Choice-Edition": [1920490],
    "Tiny-Tinas-Wonderlands": [1286680],
    "Tony-Hawk's-Pro-Skater-3-4": [2545710],
    "UNCHARTED-Legacy-of-Thieves-Collection": [1659420],
    "Wild-Hearts": [1938010],
}

QUERY_HINTS = {
    "A-Plague-Tale-Requiem": ["A Plague Tale Requiem"],
    "Assassins-Creed-Mirage": ["Assassin's Creed Mirage"],
    "Assassins-Creed-Shadows": ["Assassin's Creed Shadows"],
    "Banishers-Ghosts-of-New-Eden": ["Banishers Ghosts of New Eden"],
    "Black-Myth-Wukong": ["Black Myth Wukong"],
    "Clair-Obscur-Expedition-33": ["Clair Obscur Expedition 33"],
    "Cronos-The-New-Dawn": ["Cronos The New Dawn"],
    "DEATH-STRANDING-2-ON-THE-BEACH": ["Death Stranding 2 On The Beach"],
    "DYNASTY-WARRIORS-ORIGINS": ["Dynasty Warriors Origins"],
    "Dead-Space-(2023)": ["Dead Space 2023", "Dead Space"],
    "Diablo-4": ["Diablo IV"],
    "Dragons-Dogma-2": ["Dragon's Dogma 2"],
    "Dying-Light-2": ["Dying Light 2 Stay Human"],
    "Ghost-of-Tsushima-DIRECTORS-CUT": ["Ghost of Tsushima Directors Cut"],
    "God-of-War-2018": ["God of War"],
    "God-of-War-Ragnarok": ["God of War Ragnarok"],
    "Grand-Theft-Auto-III-‐-Definitive-Edition": ["Grand Theft Auto III The Definitive Edition"],
    "Grand-Theft-Auto-San-Andreas-‐-Definitive-Edition": ["Grand Theft Auto San Andreas The Definitive Edition"],
    "Grand-Theft-Auto-Vice-City-‐-Definitive-Edition": ["Grand Theft Auto Vice City The Definitive Edition"],
    "Hellblade-Senuas-Sacrifice": ["Hellblade Senuas Sacrifice"],
    "Indiana-Jones-and-the-Great-Circle": ["Indiana Jones and the Great Circle"],
    "Kena-Bridge-of-Spirits": ["Kena Bridge of Spirits"],
    "Mafia-The-Old-Country": ["Mafia The Old Country"],
    "Marvels-Midnight-Suns": ["Marvel Midnight Suns"],
    "Marvels-Spider‐Man-2": ["Marvel Spider Man 2"],
    "Marvels-Spider‐Man-Miles-Morales": ["Marvel Spider Man Miles Morales"],
    "Marvels-Spider‐Man-Remastered": ["Marvel Spider Man Remastered"],
    "Metal-Gear-Solid-Δ-Snake-Eater": ["Metal Gear Solid Delta Snake Eater"],
    "Monster-Hunter-Stories-3-Twisted-Reflection": ["Monster Hunter Stories 3 Twisted Reflection"],
    "POSTAL-4-No-Regerts": ["Postal 4 No Regerts"],
    "Quarantine-Zone-The-Last-Check": ["Quarantine Zone The Last Check"],
    "Resident-Evil-2-(2019)": ["Resident Evil 2"],
    "Resident-Evil-3-(2020)": ["Resident Evil 3"],
    "Resident-Evil-4-(2023)": ["Resident Evil 4"],
    "Resident-Evil-8-Village": ["Resident Evil Village"],
    "Resident-Evil-9-Requiem": ["Resident Evil Requiem"],
    "Rune-Factory-Guardians-of-Azuma": ["Rune Factory Guardians of Azuma"],
    "S.T.A.L.K.E.R.-2-Heart-of-Chornobyl": ["Stalker 2 Heart of Chornobyl"],
    "Silent-Hill-2-Remake": ["Silent Hill 2"],
    "Star-Wars-Outlaws": ["Star Wars Outlaws"],
    "The-Elder-Scrolls-IV-Oblivion-Remastered": ["The Elder Scrolls IV Oblivion Remastered"],
    "Tom-Clancys-Ghost-Recon-Breakpoint": ["Tom Clancy's Ghost Recon Breakpoint"],
    "Tom-Clancys-Ghost-Recon-Wildlands": ["Tom Clancy's Ghost Recon Wildlands"],
    "Tom-Clancys-Rainbow-Six-Siege-X": ["Tom Clancy's Rainbow Six Siege X", "Tom Clancy's Rainbow Six Siege"],
    "Tom-Clancys-The-Division-2": ["Tom Clancy's The Division 2"],
    "WUCHANG-Fallen-Feathers": ["WUCHANG Fallen Feathers"],
}

ALLOWED_SUFFIXES = {
    "complete edition",
    "definitive edition",
    "directors cut",
    "director s cut",
    "enhanced edition",
    "reloaded edition",
    "remastered",
}

BANNED_RESULT_TOKENS = {
    "artbook",
    "benchmark",
    "beta",
    "bundle",
    "character",
    "collection",
    "content",
    "creator",
    "demo",
    "dlc",
    "episode",
    "expansion",
    "kit",
    "offer",
    "pack",
    "pass",
    "soundtrack",
    "supporter",
    "tool",
    "trial",
    "upgrade",
    "wallpaper",
}


def _fetch_json(url: str, params: dict[str, str]) -> dict:
    response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    return response.json()


def _normalize_name(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.lower()
    for old, new in [
        ("™", ""),
        ("®", ""),
        ("’", "'"),
        ("‘", "'"),
        ("‐", "-"),
        ("–", "-"),
        ("—", "-"),
        ("&", " and "),
        (":", " "),
        ("Δ", " delta "),
    ]:
        normalized = normalized.replace(old, new)

    for old, new in {
        "assassins": "assassin's",
        "dragons": "dragon's",
        "marvels": "marvel's",
        "senuas": "senua's",
    }.items():
        normalized = re.sub(rf"\b{re.escape(old)}\b", new, normalized)

    roman_replacements = {
        " ii ": " 2 ",
        " iii ": " 3 ",
        " iv ": " 4 ",
        " vi ": " 6 ",
        " vii ": " 7 ",
        " viii ": " 8 ",
        " ix ": " 9 ",
    }
    padded = f" {normalized} "
    for old, new in roman_replacements.items():
        padded = padded.replace(old, new)
    normalized = padded

    for phrase in ["game of the year edition", "goty edition", "world of assassination"]:
        normalized = normalized.replace(phrase, " ")

    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _canonical_forms(value: str | None) -> set[str]:
    normalized = _normalize_name(value)
    forms = {normalized} if normalized else set()

    suffixes = [
        " complete edition",
        " definitive edition",
        " enhanced edition",
        " directors cut",
        " director s cut",
        " remastered",
        " reloaded edition",
    ]
    for suffix in suffixes:
        if normalized.endswith(suffix):
            forms.add(normalized[: -len(suffix)].strip())

    if re.search(r" (2018|2019|2020|2023)$", normalized):
        forms.add(re.sub(r" (2018|2019|2020|2023)$", "", normalized))

    return {form for form in forms if form}


def _candidate_queries(entry_key: str, entry: dict) -> list[str]:
    queries: list[str] = []
    for value in QUERY_HINTS.get(entry_key, []):
        if value and value not in queries:
            queries.append(value)

    for value in [entry.get("steam_name"), str(entry.get("wiki_slug") or "").replace("-", " ")]:
        if value and value not in queries:
            queries.append(str(value))

    for value in entry.get("aliases") or []:
        if value and value not in queries:
            queries.append(str(value))

    return queries


def _score_match(entry_forms: set[str], result_name: str, result_index: int) -> int:
    result_forms = _canonical_forms(result_name)
    score = 0

    for entry_form in entry_forms:
        for result_form in result_forms:
            if entry_form == result_form:
                score = max(score, 100)
            elif result_form.startswith(f"{entry_form} "):
                tail = result_form[len(entry_form) + 1 :]
                if tail in ALLOWED_SUFFIXES:
                    score = max(score, 96)
            elif entry_form.startswith(f"{result_form} "):
                tail = entry_form[len(result_form) + 1 :]
                if tail.isdigit() or tail in {"fg", "mod"}:
                    score = max(score, 92)
            elif len(entry_form) >= 6 and (entry_form in result_form or result_form in entry_form):
                score = max(score, 85)

    if set(_normalize_name(result_name).split()) & BANNED_RESULT_TOKENS:
        score -= 30

    score -= result_index
    return score


def _best_search_result(entry_key: str, entry: dict) -> tuple[int, str] | None:
    entry_forms: set[str] = set()
    for value in _candidate_queries(entry_key, entry):
        entry_forms |= _canonical_forms(value)

    best_result: tuple[int, str] | None = None
    best_score = 0

    for query in _candidate_queries(entry_key, entry)[:4]:
        payload = _fetch_json(
            STEAM_SEARCH_URL,
            {
                "term": query,
                "cc": "US",
                "l": "english",
            },
        )
        for index, item in enumerate(payload.get("items") or []):
            score = _score_match(entry_forms, str(item.get("name") or ""), index)
            if score > best_score:
                best_score = score
                best_result = (int(item["id"]), str(item.get("name") or ""))

        if best_score >= 95:
            break

        time.sleep(0.05)

    if best_score >= 90:
        return best_result

    return None


def main() -> int:
    payload = json.loads(QUIRKS_DB_PATH.read_text(encoding="utf-8"))
    games = payload.get("games") if isinstance(payload, dict) else None
    if not isinstance(games, dict):
        raise RuntimeError(f"unexpected quirks DB format in {QUIRKS_DB_PATH}")

    unresolved: list[str] = []
    updated_games: dict[str, dict] = {}

    for entry_key, entry in games.items():
        if entry_key in DROP_KEYS:
            continue
        if not isinstance(entry, dict):
            continue

        updated_entry = dict(entry)

        if entry_key in MANUAL_APPIDS:
            updated_entry["steam_appids"] = MANUAL_APPIDS[entry_key]
        else:
            best_result = _best_search_result(entry_key, updated_entry)
            if not best_result:
                unresolved.append(entry_key)
                updated_games[entry_key] = updated_entry
                continue
            updated_entry["steam_appids"] = [best_result[0]]

        updated_games[entry_key] = updated_entry

    if unresolved:
        print("unresolved entries:", file=sys.stderr)
        for entry_key in unresolved:
            print(f"- {entry_key}", file=sys.stderr)
        return 1

    payload["games"] = updated_games
    QUIRKS_DB_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"updated {QUIRKS_DB_PATH}")
    print(f"entries: {len(updated_games)}")
    print(f"with steam_appids: {sum(1 for entry in updated_games.values() if entry.get('steam_appids'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
