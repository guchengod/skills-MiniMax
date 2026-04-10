#!/usr/bin/env python3
"""Extract track metadata from Apple Music via osascript."""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.expanduser("~/.claude/skills/shared"))
from i18n import msg

LANG = "zh"


APPLESCRIPT = r'''
tell application "Music"
    set output to ""
    repeat with t in tracks of library playlist 1
        set output to output & (name of t) & "|||" & (artist of t) & "|||" & (album of t) & "|||" & (genre of t) & "|||" & (played count of t) & "|||" & (duration of t) & linefeed
    end repeat
    return output
end tell
'''

# Patterns that identify TTS / test / generated audio files
_TTS_PATTERNS = [
    r'^audio_',
    r'^sample_',
    r'^tts-',
    r'^tts_',
    r'^MiniMax_',
    r'^\d{10,}',            # Unix-timestamp-style names
    r'^\d{4}-\d{2}-\d{2}',  # Date-prefixed names
    r'^[\u4e00-\u9fff].*\u6d4b\u8bd5',  # Chinese text containing "测试"
    r'^\u8bed\u97f3',        # Starts with "语音"
    r'^\u5408\u6210',        # Starts with "合成"
    r'_sample\.mp3$',
]
_TTS_RE = re.compile('|'.join(_TTS_PATTERNS), re.IGNORECASE)


def _is_tts_track(name: str, artist: str) -> bool:
    """Return True if the track looks like a TTS/test file to skip."""
    if artist.strip():
        return False
    return bool(_TTS_RE.search(name))


def _music_app_running() -> bool:
    """Check whether Music.app is currently running."""
    try:
        result = subprocess.run(
            ['osascript', '-e',
             'tell application "System Events" to (name of processes) contains "Music"'],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() == 'true'
    except Exception:
        return False


def scan() -> dict:
    """Run the AppleScript and return parsed track data."""
    try:
        result = subprocess.run(
            ['osascript', '-e', APPLESCRIPT],
            capture_output=True, text=True, timeout=120,
        )
    except FileNotFoundError:
        print("Error: osascript not found. This script requires macOS.", file=sys.stderr)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("Error: osascript timed out.", file=sys.stderr)
        sys.exit(1)

    if result.returncode != 0:
        stderr = result.stderr.strip()
        # Common case: Music.app not running or no library
        if 'execution error' in stderr or 'not running' in stderr.lower():
            print(f"Warning: Could not query Music.app: {stderr}", file=sys.stderr)
            return {
                "source": "apple_music",
                "scanned_at": datetime.now(timezone.utc).isoformat(),
                "track_count": 0,
                "tracks": [],
            }
        print(f"Error from osascript: {stderr}", file=sys.stderr)
        sys.exit(1)

    raw = result.stdout
    tracks = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split('|||')
        if len(parts) < 6:
            continue

        name = parts[0].strip()
        artist = parts[1].strip()
        album = parts[2].strip()
        genre = parts[3].strip()
        try:
            played_count = int(parts[4].strip())
        except ValueError:
            played_count = 0
        try:
            duration = round(float(parts[5].strip()))
        except ValueError:
            duration = 0

        if _is_tts_track(name, artist):
            continue

        tracks.append({
            "name": name,
            "artist": artist,
            "album": album,
            "genre": genre,
            "played_count": played_count,
            "duration": duration,
        })

    return {
        "source": "apple_music",
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "track_count": len(tracks),
        "tracks": tracks,
    }


def main():
    parser = argparse.ArgumentParser(description="Scan Apple Music library")
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
