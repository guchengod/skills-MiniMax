---
name: minimax-music-playlist
description: >
  Generate personalized music playlists by analyzing the user's music taste from local
  apps (Apple Music, QQ Music) and generation feedback history. Triggers on "generate
  playlist", "make a playlist", "歌单", "推荐歌单", "根据我的口味生成", "personalized
  playlist", "music taste", "音乐画像", "scan my music", "扫描我的音乐",
  "playlist based on my taste", "根据喜好生成".
---

# MiniMax Music Playlist — Personalized Playlist Generator

Scan the user's local music libraries to build a taste profile, then generate
a personalized playlist using the MiniMax Music API.

**Requires**: `minimax-music-gen` skill installed at `~/.claude/skills/minimax-music-gen/`

---

## Workflow Overview

```
Scan music sources → Build taste profile → Plan playlist → Generate songs → Play & feedback
```

## Language Detection

Detect the user's language from their message at the start of the session:
- Chinese (中文) → Set `LANG=zh` — all interactions in Chinese, generate Chinese lyrics
- English → Set `LANG=en` — all interactions in English, generate English lyrics

Pass `--lang $LANG` to ALL script invocations throughout the workflow.
Respond to the user in their detected language. Use the matching template below.

---

## Step 1: Scan Music Sources

Scan available local music apps. Run whichever scanners are available — the skill
works with any combination of sources.

### Apple Music

```bash
python3 ~/.claude/skills/minimax-music-playlist/scripts/scan_apple_music.py \
  --lang $LANG \
  --output /tmp/apple_music_data.json
```

The script uses `osascript` to query Music.app. It auto-filters TTS/test files.
If Music.app is not running or has no library, the script outputs an empty result.

### QQ Music

```bash
python3 ~/.claude/skills/minimax-music-playlist/scripts/scan_qq_music.py \
  --lang $LANG \
  --output /tmp/qq_music_data.json
```

Reads QQ Music's SQLite database and preferences plist. Extracts songs, playlist
assignments, and search history. If QQ Music is not installed, outputs empty result.

### Spotify

```bash
python3 ~/.claude/skills/minimax-music-playlist/scripts/scan_spotify.py \
  --lang $LANG \
  --output /tmp/spotify_data.json
```

Reads Spotify's local LevelDB cache, queries the running app via osascript, and
scans the URL cache for API responses. If Spotify is newly installed, data may be
sparse — the script warns about this. Data accumulates as the user listens more.

### NetEase Cloud Music (网易云音乐)

```bash
python3 ~/.claude/skills/minimax-music-playlist/scripts/scan_netease.py \
  --lang $LANG \
  --output /tmp/netease_data.json
```

Reads NetEase's webdata JSON files (tracks, FM queue, recommendations), Cache.db,
and infers genre preferences from recommended playlist names and scene tags.
The app uses a web-based architecture, so data is in
`~/Library/Containers/com.netease.163music/Data/Documents/storage/`.

### Other Music Apps

If the user has other apps (e.g., 酷狗, 酷我) not yet supported, tell them:

**If LANG=zh:**
```
目前支持扫描 Apple Music、QQ 音乐、Spotify 和网易云音乐。
如果你用其他平台，可以告诉我你喜欢的风格/艺术家，我手动加入画像。
```

**If LANG=en:**
```
Currently supported: Apple Music, QQ Music, Spotify, and NetEase Cloud Music.
If you use other platforms, tell me your preferred styles/artists and I'll add them to your profile manually.
```

### Manual Input

If no music apps are available, or the user wants to supplement:

**If LANG=zh:**
```
🎵 告诉我你喜欢的音乐，我来帮你建画像：

💡 比如：
  · "我喜欢周杰伦、陶喆那种华语R&B"
  · "最近在听很多K-pop和日系city pop"
  · "偏好忧郁慢歌，不太听电子舞曲"
```

**If LANG=en:**
```
🎵 Tell me about your music taste, and I'll build a profile:

💡 For example:
  · "I like Jay Chou and David Tao style C-pop R&B"
  · "I've been listening to a lot of K-pop and Japanese city pop"
  · "I prefer melancholy ballads, not into EDM"
```

---

## Step 2: Build Taste Profile

Merge all data sources into a unified taste profile:

