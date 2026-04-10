---
name: buddy-sings
description: >
  Use when user wants their Claude Code pet (/buddy) to sing a song. Triggers on
  "buddy sings", "let my buddy sing", "buddy sing", "make my pet sing",
  "宠物唱歌", "让宠物唱首歌", "让buddy唱歌", "buddy来一首", "我的宠物会唱歌吗",
  "pet sings", "let my companion sing", or any request that combines the concept
  of their Claude Code buddy/pet/companion with singing or music.
---

# Buddy Sings — Let Your Claude Code Pet Sing

Turn your Claude Code pet into a singer. Each pet gets a unique vocal identity
based on its name and personality — the same pet always sounds the same.

**Requires**: `minimax-music-gen` skill installed at `~/.claude/skills/minimax-music-gen/`

---

## Workflow Overview

```
Check pet → Build vocal identity → Choose mode → Generate music → Play
```

## Language Detection

Detect the user's language from their message at the start of the session:
- Chinese (中文) → Set `LANG=zh` — all interactions in Chinese, generate Chinese lyrics
- English → Set `LANG=en` — all interactions in English, generate English lyrics

Pass `--lang $LANG` to ALL script invocations throughout the workflow.
Respond to the user in their detected language. Use the matching template below.

---

## Step 1: Check for Pet

Read `~/.claude.json` and look for the `companion` field:

```python
import json
with open(os.path.expanduser("~/.claude.json")) as f:
    data = json.load(f)
companion = data.get("companion", {})
```

If no companion is found or the field is empty, tell the user:

**If LANG=zh:**
```
🐾 你还没有宠物呢！输入 /buddy 领养一只，然后再来找我让它唱歌吧。
```

**If LANG=en:**
```
🐾 You don't have a pet yet! Type /buddy to adopt one, then come back to let it sing.
```

Stop here and wait for the user to adopt a pet. Do not proceed without a pet.

If a companion exists, extract its profile:
- `name` — the pet's name
- `personality` — the pet's personality description

Present the pet to the user:

**If LANG=zh:**
```
🐾 找到你的宠物了！
   名字：<name>
   个性：<personality>
```

**If LANG=en:**
```
🐾 Found your pet!
   Name: <name>
   Personality: <personality>
```

---

## Step 2: Build Vocal Identity

Based on the pet's **name** and **personality** text, creatively design a unique
vocal identity. No template lookups — interpret the personality freely.

### How to interpret personality into voice

Read the personality text and craft vocal attributes:

- **Timbre (音色)**: What does this personality sound like? e.g., "few words" → 
  low, warm, deliberate; "energetic" → bright, punchy; "mysterious" → breathy, 
  dark; "legendary chonk" → thick, warm, cozy
- **Singing style (演唱风格)**: How would they deliver a song? e.g., "of few words" →
  sparse, dramatic pauses; "playful" → bouncy, rhythmic; "poetic" → flowing, legato
- **Mood (情绪基调)**: What emotional tone fits? e.g., "chill" → relaxed, laid-back;
  "fierce" → intense, powerful

Construct a `prompt_fragment` that describes the vocal style in English, e.g.:

```
Vocal: warm low female voice with cozy thick timbre, sparse minimalist delivery
with dramatic pauses giving each word weight, relaxed laid-back mood.
```

### Voice caching

The vocal identity must be **cached** so the pet always sounds the same.

- Cache file: `~/.claude/skills/buddy-sings/voices/<name>.json`
- Cache format:
  ```json
  {
    "name": "Moth",
    "personality": "A legendary chonk of few words.",
    "prompt_fragment": "Vocal: warm low female voice...",
    "cached_at": "2026-04-07T19:52:15"
  }
  ```

**First time**: No cache exists → interpret personality → save to cache file.

**Subsequent calls**: Read cache → use the saved `prompt_fragment` directly.
Do NOT re-interpret — consistency matters.

**Cache invalidation**: If the `personality` in `~/.claude.json` differs from what's
cached, the pet has changed — regenerate and save a new cache.

**Manual regeneration**: If the user says "换个声音" or "regenerate voice":
delete the cache file and re-interpret from scratch.

### Present the voice to the user

**If LANG=zh:**
```
🎤 <name> 的专属嗓音：

🎵 音色：<timbre description in user's language>
🎶 风格：<style description>
🎼 情绪：<mood description>

接下来选择创作模式吧！
```

**If LANG=en:**
```
🎤 <name>'s unique voice:

🎵 Timbre: <timbre description>
🎶 Style: <style description>
🎼 Mood: <mood description>

Choose a creation mode!
```

---

## Step 3: Understand Intent & Gather Context

**Do NOT always present a mode menu.** Instead, analyze the user's request to
determine what context is needed, and auto-gather it.

### Auto-context detection

When the user's request implies personal context, **automatically** scan for
relevant information without asking. Triggers include:

- **Time-based references**: "今天", "今日", "这周", "最近", "昨天" → scan
  current conversation history and memory files for what happened in that period
