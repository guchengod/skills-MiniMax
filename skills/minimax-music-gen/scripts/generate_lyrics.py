#!/usr/bin/env python3
"""
MiniMax Lyrics Generation API Client

Calls the lyrics_generation endpoint to auto-write song lyrics.

Modes:
  - write_full_song: Generate complete lyrics from a prompt description
  - (extensible for future modes the API may support)

Usage:
  python3 generate_lyrics.py --prompt "A cheerful love song about summer at the beach"
  python3 generate_lyrics.py --prompt "深夜独自走在街头的忧伤情歌" --output lyrics.txt
  python3 generate_lyrics.py --prompt "epic battle anthem" --mode write_full_song

Output:
  Prints the generated lyrics to stdout (for piping into generate_music.py).
  If --output is given, also saves to file.
  If --json is given, outputs raw JSON response.
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, os.path.expanduser("~/.claude/skills/shared"))
from i18n import msg
from api_base import get_api_base

LANG = "zh"


def get_api_key():
    """Get MiniMax API key from environment or ~/.minimax_api_key file."""
    key = os.environ.get("MINIMAX_API_KEY") or os.environ.get("MINIMAX_MUSIC_API_KEY")
    if not key:
        fpath = os.path.expanduser("~/.minimax_api_key")
        if os.path.isfile(fpath):
            with open(fpath) as f:
                key = f.read().strip()
    if not key:
        print(msg("env_not_set", LANG, name="MINIMAX_API_KEY"), file=sys.stderr)
        print(msg("env_run_export", LANG, name="MINIMAX_API_KEY"), file=sys.stderr)
        sys.exit(1)
    return key


def generate_lyrics(api_key, prompt, mode="write_full_song"):
    """Call the lyrics generation API and return the result."""
    api_base = get_api_base(api_key)
    url = f"{api_base}/v1/lyrics_generation"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    body = {
        "mode": mode,
        "prompt": prompt,
    }

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    print(msg("generating_lyrics", LANG), file=sys.stderr)

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        print(msg("api_request_failed", LANG, code=e.code), file=sys.stderr)
        print(msg("api_response", LANG, body=error_body[:500]), file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(msg("network_error", LANG, reason=e.reason), file=sys.stderr)
        sys.exit(1)


def extract_lyrics(result):
    """Extract lyrics text from API response.

    The API response format may vary. This function tries multiple
    common structures to find the lyrics text.
    """
    if not isinstance(result, dict):
        return None

    # Direct fields
    for key in ("lyrics", "text", "content", "generated_lyrics", "result"):
        val = result.get(key)
        if isinstance(val, str) and len(val) > 10:
            return val

    # Nested in data
    data = result.get("data", {})
    if isinstance(data, dict):
        for key in ("lyrics", "text", "content", "generated_lyrics", "result"):
            val = data.get(key)
            if isinstance(val, str) and len(val) > 10:
                return val

        # Nested in data.choices / data.results
        for list_key in ("choices", "results", "outputs"):
            items = data.get(list_key, [])
            if isinstance(items, list) and items:
                first = items[0]
                if isinstance(first, dict):
                    for key in ("lyrics", "text", "content", "message"):
                        val = first.get(key)
                        if isinstance(val, str) and len(val) > 10:
                            return val
                elif isinstance(first, str) and len(first) > 10:
                    return first

    # If response has a 'choices' at top level (OpenAI-style)
    choices = result.get("choices", [])
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            msg = first.get("message", {})
            if isinstance(msg, dict):
                return msg.get("content")
            return first.get("text") or first.get("content")

    return None


def format_lyrics_display(lyrics):
    """Pretty-print lyrics with section markers highlighted."""
    lines = lyrics.split("\n")
    formatted = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            # Section marker
            formatted.append(f"\n  🎵 {stripped}")
        elif stripped:
            formatted.append(f"  {stripped}")
        else:
            formatted.append("")
    return "\n".join(formatted)


def main():
    parser = argparse.ArgumentParser(description="Generate song lyrics via MiniMax API")
    parser.add_argument(
        "--prompt", required=True,
        help="Description of the song to write lyrics for (any language)"
    )
    parser.add_argument(
        "--mode", default="write_full_song",
        help="Generation mode (default: write_full_song)"
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="Save lyrics to this file path"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output raw JSON response instead of extracted lyrics"
    )
    parser.add_argument(
        "--lang", default="zh", choices=["zh", "en"],
        help="UI language"
    )
    args = parser.parse_args()

    global LANG
    LANG = args.lang

    api_key = get_api_key()

    # Call API
    result = generate_lyrics(api_key, args.prompt, args.mode)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # Extract lyrics
    lyrics = extract_lyrics(result)

    if not lyrics:
        print(msg("no_lyrics_extracted", LANG), file=sys.stderr)
        print(msg("raw_response_label", LANG), file=sys.stderr)
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(1)

    # Display
    print("", file=sys.stderr)
    print(msg("lyrics_complete", LANG), file=sys.stderr)
    print("─" * 40, file=sys.stderr)
    print(format_lyrics_display(lyrics), file=sys.stderr)
    print("─" * 40, file=sys.stderr)

    # Output raw lyrics to stdout (for piping)
    print(lyrics)

    # Save to file if requested
    if args.output:
        out_path = Path(args.output).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(lyrics, encoding="utf-8")
        print(msg("lyrics_saved", LANG, path=out_path), file=sys.stderr)


if __name__ == "__main__":
    main()
