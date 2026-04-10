#!/usr/bin/env python3
"""
generate_playlist.py - Generate a MiniMax-compatible playlist plan from a taste profile.

Given a taste profile JSON and optional theme, produces a playlist plan (JSON)
with 3-7 songs, each with a MiniMax-compatible prompt and lyrics instruction.

Uses only Python stdlib. Seeded with current date for daily reproducibility.
"""

import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.expanduser("~/.claude/skills/shared"))
from i18n import msg

LANG = "zh"  # Module-level default, updated by main()

# ---------------------------------------------------------------------------
# Genre -> instrument pool mapping
# ---------------------------------------------------------------------------
GENRE_INSTRUMENTS: dict[str, list[str]] = {
    "华语流行": ["钢琴", "原声吉他", "鼓组", "弦乐", "合成器pad"],
    "R&B": ["电钢琴", "贝斯", "鼓组", "合成器pad", "指弹吉他"],
    "K-pop": ["合成器", "电子鼓", "synth lead", "贝斯", "钢琴"],
    "爵士": ["钢琴", "贝斯", "萨克斯", "鼓刷", "小号"],
    "民谣": ["原声吉他", "口琴", "cajon", "手风琴", "曼陀林"],
    "摇滚": ["电吉他", "贝斯", "架子鼓", "失真吉他", "风琴"],
    "电子流行": ["合成器", "808 bass", "电子鼓", "arpeggiator", "vocoder"],
    "中国风": ["古筝", "竹笛", "琵琶", "二胡", "扬琴"],
    "Lo-fi": ["lo-fi钢琴", "采样鼓", "vinyl crackle", "Rhodes", "贝斯"],
    "古典crossover": ["钢琴", "弦乐四重奏", "大提琴", "竖琴", "长笛"],
    "嘻哈": ["808 bass", "hi-hat", "采样loop", "合成器", "scratch"],
    "拉丁": ["原声吉他", "手鼓", "贝斯", "铜管", "沙锤"],
    "乡村": ["原声吉他", "班卓琴", "小提琴", "贝斯", "口琴"],
    "放克": ["电贝斯", "clavinet", "铜管", "架子鼓", "wah吉他"],
    "雷鬼": ["贝斯", "节奏吉他", "风琴", "鼓组", "铜管"],
    "灵魂乐": ["电钢琴", "贝斯", "铜管", "鼓组", "风琴"],
    "蓝调": ["电吉他", "口琴", "钢琴", "贝斯", "架子鼓"],
    "金属": ["失真吉他", "双踩大鼓", "贝斯", "solo吉他", "尖叫人声"],
    "朋克": ["电吉他", "贝斯", "架子鼓", "失真"],
    "新世纪": ["合成器pad", "竖琴", "长笛", "钢琴", "弦乐"],
    "世界音乐": ["手鼓", "西塔琴", "竹笛", "贝斯", "打击乐"],
}

# Fallback instruments for unknown genres
DEFAULT_INSTRUMENTS = ["钢琴", "吉他", "贝斯", "鼓组", "合成器"]

# ---------------------------------------------------------------------------
# Theme genre keyword -> genre name mapping
# Allows theme strings like "爵士风格" or "jazz style" to constrain genre selection
# ---------------------------------------------------------------------------
THEME_GENRE_KEYWORDS: dict[str, str] = {
    "爵士": "爵士", "jazz": "爵士",
    "摇滚": "摇滚", "rock": "摇滚",
    "民谣": "民谣", "folk": "民谣",
    "电子": "电子流行", "electronic": "电子流行",
    "嘻哈": "嘻哈", "hip-hop": "嘻哈", "hiphop": "嘻哈",
    "古典": "古典crossover", "classical": "古典crossover",
    "中国风": "中国风", "古风": "中国风",
    "r&b": "R&B", "rnb": "R&B",
    "蓝调": "蓝调", "blues": "蓝调",
    "拉丁": "拉丁", "latin": "拉丁",
    "放克": "放克", "funk": "放克",
    "乡村": "乡村", "country": "乡村",
    "金属": "金属", "metal": "金属",
    "雷鬼": "雷鬼", "reggae": "雷鬼",
    "lo-fi": "Lo-fi", "lofi": "Lo-fi",
    "灵魂乐": "灵魂乐", "soul": "灵魂乐",
    "kpop": "K-pop", "k-pop": "K-pop",
    "jpop": "J-pop", "j-pop": "J-pop",
    "bossa nova": "爵士",
    "bossa": "爵士",
    "neo-soul": "R&B",
    "neo soul": "R&B",
    "朋克": "朋克", "punk": "朋克",
    "新世纪": "新世纪", "new age": "新世纪",
    "世界音乐": "世界音乐", "world": "世界音乐",
}

