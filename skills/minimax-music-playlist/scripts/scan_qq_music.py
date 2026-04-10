#!/usr/bin/env python3
"""Extract track and playlist data from QQ Music's SQLite database and preferences."""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.expanduser("~/.claude/skills/shared"))
from i18n import msg

LANG = "zh"


_DB_PATH = os.path.expanduser(
    '~/Library/Containers/com.tencent.QQMusicMac/Data/'
    'Library/Application Support/QQMusicMac/qqmusic.sqlite'
)


def _read_search_history() -> list:
    """Read search history from QQ Music's preferences plist.

    The key is intentionally misspelled as 'serachHistory' -- that is how
    QQ Music stores it.
    """
    try:
        result = subprocess.run(
            ['defaults', 'read', 'com.tencent.QQMusicMac', 'serachHistory'],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return []

    if result.returncode != 0:
        return []

    raw = result.stdout.strip()
    if not raw:
        return []

    # Apple's old-style plist format uses parentheses for arrays and
    # double-quoted strings:
    #   (
    #       "\U70df\U82b1\U6613\U51b7 \U5468\U6770\U4f26",
    #       "Love Story Taylor Swift",
    #       ...
    #   )
    # We parse this with a simple regex.
    entries = []
    for match in re.finditer(r'"((?:[^"\\]|\\.)*)"', raw):
        value = match.group(1)
        # Decode \Uxxxx escapes that Apple plist uses
        value = re.sub(
            r'\\U([0-9a-fA-F]{4})',
            lambda m: chr(int(m.group(1), 16)),
            value,
        )
        # Also handle standard backslash escapes
        value = value.replace('\\"', '"').replace('\\\\', '\\')
        entries.append(value)

    # Also handle unquoted entries (bare strings between commas)
    if not entries:
        inner = raw.strip('()\n ')
        for item in inner.split(','):
            item = item.strip().strip('"').strip()
            if item:
                entries.append(item)

    return entries


def scan() -> dict:
    """Read QQ Music's SQLite database and return structured data."""
    if not os.path.exists(_DB_PATH):
        print(
            f"Warning: QQ Music database not found at {_DB_PATH}",
            file=sys.stderr,
        )
        return {
            "source": "qq_music",
            "scanned_at": datetime.now(timezone.utc).isoformat(),
            "track_count": 0,
            "tracks": [],
            "playlists": {},
            "playlist_counts": {},
            "search_history": [],
        }

    try:
        conn = sqlite3.connect(f'file:{_DB_PATH}?mode=ro', uri=True)
    except sqlite3.OperationalError as exc:
        print(f"Error opening database: {exc}", file=sys.stderr)
        sys.exit(1)

    conn.row_factory = sqlite3.Row

    # --- Tracks ---
    try:
        tracks_rows = conn.execute(
            'SELECT id, name, singer, album FROM SONGS'
        ).fetchall()
    except sqlite3.OperationalError as exc:
        print(f"Error querying SONGS table: {exc}", file=sys.stderr)
        tracks_rows = []

    tracks = []
    track_ids = set()
    for row in tracks_rows:
        tid = row['id']
        track_ids.add(tid)
        tracks.append({
            "id": tid,
            "name": row['name'] or '',
            "singer": row['singer'] or '',
            "album": row['album'] or '',
        })

    # --- Playlists (folders) ---
    try:
        folder_rows = conn.execute(
            'SELECT seq, folderName, foldercount FROM NEWFOLDERS'
        ).fetchall()
    except sqlite3.OperationalError:
        folder_rows = []

    folder_name_by_seq = {}
    playlist_counts = {}
    for row in folder_rows:
        seq = row['seq']
        name = row['folderName'] or ''
        count = row['foldercount'] if row['foldercount'] else 0
        folder_name_by_seq[seq] = name
        playlist_counts[name] = count

    # --- Playlist-Song mapping ---
    try:
        mapping_rows = conn.execute(
            'SELECT seq, id FROM NEWFOLDERSONGS'
        ).fetchall()
    except sqlite3.OperationalError:
        mapping_rows = []

    playlists = {}
    for row in mapping_rows:
        seq = row['seq']
        song_id = row['id']
        folder_name = folder_name_by_seq.get(seq)
        if folder_name is None:
            continue
        playlists.setdefault(folder_name, []).append(song_id)

    conn.close()

    # --- Search history ---
    search_history = _read_search_history()

    return {
        "source": "qq_music",
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "track_count": len(tracks),
        "tracks": tracks,
        "playlists": playlists,
        "playlist_counts": playlist_counts,
        "search_history": search_history,
    }


def main():
    parser = argparse.ArgumentParser(description="Scan QQ Music library")
    parser.add_argument('--output', type=str, default=None,
                        help="Path to write JSON output (default: stdout)")
    parser.add_argument("--lang", default="zh", choices=["zh", "en"], help="UI language")
    args = parser.parse_args()

    global LANG
    LANG = args.lang

    data = scan()
    output_json = json.dumps(data, ensure_ascii=False, indent=2)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(output_json)
            f.write('\n')
        print(f"Wrote {data['track_count']} tracks to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == '__main__':
    main()
