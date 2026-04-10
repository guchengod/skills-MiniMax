---
name: minimax-music-gen
description: >
  Use when user wants to generate music, songs, or audio tracks. Triggers on phrases like
  "generate a song", "make music", "create a track", "写首歌", "生成音乐", "来一首歌",
  "帮我做首歌", "纯音乐", "cover", "唱一首", or any request involving music creation,
  song writing, lyrics generation, or audio production. Also triggers when user provides
  lyrics and wants them turned into a song, or describes a mood/scene and wants background
  music. Even casual requests like "给我来点音乐" or "I want a chill beat" should trigger
  this skill. Do NOT use for music playback of existing files, music theory questions, or
  music recommendation without generation.
---

# MiniMax Music Generation Skill

Generate songs (vocal or instrumental) using the MiniMax Music API. Supports two creation
modes: **Basic** (one-sentence-in, song-out) and **Advanced Control** (edit lyrics, refine
prompt, plan before generating).

## Prerequisites

- **Credentials**: The scripts auto-read credentials from local files:
  - API Key: `~/.minimax_api_key`
  - Group ID: `~/.minimax_group_id`
  
  To check if credentials are configured, only test **file existence** — NEVER
  read, print, echo, or export the actual values:
  ```bash
  test -f ~/.minimax_api_key && test -f ~/.minimax_group_id && echo "✅ Credentials OK" || echo "❌ Missing credentials"
  ```
  If missing, trigger the `minimax-account-setup` skill to guide the user through setup.

  **⚠️ SECURITY: NEVER do any of the following:**
  - `cat ~/.minimax_api_key` — exposes the full API key
  - `echo $MINIMAX_API_KEY` — prints the key to terminal
  - `export MINIMAX_API_KEY=$(cat ...)` — leaks key in process list and terminal history
  - Any command that outputs credential values to stdout/stderr
  
  The scripts handle credential loading internally. You do NOT need to set
  environment variables — just call the scripts directly.

- Python 3.8+ (scripts use only stdlib — no pip install needed).
- `ffplay` or `mpv` or `afplay` (macOS) for local playback. The script auto-detects.

## APIs Used

This skill uses two MiniMax API endpoints in a pipeline:

1. **Lyrics Generation** — `POST /v1/lyrics_generation`
   - Base URL: `https://api.minimax.io` (overseas) or `https://api.minimaxi.com` (domestic)
   - Scripts auto-detect the correct domain based on the user's API key
   - Generates song lyrics from a natural language description
   - Mode: `write_full_song`
   - Used automatically for vocal tracks when the user hasn't provided lyrics
   - Script: `scripts/generate_lyrics.py`

2. **Music Generation** — `POST /v1/music_generation`
   - Base URL: `https://api.minimax.io` (overseas) or `https://api.minimaxi.com` (domestic)
   - Scripts auto-detect the correct domain based on the user's API key
   - Generates the actual audio (MP3) from a prompt + optional lyrics
   - Model: `music-2.6-free` (fallback: `music-2.6`), cover: `music-cover-free` (fallback: `music-cover`)
   - Supports: `is_instrumental` (true/false), `bedrock_lane: cover` header
   - Script: `scripts/generate_music.py`

**Pipeline**: For vocal tracks, the typical flow is:
```
User description → [Lyrics API] → lyrics → [Music API + prompt] → MP3
```
For instrumental tracks, the lyrics step is skipped entirely.

## Storage

All generated music is saved to `~/Music/minimax-gen/`. Create the directory if it doesn't
exist. Files are named with a timestamp and a short slug derived from the prompt:
`YYYYMMDD_HHMMSS_<slug>.mp3`

---

## Workflow

## Language Detection

Detect the user's language from their message at the start of the session:
- Chinese (中文) → Set `LANG=zh` — all interactions in Chinese, generate Chinese lyrics
- English → Set `LANG=en` — all interactions in English, generate English lyrics

**IMPORTANT — Lyrics language rule**:
- Default lyrics language = user's language. 用户说中文 → 生成中文歌词。User speaks English → English lyrics.
- Only generate a different language if the user **explicitly** asks (e.g., "给我写首英文歌", "write Chinese lyrics").
- The `--prompt` passed to `generate_lyrics.py` must be written in the **target lyrics language** — if generating Chinese lyrics, write the prompt in Chinese. The API uses prompt language to determine output language.

Pass `--lang $LANG` to ALL script invocations throughout the workflow.
Respond to the user in their detected language. Use the matching template below.

### Step 0: Detect Language & Intent

Detect the user's language and respond in the same language throughout. Parse their message
to determine:

1. **Song category**: vocal (人声音乐), instrumental (纯音乐), or cover
2. **Creation mode preference**: did they provide detailed requirements (→ Advanced) or a
   casual one-liner (→ Basic)?

