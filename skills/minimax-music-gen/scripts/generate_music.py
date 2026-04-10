#!/usr/bin/env python3
"""
MiniMax Music Generation API Client (Production API)

Handles the full lifecycle:
  1. Submit generation request (synchronous, hex output)
  2. Decode hex audio and save MP3
  3. Report status throughout

Usage:
  python3 generate_music.py \
    --prompt "indie folk, 忧郁, 原声吉他" \
    --lyrics "[verse]\n歌词..." \
    --output ~/Music/minimax-gen/song.mp3

  python3 generate_music.py \
    --prompt "lo-fi, 放松, 钢琴" \
    --instrumental \
    --output ~/Music/minimax-gen/lofi.mp3

  python3 generate_music.py \
    --prompt "男高音，流行歌" \
    --cover --audio ~/Desktop/original.mp3 \
    --output ~/Music/minimax-gen/cover.mp3
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.expanduser("~/.claude/skills/shared"))
from i18n import msg
from api_base import get_api_base

LANG = "zh"  # Module-level default, updated by main()

# Fallback models: if *-free models are retired, auto-downgrade
MODEL_FALLBACKS = {
    "music-2.6-free": "music-2.6",
    "music-cover-free": "music-cover",
}


def get_env(name, alt_name=None, required=True):
    """Get environment variable with optional fallback to ~/.minimax_* files."""
    val = os.environ.get(name)
    if not val and alt_name:
        val = os.environ.get(alt_name)
    if not val:
        file_map = {
            "MINIMAX_API_KEY": os.path.expanduser("~/.minimax_api_key"),
            "MINIMAX_GROUP_ID": os.path.expanduser("~/.minimax_group_id"),
        }
        fpath = file_map.get(name) or (file_map.get(alt_name) if alt_name else None)
        if fpath and os.path.isfile(fpath):
            with open(fpath) as f:
                val = f.read().strip()
    if not val and required:
        print(msg("env_not_set", LANG, name=name))
        print(msg("env_run_export", LANG, name=name))
        sys.exit(1)
    return val


def build_request_body(args):
    """Construct the API request JSON body."""
    # Cover mode uses a different model
    model = "music-cover-free" if args.cover else args.model

    body = {
        "model": model,
        "prompt": args.prompt,
        "audio_setting": {
            "sample_rate": args.sample_rate,
            "bitrate": args.bitrate,
            "format": args.format,
        },
        "stream": False,
        "output_format": "hex",
    }

    # Cover mode: encode source audio as base64
    if args.cover and args.audio:
        audio_path = Path(args.audio).expanduser()
        if not audio_path.exists():
            print(msg("file_not_found", LANG, path=str(audio_path)))
            sys.exit(1)
        with open(audio_path, "rb") as f:
            body["audio_base64"] = base64.b64encode(f.read()).decode("utf-8")
    elif not args.cover:
        # Regular generation fields
        body["is_instrumental"] = args.instrumental
        if not args.instrumental and args.lyrics:
            body["lyrics"] = args.lyrics

    return body


def submit_generation(url, api_key, body, is_cover=False):
    """Submit the music generation request (synchronous).

    Returns (result_dict, error_string). On success error is None.
    On failure result may be None and error describes what happened.
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if is_cover:
        headers["bedrock_lane"] = "cover"

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result, None
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        return None, f"HTTP {e.code}: {error_body[:500]}"
    except urllib.error.URLError as e:
        return None, f"Network error: {e.reason}"