# ---------------------------------------------------------------------------
# Theme -> scene tags mapping
# ---------------------------------------------------------------------------
THEME_SCENES: dict[str, list[str]] = {
    "深夜放松": ["深夜独处", "星空下"],
    "深夜": ["深夜独处", "星空下"],
    "放松": ["深夜独处", "午后阳光"],
    "通勤路上": ["日出公路", "城市霓虹"],
    "通勤": ["日出公路", "城市霓虹"],
    "雨天": ["雨天窗前", "咖啡馆午后"],
    "下雨": ["雨天窗前", "咖啡馆午后"],
    "运动": [],
    "workout": [],
    "健身": [],
    "清晨": ["日出", "清晨薄雾"],
    "morning": ["日出", "清晨薄雾"],
    "学习": ["图书馆", "安静书房"],
    "读书": ["图书馆", "午后阳光"],
    "旅行": ["公路旅行", "异国街头"],
    "travel": ["公路旅行", "异国街头"],
    "派对": ["霓虹灯下", "午夜舞池"],
    "party": ["霓虹灯下", "午夜舞池"],
    "浪漫": ["烛光晚餐", "月光下"],
    "romantic": ["烛光晚餐", "月光下"],
    "思念": ["深夜独处", "窗前雨滴"],
    "怀旧": ["老唱片机", "黄昏街角"],
    "夏天": ["海边落日", "夏夜微风"],
    "summer": ["海边落日", "夏夜微风"],
    "冬天": ["雪夜壁炉", "冬日暖阳"],
    "winter": ["雪夜壁炉", "冬日暖阳"],
    "咖啡": ["咖啡馆午后", "爵士酒吧"],
    "工作": ["安静书房", "办公室"],
    "冥想": ["寂静山林", "晨曦"],
    "meditation": ["寂静山林", "晨曦"],
}

# ---------------------------------------------------------------------------
# Theme -> tempo bias
# ---------------------------------------------------------------------------
SLOW_THEMES = {"深夜放松", "深夜", "放松", "冥想", "meditation", "思念", "读书", "学习"}
FAST_THEMES = {"运动", "workout", "健身", "派对", "party"}

# Instrumental-suggestive themes
INSTRUMENTAL_THEMES = {"纯音乐", "background music", "bgm", "冥想", "meditation", "学习", "读书", "工作"}

# ---------------------------------------------------------------------------
# Mood pools for blending
# ---------------------------------------------------------------------------
DEFAULT_MOODS = ["温暖", "忧郁", "平静", "浪漫", "内省", "梦幻", "治愈", "孤独",
                 "热情", "自由", "活力", "甜蜜", "伤感", "慵懒", "力量"]

THEME_MOOD_MAP: dict[str, list[str]] = {
    "深夜放松": ["忧郁", "内省", "平静", "慵懒", "治愈"],
    "深夜": ["忧郁", "内省", "孤独", "慵懒"],
    "放松": ["平静", "治愈", "慵懒", "温暖"],
    "运动": ["活力", "力量", "热情", "自由"],
    "workout": ["活力", "力量", "热情", "自由"],
    "健身": ["活力", "力量", "热情"],
    "通勤路上": ["平静", "自由", "温暖", "活力"],
    "通勤": ["平静", "自由", "温暖"],
    "雨天": ["忧郁", "内省", "平静", "孤独", "治愈"],
    "下雨": ["忧郁", "内省", "平静", "孤独"],
    "浪漫": ["浪漫", "甜蜜", "温暖", "梦幻"],
    "romantic": ["浪漫", "甜蜜", "温暖", "梦幻"],
    "思念": ["忧郁", "伤感", "内省", "孤独"],
    "怀旧": ["温暖", "伤感", "内省", "治愈"],
    "派对": ["热情", "活力", "自由", "甜蜜"],
    "party": ["热情", "活力", "自由"],
    "夏天": ["活力", "自由", "热情", "甜蜜"],
    "summer": ["活力", "自由", "热情"],
    "冬天": ["温暖", "内省", "平静", "治愈"],
    "winter": ["温暖", "内省", "平静"],
    "咖啡": ["慵懒", "平静", "温暖", "浪漫"],
    "清晨": ["平静", "温暖", "治愈", "自由"],
    "morning": ["平静", "温暖", "治愈"],
    "旅行": ["自由", "热情", "温暖", "活力"],
    "travel": ["自由", "热情", "温暖"],
    "冥想": ["平静", "治愈", "梦幻"],
    "meditation": ["平静", "治愈", "梦幻"],
}

# ---------------------------------------------------------------------------
# Sub-genre pools per genre
# ---------------------------------------------------------------------------
GENRE_SUB: dict[str, list[str]] = {
    "华语流行": ["都市流行", "抒情流行", "dance-pop", "synth-pop", "成人抒情"],
    "R&B": ["neo-soul", "contemporary R&B", "slow jam", "alternative R&B", "urban"],
    "K-pop": ["抒情", "dance", "ballad", "tropical house", "future bass"],
    "爵士": ["smooth jazz", "bossa nova", "vocal jazz", "cool jazz", "swing"],
    "民谣": ["独立民谣", "城市民谣", "acoustic folk", "新民谣", "校园民谣"],
    "摇滚": ["alternative rock", "indie rock", "post-rock", "soft rock", "brit-pop"],
    "电子流行": ["synthwave", "future pop", "electro-pop", "dream pop", "chillwave"],
    "中国风": ["古风", "戏腔流行", "国潮电子", "新中式", "水墨意境"],
    "Lo-fi": ["lo-fi hip-hop", "chillhop", "lo-fi beats", "study beats", "bedroom pop"],
    "古典crossover": ["新古典", "cinematic", "orchestral pop", "chamber pop"],
    "嘻哈": ["trap", "boom bap", "cloud rap", "old school", "conscious hip-hop"],
    "拉丁": ["reggaeton", "bossa nova", "salsa", "bachata", "latin pop"],
    "乡村": ["country pop", "americana", "bluegrass", "folk country"],
    "放克": ["p-funk", "electro-funk", "nu-funk", "disco-funk"],
    "雷鬼": ["roots reggae", "dub", "dancehall", "lover's rock"],
    "灵魂乐": ["classic soul", "neo-soul", "Motown", "southern soul"],
    "蓝调": ["Chicago blues", "delta blues", "electric blues", "blues rock"],
    "金属": ["heavy metal", "progressive metal", "symphonic metal", "nu-metal"],
    "朋克": ["pop-punk", "post-punk", "hardcore", "skate punk"],
    "新世纪": ["ambient", "new age", "space music", "meditative"],
    "世界音乐": ["ethnic fusion", "tribal", "Afrobeat", "Celtic"],
}