```bash
python3 ~/.claude/skills/minimax-music-playlist/scripts/build_taste_profile.py \
  --apple-music /tmp/apple_music_data.json \
  --qq-music /tmp/qq_music_data.json \
  --spotify /tmp/spotify_data.json \
  --netease /tmp/netease_data.json \
  --gen-history ~/Music/minimax-gen/ \
  --artist-map ~/.claude/skills/minimax-music-playlist/data/artist_genre_map.json \
  --lang $LANG \
  --output ~/.claude/skills/minimax-music-playlist/data/taste_profile.json
```

The script infers genres from artists using the artist-genre mapping table, computes
weighted scores, and outputs a taste profile.

**Show the user a privacy-safe summary** — never expose raw track lists:

**If LANG=zh:**
```
🎵 你的音乐画像：
  📊 数据源：QQ音乐 145首 | Apple Music 42首 | Spotify 20首 | 网易云 15首 | 已生成 9首
  🎸 Top 风格：华语流行 35% | R&B 20% | K-pop 10% | 中国风 8%
  🌍 语言：中文 70% | 韩语 12% | 英语 10% | 日语 8%
  💭 情绪：忧郁 30% | 浪漫 25% | 温暖 20%
  🎤 声线：偏好男声 55% | 女声 40%
  🎵 Top 艺术家：周杰伦、陶喆、孙燕姿、王力宏、方大同

这个画像准确吗？(确认后开始生成歌单，或告诉我要调整什么)
```

**If LANG=en:**
```
🎵 Your Music Profile:
  📊 Sources: QQ Music 145 | Apple Music 42 | Spotify 20 | NetEase 15 | Generated 9
  🎸 Top styles: C-pop 35% | R&B 20% | K-pop 10% | Chinese-style 8%
  🌍 Languages: Chinese 70% | Korean 12% | English 10% | Japanese 8%
  💭 Moods: Melancholy 30% | Romantic 25% | Warm 20%
  🎤 Vocals: Male 55% | Female 40%
  🎵 Top artists: Jay Chou, David Tao, Stefanie Sun, Leehom Wang, Khalil Fong

Does this look right? (Confirm to generate playlist, or tell me what to adjust)
```

### Profile caching

The taste profile is saved at:
`~/.claude/skills/minimax-music-playlist/data/taste_profile.json`

- **First time**: Always scan and build
- **Subsequent calls**: If a profile exists and is less than 7 days old, reuse it.
  Show the summary and ask if the user wants to rescan.
- **Force rescan**: If the user says "重新扫描" or "rescan", delete and rebuild.

---

## Step 3: Plan Playlist

Ask the user for a theme (optional):

**If LANG=zh:**
```
🎵 想要什么主题的歌单？

💡 比如：
  · "深夜放松" — 适合睡前的慢歌
  · "通勤路上" — 节奏轻快提神
  · "雨天" — 配合窗外的雨
  · "让我自己选" — 不指定主题，根据画像随机
  · 或者直接描述你想要的氛围
```

**If LANG=en:**
```
🎵 What theme for your playlist?

💡 Examples:
  · "Late night chill" — relaxing slow songs
  · "Commute" — upbeat and energizing
  · "Rainy day" — matching the rain outside
  · "Surprise me" — random based on your profile
  · Or just describe the vibe you want
```

If the user doesn't specify, use the top mood from their profile as default.

Generate the playlist plan:

```bash
python3 ~/.claude/skills/minimax-music-playlist/scripts/generate_playlist.py \
  --profile ~/.claude/skills/minimax-music-playlist/data/taste_profile.json \
  --theme "<user theme>" \
  --count <number> \
  --lang $LANG \
  --output /tmp/playlist_plan.json
```

**Show the full plan to the user** for review:

**If LANG=zh:**
```
🎵 歌单计划：深夜放松 (5首)

  1. 华语R&B慢歌 — 忧郁, 内省 [中文/男声]
     Prompt: R&B, neo-soul, 忧郁, 内省, 温柔男声, 电钢琴, 贝斯, 慢板, 深夜独处

  2. K-pop 抒情 — 温暖, 浪漫 [韩语/女声]
     Prompt: K-pop, 流行, 温暖, 浪漫, 清澈女声, 合成器, 钢琴, 中板, 星空下

  3. 独立民谣 — 内省, 平静 [中文/男声]
     Prompt: 独立民谣, folk, 内省, 平静, 温柔男声, 原声吉他, 口琴, 慢板, 深夜独处

  4. Lo-fi hip-hop — 平静, 梦幻 [纯音乐]
     Prompt: lo-fi hip-hop, 平静, 梦幻, 采样钢琴, 电子鼓, vinyl crackle, 慢板, 深夜书桌

  5. 爵士 — 温暖, 浪漫 [英语/女声]
     Prompt: smooth jazz, bossa nova, 温暖, 浪漫, 清澈女声, 钢琴, 贝斯, 萨克斯, 中板

确认生成？(直接回车确认，或告诉我要调整哪首)
```