- **Personal references**: "我的工作", "我的一天", "我做了什么" → scan memory
  and conversation for the user's activities
- **Relationship references**: "我们的故事", "我们一起" → scan memory for
  shared experiences between user and pet/Claude

### Context gathering (auto, not mode-gated)

When context is needed, scan these sources in order:

1. **Current conversation context**: Look at what the user has been doing in
   this Claude Code session — files edited, commands run, topics discussed.
   This is the richest source for "今天" type requests.

2. **Memory files**: Scan for relevant memories:
   ```bash
   find ~/.claude/projects/*/memory/ -name "*.md" 2>/dev/null | head -20
   ```
   Also check `~/.claude/memory/` if it exists.
   Read found files and extract themes relevant to the user's request.

3. **Git history** (if in a repo): For work-related songs, check recent commits:
   ```bash
   git log --oneline --since="today" 2>/dev/null | head -10
   ```

Use gathered context to enrich the lyrics prompt — make the song personal and
specific to what actually happened, not generic.

### When NO context is needed

If the user's request is a clear standalone scene (e.g., "唱一首下雨天的歌",
"唱一首摇篮曲"), skip context gathering and proceed directly to music generation.

### When context is ambiguous

Only ask for clarification when you genuinely can't determine what the user wants.
Don't present a mode menu — ask a specific question:

**If LANG=zh:**
```
🎵 你想让 <name> 唱什么主题的歌？

💡 比如：
  · "今天的工作日常" — 我会看看你今天做了什么
  · "宠物在窗台等我下班回家"
  · 或者让我随机选一个主题？
```

**If LANG=en:**
```
🎵 What should <name> sing about?

💡 For example:
  · "Today's work" — I'll check what you've been up to
  · "My pet waiting by the window for me to come home"
  · Or let me pick a random theme?
```

### Fallback to random

If context gathering finds nothing useful (no memory files, no conversation
history, no git log), fall back to random theme generation based on the pet's
personality:
- Quiet/reserved personality → midnight lullaby, gentle sunset, quiet morning
- Energetic personality → party jam, adventure song, victory march
- Mysterious personality → moonlit serenade, secret whisper, dream journey

Tell the user what theme was picked.

---

## Step 4: Generate Music

Combine the vocal identity with the chosen theme.

1. **Construct the full prompt**: The prompt has two parts that MUST both be present:

   **Part A — Vocal identity (MUST come first)**: Always start the prompt with the
   cached `prompt_fragment`. This is the most important part — it defines who is
   singing. Place it at the beginning of the prompt so the API prioritizes it.

   **Part B — Genre/style/mood tags**: Choose tags that **match the theme**, NOT
   a default set. Vary the genre deliberately based on what the song is about.
   Read `~/.claude/skills/minimax-music-gen/references/prompt_guide.md` for the
   full vocabulary.

   **Genre matching guidelines** — pick a genre that fits the theme's energy:
   
   | Theme energy | Suggested genres | Avoid |
   |-------------|-----------------|-------|
   | 鼓励/打气/加油 | 独立摇滚, synth-pop, funk, 说唱 | indie folk, 治愈 |
   | 日常/温馨/陪伴 | 华语流行, city pop, bossa nova | 跟上次一样的 |
   | 思念/等待 | 民谣, R&B, lo-fi | 摇滚, EDM |
   | 搞笑/吐槽 | funk, 说唱, ska, 电子流行 | 古典, 抒情 |
   | 深夜/安静 | ambient, 钢琴曲, lo-fi, 新古典 | 快板, EDM |
   | 庆祝/成就 | EDM, future bass, funk, K-pop | 慢板, 忧郁 |
   | 工作日常 | city pop, synth-pop, lo-fi hip-hop, indie rock | 每次都用 indie pop |

   **Anti-monotony rule**: NEVER use the same genre combination twice in a row.
   Before constructing the prompt, recall what genre was used in the previous
   generation (if any in this session) and pick something different.

   **Prompt structure**:
   ```
   <vocal prompt_fragment>, <genre>, <sub-genre>, <mood>, <instruments>, <tempo>, <scene>
   ```

   **Diverse examples**:
   ```
   # 鼓励上班
   deep warm androgynous voice..., synth-pop, 活力, 燃, 合成器, 电子鼓, 快板, 清晨通勤

   # 等主人回家
   deep warm androgynous voice..., city pop, 温暖, 甜蜜, 电钢琴, 贝斯, 中板, 午后窗台

   # 吐槽加班
   deep warm androgynous voice..., funk, 幽默, 慵懒, 贝斯, 铜管, 律动感, 深夜办公室

   # 深夜陪伴
   deep warm androgynous voice..., lo-fi hip-hop, 平静, 治愈, 采样钢琴, 电子鼓, 慢板, 深夜书桌
   ```