DEFAULT_SUBS = ["alternative", "indie", "fusion"]

# ---------------------------------------------------------------------------
# Vocal description templates
# ---------------------------------------------------------------------------
VOCAL_DESCS: dict[str, list[str]] = {
    "male": ["温柔男声", "低沉男声", "清澈男声", "磁性男声", "沧桑男声"],
    "female": ["温柔女声", "空灵女声", "甜美女声", "低音女声", "清亮女声"],
    "instrumental": [],
}

# ---------------------------------------------------------------------------
# English translation maps for narrative prompt construction
# ---------------------------------------------------------------------------
MOOD_EN: dict[str, str] = {
    "温暖": "warm", "忧郁": "melancholy", "平静": "peaceful", "浪漫": "romantic",
    "内省": "introspective", "梦幻": "dreamy", "治愈": "healing", "孤独": "lonely",
    "热情": "passionate", "自由": "free-spirited", "活力": "energetic",
    "甜蜜": "sweet", "伤感": "wistful", "慵懒": "laid-back", "力量": "powerful",
    "热血": "fiery", "悲伤": "sorrowful", "幽默": "playful", "阳光": "sunny",
    "神秘": "mysterious", "空灵": "ethereal", "压抑": "brooding",
    "欢快": "cheerful", "律动感": "groovy", "燃": "blazing",
    "dark": "dark", "gloomy": "gloomy", "温柔": "tender",
}

GENRE_EN: dict[str, str] = {
    "华语流行": "C-pop", "流行": "Pop", "R&B": "R&B", "K-pop": "K-pop",
    "J-pop": "J-pop", "独立流行": "Indie Pop", "neo-soul": "Neo-Soul",
    "摇滚": "Rock", "中国风": "Chinese Traditional", "古典crossover": "Classical Crossover",
    "古典": "Classical", "爵士": "Jazz", "民谣": "Folk", "电子流行": "Electropop",
    "粤语流行": "Cantopop",
    "嘻哈": "Hip-Hop", "蓝调": "Blues", "拉丁": "Latin", "放克": "Funk",
    "乡村": "Country", "金属": "Metal", "雷鬼": "Reggae", "灵魂乐": "Soul",
    "Lo-fi": "Lo-fi", "朋克": "Punk", "新世纪": "New Age", "世界音乐": "World Music",
    "独立民谣": "Indie Folk", "独立摇滚": "Indie Rock",
    "中国传统": "Chinese Traditional", "民族声乐": "Chinese Vocal",
    "hip-hop": "Hip-Hop", "ambient": "Ambient", "funk": "Funk",
    "bossa nova": "Bossa Nova", "smooth jazz": "Smooth Jazz",
    "city pop": "City Pop", "indie pop": "Indie Pop", "indie folk": "Indie Folk",
    "民谣摇滚": "Folk Rock", "梦幻流行": "Dream Pop", "纯音乐": "Instrumental",
    "后摇": "Post-Rock", "post-rock": "Post-Rock", "jazz": "Jazz",
    "电子": "Electronic", "交响": "Symphonic", "说唱": "Rap", "舞曲": "Dance",
}

VOCAL_EN: dict[str, str] = {
    "温柔男声": "smooth, gentle male vocals with intimate delivery",
    "低沉男声": "deep, resonant male baritone with warm delivery",
    "清澈男声": "clear, bright male vocals with crisp articulation",
    "磁性男声": "sultry, magnetic male vocals with breathy phrasing",
    "沧桑男声": "weathered, soulful male vocals with raw emotional depth",
    "温柔女声": "soft, gentle female vocals with tender delivery",
    "空灵女声": "ethereal, crystal-clear female vocals with lush reverb",
    "甜美女声": "sweet, delicate female vocals with airy delivery",
    "低音女声": "rich, smoky female alto with sophisticated phrasing",
    "清亮女声": "bright, powerful female vocals with soaring clarity",
}