**If LANG=en:**
```
🎵 Playlist Plan: Late Night Chill (5 songs)

  1. C-pop R&B Ballad — melancholy, introspective [Chinese/male vocal]
     Prompt: R&B, neo-soul, melancholy, introspective, gentle male voice, electric piano, bass, slow tempo, late night solitude

  2. K-pop Ballad — warm, romantic [Korean/female vocal]
     Prompt: K-pop, pop, warm, romantic, clear female voice, synth, piano, mid-tempo, under the stars

  3. Indie Folk — introspective, calm [Chinese/male vocal]
     Prompt: indie folk, folk, introspective, calm, gentle male voice, acoustic guitar, harmonica, slow tempo, late night solitude

  4. Lo-fi hip-hop — calm, dreamy [instrumental]
     Prompt: lo-fi hip-hop, calm, dreamy, sampled piano, electronic drums, vinyl crackle, slow tempo, late night desk

  5. Jazz — warm, romantic [English/female vocal]
     Prompt: smooth jazz, bossa nova, warm, romantic, clear female voice, piano, bass, saxophone, mid-tempo

Confirm? (press enter to confirm, or tell me which song to adjust)
```

The user can:
- Confirm all → proceed to generation
- Modify individual songs ("第3首换成摇滚")
- Change count ("只要3首")
- Regenerate plan ("换一批")

---

## Step 4: Generate & Play (Stream Mode)

Generate songs sequentially. **Play each song as soon as it's ready** instead of
waiting for all songs to finish. This gives the user music to listen to while the
rest of the playlist is being generated.

### Generation + Playback Loop

For each song in the plan:

1. If `instrumental: false`, generate lyrics first:
   ```bash
   python3 ~/.claude/skills/minimax-music-gen/scripts/generate_lyrics.py \
     --prompt "<lyrics_prompt from plan>" \
     --lang $LANG \
     --output /tmp/playlist_lyrics_<NN>.txt
   ```

2. Generate music (always `--no-play` during generation):
   ```bash
   python3 ~/.claude/skills/minimax-music-gen/scripts/generate_music.py \
     --prompt "<prompt from plan>" \
     --lyrics "<lyrics or empty>" \
     --output ~/Music/minimax-gen/playlists/<playlist_name>/<filename> \
     --lang $LANG \
     --no-play
   ```
   # Add --instrumental for instrumental tracks. Omit for vocal tracks.

3. **After each song completes, decide whether to play it immediately:**

   - **Song 1 (first song):** Always play immediately after generation. Use
     `play_music.py --background` so playback starts without blocking generation
     of the next song:
     ```bash
     python3 ~/.claude/skills/minimax-music-gen/scripts/play_music.py \
       ~/Music/minimax-gen/playlists/<playlist_name>/<filename> \
       --background --lang $LANG
     ```

   - **Song 2+ (subsequent songs):** Check if Music.app is idle (not playing).
     Use the `is_idle` check from `play_playlist.py`:
     ```bash
     python3 -c "
     import subprocess
     r = subprocess.run(['osascript', '-e',
       'tell application \"System Events\" to (name of processes) contains \"Music\"'],
       capture_output=True, text=True, timeout=5)
     if r.stdout.strip() != 'true':
         print('idle')
     else:
         s = subprocess.run(['osascript', '-e',
           'tell application \"Music\" to player state as string'],
           capture_output=True, text=True, timeout=5)
         state = s.stdout.strip().lower()
         print('idle' if 'playing' not in state else 'playing')
     "
     ```
     - If **idle** → play this song immediately with `play_music.py --background`
     - If **playing** → do NOT interrupt; the song is saved to disk and will be
       available for replay later. Show a note:

     **If LANG=zh:** `💾 [2/5] 已保存，播放器正忙，稍后可重播`
     **If LANG=en:** `💾 [2/5] Saved, player busy — available for replay later`

4. Show progress after each song:

