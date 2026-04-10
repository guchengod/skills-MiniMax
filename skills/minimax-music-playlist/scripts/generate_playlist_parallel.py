#!/usr/bin/env python3
"""Parallel playlist generator with sequential playback.

Generates up to 3 songs concurrently (RPM=3), plays each in order
as soon as it's ready. While songs 1-3 play, songs 4+ generate in
freed-up slots.

Usage:
    python3 generate_playlist_parallel.py \
        --plan /tmp/playlist_plan.json \
        --output-dir ~/Music/minimax-gen/playlists/my_playlist/ \
        --lang zh
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPTS_DIR = Path.home() / ".claude" / "skills" / "minimax-music-gen" / "scripts"
GENERATE_LYRICS = SCRIPTS_DIR / "generate_lyrics.py"
GENERATE_MUSIC = SCRIPTS_DIR / "generate_music.py"
PLAY_MUSIC = SCRIPTS_DIR / "play_music.py"

print_lock = threading.Lock()


def log(msg):
    with print_lock:
        print(msg, flush=True)


def generate_song(index, song, output_dir, lang, events, results):
    """Worker: generate lyrics (if vocal) + music for one song."""
    total = len(events)
    tag = f"[{index + 1}/{total}]"

    try:
        log(f"⏳ {tag} 开始生成：{song['description']}")
        lyrics_text = ""

        # Step 1: Generate lyrics (skip for instrumental), retry up to 2 times
        if not song.get("instrumental", False):
            lyrics_file = f"/tmp/playlist_parallel_lyrics_{index:02d}.txt"
            cmd = [
                sys.executable, str(GENERATE_LYRICS),
                "--prompt", song["lyrics_prompt"],
                "--output", lyrics_file,
                "--lang", lang,
            ]
            for attempt in range(3):
                if attempt > 0:
                    delay = 5 * attempt
                    log(f"🔄 {tag} 歌词重试 ({attempt + 1}/3)，等待 {delay}s...")
                    time.sleep(delay)
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if r.returncode == 0:
                    break
            if r.returncode != 0:
                log(f"❌ {tag} 歌词生成失败：{r.stderr[:200]}")
                events[index].set()
                return
            if os.path.exists(lyrics_file):
                with open(lyrics_file, "r") as f:
                    lyrics_text = f.read()

        # Step 2: Generate music
        output_path = os.path.join(output_dir, song["filename"])
        cmd = [
            sys.executable, str(GENERATE_MUSIC),
            "--prompt", song["prompt"],
            "--output", output_path,
            "--lang", lang,
            "--no-play",
        ]
        if lyrics_text:
            cmd.extend(["--lyrics", lyrics_text])
        if song.get("instrumental", False):
            cmd.append("--instrumental")

        r = subprocess.run(cmd, capture_output=True, text=True, timeout=360)
        if r.returncode != 0:
            log(f"❌ {tag} 音乐生成失败：{r.stderr[:200]}")
            events[index].set()
            return

        if os.path.exists(output_path):
            results[index] = output_path
            log(f"✅ {tag} 生成完毕：{song['filename']}")
        else:
            log(f"❌ {tag} 输出文件未找到")

    except subprocess.TimeoutExpired:
        log(f"❌ {tag} 生成超时")
    except Exception as e:
        log(f"❌ {tag} 错误：{e}")
    finally:
        events[index].set()


def play_song_blocking(filepath, lang):
    """Play a song and block until playback finishes."""
    cmd = [sys.executable, str(PLAY_MUSIC), filepath, "--lang", lang]
    subprocess.run(cmd, timeout=600)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, help="Playlist plan JSON path")
    parser.add_argument("--output-dir", required=True, help="Output directory for MP3s")
    parser.add_argument("--lang", default="zh", choices=["zh", "en"])
    parser.add_argument("--max-workers", type=int, default=3, help="Max concurrent generations")
    args = parser.parse_args()

    with open(args.plan, "r") as f:
        plan = json.load(f)

    songs = plan["songs"]
    total = len(songs)
    output_dir = os.path.expanduser(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    log(f"🎵 歌单「{plan.get('playlist_name', plan.get('theme', ''))}」— {total} 首")
    log(f"   并行生成数：{args.max_workers}，生成完即播放\n")

    # Per-song completion events and result paths
    events = [threading.Event() for _ in range(total)]
    results = {}  # index -> filepath

    # Submit all songs to thread pool
    pool = ThreadPoolExecutor(max_workers=args.max_workers)
    for i, song in enumerate(songs):
        pool.submit(generate_song, i, song, output_dir, args.lang, events, results)

    # Main thread: play songs sequentially in order
    played = 0
    for i in range(total):
        tag = f"[{i + 1}/{total}]"
        events[i].wait()  # Block until song i is ready

        if i not in results:
            log(f"⏭️  {tag} 跳过（生成失败）")
            continue

        filepath = results[i]
        log(f"▶️  {tag} 播放中：{os.path.basename(filepath)}")
        play_song_blocking(filepath, args.lang)
        played += 1

    pool.shutdown(wait=False)

    log(f"\n🎉 歌单播放完毕！共播放 {played}/{total} 首")
    log(f"📁 文件目录：{output_dir}")

    # Output machine-readable summary
    print(json.dumps({
        "status": "completed",
        "played": played,
        "total": total,
        "output_dir": output_dir,
    }))


if __name__ == "__main__":
    main()