INSTRUMENT_EN: dict[str, str] = {
    "钢琴": "piano", "吉他": "guitar", "原声吉他": "acoustic guitar", "鼓组": "live drums",
    "弦乐": "orchestral strings", "合成器pad": "synth pads",
    "电钢琴": "Rhodes piano", "贝斯": "bass", "指弹吉他": "fingerpicked guitar",
    "合成器": "synthesizer", "电子鼓": "electronic drums", "synth lead": "synth lead",
    "萨克斯": "saxophone", "鼓刷": "brushed drums", "小号": "trumpet",
    "口琴": "harmonica", "cajon": "cajón", "手风琴": "accordion",
    "曼陀林": "mandolin", "电吉他": "electric guitar", "架子鼓": "live drums",
    "失真吉他": "distorted guitar", "风琴": "organ",
    "古筝": "guzheng", "竹笛": "bamboo flute", "琵琶": "pipa", "二胡": "erhu",
    "扬琴": "yangqin", "lo-fi钢琴": "lo-fi sampled piano",
    "采样鼓": "sampled drums", "vinyl crackle": "vinyl crackle", "Rhodes": "Rhodes piano",
    "弦乐四重奏": "string quartet", "大提琴": "cello", "竖琴": "harp", "长笛": "flute",
    "808 bass": "808 bass", "hi-hat": "hi-hats", "采样loop": "sampled loops",
    "scratch": "turntable scratches", "手鼓": "hand drums", "铜管": "brass section",
    "沙锤": "shakers", "班卓琴": "banjo", "小提琴": "violin",
    "电贝斯": "electric bass", "clavinet": "clavinet", "wah吉他": "wah guitar",
    "节奏吉他": "rhythm guitar", "solo吉他": "lead guitar",
    "尖叫人声": "screaming vocals", "失真": "distortion",
    "双踩大鼓": "double kick drums", "竹笛": "bamboo flute",
    "arpeggiator": "arpeggiator", "vocoder": "vocoder",
    "西塔琴": "sitar", "打击乐": "percussion",
}

TEMPO_BPM: dict[str, tuple[int, int]] = {
    "慢板": (60, 80),
    "中板": (85, 110),
    "稍快": (110, 130),
    "快板": (130, 160),
}

# ---------------------------------------------------------------------------
# Language -> lyrics prompt language hint
# ---------------------------------------------------------------------------
LANG_HINT: dict[str, str] = {
    "中文": "Chinese",
    "英语": "English",
    "英文": "English",
    "日语": "Japanese",
    "日文": "Japanese",
    "韩语": "Korean",
    "韩文": "Korean",
    "粤语": "Cantonese",
    "西班牙语": "Spanish",
    "法语": "French",
    "葡萄牙语": "Portuguese",
    "俄语": "Russian",
    "印地语": "Hindi",
    "印尼语": "Indonesian",
    "土耳其语": "Turkish",
    "越南语": "Vietnamese",
}

# ---------------------------------------------------------------------------
# Tempo labels
# ---------------------------------------------------------------------------
TEMPOS = ["慢板", "中板", "快板"]

# ---------------------------------------------------------------------------
# Filename-safe slug helpers
# ---------------------------------------------------------------------------
_GENRE_SLUG: dict[str, str] = {
    "华语流行": "cpop",
    "R&B": "rnb",
    "K-pop": "kpop",
    "爵士": "jazz",
    "民谣": "folk",
    "摇滚": "rock",
    "电子流行": "electropop",
    "中国风": "chinese_style",
    "Lo-fi": "lofi",
    "古典crossover": "classical_crossover",
    "嘻哈": "hiphop",
    "拉丁": "latin",
    "乡村": "country",
    "放克": "funk",
    "雷鬼": "reggae",
    "灵魂乐": "soul",
    "蓝调": "blues",
    "金属": "metal",
    "朋克": "punk",
    "新世纪": "newage",
    "世界音乐": "world",
}

_THEME_SLUG: dict[str, str] = {
    "深夜放松": "midnight",
    "深夜": "night",
    "放松": "relax",
    "运动": "workout",
    "workout": "workout",
    "健身": "gym",
    "通勤路上": "commute",
    "通勤": "commute",
    "雨天": "rain",
    "下雨": "rain",
    "浪漫": "romantic",
    "romantic": "romantic",
    "思念": "missing",
    "怀旧": "nostalgia",
    "派对": "party",
    "party": "party",
    "夏天": "summer",
    "summer": "summer",
    "冬天": "winter",
    "winter": "winter",
    "咖啡": "cafe",
    "清晨": "morning",
    "morning": "morning",
    "旅行": "travel",
    "travel": "travel",
    "冥想": "meditation",
    "meditation": "meditation",
    "学习": "study",
    "读书": "reading",
    "工作": "work",
}


# ---------------------------------------------------------------------------
# Extract genre override from theme string
# ---------------------------------------------------------------------------
def _extract_genre_from_theme(theme: str) -> str | None:
    """Scan theme for genre keywords and return the matched genre name, or None."""
    theme_lower = theme.lower()
    # Sort by key length descending so longer matches win (e.g. "bossa nova" before "nova")
    for keyword in sorted(THEME_GENRE_KEYWORDS, key=len, reverse=True):
        if keyword in theme_lower:
            return THEME_GENRE_KEYWORDS[keyword]
    return None


# ---------------------------------------------------------------------------
# Weighted random choice helper
# ---------------------------------------------------------------------------
def weighted_choice(items: list[str], weights: list[float]) -> str:
    """Pick one item using weighted random selection (stdlib only)."""
    total = sum(weights)
    r = random.random() * total
    cumulative = 0.0
    for item, w in zip(items, weights):
        cumulative += w
        if r <= cumulative:
            return item
    return items[-1]


def weighted_choices_unique(items: list[str], weights: list[float], k: int) -> list[str]:
    """Pick k unique items with weighted random (without replacement)."""
    items = list(items)
    weights = list(weights)
    chosen: list[str] = []
    for _ in range(k):
        if not items:
            break
        pick = weighted_choice(items, weights)
        chosen.append(pick)
        idx = items.index(pick)
        items.pop(idx)
        weights.pop(idx)
    return chosen


