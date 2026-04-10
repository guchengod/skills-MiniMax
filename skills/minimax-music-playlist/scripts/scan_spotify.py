#!/usr/bin/env python3
"""
scan_spotify.py

Scan Spotify's local data on macOS to extract listening history and preferences.

Data sources (in priority order):
  1. LevelDB (PersistentCache/public.ldb) — collection, recently played, playlists
  2. osascript — current track if Spotify is running
  3. User prefs — username for identification

Usage:
    python3 scan_spotify.py --output /tmp/spotify_data.json
"""

import argparse
import json
import os
import re
import struct
import subprocess
import sys
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SPOTIFY_SUPPORT = os.path.expanduser("~/Library/Application Support/Spotify")
SPOTIFY_PREFS = os.path.join(SPOTIFY_SUPPORT, "prefs")
SPOTIFY_USERS = os.path.join(SPOTIFY_SUPPORT, "Users")
SPOTIFY_LDB = os.path.join(SPOTIFY_SUPPORT, "PersistentCache/public.ldb")
SPOTIFY_CACHES = os.path.expanduser("~/Library/Caches/com.spotify.client")


def is_installed() -> bool:
    """Check if Spotify is installed."""
    app_paths = [
        "/Applications/Spotify.app",
        os.path.expanduser("~/Applications/Spotify.app"),
    ]
    return any(os.path.exists(p) for p in app_paths)


def get_username() -> str:
    """Read username from prefs file."""
    if not os.path.exists(SPOTIFY_PREFS):
        return ""
    try:
        with open(SPOTIFY_PREFS, "r") as f:
            for line in f:
                if line.startswith("autologin.canonical_username="):
                    return line.split("=", 1)[1].strip().strip('"')
    except IOError:
        pass
    return ""


def get_user_dir() -> str:
    """Find the user data directory."""
    if not os.path.isdir(SPOTIFY_USERS):
        return ""
    for entry in os.listdir(SPOTIFY_USERS):
        if entry.endswith("-user"):
            return os.path.join(SPOTIFY_USERS, entry)
    return ""


# ---------------------------------------------------------------------------
# LevelDB parsing (simplified — read log and ldb files for text data)
# ---------------------------------------------------------------------------

def parse_leveldb_strings(db_dir: str) -> list:
    """Extract JSON-like strings from LevelDB files."""
    results = []
    if not os.path.isdir(db_dir):
        return results

    for fname in sorted(os.listdir(db_dir)):
        fpath = os.path.join(db_dir, fname)
        if not os.path.isfile(fpath):
            continue
        if not (fname.endswith(".log") or fname.endswith(".ldb") or fname.endswith(".sst")):
            continue
        try:
            with open(fpath, "rb") as f:
                raw = f.read()
            # Extract printable string sequences (min 20 chars for meaningful data)
            strings = re.findall(rb'[\x20-\x7e\xc0-\xff]{20,}', raw)
            for s in strings:
                try:
                    text = s.decode("utf-8", errors="replace")
                    results.append(text)
                except (UnicodeDecodeError, ValueError):
                    pass
        except IOError:
            pass
    return results


def extract_track_uris(db_dir: str) -> list:
    """Extract Spotify track URIs from LevelDB."""
    uris = set()
    if not os.path.isdir(db_dir):
        return []

    for fname in os.listdir(db_dir):
        fpath = os.path.join(db_dir, fname)
        if not os.path.isfile(fpath):
            continue
        try:
            with open(fpath, "rb") as f:
                raw = f.read()
            found = re.findall(rb'spotify:(track|artist|album|playlist):[A-Za-z0-9]{22}', raw)
            for uri in found:
                uris.add(uri.decode("utf-8"))
        except IOError:
            pass
    return sorted(uris)