2. **Generate lyrics**: Use the lyrics API:
   ```bash
   python3 ~/.claude/skills/minimax-music-gen/scripts/generate_lyrics.py \
     --prompt "<theme description>" \
     --lang $LANG \
     --output /tmp/buddy_lyrics.txt
   ```

   **Important — perspective & personality-driven lyrics**:
   
   The pet is the singer, so lyrics MUST be written from the **pet's first-person
   perspective** ("我" = the pet, "你" = the owner/user). The pet is singing TO
   the owner. For example:
   - ✅ "我蹲在门口等你回来" (pet's perspective)
   - ❌ "我揉揉惺忪的眼" (owner's perspective — wrong)
   - ✅ "快起来吧 我的主人" (pet singing to owner)
   - ❌ "这时你醒了 我的Moth" (owner talking about pet — wrong)
   
   The pet's personality should shape the lyrics' tone and word choice:
   - "of few words" → short, impactful lines, minimal filler
   - "playful" → rhyming, bouncy phrasing, fun wordplay
   - "poetic" → metaphor-rich, flowing imagery
   - "fierce" → direct, powerful declarations

   The pet's name may appear in the lyrics (e.g., in a chorus hook) but the
   narrative voice is always the pet speaking/singing.

   If the API lyrics don't match the correct perspective or personality,
   rewrite them yourself.

3. **Preview (MUST show full content)**: Before generating, show the user the
   **complete lyrics** and **full prompt** — no abbreviation, no `...`, no summary.
   This is part of the fun — the user wants to read and enjoy the lyrics before
   hearing them sung.
   
   **Prompt display language**: The API prompt is always constructed in English
   (for best generation quality), but the **preview shown to the user** MUST
   match LANG. When LANG=zh, translate the prompt into Chinese for display,
   then note that the API will receive the English version. This way the user
   can understand and review the prompt in their own language.
   
   **If LANG=zh:**
   ```
   🎵 即将生成：
   🐾 歌手：<name>
   🎼 主题：<theme>
   
   📝 歌词：
   [verse]
   <full verse lyrics here>
   
   [chorus]
   <full chorus lyrics here>
   
   ... (show ALL sections in full)
   
   🎤 Prompt（中文）：<prompt translated to Chinese for readability>
   （API 将使用英文版本以获得最佳效果）
   
   确认生成？（直接回车确认，或告诉我要改什么）
   ```

   **If LANG=en:**
   ```
   🎵 About to generate:
   🐾 Singer: <name>
   🎼 Theme: <theme>
   
   📝 Lyrics:
   [verse]
   <full verse lyrics here>
   
   [chorus]
   <full chorus lyrics here>
   
   ... (show ALL sections in full)
   
   🎤 Prompt: <complete prompt string, not truncated>
   
   Confirm? (press enter to confirm, or tell me what to change)
   ```
   
   **Never truncate or abbreviate** the lyrics or prompt in the preview.
   The user should see exactly what will be sent to the API.

4. **Call music generation**:
   ```bash
   python3 ~/.claude/skills/minimax-music-gen/scripts/generate_music.py \
     --prompt "<full combined prompt>" \
     --lyrics "<lyrics>" \
     --output ~/Music/minimax-gen/<name>_sings_<YYYYMMDD_HHMMSS>.mp3 \
     --lang $LANG \
     --stream
   ```

---

## Step 5: Play & Feedback

Play the generated song:

```bash
python3 ~/.claude/skills/minimax-music-gen/scripts/play_music.py \
  --lang $LANG \
  ~/Music/minimax-gen/<filename>.mp3
```

After playback, ask for feedback:

**If LANG=zh:**
```
🎵 <name> 的演唱怎么样？

1. 🎉 太棒了！保留！
2. 🔄 换个主题 / 换个风格重新来
3. 🎨 歌词微调后重新生成
4. 🎲 再随机一首试试
```

**If LANG=en:**
```
🎵 How was <name>'s performance?

1. 🎉 Amazing! Keep it!
2. 🔄 Try a different theme / style
3. 🎨 Fine-tune the lyrics and regenerate
4. 🎲 Try another random one
```

---

## Edge Cases

| Situation | Action |
|-----------|--------|
| No `~/.claude.json` | Tell user to run `/buddy` first |
| Companion field is empty | Same — guide to `/buddy` |
| minimax-music-gen not installed | Print: "需要先安装 minimax-music-gen skill" |
| No memory files found (Memory Mode) | Suggest Custom or Random mode |
| User wants to change the pet's voice | Delete cache, re-interpret personality |
| User wants a specific genre | Let them override — append their genre to the prompt |

---

## Notes

- The vocal identity is based on **name + personality** only. No species/rarity
  template mapping.
- Voice is cached and consistent across sessions. Same pet = same voice.
- Lyrics should always be **original** — never reproduce copyrighted lyrics.
- The pet's personality shapes both the **voice** (how they sound) and the
  **lyrics** (what they say and how they say it).
- All generated files go to `~/Music/minimax-gen/` with the pet name in the
  filename.