If ambiguous, ask using this decision tree:

**If LANG=zh:**
```
Q1: 你想要哪种类型？
  - 🎤 人声音乐（有歌词演唱）
  - 🎵 纯音乐（无人声）
  - 🎧 Cover（翻唱风格）

Q2: 创作模式？
  - ⚡ 基础版 — 一句话描述，自动搞定
  - 🎛️ 强控制版 — 自己调歌词、prompt、风格
```

**If LANG=en:**
```
Q1: What type of music?
  - 🎤 Vocal (with lyrics)
  - 🎵 Instrumental (no vocals)
  - 🎧 Cover

Q2: Creation mode?
  - ⚡ Basic — one-line description, auto-generate
  - 🎛️ Advanced — edit lyrics, refine prompt, plan
```

If the user gives a clear one-liner like "帮我生成一首悲伤的钢琴曲", skip the questions —
infer instrumental + basic mode and proceed.

---

### Step 1: Basic Mode

**Goal**: User provides a short description → skill auto-generates everything → call API.

1. **Expand the description into a prompt**: Take the user's one-liner and expand it into a
   rich music prompt. Read `references/prompt_guide.md` for the style vocabulary and
   prompt structure. The **music generation prompt must match the user's language** (LANG):
   - When LANG=zh, write the prompt in Chinese
   - When LANG=en, write the prompt in English
   
   Follow this pattern:
   ```
   # LANG=zh example:
   一首 [情绪] [BPM 可选] 的 [曲风] 歌曲，[人声描述]，关于 [主题/叙事]，
   [氛围/场景]，[乐器和编曲元素]。
   
   # LANG=en example:
   A [mood] [BPM optional] [genre] song, featuring [vocal description],
   about [narrative/theme], [atmosphere], [key instruments and production].
   ```

2. **Generate lyrics** (if vocal): Call the MiniMax Lyrics API to auto-generate lyrics.
   Run the lyrics script:
   ```bash
   python3 ~/.claude/skills/minimax-music-gen/scripts/generate_lyrics.py \
     --prompt "<lyrics prompt in TARGET LANGUAGE>" \
     --lang $LANG \
     --output /tmp/lyrics_draft.txt
   ```
   The API endpoint is `/v1/lyrics_generation` (domain auto-detected) with mode
   `write_full_song`. The prompt should be a vivid description of the song's theme,
   mood, and story — written in the **target lyrics language**.
   
   **Chinese lyrics example** (LANG=zh):
   - User says "写首关于夏天海边的情歌"
   - Lyrics prompt: "一首关于夏天海边的甜蜜情歌，阳光沙滩，海浪声中牵手漫步，初恋般的心动与美好"
   
   **English lyrics example** (LANG=en):
   - User says "write a love song about the beach"
   - Lyrics prompt: "A cheerful love song about a summer day at the beach, with
     warm sunshine, ocean waves, and the joy of being with someone special"
   
   The API returns lyrics with section markers like `[verse]`, `[chorus]`, etc.
   If the returned lyrics lack section markers, add them automatically following
   this structure:
   ```
   [verse]    — 4 lines
   [chorus]   — 4 lines
   [verse]    — 4 lines
   [chorus]   — 4 lines
   [outro]    — 2 lines
   ```
   
   **Fallback**: If the lyrics API fails or returns low-quality results, generate
   lyrics directly using your own capabilities. Keep lines rhythmically consistent
   (similar syllable count per line within a section). Avoid clichés.

3. **Show the user a preview** before generating:

   **If LANG=zh:**
   ```
   🎵 即将为你生成：
   类型：人声音乐
   Prompt：独立民谣, 忧郁, 内省, 原声吉他, 温柔女声, 深夜独处
   歌词：
   [verse]
   ...
   
   确认生成？(直接回车确认，或告诉我要改什么)
   ```

   **If LANG=en:**
   ```
   🎵 About to generate:
   Type: Vocal
   Prompt: indie folk, melancholy, acoustic guitar, gentle female voice
   Lyrics:
   [verse]
   ...
   
   Confirm? (press enter to confirm, or tell me what to change)
   ```

4. **Call the API**: Run `scripts/generate_music.py` with the constructed parameters.

---

### Step 2: Advanced Control Mode

**Goal**: User has full control over every parameter before generation.

1. **Lyrics phase**:
   - If user provided lyrics: display them formatted with section markers, ask for edits.
   - If user has a theme but no lyrics: call the lyrics API to generate a draft:
     ```bash
     python3 ~/.claude/skills/minimax-music-gen/scripts/generate_lyrics.py \
       --prompt "<vivid description of the song's theme and story>" \
       --lang $LANG \
       --output /tmp/lyrics_draft.txt
     ```
     Present the generated lyrics to the user for review and editing.
   - Support iterative editing: "第二段副歌改一下" → only rewrite that section.
   - User can choose to regenerate lyrics with a different prompt if unsatisfied.