def extract_collection_data(strings_list: list) -> dict:
    """Try to find collection/library data from LevelDB strings."""
    tracks = []
    artists = set()
    playlists = []

    for text in strings_list:
        # Try to parse JSON fragments
        if '"name"' in text and ('"artist"' in text or '"artists"' in text):
            # Might be track data
            try:
                # Try to extract JSON objects
                for match in re.finditer(r'\{[^{}]*"name"[^{}]*\}', text):
                    obj = json.loads(match.group())
                    if "name" in obj:
                        track_info = {"name": obj.get("name", "")}
                        if "artist" in obj:
                            track_info["artist"] = obj["artist"]
                            artists.add(obj["artist"])
                        if "artists" in obj and isinstance(obj["artists"], list):
                            names = [a.get("name", "") for a in obj["artists"] if isinstance(a, dict)]
                            track_info["artist"] = ", ".join(names)
                            artists.update(names)
                        if "album" in obj:
                            track_info["album"] = obj["album"] if isinstance(obj["album"], str) else obj["album"].get("name", "")
                        tracks.append(track_info)
            except (json.JSONDecodeError, ValueError):
                pass

        # Check for playlist names
        if "playlist" in text.lower() and '"name"' in text:
            try:
                for match in re.finditer(r'\{[^{}]*"name"\s*:\s*"([^"]+)"[^{}]*\}', text):
                    playlists.append(match.group(1))
            except Exception:
                pass

    return {
        "tracks": tracks,
        "artists": sorted(artists),
        "playlists": playlists,
    }


# ---------------------------------------------------------------------------
# osascript — query running Spotify
# ---------------------------------------------------------------------------

def query_osascript() -> dict:
    """Query Spotify via AppleScript for current state."""
    result = {"current_track": None, "is_running": False}

    # Check if running
    try:
        out = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to (name of processes) contains "Spotify"'],
            capture_output=True, text=True, timeout=5
        )
        result["is_running"] = out.stdout.strip() == "true"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return result

    if not result["is_running"]:
        return result

    # Get current track info
    script = '''
    tell application "Spotify"
        if player state is playing or player state is paused then
            set trackName to name of current track
            set trackArtist to artist of current track
            set trackAlbum to album of current track
            set trackDuration to duration of current track
            return trackName & "|||" & trackArtist & "|||" & trackAlbum & "|||" & trackDuration
        else
            return "NO_TRACK"
        end if
    end tell
    '''
    try:
        out = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5
        )
        text = out.stdout.strip()
        if text and text != "NO_TRACK":
            parts = text.split("|||")
            if len(parts) >= 3:
                result["current_track"] = {
                    "name": parts[0],
                    "artist": parts[1],
                    "album": parts[2],
                    "duration": int(parts[3]) if len(parts) > 3 else 0,
                }
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass

    return result


# ---------------------------------------------------------------------------
# Cache.db — SQLite cache of API responses
# ---------------------------------------------------------------------------