def save_hex_audio(hex_data, output_path):
    """Decode hex audio data and save to file."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    audio_bytes = bytes.fromhex(hex_data)
    with open(output, "wb") as f:
        f.write(audio_bytes)

    file_size = output.stat().st_size
    print(msg("download_complete", LANG, output=output, size=file_size // 1024) + " " * 20)
    return str(output)


def main():
    parser = argparse.ArgumentParser(description="Generate music via MiniMax API")
    parser.add_argument("--prompt", required=True, help="Music generation prompt (comma-separated tags)")
    parser.add_argument("--lyrics", default="", help="Song lyrics with section markers")
    parser.add_argument("--instrumental", action="store_true", help="Generate instrumental (no vocal)")
    parser.add_argument("--cover", action="store_true", help="Use cover mode")
    parser.add_argument("--audio", default="", help="Source audio file for cover mode")
    parser.add_argument("--output", required=True, help="Output file path (.mp3)")
    parser.add_argument("--no-play", action="store_true", help="Download only, do not auto-play")
    parser.add_argument("--model", default="music-2.6-free", help="Model version (default: music-2.6-free)")
    parser.add_argument("--sample-rate", type=int, default=44100, help="Audio sample rate")
    parser.add_argument("--bitrate", type=int, default=256000, help="Audio bitrate")
    parser.add_argument("--format", default="mp3", help="Audio format (default: mp3)")
    parser.add_argument("--lang", default="zh", choices=["zh", "en"], help="UI language")
    args = parser.parse_args()

    global LANG
    LANG = args.lang

    # Get credentials
    api_key = get_env("MINIMAX_API_KEY")

    # Auto-detect overseas/domestic API domain
    api_base = get_api_base(api_key)
    url = f"{api_base}/v1/music_generation"

    # Build request
    body = build_request_body(args)

    # Display header
    model_display = "music-cover-free" if args.cover else args.model
    print(msg("header_title", LANG))
    print(msg("label_model", LANG, model=model_display))
    if args.cover:
        print(f"   Cover: {args.audio or 'N/A'}")
    else:
        print(msg("label_type", LANG, type=msg("type_instrumental", LANG) if args.instrumental else msg("type_vocal", LANG)))
    print(f"   Prompt: {args.prompt[:80]}{'...' if len(args.prompt) > 80 else ''}")
    if args.lyrics:
        lines = args.lyrics.replace("\\n", "\n").split("\n")
        print(msg("label_lyrics", LANG, first_line=lines[0], count=len(lines)))
    print()

    # Submit request (synchronous — waits for full generation)
    print(msg("submitting_request", LANG))
    start_time = time.time()
    result, error = submit_generation(url, api_key, body, is_cover=args.cover)

    # Fallback: if primary model fails, try backup model
    current_model = body["model"]
    if (error or (result and result.get("base_resp", {}).get("status_code", 0) != 0)) \
            and current_model in MODEL_FALLBACKS:
        fallback_model = MODEL_FALLBACKS[current_model]
        err_detail = error or result.get("base_resp", {}).get("status_msg", "unknown")
        print(f"⚠️  模型 {current_model} 失败 ({err_detail})，切换到 {fallback_model} 重试...")
        body["model"] = fallback_model
        model_display = fallback_model
        result, error = submit_generation(url, api_key, body, is_cover=args.cover)

    if error:
        print(f"❌ {error}")
        sys.exit(1)

    elapsed = time.time() - start_time

    print(f"📋 API response: {json.dumps(result, ensure_ascii=False, indent=2)[:2000]}", file=sys.stderr)

    # Extract hex audio from response
    audio_hex = ""
    data = result.get("data") or {}
    if isinstance(data, dict):
        audio_hex = data.get("audio", "")

    if not audio_hex:
        # Check base_resp for error details
        base_resp = result.get("base_resp", {})
        if base_resp.get("status_code", 0) != 0:
            print(f"❌ API Error: {base_resp.get('status_msg', 'unknown')}")
        else:
            print(msg("no_audio_url", LANG))
            print(msg("raw_response", LANG, resp=json.dumps(result, ensure_ascii=False, indent=2)[:1000]))
        sys.exit(1)

    # Save audio
    output_path = save_hex_audio(audio_hex, args.output)
    print(msg("generation_complete", LANG, elapsed=int(elapsed)))

    if not args.no_play:
        subprocess.Popen(["open", output_path])
        print()
        print(msg("opened_player", LANG))

    # Summary
    print()
    print("═" * 50)
    print(msg("generation_success", LANG))
    print(msg("file_path", LANG, path=output_path))
    print("═" * 50)

    # Write metadata alongside the audio file
    meta_path = Path(output_path).with_suffix(".json")
    metadata = {
        "prompt": args.prompt,
        "lyrics": args.lyrics if args.lyrics else None,
        "instrumental": args.instrumental,
        "cover": args.cover,
        "model": model_display,
        "generated_at": datetime.now().isoformat(),
        "file": str(output_path),
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    print(msg("metadata_label", LANG, path=meta_path))

    # Machine-readable output for agent parsing (last line)
    print(json.dumps({"status": "ok", "file": str(output_path), "metadata": str(meta_path)}))


if __name__ == "__main__":
    main()