2. **Prompt phase**:
   - Generate a recommended prompt based on the lyrics' mood and content.
   - Present it as editable tags the user can add/remove/modify.
   - Read `references/prompt_guide.md` for the full vocabulary.

3. **Advanced planning** (optional, offer but don't force):
   - Song structure: verse-chorus-verse-chorus-bridge-chorus or custom
   - BPM suggestion (encode in prompt as tempo descriptor)
   - Reference style: "类似某种风格" → map to prompt tags
   - Vocal character description

4. **Final confirmation**: Show complete parameter summary, then generate.

---

### Step 3: Call the API

Run the generation script:

```bash
python3 ~/.claude/skills/minimax-music-gen/scripts/generate_music.py \
  --prompt "<prompt>" \
  --lyrics "<lyrics or empty>" \
  --lang $LANG \
  --output ~/Music/minimax-gen/<filename>.mp3
  # Add --instrumental for instrumental (no vocal). Omit for vocal tracks.
  # Add --cover for cover mode. Omit for original tracks.
  # Add --no-play to skip auto-playback after generation.
```

The script handles:
- API call with proper headers
- Polling for completion (the API may return a task ID)
- Downloading the result MP3
- Error handling with clear messages

Display a progress indicator while waiting. Typical generation takes 30-120 seconds.

---

### Step 4: Playback

After generation, play the song:

```bash
python3 ~/.claude/skills/minimax-music-gen/scripts/play_music.py \
  --lang $LANG \
  ~/Music/minimax-gen/<filename>.mp3
```

The script auto-detects the best available player (`mpv` > `ffplay` > `afplay` > `aplay`).
Tell the user:

**If LANG=zh:**
```
🎵 正在播放：<filename>.mp3
📁 文件已保存到：~/Music/minimax-gen/<filename>.mp3
⏸️  按 q 或 Ctrl+C 可暂停/停止播放
```

**If LANG=en:**
```
🎵 Now playing: <filename>.mp3
📁 Saved to: ~/Music/minimax-gen/<filename>.mp3
⏸️  Press q or Ctrl+C to pause/stop playback
```

---

### Step 5: Feedback & Iteration

After playback, ask for feedback:

**If LANG=zh:**
```
这首歌怎么样？
  1. 🎉 很满意，保留！
  2. 🔄 不太行，调整后重新生成
  3. 🎨 歌词/风格微调后重新生成
  4. 🗑️ 不要了，删掉重来
```

**If LANG=en:**
```
How was this song?
  1. 🎉 Love it, keep it!
  2. 🔄 Not quite, adjust and regenerate
  3. 🎨 Fine-tune lyrics/style then regenerate
  4. 🗑️ Don't want it, start over
```

Based on feedback:
- **Satisfied**: Done. Mention the file path again.
- **Adjust & regenerate**: Ask what to change (prompt? lyrics? style?), apply edits,
  re-run generation. Keep the old file with a `_v1` suffix for comparison.
- **Fine-tune**: Enter Advanced Control Mode with the current parameters pre-filled.
- **Delete & restart**: Remove the file, go back to Step 0.

---

## Error Handling

| Error | Action |
|-------|--------|
| Missing API key | Print setup instructions for `MINIMAX_API_KEY` |
| Missing Group ID | Ask user for their GroupId |
| API timeout (>3min) | Retry once, then report failure with request ID |
| Invalid lyrics format | Auto-fix section markers, warn user |
| Download URL expired | Re-request from API |
| No audio player found | Save file and tell user the path, suggest installing mpv |
| Network error | Show error detail, suggest checking connection |

---

## Cover Mode

When the user selects Cover mode:
1. Ask for the song they want to cover (name + artist)
2. Set the `bedrock_lane: cover` header
3. Generate a prompt that describes the cover style (e.g., "acoustic cover of pop song,
   stripped-down arrangement, intimate vocal")
4. Lyrics: user provides or we look up a rough theme (never reproduce copyrighted lyrics —
   write original lyrics inspired by the theme)
5. Proceed with normal generation flow

---

## Important Notes

- **Never reproduce copyrighted lyrics.** When doing covers, always write original lyrics
  inspired by the song's theme. Explain this to the user.
- **Prompt language**: The API prompt works best with Chinese tags or English tags. Mix is OK.
- **Section markers in lyrics**: The API recognizes `[verse]`, `[chorus]`, `[bridge]`,
  `[outro]`, `[intro]`. Always include them.
- **File management**: If `~/Music/minimax-gen/` has more than 50 files, suggest cleanup
  when starting a new session.