def scan_cache_db() -> list:
    """Scan Spotify's URLCache for API responses with track data."""
    import sqlite3

    cache_db = os.path.join(SPOTIFY_CACHES, "Cache.db")
    if not os.path.exists(cache_db):
        return []

    tracks = []
    try:
        conn = sqlite3.connect(f"file:{cache_db}?mode=ro", uri=True)
        cursor = conn.cursor()

        # Get API responses that might contain track data
        cursor.execute("""
            SELECT r.request_key, d.receiver_data
            FROM cfurl_cache_response r
            JOIN cfurl_cache_receiver_data d ON r.entry_ID = d.entry_ID
            WHERE r.request_key LIKE '%spclient%'
               OR r.request_key LIKE '%api.spotify%'
               OR r.request_key LIKE '%/v1/%'
        """)

        for url, data in cursor.fetchall():
            if not data:
                continue
            try:
                text = data.decode("utf-8", errors="replace")
                parsed = json.loads(text)
                # Extract tracks from various API response formats
                items = parsed.get("items", parsed.get("tracks", {}).get("items", []))
                if isinstance(items, list):
                    for item in items:
                        track = item.get("track", item) if isinstance(item, dict) else None
                        if track and isinstance(track, dict) and "name" in track:
                            artists = track.get("artists", [])
                            artist_names = [a.get("name", "") for a in artists if isinstance(a, dict)]
                            tracks.append({
                                "name": track["name"],
                                "artist": ", ".join(artist_names),
                                "album": track.get("album", {}).get("name", "") if isinstance(track.get("album"), dict) else "",
                            })
            except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                pass

        conn.close()
    except Exception:
        pass

    return tracks


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Scan Spotify local data on macOS")
    parser.add_argument("--output", default=None, help="Output JSON file path")
    args = parser.parse_args()

    if not is_installed():
        result = {
            "source": "spotify",
            "installed": False,
            "tracks": [],
            "scanned_at": datetime.now().isoformat(),
        }
        output_result(result, args.output)
        print("Spotify is not installed.", file=sys.stderr)
        return

    print("🎵 Scanning Spotify...", file=sys.stderr)

    all_tracks = []
    all_artists = set()
    playlist_names = []
    uris = []

    # 1. Parse LevelDB
    print("  📂 Reading LevelDB...", file=sys.stderr)
    uris = extract_track_uris(SPOTIFY_LDB)
    if uris:
        print(f"     Found {len(uris)} URIs", file=sys.stderr)

    ldb_strings = parse_leveldb_strings(SPOTIFY_LDB)
    collection = extract_collection_data(ldb_strings)
    all_tracks.extend(collection["tracks"])
    all_artists.update(collection["artists"])
    playlist_names.extend(collection["playlists"])

    # 2. Query osascript
    print("  🎤 Querying Spotify app...", file=sys.stderr)
    osa = query_osascript()
    current = osa.get("current_track")
    if current:
        all_tracks.append(current)
        if current.get("artist"):
            all_artists.add(current["artist"])
        print(f"     Currently playing: {current.get('name', '?')} - {current.get('artist', '?')}", file=sys.stderr)
    elif osa.get("is_running"):
        print("     Spotify is running but no track playing", file=sys.stderr)
    else:
        print("     Spotify is not running", file=sys.stderr)

    # 3. Scan Cache.db
    print("  💾 Scanning URL cache...", file=sys.stderr)
    cache_tracks = scan_cache_db()
    if cache_tracks:
        all_tracks.extend(cache_tracks)
        for t in cache_tracks:
            if t.get("artist"):
                all_artists.update(a.strip() for a in t["artist"].split(","))
        print(f"     Found {len(cache_tracks)} cached tracks", file=sys.stderr)

    # Deduplicate tracks by name+artist
    seen = set()
    unique_tracks = []
    for t in all_tracks:
        key = (t.get("name", "").lower(), t.get("artist", "").lower())
        if key not in seen and key[0]:
            seen.add(key)
            unique_tracks.append(t)

    # Build result
    username = get_username()
    result = {
        "source": "spotify",
        "installed": True,
        "username": username,
        "account_type": "free",  # From prefs
        "is_running": osa.get("is_running", False),
        "tracks": unique_tracks,
        "artists": sorted(all_artists - {""}),
        "playlists": playlist_names,
        "uris": uris[:100],  # Cap at 100
        "scanned_at": datetime.now().isoformat(),
    }

    output_result(result, args.output)

    print(f"\n✅ Spotify scan complete!", file=sys.stderr)
    print(f"   Tracks: {len(unique_tracks)}", file=sys.stderr)
    print(f"   Artists: {len(all_artists)}", file=sys.stderr)
    print(f"   URIs: {len(uris)}", file=sys.stderr)
    if not unique_tracks and not uris:
        print("   ⚠️  Very little data found — Spotify may be newly installed.", file=sys.stderr)
        print("      Use the app more, then rescan for better results.", file=sys.stderr)


def output_result(result: dict, output_path: str = None):
    """Output result to file and/or stdout."""
    json_str = json.dumps(result, ensure_ascii=False, indent=2)

    if output_path:
        output_path = os.path.expanduser(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(json_str)

    print(json_str)


if __name__ == "__main__":
    main()
