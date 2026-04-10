#!/usr/bin/env python3
"""
build_taste_profile.py

Merge data from Apple Music scan, QQ Music scan, and generated music history
to build a user taste profile. All inputs are optional.

Usage:
    python3 build_taste_profile.py \
      --apple-music /tmp/apple_music_data.json \
      --qq-music /tmp/qq_music_data.json \
      --gen-history ~/Music/minimax-gen/ \
      --artist-map ~/.claude/skills/minimax-music-playlist/data/artist_genre_map.json \
      --output ~/.claude/skills/minimax-music-playlist/data/taste_profile.json
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.expanduser("~/.claude/skills/shared"))
from i18n import msg
from api_base import get_api_base

LANG = "zh"

# ---------------------------------------------------------------------------
# Prompt guide vocabulary (embedded from prompt_guide.md)
# ---------------------------------------------------------------------------

PROMPT_GENRES = {
    # Pop
    "流行", "pop", "电子流行", "electropop", "梦幻流行", "dream pop",
    "独立流行", "indie pop", "华语流行", "c-pop", "k-pop", "j-pop",
    "synth-pop", "city pop",
    # Rock
    "摇滚", "rock", "独立摇滚", "indie rock", "后摇", "post-rock",
    "民谣摇滚", "folk rock", "朋克", "punk", "金属", "metal",
    "车库摇滚", "garage rock", "shoegaze",
    # Folk
    "民谣", "folk", "独立民谣", "indie folk", "中国风", "chinese traditional",
    "古风", "世界音乐", "world music",
    # Electronic
    "电子", "electronic", "lo-fi", "lo-fi hip-hop", "ambient", "house",
    "techno", "drum and bass", "dnb", "chillwave", "vaporwave", "trap",
    "future bass", "edm",
    # Hip-Hop & R&B
    "说唱", "rap", "hip-hop", "r&b", "neo-soul", "boom bap",
    # Jazz & Blues
    "爵士", "jazz", "布鲁斯", "blues", "bossa nova", "smooth jazz",
    "jazz fusion",
    # Classical & Cinematic
    "古典", "classical", "交响", "orchestral", "电影配乐", "cinematic",
    "film score", "史诗", "epic", "钢琴曲", "piano solo", "新古典",
    "neoclassical",
    # Other
    "乡村", "country", "雷鬼", "reggae", "拉丁", "latin", "funk",
    "gospel", "二次元", "anime style", "游戏音乐", "game music",
    # Combined
    "舞曲", "粤语流行", "中国传统", "民族声乐",
}

PROMPT_MOODS = {
    # Positive
    "欢快", "温暖", "甜蜜", "阳光", "活力", "浪漫", "幸福", "治愈", "温柔",
    "感恩", "hopeful", "uplifting", "cheerful", "warm", "sweet", "bright",
    "energetic", "romantic",
    # Negative / deep
    "忧郁", "悲伤", "孤独", "思念", "心碎", "迷茫", "苦涩", "压抑",
    "melancholic", "sad", "lonely", "nostalgic", "bittersweet", "gloomy", "dark",
    # Neutral / atmospheric
    "内省", "平静", "梦幻", "神秘", "空灵", "冥想", "深邃", "淡然",
    "reflective", "calm", "dreamy", "mysterious", "ethereal", "meditative",
    "serene",
    # High energy
    "燃", "热血", "力量", "战斗", "狂野", "爆发", "解放",
    "powerful", "fierce", "wild", "explosive", "liberating", "intense",
    # Extra
    "律动感", "幽默",
}

PROMPT_INSTRUMENTS = {
    # Strings
    "原声吉他", "电吉他", "失真吉他", "古典吉他", "尤克里里", "贝斯",
    "小提琴", "大提琴", "二胡", "琵琶", "古筝", "竖琴",
    # Keys
    "钢琴", "电钢琴", "风琴", "手风琴", "合成器", "synth pad", "复古键盘",
    # Percussion
    "鼓组", "架子鼓", "电子鼓", "打击乐", "手鼓", "cajon", "808 bass",
    # Wind
    "萨克斯", "长笛", "小号", "口琴", "竹笛", "箫", "唢呐",
    # Electronic
    "synth lead", "arpeggiator", "采样器", "glitch",
    # Extra
    "手拍",
}

PROMPT_TEMPOS = {
    "极慢板", "very slow", "adagio",
    "慢板", "slow", "ballad tempo",
    "中板", "moderate", "mid-tempo",
    "稍快", "slightly upbeat",
    "快板", "fast", "upbeat",
    "极快", "very fast", "high energy",
}

PROMPT_VOCALS = {
    "男声", "女声", "中性声", "合唱",
    "male vocal", "female vocal", "androgynous vocal", "choir",
}

ALL_PROMPT_VOCAB = PROMPT_GENRES | PROMPT_MOODS | PROMPT_INSTRUMENTS | PROMPT_TEMPOS | PROMPT_VOCALS

# ---------------------------------------------------------------------------
# QQ Music playlist name -> genre boosters
# ---------------------------------------------------------------------------
PLAYLIST_BOOSTERS = {
    "hy":    [("华语流行", 2.0)],
    "hrnb":  [("R&B", 2.0)],
    "kpop":  [("K-pop", 2.0)],
    "ktv":   [("华语流行", 1.5), ("ballad", 1.5)],
    "jr":    [("爵士", 1.5), ("smooth jazz", 1.5)],
    "aespa": [("K-pop", 1.5), ("电子流行", 1.5)],
}

# ---------------------------------------------------------------------------
# Genre -> inferred tempo
# ---------------------------------------------------------------------------
GENRE_TEMPO_MAP = {
    "R&B":        ["慢板", "中板"],
    "neo-soul":   ["慢板", "中板"],
    "ballad":     ["慢板"],
    "K-pop":      ["稍快", "快板"],
    "电子流行":   ["稍快", "快板"],
    "民谣":       ["慢板"],
    "独立民谣":   ["慢板"],
    "folk":       ["慢板"],
    "indie folk":  ["慢板"],
    "华语流行":   ["中板"],
    "流行":       ["中板"],
    "摇滚":       ["稍快", "快板"],
    "独立摇滚":   ["稍快"],
    "indie rock":  ["稍快"],
    "hip-hop":    ["中板", "稍快"],
    "说唱":       ["中板", "稍快"],
    "爵士":       ["慢板", "中板"],
    "jazz":       ["慢板", "中板"],
    "smooth jazz": ["慢板"],
    "bossa nova": ["慢板", "中板"],
    "电子":       ["稍快", "快板"],
    "EDM":        ["快板"],
    "house":      ["稍快", "快板"],
    "techno":     ["快板"],
    "lo-fi":      ["慢板", "中板"],
    "古风":       ["慢板", "中板"],
    "中国风":     ["慢板", "中板"],
    "粤语流行":   ["中板"],
    "梦幻流行":   ["慢板", "中板"],
    "city pop":   ["中板", "稍快"],
    "J-pop":      ["中板", "稍快"],
    "funk":       ["中板", "稍快"],
    "舞曲":       ["稍快", "快板"],
    "古典":       ["慢板", "中板"],
    "交响":       ["中板"],
    "史诗":       ["稍快", "快板"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_cjk(text: str) -> bool:
    """Return True if text contains any CJK Unified Ideograph."""
    return bool(re.search(r"[\u4e00-\u9fff\u3400-\u4dbf]", text))


def _strip_paren_suffix(name: str) -> str:
    """Strip parenthetical suffixes like '(에스파)' or '(태연)' for matching."""
    return re.sub(r"\s*[\(（].*?[\)）]\s*$", "", name).strip()


def _normalize_dict(d: dict) -> dict:
    """Normalize dict values to sum to 1.0."""
    total = sum(d.values())
    if total <= 0:
        return d
    return {k: round(v / total, 4) for k, v in d.items()}


def _top_n_pct(d: dict, n: int) -> list:
    """Return top n items as 'key XX%' strings."""
    items = sorted(d.items(), key=lambda x: -x[1])[:n]
    return [f"{k} {int(v * 100)}%" for k, v in items]


def _load_json(path: str) -> dict | None:
    """Load a JSON file, return None on any error."""
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


# MusicBrainz genre -> our prompt tag mapping
_MB_GENRE_MAP = {
    "pop": "流行", "mandopop": "华语流行", "c-pop": "华语流行",
    "cantopop": "粤语流行", "k-pop": "K-pop", "j-pop": "J-pop",
    "rock": "摇滚", "indie rock": "独立摇滚", "post-rock": "后摇",
    "punk": "朋克", "metal": "金属", "folk rock": "民谣摇滚",
    "folk": "民谣", "indie folk": "独立民谣",
    "electronic": "电子", "electropop": "电子流行", "synth-pop": "synth-pop",
    "edm": "EDM", "house": "house", "techno": "techno", "ambient": "ambient",
    "hip hop": "hip-hop", "rap": "说唱", "trap": "trap",
    "r&b": "R&B", "soul": "neo-soul", "neo-soul": "neo-soul",
    "jazz": "爵士", "smooth jazz": "smooth jazz", "bossa nova": "bossa nova",
    "blues": "布鲁斯",
    "classical": "古典", "orchestral": "交响",
    "country": "乡村", "reggae": "雷鬼", "latin": "拉丁", "funk": "funk",
    "city pop": "city pop", "shoegaze": "shoegaze",
    "dream pop": "梦幻流行", "indie pop": "独立流行",
    "singer-songwriter": "独立民谣",
}

_MB_GENRE_TO_MOOD = {
    "pop": ["温暖", "活力"], "rock": ["力量", "活力"], "folk": ["内省", "温暖"],
    "electronic": ["活力"], "r&b": ["浪漫", "温暖"], "soul": ["温暖", "内省"],
    "jazz": ["平静", "温暖"], "blues": ["忧郁"], "hip hop": ["活力"],
    "classical": ["平静"], "metal": ["力量", "燃"], "punk": ["燃", "力量"],
    "ambient": ["平静", "梦幻"],
}

_MB_LANG_MAP = {
    "zho": "zh", "cmn": "zh", "yue": "zh",
    "kor": "ko", "eng": "en", "jpn": "ja",
    "spa": "es", "fra": "fr", "por": "pt",
}


def _query_musicbrainz(name: str) -> dict | None:
    """Query MusicBrainz API for artist genre info. Returns None on failure."""
    import urllib.request
    import urllib.parse
    import urllib.error
    import time

    stripped = _strip_paren_suffix(name)
    query = urllib.parse.quote(stripped)
    url = f"https://musicbrainz.org/ws/2/artist/?query={query}&fmt=json&limit=3"
    headers = {"User-Agent": "MiniMaxMusicPlaylist/1.0 (claude-code-skill)"}
    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None

    artists = data.get("artists", [])
    if not artists:
        return None

    # Pick best match
    artist = artists[0]
    mbid = artist.get("id", "")
    if not mbid:
        return None

    # Fetch genres with a second request
    time.sleep(1.1)  # MusicBrainz rate limit: 1 req/sec
    detail_url = f"https://musicbrainz.org/ws/2/artist/{mbid}?inc=genres&fmt=json"
    req2 = urllib.request.Request(detail_url, headers=headers)

    try:
        with urllib.request.urlopen(req2, timeout=10) as resp:
            detail = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None

    # Extract genres
    mb_genres = [g.get("name", "").lower() for g in detail.get("genres", []) if g.get("count", 0) > 0]

    # Map to our prompt tags
    mapped_genres = []
    mapped_moods = set()
    for g in mb_genres:
        if g in _MB_GENRE_MAP:
            mapped_genres.append(_MB_GENRE_MAP[g])
        # Also check partial matches
        for mb_key, prompt_tag in _MB_GENRE_MAP.items():
            if mb_key in g or g in mb_key:
                if prompt_tag not in mapped_genres:
                    mapped_genres.append(prompt_tag)
        for mb_key, moods in _MB_GENRE_TO_MOOD.items():
            if mb_key in g:
                mapped_moods.update(moods)

    if not mapped_genres:
        # Fallback: infer from area/type
        area = artist.get("area", {}).get("name", "")
        if area in ("China", "Taiwan", "Hong Kong"):
            mapped_genres = ["华语流行"]
        elif area in ("South Korea", "Korea"):
            mapped_genres = ["K-pop"]
        elif area in ("Japan",):
            mapped_genres = ["J-pop"]
        else:
            mapped_genres = ["流行"]

    if not mapped_moods:
        mapped_moods = {"温暖"}

    # Infer language
    area = artist.get("area", {}).get("name", "")
    lang = "en"  # default
    if area in ("China", "Taiwan"):
        lang = "zh"
    elif area in ("Hong Kong",):
        lang = "zh"
    elif area in ("South Korea", "Korea"):
        lang = "ko"
    elif area in ("Japan",):
        lang = "ja"
    elif _has_cjk(name):
        lang = "zh"

    # Infer vocal from gender
    gender = artist.get("gender", "").lower()
    vocal = "male" if gender == "male" else ("female" if gender == "female" else "unknown")

    return {
        "genres": mapped_genres[:3],
        "mood": list(mapped_moods)[:3],
        "vocal": vocal,
        "lang": lang,
    }


def _get_api_key() -> str | None:
    """Get MiniMax API key from env or file."""
    key = os.environ.get("MINIMAX_API_KEY") or os.environ.get("MINIMAX_MUSIC_API_KEY")
    if not key:
        fpath = os.path.expanduser("~/.minimax_api_key")
        if os.path.isfile(fpath):
            with open(fpath) as f:
                key = f.read().strip()
    return key or None


def _query_llm_genre(name: str) -> dict | None:
    """Use MiniMax Chat API to look up artist genre when MusicBrainz fails."""
    import urllib.request
    import urllib.error

    api_key = _get_api_key()
    if not api_key:
        return None

    prompt = (
        f"You are a music knowledge assistant. Given an artist/musician name, "
        f"return ONLY a JSON object with these fields:\n"
        f"- genres: array of 1-3 genre tags from this list: "
        f"华语流行, 流行, R&B, K-pop, J-pop, 独立流行, neo-soul, 摇滚, 中国风, "
        f"古典, 爵士, 民谣, 电子流行, 粤语流行, 嘻哈, 蓝调, 拉丁, 放克, 乡村, "
        f"金属, 雷鬼, 灵魂乐, Lo-fi, 朋克, 独立民谣, 独立摇滚, city pop, ambient, "
        f"bossa nova, smooth jazz, hip-hop, funk\n"
        f"- mood: array of 1-3 mood tags from: 温暖, 忧郁, 平静, 浪漫, 内省, 活力, 力量, 治愈, 梦幻\n"
        f"- vocal: one of 'male', 'female', or 'unknown'\n"
        f"- lang: language code: zh, en, ja, ko, es, fr, pt\n\n"
        f"If you don't know this artist at all, return exactly: null\n\n"
        f"Artist: {name}\n"
        f"JSON:"
    )

    body = json.dumps({
        "model": "MiniMax-Text-01",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 200,
    }).encode("utf-8")

    api_base = get_api_base(api_key)

    req = urllib.request.Request(
        f"{api_base}/v1/text/chatcompletion_v2",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None

    # Extract text from response
    try:
        text = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        return None

    if text == "null" or text.lower() == "null":
        return None

    # Parse JSON from response (handle markdown code blocks)
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        return None

    if not isinstance(result, dict) or "genres" not in result:
        return None

    # Validate structure
    genres = result.get("genres", [])
    if not genres or not isinstance(genres, list):
        return None

    return {
        "genres": genres[:3],
        "mood": result.get("mood", ["温暖"])[:3],
        "vocal": result.get("vocal", "unknown"),
        "lang": result.get("lang", "en"),
    }


def _lookup_artist(name: str, artist_map: dict, *, online: bool = True, map_path: str = "") -> dict:
    """Look up artist in the map. Try exact, stripped, reverse, then MusicBrainz API, then defaults."""
    if name in artist_map:
        return artist_map[name]
    stripped = _strip_paren_suffix(name)
    if stripped != name and stripped in artist_map:
        return artist_map[stripped]
    # Also try matching map entries whose stripped form matches
    for map_name, info in artist_map.items():
        if map_name.startswith("_"):
            continue
        if _strip_paren_suffix(map_name) == name or _strip_paren_suffix(map_name) == stripped:
            return info

    # Online lookup via MusicBrainz
    if online and name.strip():
        result = _query_musicbrainz(name)
        if result:
            print(msg("querying_musicbrainz", LANG, name=name), file=sys.stderr, end="", flush=True)
            print(f" → {', '.join(result['genres'])}", file=sys.stderr)
            # Cache to artist_map and persist
            artist_map[name] = result
            if map_path:
                try:
                    with open(map_path, "w", encoding="utf-8") as f:
                        json.dump(artist_map, f, ensure_ascii=False, indent=2)
                except IOError:
                    pass
            return result
        else:
            # Fallback: query LLM for genre info
            llm_result = _query_llm_genre(name)
            if llm_result:
                llm_label = "🤖 LLM查询" if LANG == "zh" else "🤖 LLM lookup"
                print(f"   {llm_label}: {name} → {', '.join(llm_result['genres'])}", file=sys.stderr)
                artist_map[name] = llm_result
                if map_path:
                    try:
                        with open(map_path, "w", encoding="utf-8") as f:
                            json.dump(artist_map, f, ensure_ascii=False, indent=2)
                    except IOError:
                        pass
                return llm_result
            else:
                # Both MB and LLM failed — skip silently
                return None

    # Not in map and online lookup disabled or skipped
    return None


# ---------------------------------------------------------------------------
# Accumulators
# ---------------------------------------------------------------------------

class TasteAccumulator:
    """Accumulates weighted scores for genres, languages, moods, vocals, tempos, artists."""

    def __init__(self):
        self.genres = defaultdict(float)
        self.languages = defaultdict(float)
        self.moods = defaultdict(float)
        self.vocals = defaultdict(float)
        self.tempos = defaultdict(float)
        self.artists = defaultdict(float)

    def add_artist_info(self, info: dict, weight: float):
        """Add weighted contribution from an artist_genre_map entry."""
        for g in info.get("genres", []):
            self.genres[g] += weight
        for m in info.get("mood", []):
            self.moods[m] += weight
        lang = info.get("lang", "")
        if lang:
            lang_label = _lang_code_to_label(lang)
            self.languages[lang_label] += weight
        vocal = info.get("vocal", "unknown")
        if vocal and vocal != "unknown":
            self.vocals[vocal] += weight

    def add_genre(self, genre: str, weight: float):
        self.genres[genre] += weight

    def add_mood(self, mood: str, weight: float):
        self.moods[mood] += weight

    def add_tempo(self, tempo: str, weight: float):
        self.tempos[tempo] += weight

    def infer_tempo_from_genres(self):
        """Infer tempo preferences from accumulated genres."""
        for genre, genre_weight in list(self.genres.items()):
            tempos = GENRE_TEMPO_MAP.get(genre, [])
            if tempos:
                per_tempo = genre_weight / len(tempos)
                for t in tempos:
                    self.tempos[t] += per_tempo


def _lang_code_to_label(code: str) -> str:
    mapping = {
        "zh": "中文",
        "ko": "韩语",
        "en": "英语",
        "ja": "日语",
        "es": "西班牙语",
        "fr": "法语",
        "pt": "葡萄牙语",
    }
    return mapping.get(code, code)


# ---------------------------------------------------------------------------
# Source processors
# ---------------------------------------------------------------------------

def process_qq_music(data: dict, artist_map: dict, acc: TasteAccumulator, *, map_path: str = "") -> dict:
    """Process QQ Music scan data. Returns source info dict."""
    tracks = data.get("tracks", [])
    playlists = data.get("playlists", [])

    # Count songs per artist
    artist_counts = defaultdict(int)
    for track in tracks:
        artist = (track.get("singer") or track.get("artist") or "").strip()
        if artist:
            artist_counts[artist] += 1

    # Process each artist
    for artist, count in artist_counts.items():
        weight = count * 1.0
        info = _lookup_artist(artist, artist_map, map_path=map_path)
        if info is None:
            continue
        acc.add_artist_info(info, weight)
        acc.artists[artist] += weight

    # Playlist name boosters
    playlist_names = []
    if isinstance(playlists, list):
        for pl in playlists:
            if isinstance(pl, dict):
                playlist_names.append(pl.get("name", "").lower().strip())
            elif isinstance(pl, str):
                playlist_names.append(pl.lower().strip())

    for pname in playlist_names:
        for key, boosts in PLAYLIST_BOOSTERS.items():
            if key in pname:
                for genre, boost_weight in boosts:
                    acc.add_genre(genre, boost_weight)

    scanned_at = data.get("scanned_at", datetime.now().isoformat())
    return {"track_count": len(tracks), "scanned_at": scanned_at}


def process_apple_music(data: dict, artist_map: dict, acc: TasteAccumulator, *, map_path: str = "") -> dict:
    """Process Apple Music scan data. Returns source info dict."""
    tracks = data.get("tracks", [])

    # Auto-detect low-quality source
    recognized_count = 0
    for track in tracks:
        artist = (track.get("singer") or track.get("artist") or "").strip()
        if artist and artist in artist_map:
            recognized_count += 1
        elif artist and _strip_paren_suffix(artist) in artist_map:
            recognized_count += 1
        elif artist:
            # Check reverse match
            for map_name in artist_map:
                if not map_name.startswith("_") and _strip_paren_suffix(map_name) == artist:
                    recognized_count += 1
                    break

    low_quality = recognized_count < 5
    source_multiplier = 0.3 if low_quality else 1.0

    # Process tracks
    for track in tracks:
        artist = (track.get("singer") or track.get("artist") or "").strip()
        if not artist:
            continue
        played_count = track.get("played_count", 0)
        if isinstance(played_count, str):
            try:
                played_count = int(played_count)
            except ValueError:
                played_count = 0
        base_weight = max(played_count * 0.5, 0.5)
        weight = base_weight * source_multiplier
        info = _lookup_artist(artist, artist_map, map_path=map_path)
        if info is None:
            continue
        acc.add_artist_info(info, weight)
        acc.artists[artist] += weight

    scanned_at = data.get("scanned_at", datetime.now().isoformat())
    return {"track_count": len(tracks), "scanned_at": scanned_at}


def process_gen_history(gen_dir: str, acc: TasteAccumulator) -> dict:
    """Process generated music history JSON files. Returns source info dict."""
    gen_dir = os.path.expanduser(gen_dir)
    if not os.path.isdir(gen_dir):
        return None

    count = 0
    vocab_lower = {v.lower(): v for v in ALL_PROMPT_VOCAB}

    for fname in os.listdir(gen_dir):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(gen_dir, fname)
        data = _load_json(fpath)
        if data is None or not isinstance(data, dict):
            continue
        prompt_str = data.get("prompt", "")
        if not prompt_str:
            continue

        count += 1
        weight = 0.3  # lower weight for aspirational taste

        # Split prompt by comma, strip whitespace
        tokens = [t.strip().lower() for t in prompt_str.split(",") if t.strip()]

        for token in tokens:
            # Check genres
            if token in vocab_lower:
                original = vocab_lower[token]
                if original in PROMPT_GENRES or token in PROMPT_GENRES:
                    acc.add_genre(original, weight)
                if original in PROMPT_MOODS or token in PROMPT_MOODS:
                    acc.add_mood(original, weight)
                if original in PROMPT_TEMPOS or token in PROMPT_TEMPOS:
                    acc.add_tempo(original, weight)
                # Vocal hints
                if token in {"男声", "male vocal"}:
                    acc.vocals["male"] += weight
                elif token in {"女声", "female vocal"}:
                    acc.vocals["female"] += weight
                elif token in {"instrumental"}:
                    acc.vocals["instrumental"] += weight
            else:
                # Check partial matches for compound tokens like "清澈女声"
                if "女声" in token:
                    acc.vocals["female"] += weight
                elif "男声" in token:
                    acc.vocals["male"] += weight

        # Try to detect language from prompt content
        if _has_cjk(prompt_str):
            acc.languages["中文"] += weight

    if count == 0:
        return None
    return {"track_count": count, "scanned_at": datetime.now().isoformat()}


def process_spotify(data: dict, artist_map: dict, acc: TasteAccumulator, *, map_path: str = "") -> dict | None:
    """Process Spotify scan data. Returns source info dict."""
    if not data.get("installed"):
        return None

    tracks = data.get("tracks", [])
    artists_list = data.get("artists", [])

    # Process tracks (each has name + artist string)
    artist_counts = defaultdict(int)
    for track in tracks:
        artist_str = (track.get("singer") or track.get("artist") or "").strip()
        # Spotify uses comma-separated artists
        for artist in (a.strip() for a in artist_str.split(",") if a.strip()):
            artist_counts[artist] += 1

    # Also count standalone artist list
    for artist in artists_list:
        if artist and artist not in artist_counts:
            artist_counts[artist] = 1

    for artist, count in artist_counts.items():
        weight = count * 0.8  # Slightly lower weight — less reliable than full library
        info = _lookup_artist(artist, artist_map, map_path=map_path)
        if info is None:
            continue
        acc.add_artist_info(info, weight)
        acc.artists[artist] += weight

    if not tracks and not artists_list:
        return None

    scanned_at = data.get("scanned_at", datetime.now().isoformat())
    return {"track_count": len(tracks), "scanned_at": scanned_at}


def process_netease(data: dict, artist_map: dict, acc: TasteAccumulator, *, map_path: str = "") -> dict | None:
    """Process NetEase Cloud Music scan data. Returns source info dict."""
    if not data.get("installed"):
        return None

    tracks = data.get("tracks", [])
    playlists = data.get("playlists", [])
    inferred_genres = data.get("inferred_genres", {})
    inferred_moods = data.get("inferred_moods", {})

    # Process tracks
    artist_counts = defaultdict(int)
    for track in tracks:
        artist_str = (track.get("singer") or track.get("artist") or "").strip()
        # NetEase uses " / " separated artists
        for artist in (a.strip() for a in artist_str.split("/") if a.strip()):
            artist_counts[artist] += 1

    for artist, count in artist_counts.items():
        weight = count * 0.6  # Lower weight — mostly recommendations, not user library
        info = _lookup_artist(artist, artist_map, map_path=map_path)
        if info is None:
            continue
        acc.add_artist_info(info, weight)
        acc.artists[artist] += weight

    # Add inferred genres from playlist names (weak signal)
    for genre, count in inferred_genres.items():
        acc.add_genre(genre, count * 0.5)

    # Add inferred moods from playlist names
    for mood, count in inferred_moods.items():
        acc.add_mood(mood, count * 0.3)

    if not tracks and not inferred_genres:
        return None

    scanned_at = data.get("scanned_at", datetime.now().isoformat())
    return {"track_count": len(tracks), "scanned_at": scanned_at}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_profile(args) -> dict:
    """Build the taste profile from all available sources."""
    # Load artist map
    artist_map_path = os.path.expanduser(args.artist_map)
    artist_map = _load_json(artist_map_path)
    if artist_map is None:
        artist_map = {}
        print("Warning: artist_genre_map.json not found, using empty map", file=sys.stderr)

    acc = TasteAccumulator()
    sources = {}

    # QQ Music
    if args.qq_music:
        qq_data = _load_json(args.qq_music)
        if qq_data is not None:
            info = process_qq_music(qq_data, artist_map, acc, map_path=artist_map_path)
            sources["qq_music"] = info
        else:
            print(f"Warning: could not load QQ Music data from {args.qq_music}", file=sys.stderr)

    # Apple Music
    if args.apple_music:
        am_data = _load_json(args.apple_music)
        if am_data is not None:
            info = process_apple_music(am_data, artist_map, acc, map_path=artist_map_path)
            sources["apple_music"] = info
        else:
            print(f"Warning: could not load Apple Music data from {args.apple_music}", file=sys.stderr)

    # Spotify
    if args.spotify:
        sp_data = _load_json(args.spotify)
        if sp_data is not None:
            info = process_spotify(sp_data, artist_map, acc, map_path=artist_map_path)
            if info:
                sources["spotify"] = info
        else:
            print(f"Warning: could not load Spotify data from {args.spotify}", file=sys.stderr)

    # NetEase Cloud Music
    if args.netease:
        ne_data = _load_json(args.netease)
        if ne_data is not None:
            info = process_netease(ne_data, artist_map, acc, map_path=artist_map_path)
            if info:
                sources["netease"] = info
        else:
            print(f"Warning: could not load NetEase data from {args.netease}", file=sys.stderr)

    # Generated history
    if args.gen_history:
        info = process_gen_history(args.gen_history, acc)
        if info is not None:
            sources["generated"] = info

    # Infer tempos from genres
    acc.infer_tempo_from_genres()

    # Normalize all dimensions
    genres_norm = _normalize_dict(dict(acc.genres))
    languages_norm = _normalize_dict(dict(acc.languages))
    moods_norm = _normalize_dict(dict(acc.moods))
    tempos_norm = _normalize_dict(dict(acc.tempos))
    vocals_norm = _normalize_dict(dict(acc.vocals))

    # Top artists
    sorted_artists = sorted(acc.artists.items(), key=lambda x: -x[1])
    top_artists = [name for name, _ in sorted_artists[:10]]

    # Build profile
    profile = {
        "version": 1,
        "last_updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "sources": sources,
        "genres": dict(sorted(genres_norm.items(), key=lambda x: -x[1])),
        "languages": dict(sorted(languages_norm.items(), key=lambda x: -x[1])),
        "mood_tendencies": dict(sorted(moods_norm.items(), key=lambda x: -x[1])),
        "tempo_preference": dict(sorted(tempos_norm.items(), key=lambda x: -x[1])),
        "vocal_preference": dict(sorted(vocals_norm.items(), key=lambda x: -x[1])),
        "top_artists": top_artists,
        "feedback": {
            "liked_prompts": [],
            "disliked_prompts": [],
            "liked_genres": [],
            "disliked_genres": [],
        },
    }

    return profile


def print_summary(profile: dict):
    """Print human-readable summary to stderr."""
    sources = profile.get("sources", {})
    parts = []
    if "qq_music" in sources:
        cnt = sources['qq_music']['track_count']
        parts.append(f"{msg('source_label_qq', LANG)} {cnt}{msg('tracks_unit', LANG)}")
    if "apple_music" in sources:
        cnt = sources['apple_music']['track_count']
        parts.append(f"{msg('source_label_apple', LANG)} {cnt}{msg('tracks_unit', LANG)}")
    if "spotify" in sources:
        cnt = sources['spotify']['track_count']
        parts.append(f"{msg('source_label_spotify', LANG)} {cnt}{msg('tracks_unit', LANG)}")
    if "netease" in sources:
        cnt = sources['netease']['track_count']
        parts.append(f"{msg('source_label_netease', LANG)} {cnt}{msg('tracks_unit', LANG)}")
    if "generated" in sources:
        cnt = sources['generated']['track_count']
        parts.append(f"{msg('source_label_generated', LANG)} {cnt}{msg('tracks_unit', LANG)}")
    no_source = "无数据源" if LANG == "zh" else "No data sources"
    source_str = " | ".join(parts) if parts else no_source

    genres = profile.get("genres", {})
    langs = profile.get("languages", {})
    moods = profile.get("mood_tendencies", {})
    vocals = profile.get("vocal_preference", {})

    none_label = "无" if LANG == "zh" else "None"
    genre_str = " | ".join(_top_n_pct(genres, 3)) or none_label
    lang_str = " | ".join(_top_n_pct(langs, 3)) or none_label
    mood_str = " | ".join(_top_n_pct(moods, 3)) or none_label

    vocal_parts = []
    for label_key, key in [("label_male", "male"), ("label_female", "female"), ("label_instrumental", "instrumental")]:
        v = vocals.get(key, 0)
        if v > 0:
            vocal_parts.append(f"{msg(label_key, LANG)} {int(v * 100)}%")
    vocal_str = " | ".join(vocal_parts) or none_label

    print("🎵 音乐画像构建完成！" if LANG == "zh" else "🎵 Music taste profile built!", file=sys.stderr)
    print(f"  📊 {'数据源' if LANG == 'zh' else 'Sources'}：{source_str}" if LANG == "zh" else f"  📊 Sources: {source_str}", file=sys.stderr)
    print(f"  🎸 Top {'风格' if LANG == 'zh' else 'Genres'}：{genre_str}" if LANG == "zh" else f"  🎸 Top Genres: {genre_str}", file=sys.stderr)
    print(f"  🌍 {'语言' if LANG == 'zh' else 'Languages'}：{lang_str}" if LANG == "zh" else f"  🌍 Languages: {lang_str}", file=sys.stderr)
    print(f"  💭 {'情绪' if LANG == 'zh' else 'Moods'}：{mood_str}" if LANG == "zh" else f"  💭 Moods: {mood_str}", file=sys.stderr)
    print(f"  🎤 {'声线' if LANG == 'zh' else 'Vocals'}：{vocal_str}" if LANG == "zh" else f"  🎤 Vocals: {vocal_str}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Build a user music taste profile from multiple sources.")
    parser.add_argument("--apple-music", default=None,
                        help="Path to Apple Music scan JSON")
    parser.add_argument("--qq-music", default=None,
                        help="Path to QQ Music scan JSON")
    parser.add_argument("--spotify", default=None,
                        help="Path to Spotify scan JSON")
    parser.add_argument("--netease", default=None,
                        help="Path to NetEase Cloud Music scan JSON")
    parser.add_argument("--gen-history", default=None,
                        help="Path to generated music history directory")
    parser.add_argument("--artist-map",
                        default="~/.claude/skills/minimax-music-playlist/data/artist_genre_map.json",
                        help="Path to artist_genre_map.json")
    parser.add_argument("--output",
                        default="~/.claude/skills/minimax-music-playlist/data/taste_profile.json",
                        help="Output path for taste_profile.json")
    parser.add_argument("--lang", default="zh", choices=["zh", "en"],
                        help="UI language")
    args = parser.parse_args()

    global LANG
    LANG = args.lang

    profile = build_profile(args)

    # Write output
    output_path = os.path.expanduser(args.output)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    # Print to stdout only if no output file specified
    if not args.output:
        print(json.dumps(profile, ensure_ascii=False, indent=2))
    else:
        print(f"Profile saved to {output_path}", file=sys.stderr)

    # Summary to stderr
    print_summary(profile)


if __name__ == "__main__":
    main()