**If LANG=zh:**
```
✅ [1/5] 生成完毕：01_bossa_nova.mp3
▶️  正在播放...
⏳ [2/5] 正在生成...
```

**If LANG=en:**
```
✅ [1/5] Complete: 01_bossa_nova.mp3
▶️  Now playing...
⏳ [2/5] Generating...
```

5. If generation fails for a song, log the error and continue with the next song.

### When all songs complete:

**If LANG=zh:**
```
🎉 歌单「深夜放松」生成完毕！共 5 首

📁 文件：~/Music/minimax-gen/playlists/深夜放松/
  01_rnb_midnight.mp3
  02_kpop_stars.mp3
  ...

💡 重播整个歌单：告诉我「重播」
```

**If LANG=en:**
```
🎉 Playlist "Late Night Chill" complete! 5 songs

📁 Files: ~/Music/minimax-gen/playlists/late_night_chill/
  01_rnb_midnight.mp3
  02_kpop_stars.mp3
  ...

💡 Replay the full playlist: just say "replay"
```

### Replaying existing playlists

For replaying a previously generated playlist, use the dedicated script:

```bash
python3 ~/.claude/skills/minimax-music-gen/scripts/play_playlist.py \
  ~/Music/minimax-gen/playlists/<playlist_name>/ \
  --lang $LANG \
  --auto
```

---

## Step 5: Save Playlist

Create a playlist metadata file:

```
~/Music/minimax-gen/playlists/<playlist_name>/playlist.json
```

Content:
```json
{
  "name": "深夜放松",
  "theme": "深夜放松",
  "created_at": "ISO timestamp",
  "song_count": 5,
  "songs": [
    {
      "index": 1,
      "filename": "01_rnb_midnight.mp3",
      "prompt": "...",
      "lyrics": "...",
      "rating": null
    }
  ]
}
```

---

## Step 6: Feedback & Profile Update

After listening, ask for feedback:

**If LANG=zh:**
```
🎵 这个歌单怎么样？

  对每首歌打分（可选）：
  1. 华语R&B慢歌 — 👍 / 👎 / 跳过
  2. K-pop 抒情 — 👍 / 👎 / 跳过
  ...

  或者整体评价：
  🎉 很满意！以后多来这种
  🔄 还行，某些方面可以调整
  🗑️ 不太喜欢，换个方向
```

**If LANG=en:**
```
🎵 How was this playlist?

  Rate each song (optional):
  1. C-pop R&B Ballad — 👍 / 👎 / skip
  2. K-pop Ballad — 👍 / 👎 / skip
  ...

  Or overall rating:
  🎉 Loved it! More like this
  🔄 Decent, but could adjust some things
  🗑️ Not my vibe, try a different direction
```

Based on feedback:
- **Per-song ratings**: Update playlist.json with ratings. Extract prompt tags from
  liked/disliked songs and update taste_profile.json's feedback section.
- **Overall positive**: Record the theme + genre combination as successful.
- **Needs adjustment**: Ask what to change, regenerate specific songs.
- **Negative**: Ask what went wrong, note disliked genres/moods in feedback.

---

## Replaying Playlists

If the user asks to play a previously generated playlist:

```bash
ls ~/Music/minimax-gen/playlists/
```

Show available playlists and play the selected one song by song.

---

## Error Handling

| Error | Action |
|-------|--------|
| No music apps installed | Guide to manual input mode |
| QQ Music DB locked | Suggest closing QQ Music and retrying |
| Apple Music not running | Try to launch via osascript, or skip |
| Spotify newly installed | Warn that data is sparse, suggest using app more |
| NetEase no track data | Data accumulates with usage, suggest browsing/playing |
| API timeout during generation | Retry once, then skip that song and continue |
| Generation fails for a song | Log error, continue with next song |
| No taste profile exists | Run scan first |
| Profile older than 7 days | Suggest rescan, but allow using old profile |

---

## Notes

- Privacy: Never show raw track lists. Only show aggregated statistics (top genres,
  language percentages, top artists).
- The artist_genre_map.json at `data/artist_genre_map.json` can be extended manually
  if the user's library has artists not in the map.
- Generated playlists are saved alongside individual songs in `~/Music/minimax-gen/playlists/`.
- The taste profile is persistent across sessions.
- All scripts use Python stdlib only — no pip dependencies.
- Reuses `generate_lyrics.py`, `generate_music.py`, `play_music.py` from
  `~/.claude/skills/minimax-music-gen/scripts/`.