# ---------------------------------------------------------------------------
# Profile loading + normalization
# ---------------------------------------------------------------------------
def load_profile(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        profile = json.load(f)

    # Normalize genres to {name: weight} dict
    genres = profile.get("genres", {})
    if isinstance(genres, list):
        genres = {g: 1.0 for g in genres}
    profile["genres"] = genres

    # Normalize languages
    langs = profile.get("languages", {})
    if isinstance(langs, list):
        langs = {l: 1.0 for l in langs}
    profile["languages"] = langs

    # Normalize mood_tendencies
    moods = profile.get("mood_tendencies", {})
    if isinstance(moods, list):
        moods = {m: 1.0 for m in moods}
    profile["mood_tendencies"] = moods

    # Normalize tempo_preference
    tempo = profile.get("tempo_preference", {})
    if isinstance(tempo, list):
        tempo = {t: 1.0 for t in tempo}
    if not tempo:
        tempo = {"慢板": 0.3, "中板": 0.5, "快板": 0.2}
    profile["tempo_preference"] = tempo

    # Normalize vocal_preference
    vocal = profile.get("vocal_preference", {})
    if isinstance(vocal, list):
        vocal = {v: 1.0 for v in vocal}
    if not vocal:
        vocal = {"male": 0.4, "female": 0.4, "instrumental": 0.05}
    profile["vocal_preference"] = vocal

    # Ensure feedback exists
    if "feedback" not in profile:
        profile["feedback"] = {}
    fb = profile["feedback"]
    fb.setdefault("liked_genres", [])
    fb.setdefault("disliked_genres", [])

    return profile


# ---------------------------------------------------------------------------
# Core playlist generation
# ---------------------------------------------------------------------------
def generate_playlist(profile: dict, theme: str | None, count: int) -> dict:
    """Generate a playlist plan dict."""

    # --- Determine theme ---
    if not theme:
        moods = profile["mood_tendencies"]
        if moods:
            theme = max(moods, key=lambda k: moods[k])
        else:
            theme = "放松"

    # --- Prepare genre weights with feedback adjustments ---
    genres = dict(profile["genres"])
    if not genres:
        genres = {"华语流行": 1.0}

    fb = profile["feedback"]
    for g in fb["liked_genres"]:
        if g in genres:
            genres[g] *= 1.5
        else:
            genres[g] = 0.5  # add liked genre even if not in original profile
    for g in fb["disliked_genres"]:
        if g in genres:
            genres[g] *= 0.5

    # --- Apply theme genre override ---
    theme_genre = _extract_genre_from_theme(theme)
    if theme_genre:
        # Ensure the theme genre exists in the pool
        if theme_genre not in genres:
            genres[theme_genre] = 0.0
        # Set theme genre to 70% of total weight, rest shares 30%
        total = sum(genres.values())
        target_weight = total * (70.0 / 30.0)  # so it's 70% of new total
        genres[theme_genre] = target_weight

    genre_names = list(genres.keys())
    genre_weights = [genres[g] for g in genre_names]

    # --- Prepare language weights ---
    languages = profile["languages"]
    if not languages:
        languages = {"中文": 1.0}
    lang_names = list(languages.keys())
    lang_weights = [languages[l] for l in lang_names]

    # --- Prepare vocal weights ---
    vocal_pref = profile["vocal_preference"]
    vocal_types = [k for k in vocal_pref if k != "instrumental"]
    vocal_weights = [vocal_pref[k] for k in vocal_types]
    instrumental_weight = vocal_pref.get("instrumental", 0.05)

    # --- Prepare tempo weights ---
    tempo_pref = dict(profile["tempo_preference"])

    # --- Prepare theme moods ---
    theme_moods = THEME_MOOD_MAP.get(theme, None)
    if theme_moods is None:
        # Try partial match
        for key in THEME_MOOD_MAP:
            if key in theme or theme in key:
                theme_moods = THEME_MOOD_MAP[key]
                break
    if theme_moods is None:
        theme_moods = ["温暖", "平静", "治愈"]

    profile_moods = profile["mood_tendencies"]
    profile_mood_names = list(profile_moods.keys()) if profile_moods else DEFAULT_MOODS[:5]
    profile_mood_weights = [profile_moods.get(m, 1.0) for m in profile_mood_names]

    # --- Determine instrumental bias from theme ---
    instrumental_bias = 0.05
    theme_lower = theme.lower()
    for it in INSTRUMENTAL_THEMES:
        if it in theme_lower or theme_lower in it:
            instrumental_bias = 0.50
            break

    # --- Build songs ---
    songs: list[dict] = []
    used_genres: list[str] = []

    for i in range(count):
        # (a) Pick genre with diversity rule
        chosen_genre = _pick_genre(genre_names, genre_weights, used_genres)
        used_genres.append(chosen_genre)

        # (b) Pick moods (2 moods: blend theme 60% + profile 40%)
        mood1 = _pick_blended_mood(theme_moods, profile_mood_names, profile_mood_weights, 0.6)
        mood2 = _pick_blended_mood(theme_moods, profile_mood_names, profile_mood_weights, 0.6)
        # Ensure mood2 differs from mood1
        attempts = 0
        while mood2 == mood1 and attempts < 10:
            mood2 = _pick_blended_mood(theme_moods, profile_mood_names, profile_mood_weights, 0.6)
            attempts += 1

        # (c) Pick vocal type with alternation
        is_instrumental = random.random() < instrumental_bias
        if is_instrumental:
            vocal_type = "instrumental"
            vocal_desc = ""
        else:
            vocal_type = _pick_vocal(vocal_types, vocal_weights, songs)
            descs = VOCAL_DESCS.get(vocal_type, VOCAL_DESCS["male"])
            vocal_desc = random.choice(descs) if descs else ""

        # (d) Pick tempo based on theme
        tempo = _pick_tempo(theme, tempo_pref, chosen_genre)

        # (e) Pick instruments (2-3)
        instruments = _pick_instruments(chosen_genre, random.randint(2, 3))

        # (f) Pick scene
        scenes = _find_scenes(theme)
        scene = random.choice(scenes) if scenes else ""

        # (g) Pick language
        language = weighted_choice(lang_names, lang_weights)

        # (h) Pick sub-genre
        subs = GENRE_SUB.get(chosen_genre, DEFAULT_SUBS)
        sub_genre = random.choice(subs)

        # (i) Construct narrative English prompt (per prompt_guide.md)
        prompt = _build_narrative_prompt(
            genre=chosen_genre, sub_genre=sub_genre,
            mood1=mood1, mood2=mood2, vocal_desc=vocal_desc,
            instruments=instruments, tempo=tempo, scene=scene,
            is_instrumental=is_instrumental, theme=theme,
        )

        # (j) Build description
        if is_instrumental:
            desc = f"{chosen_genre} {sub_genre}，{mood1}"
            vocal_label = msg("label_instrumental", LANG)
        else:
            gender_label = msg("label_male", LANG) if vocal_type == "male" else msg("label_female", LANG)
            desc = f"{chosen_genre} {sub_genre}，{mood1}"
            vocal_label = f"{language}/{gender_label}"

        # (k) Lyrics prompt
        # Override language based on --lang if set
        if LANG == "en":
            lang_hint = "English"
        elif LANG == "zh":
            lang_hint = "Chinese"
        else:
            lang_hint = LANG_HINT.get(language, language)
        mood1_en = _translate(mood1, MOOD_EN)
        mood2_en = _translate(mood2, MOOD_EN)
        genre_en = _translate(chosen_genre, GENRE_EN)
        instruments_en = [_translate(inst, INSTRUMENT_EN) for inst in instruments]
        lp_article = "An" if mood1_en[0].lower() in "aeiou" else "A"
        if is_instrumental:
            lyrics_prompt = (
                f"{lp_article} instrumental {sub_genre} piece with a {mood1_en} and {mood2_en} atmosphere, "
                f"featuring {_format_instrument_list(instruments_en)}. No vocals."
            )
        else:
            lyrics_prompt = (
                f"{lp_article} {mood1_en} {genre_en} {sub_genre} song in {lang_hint} about "
                f"{_lyrics_theme_description(theme, mood1, mood2)}. "
                f"The mood shifts from {mood1_en} to {mood2_en}. "
                f"Tempo: {_random_bpm(tempo)} BPM."
            )

        # (l) Filename
        genre_slug = _GENRE_SLUG.get(chosen_genre, chosen_genre.lower().replace(" ", "_"))
        theme_slug = _THEME_SLUG.get(theme, theme.lower().replace(" ", "_"))
        filename = f"{i+1:02d}_{genre_slug}_{theme_slug}.mp3"

        songs.append({
            "index": i + 1,
            "description": desc,
            "prompt": prompt,
            "instrumental": is_instrumental,
            "lyrics_prompt": lyrics_prompt,
            "language": language if not is_instrumental else "instrumental",
            "filename": filename,
        })

    # --- Build output ---
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    playlist = {
        "playlist_name": theme,
        "theme": theme,
        "song_count": count,
        "created_at": now,
        "songs": songs,
    }
    return playlist


def _pick_genre(genre_names: list[str], genre_weights: list[float],
                used_genres: list[str]) -> str:
    """Pick a genre ensuring no two consecutive songs share the same primary genre."""
    last_genre = used_genres[-1] if used_genres else None

    for _ in range(5):
        pick = weighted_choice(genre_names, genre_weights)
        if pick != last_genre:
            return pick

    # All attempts failed - pick least recently used
    # Build frequency map of recent uses
    freq: dict[str, int] = {}
    for g in genre_names:
        freq[g] = 0
    for g in used_genres:
        if g in freq:
            freq[g] += 1

    candidates = [g for g in genre_names if g != last_genre]
    if not candidates:
        candidates = genre_names

    return min(candidates, key=lambda g: freq.get(g, 0))


def _pick_blended_mood(theme_moods: list[str],
                       profile_mood_names: list[str],
                       profile_mood_weights: list[float],
                       theme_weight: float) -> str:
    """Blend theme moods (theme_weight) with profile moods (1-theme_weight)."""
    if random.random() < theme_weight:
        return random.choice(theme_moods)
    else:
        return weighted_choice(profile_mood_names, profile_mood_weights)


def _pick_vocal(vocal_types: list[str], vocal_weights: list[float],
                previous_songs: list[dict]) -> str:
    """Pick vocal type, alternating male/female when possible."""
    if previous_songs:
        last = previous_songs[-1]
        last_vocal = None
        if not last["instrumental"]:
            # Determine last vocal type from description
            for vt in vocal_types:
                descs = VOCAL_DESCS.get(vt, [])
                # Check if any desc substring is in prompt
                for d in descs:
                    if d in last["prompt"]:
                        last_vocal = vt
                        break
                if last_vocal:
                    break

        if last_vocal and len(vocal_types) > 1:
            # Try to pick a different type
            other_types = [v for v in vocal_types if v != last_vocal]
            other_weights = [vocal_weights[vocal_types.index(v)] for v in other_types]
            if other_types and sum(other_weights) > 0:
                if random.random() < 0.7:  # 70% chance to alternate
                    return weighted_choice(other_types, other_weights)

    return weighted_choice(vocal_types, vocal_weights)


def _pick_tempo(theme: str, tempo_pref: dict[str, float], genre: str) -> str:
    """Pick tempo biased by theme."""
    theme_lower = theme.lower()

    # Check slow themes
    for st in SLOW_THEMES:
        if st in theme_lower or theme_lower in st:
            # Bias toward slow/medium
            adjusted = dict(tempo_pref)
            adjusted["慢板"] = adjusted.get("慢板", 0.3) * 2.0
            adjusted["中板"] = adjusted.get("中板", 0.5) * 1.5
            adjusted["快板"] = adjusted.get("快板", 0.2) * 0.3
            names = list(adjusted.keys())
            weights = [adjusted[n] for n in names]
            return weighted_choice(names, weights)

    # Check fast themes
    for ft in FAST_THEMES:
        if ft in theme_lower or theme_lower in ft:
            adjusted = dict(tempo_pref)
            adjusted["慢板"] = adjusted.get("慢板", 0.3) * 0.3
            adjusted["中板"] = adjusted.get("中板", 0.5) * 0.8
            adjusted["快板"] = adjusted.get("快板", 0.2) * 3.0
            names = list(adjusted.keys())
            weights = [adjusted[n] for n in names]
            return weighted_choice(names, weights)

    # Default: use profile preference
    names = list(tempo_pref.keys())
    weights = [tempo_pref[n] for n in names]
    return weighted_choice(names, weights)


def _pick_instruments(genre: str, n: int) -> list[str]:
    """Pick n instruments from the genre's instrument pool."""
    pool = GENRE_INSTRUMENTS.get(genre, DEFAULT_INSTRUMENTS)
    n = min(n, len(pool))
    return random.sample(pool, n)


def _find_scenes(theme: str) -> list[str]:
    """Find scene tags matching the theme."""
    # Direct match
    if theme in THEME_SCENES:
        return THEME_SCENES[theme]
    # Partial match
    for key, scenes in THEME_SCENES.items():
        if key in theme or theme in key:
            return scenes
    return []


def _lyrics_theme_description(theme: str, mood1: str, mood2: str) -> str:
    """Generate a natural-language description for the lyrics prompt based on theme."""
    descriptions: dict[str, list[str]] = {
        "深夜放松": [
            "quiet moments alone at midnight, reflecting on the day",
            "the stillness of late night and finding peace in solitude",
            "drifting thoughts under city lights at 3am",
        ],
        "深夜": [
            "the beauty and loneliness of the late night hours",
            "midnight confessions and unspoken feelings",
        ],
        "放松": [
            "letting go of stress and finding inner calm",
            "a peaceful afternoon with nothing to worry about",
        ],
        "运动": [
            "pushing through limits and chasing your best self",
            "the rush of adrenaline and the joy of movement",
        ],
        "workout": [
            "pushing past your limits and feeling unstoppable",
            "the energy and drive of a powerful workout",
        ],
        "通勤路上": [
            "the daily journey through the city and daydreams along the way",
            "watching the sunrise from a bus window while the city wakes up",
        ],
        "雨天": [
            "the gentle rhythm of rain and memories it brings",
            "watching raindrops on the window while lost in thought",
        ],
        "浪漫": [
            "falling in love and the butterflies that come with it",
            "a tender moment between two people under the moonlight",
        ],
        "思念": [
            "missing someone far away and the ache of distance",
            "memories of someone who is no longer here",
        ],
        "怀旧": [
            "looking back at cherished memories from years past",
            "the bittersweet feeling of revisiting old places",
        ],
        "派对": [
            "the electric energy of a night out with friends",
            "dancing under neon lights without a care in the world",
        ],
        "夏天": [
            "endless summer days and the freedom of youth",
            "a sunset at the beach with friends and music",
        ],
        "冬天": [
            "the warmth of a fireplace on a cold winter night",
            "snowfall and the quiet beauty of winter",
        ],
        "旅行": [
            "discovering new places and the excitement of the unknown",
            "a road trip with the windows down and music playing",
        ],
        "咖啡": [
            "a lazy afternoon in a cozy cafe, watching people go by",
            "the aroma of coffee and quiet conversations",
        ],
        "清晨": [
            "the first light of dawn and a fresh start",
            "waking up to a new day full of possibilities",
        ],
        "冥想": [
            "finding stillness within and connecting with the present moment",
            "breathing deeply and letting all thoughts dissolve",
        ],
    }

    # Direct match
    if theme in descriptions:
        return random.choice(descriptions[theme])

    # Partial match
    for key, descs in descriptions.items():
        if key in theme or theme in key:
            return random.choice(descs)

    # Fallback: generate from moods
    return f"feelings of {mood1} and {mood2}, and the stories they tell"


def _random_bpm(tempo: str) -> int:
    """Convert a Chinese tempo label to a random BPM within range."""
    lo, hi = TEMPO_BPM.get(tempo, (85, 110))
    return random.randint(lo, hi)


def _translate(word: str, table: dict[str, str]) -> str:
    """Translate a Chinese term to English using a mapping table, fallback to original."""
    return table.get(word, word)


def _build_narrative_prompt(
    genre: str, sub_genre: str, mood1: str, mood2: str,
    vocal_desc: str, instruments: list[str], tempo: str,
    scene: str, is_instrumental: bool, theme: str,
) -> str:
    """Build an English narrative-style prompt following prompt_guide.md patterns."""
    genre_en = _translate(genre, GENRE_EN)
    mood1_en = _translate(mood1, MOOD_EN)
    mood2_en = _translate(mood2, MOOD_EN)
    bpm = _random_bpm(tempo)
    instruments_en = [_translate(inst, INSTRUMENT_EN) for inst in instruments]

    # a/an article
    article = "An" if mood1_en[0].lower() in "aeiou" else "A"

    # Scene narrative from the theme
    scene_desc = _lyrics_theme_description(theme, mood1, mood2)

    if is_instrumental:
        inst_list = _format_instrument_list(instruments_en)
        prompt = (
            f"{article} {mood1_en} and {mood2_en} {bpm} BPM {genre_en} {sub_genre} instrumental piece, "
            f"evoking {scene_desc}, "
            f"featuring {inst_list}."
        )
    else:
        vocal_en = VOCAL_EN.get(vocal_desc, "smooth emotional vocals")
        inst_list = _format_instrument_list(instruments_en)
        prompt = (
            f"{article} {mood1_en} yet {mood2_en} {bpm} BPM {genre_en} {sub_genre} song, "
            f"featuring {vocal_en}, "
            f"about {scene_desc}, "
            f"with {inst_list}."
        )

    return prompt


def _format_instrument_list(instruments: list[str]) -> str:
    """Format a list of instruments with Oxford comma: 'a, b, and c'."""
    if len(instruments) == 0:
        return "piano"
    if len(instruments) == 1:
        return instruments[0]
    if len(instruments) == 2:
        return f"{instruments[0]} and {instruments[1]}"
    return f"{', '.join(instruments[:-1])}, and {instruments[-1]}"


# ---------------------------------------------------------------------------
# Human-readable summary to stderr
# ---------------------------------------------------------------------------
def print_summary(playlist: dict, file=sys.stderr) -> None:
    theme = playlist["theme"]
    count = playlist["song_count"]
    print(msg("playlist_plan_header", LANG, theme=theme, count=count), file=file)

    for song in playlist["songs"]:
        idx = song["index"]
        desc = song["description"]

        # Extract moods from prompt (3rd and 4th comma-separated items)
        prompt_parts = [p.strip() for p in song["prompt"].split(",")]
        mood_str = ""
        if len(prompt_parts) >= 4:
            mood_str = f"{prompt_parts[2]}, {prompt_parts[3]}"

        if song["instrumental"]:
            vocal_label = msg("label_instrumental", LANG)
        else:
            lang = song["language"]
            # Determine gender from prompt
            if any(m in song["prompt"] for m in ["\u7537\u58f0"]):
                gender = msg("label_male", LANG)
            elif any(f in song["prompt"] for f in ["\u5973\u58f0"]):
                gender = msg("label_female", LANG)
            else:
                gender = ""
            vocal_label = f"{lang}/{gender}" if gender else lang

        print(f"  {idx}. {desc} \u2014 {mood_str} [{vocal_label}]", file=file)

    print(file=file)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a MiniMax-compatible playlist plan from a taste profile."
    )
    parser.add_argument(
        "--profile", required=True,
        help="Path to taste_profile.json"
    )
    parser.add_argument(
        "--theme", default=None,
        help="Theme/mood for the playlist (e.g. '\u6df1\u591c\u653e\u677e', 'workout', '\u901a\u52e4\u8def\u4e0a')"
    )
    parser.add_argument(
        "--count", type=int, default=5,
        help="Number of songs (3-7, default 5)"
    )
    parser.add_argument(
        "--output", default=None,
        help="Output file path (default: stdout)"
    )
    parser.add_argument(
        "--lang", default="zh", choices=["zh", "en"],
        help="UI language and lyrics language (default: zh)"
    )

    args = parser.parse_args()

    global LANG
    LANG = args.lang

    # Validate count
    original_count = args.count
    count = max(3, min(7, args.count))
    if count != original_count:
        print(f"⚠️  Count adjusted from {original_count} to {count} (range: 3-7)", file=sys.stderr)

    # Use system entropy for randomness (no fixed seed — regeneration produces new results)
    random.seed()

    # Load profile
    profile = load_profile(args.profile)

    # Generate playlist
    playlist = generate_playlist(profile, args.theme, count)

    # Print summary to stderr
    print_summary(playlist)

    # Output JSON
    output_json = json.dumps(playlist, ensure_ascii=False, indent=2)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
            f.write("\n")
        print(f"Playlist plan written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
