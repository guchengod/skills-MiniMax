#!/usr/bin/env python3
"""
scan_netease.py

Scan NetEase Cloud Music (网易云音乐) local data on macOS.

Data sources:
  1. webdata files — cached JSON with tracks, playlists, FM queue, recommendations
  2. Cache.db — SQLite URL cache with API responses
  3. Public API — user's personal playlists and track details (no auth needed)

Usage:
    python3 scan_netease.py --output /tmp/netease_data.json
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.expanduser("~/.claude/skills/shared"))
from i18n import msg

LANG = "zh"


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

NETEASE_CONTAINER = os.path.expanduser(
    "~/Library/Containers/com.netease.163music/Data/Documents/storage"
)
NETEASE_WEBDATA = os.path.join(NETEASE_CONTAINER, "file_storage/webdata/file")
NETEASE_CEFCACHE = os.path.join(NETEASE_CONTAINER, "CEFCache")
NETEASE_CACHES = os.path.expanduser("~/Library/Caches/com.netease.163music")


def is_installed() -> bool:
    """Check if NetEase Cloud Music is installed."""
    app_paths = [
        "/Applications/NeteaseMusic.app",
        os.path.expanduser("~/Applications/NeteaseMusic.app"),
    ]
    return any(os.path.exists(p) for p in app_paths)


# ---------------------------------------------------------------------------
# Track extraction helpers
# ---------------------------------------------------------------------------

def extract_track(item: dict) -> dict | None:
    """Extract normalized track info from a NetEase track object."""
    if not isinstance(item, dict):
        return None
    name = item.get("name", "")
    if not name:
        return None

    # Artists: NetEase uses 'ar' (short) or 'artists' (full)
    ar = item.get("ar", item.get("artists", []))
    artist_names = []
    if isinstance(ar, list):
        for a in ar:
            if isinstance(a, dict) and a.get("name"):
                artist_names.append(a["name"])

    # Album
    al = item.get("al", item.get("album", {}))
    album_name = ""
    if isinstance(al, dict):
        album_name = al.get("name", "")

    return {
        "name": name,
        "singer": " / ".join(artist_names) if artist_names else "",
        "album": album_name,
        "id": item.get("id", ""),
        "duration": item.get("dt", item.get("duration", 0)),
    }


def extract_tracks_from_list(items: list) -> list:
    """Extract tracks from a list of track objects."""
    tracks = []
    if not isinstance(items, list):
        return tracks
    for item in items:
        t = extract_track(item)
        if t:
            tracks.append(t)
    return tracks


# ---------------------------------------------------------------------------
# Webdata file readers
# ---------------------------------------------------------------------------

def read_json_file(path: str) -> dict | list | None:
    """Read and parse a JSON file."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            return json.loads(f.read())
    except (json.JSONDecodeError, IOError):
        return None


def scan_essential() -> dict:
    """Read essential file — official playlists and latest songs."""
    result = {"playlists": [], "tracks": []}
    data = read_json_file(os.path.join(NETEASE_WEBDATA, "essential"))
    if data is None or not isinstance(data, dict):
        return result

    # Official playlists (curated by NetEase, reflects user's taste tags)
    for pl in data.get("officialPlaylists", []):
        if isinstance(pl, dict) and pl.get("name"):
            result["playlists"].append({
                "name": pl["name"],
                "id": pl.get("id", ""),
                "trackCount": pl.get("trackCount", 0),
                "type": "official",
            })
            # Extract tracks if available
            result["tracks"].extend(extract_tracks_from_list(pl.get("tracks", [])))

    # Latest songs
    result["tracks"].extend(extract_tracks_from_list(data.get("latestSongs", [])))

    return result


def scan_home_page() -> dict:
    """Read homePage file — recommendations, style blocks, playlists."""
    result = {"playlists": [], "tracks": [], "uid": ""}
    data = read_json_file(os.path.join(NETEASE_WEBDATA, "homePage"))
    if data is None or not isinstance(data, dict):
        return result

    result["uid"] = str(data.get("uid", ""))

    # Recommended playlists (algorithmically chosen based on user taste)
    for pl in data.get("recommendPlaylist", []):
        if isinstance(pl, dict) and pl.get("name"):
            result["playlists"].append({
                "name": pl["name"],
                "id": pl.get("id", ""),
                "trackCount": pl.get("trackCount", 0),
                "type": "recommended",
            })

    # Style recommendation tracks
    srb = data.get("styleRecommendBlock", {})
    if isinstance(srb, dict):
        result["tracks"].extend(extract_tracks_from_list(srb.get("trackList", [])))

    # Heartbeat (daily mix) tracks
    hrb = data.get("heartbeatRecommendBlock", {})
    if isinstance(hrb, dict):
        result["tracks"].extend(extract_tracks_from_list(hrb.get("trackList", [])))

    # VIP recommendation tracks
    vrb = data.get("vipRecommendBlock", {})
    if isinstance(vrb, dict):
        result["tracks"].extend(extract_tracks_from_list(vrb.get("trackList", [])))

    # Scene playlist tags (e.g., "夜晚", "运动") — reflect user preferences
    scene_tags = []
    for tag in data.get("scenePlaylistTags", []):
        if isinstance(tag, dict):
            pt = tag.get("playlistTag", {})
            if isinstance(pt, dict) and pt.get("name"):
                scene_tags.append(pt["name"])
    result["scene_tags"] = scene_tags

    return result


def scan_fm_play() -> dict:
    """Read fmPlay file — FM radio queue (recent listening)."""
    result = {"tracks": []}
    data = read_json_file(os.path.join(NETEASE_WEBDATA, "fmPlay"))
    if data is None or not isinstance(data, dict):
        return result

    result["tracks"] = extract_tracks_from_list(data.get("queue", []))
    return result


def scan_playing_list() -> dict:
    """Read playingList file — current playing list."""
    result = {"tracks": []}
    data = read_json_file(os.path.join(NETEASE_WEBDATA, "playingList"))
    if data is None or not isinstance(data, dict):
        return result

    result["tracks"] = extract_tracks_from_list(data.get("list", []))
    return result


# ---------------------------------------------------------------------------
# Cache.db — SQLite URL cache with API responses
# ---------------------------------------------------------------------------

def scan_cache_db() -> dict:
    """Scan NetEase Cache.db for API responses containing track data."""
    import sqlite3

    result = {"tracks": [], "playlists": []}
    cache_db = os.path.join(NETEASE_CACHES, "Cache.db")
    if not os.path.exists(cache_db):
        return result

    try:
        conn = sqlite3.connect(f"file:{cache_db}?mode=ro", uri=True)
        cursor = conn.cursor()

        # Find API responses (not images/static resources)
        cursor.execute("""
            SELECT r.request_key, d.receiver_data
            FROM cfurl_cache_response r
            JOIN cfurl_cache_receiver_data d ON r.entry_ID = d.entry_ID
            WHERE d.isDataOnFS = 0
              AND length(d.receiver_data) > 100
              AND r.request_key NOT LIKE '%jpg%'
              AND r.request_key NOT LIKE '%png%'
              AND r.request_key NOT LIKE '%webp%'
              AND r.request_key NOT LIKE '%svg%'
              AND r.request_key NOT LIKE '%.js%'
              AND r.request_key NOT LIKE '%.css%'
        """)

        for url, data in cursor.fetchall():
            if not data:
                continue
            try:
                text = data.decode("utf-8", errors="replace")
                parsed = json.loads(text)
                if not isinstance(parsed, dict):
                    continue

                # Extract tracks from various API response formats
                for key in ("songs", "tracks", "playlist", "data"):
                    items = parsed.get(key)
                    if isinstance(items, list):
                        result["tracks"].extend(extract_tracks_from_list(items))
                    elif isinstance(items, dict) and "tracks" in items:
                        result["tracks"].extend(
                            extract_tracks_from_list(items.get("tracks", []))
                        )

                # Extract playlist info
                pl = parsed.get("playlist")
                if isinstance(pl, dict) and pl.get("name"):
                    result["playlists"].append({
                        "name": pl["name"],
                        "id": pl.get("id", ""),
                        "trackCount": pl.get("trackCount", 0),
                        "type": "user",
                    })

            except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                pass

        conn.close()
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Playlist name → genre inference
# ---------------------------------------------------------------------------

PLAYLIST_GENRE_KEYWORDS = {
    "kpop": "K-pop", "k-pop": "K-pop", "韩": "K-pop",
    "jpop": "J-pop", "j-pop": "J-pop", "日系": "J-pop", "acg": "J-pop",
    "华语": "华语流行", "中文": "华语流行", "国语": "华语流行",
    "粤语": "粤语流行", "广东": "粤语流行",
    "r&b": "R&B", "rnb": "R&B", "节奏蓝调": "R&B",
    "摇滚": "摇滚", "rock": "摇滚",
    "民谣": "民谣", "folk": "民谣",
    "电子": "电子", "edm": "EDM", "电音": "电子",
    "爵士": "爵士", "jazz": "爵士",
    "古典": "古典", "classical": "古典",
    "说唱": "hip-hop", "rap": "hip-hop", "hip-hop": "hip-hop", "嘻哈": "hip-hop",
    "舞曲": "舞曲", "dance": "舞曲",
    "纯音乐": "纯音乐", "轻音乐": "纯音乐",
    "lo-fi": "lo-fi", "lofi": "lo-fi",
    "indie": "独立流行", "独立": "独立流行",
    "欧美": "流行", "西洋": "流行",
}

PLAYLIST_MOOD_KEYWORDS = {
    "治愈": "治愈", "温柔": "温柔", "温暖": "温暖",
    "忧郁": "忧郁", "伤感": "忧郁", "悲伤": "悲伤",
    "安静": "平静", "静": "平静", "放松": "平静",
    "燃": "燃", "高燃": "燃", "热血": "热血",
    "浪漫": "浪漫", "甜": "甜蜜", "恋爱": "浪漫",
    "活力": "活力", "元气": "活力", "欢快": "欢快",
    "宿命": "忧郁", "催泪": "悲伤",
    "深夜": "忧郁", "夜晚": "忧郁",
    "学习": "平静", "工作": "活力",
}


def infer_genres_from_playlists(playlists: list) -> dict:
    """Infer genre and mood preferences from playlist names."""
    genres = {}
    moods = {}

    for pl in playlists:
        name = pl.get("name", "").lower() if isinstance(pl, dict) else str(pl).lower()
        for keyword, genre in PLAYLIST_GENRE_KEYWORDS.items():
            if keyword in name:
                genres[genre] = genres.get(genre, 0) + 1
        for keyword, mood in PLAYLIST_MOOD_KEYWORDS.items():
            if keyword in name:
                moods[mood] = moods.get(mood, 0) + 1

    return {"genres": genres, "moods": moods}


# ---------------------------------------------------------------------------
# Public API — fetch user's personal playlists and tracks
# ---------------------------------------------------------------------------

API_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://music.163.com/",
}


def api_get(url: str) -> dict | None:
    """GET a NetEase public API endpoint, return parsed JSON or None."""
    try:
        req = urllib.request.Request(url, headers=API_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        print(f"     ⚠️  API request failed: {e}", file=sys.stderr)
        return None


def fetch_user_playlists(uid: str) -> list:
    """Fetch all playlists for a user via public API."""
    if not uid:
        return []
    url = f"https://music.163.com/api/user/playlist/?uid={uid}&limit=1000&offset=0"
    data = api_get(url)
    if not data or data.get("code") != 200:
        return []
    return data.get("playlist", [])


def fetch_playlist_tracks(playlist_id: int | str) -> list:
    """Fetch all tracks from a playlist via public API.

    The v6/playlist/detail endpoint returns full track objects (max ~10) plus
    a complete trackIds list.  When trackIds has more entries than tracks,
    we fetch the remaining ones via song/detail in batches.
    """
    url = (
        f"https://music.163.com/api/v6/playlist/detail"
        f"?id={playlist_id}&n=1000&s=0"
    )
    data = api_get(url)
    if not data or data.get("code") != 200:
        return []

    pl = data.get("playlist", {})
    tracks = pl.get("tracks", [])
    track_ids_raw = pl.get("trackIds", [])

    # Extract IDs we already have full data for
    have_ids = {t.get("id") for t in tracks if isinstance(t, dict)}

    # Find IDs that are missing full track data
    missing_ids = [
        t["id"] for t in track_ids_raw
        if isinstance(t, dict) and "id" in t and t["id"] not in have_ids
    ]

    if missing_ids:
        extra = fetch_tracks_by_ids(missing_ids)
        tracks.extend(extra)

    return tracks


def fetch_tracks_by_ids(track_ids: list, batch_size: int = 50) -> list:
    """Fetch track details by IDs using song/detail API."""
    all_tracks = []
    for i in range(0, len(track_ids), batch_size):
        batch = track_ids[i:i + batch_size]
        ids_param = ",".join(str(tid) for tid in batch)
        url = f"https://music.163.com/api/song/detail?ids=[{ids_param}]"
        data = api_get(url)
        if data and isinstance(data.get("songs"), list):
            all_tracks.extend(data["songs"])
        time.sleep(0.3)
    return all_tracks


def scan_user_playlists(uid: str) -> dict:
    """Scan user's personal playlists via public API."""
    result = {"playlists": [], "tracks": [], "owned_count": 0, "collected_count": 0}

    if not uid:
        return result

    print(f"  🌐 Fetching playlists for uid {uid}...", file=sys.stderr)
    playlists = fetch_user_playlists(uid)
    if not playlists:
        print("     No playlists found via API", file=sys.stderr)
        return result

    # Separate owned vs collected playlists
    owned = []
    collected = []
    for pl in playlists:
        if not isinstance(pl, dict):
            continue
        creator = pl.get("creator", {})
        creator_uid = str(creator.get("userId", "")) if isinstance(creator, dict) else ""
        if creator_uid == str(uid):
            owned.append(pl)
        else:
            collected.append(pl)

    result["owned_count"] = len(owned)
    result["collected_count"] = len(collected)

    print(f"     Found {len(owned)} owned, {len(collected)} collected playlists",
          file=sys.stderr)

    # Fetch tracks from owned playlists (these reflect user's actual taste)
    for pl in owned:
        pl_name = pl.get("name", "")
        pl_id = pl.get("id", "")
        track_count = pl.get("trackCount", 0)

        if not pl_id or pl_name == "喜欢的音乐":
            # "喜欢的音乐" is the default "liked songs" playlist — still fetch it
            pass

        result["playlists"].append({
            "name": pl_name,
            "id": pl_id,
            "trackCount": track_count,
            "type": "owned",
        })

        if track_count == 0:
            continue

        print(f"     📂 {pl_name} ({track_count} tracks)...", file=sys.stderr)
        tracks = fetch_playlist_tracks(pl_id)
        extracted = extract_tracks_from_list(tracks)
        result["tracks"].extend(extracted)
        print(f"        Got {len(extracted)} tracks", file=sys.stderr)
        time.sleep(0.3)

    # Also record collected playlist names for genre inference
    for pl in collected:
        pl_name = pl.get("name", "")
        if pl_name:
            result["playlists"].append({
                "name": pl_name,
                "id": pl.get("id", ""),
                "trackCount": pl.get("trackCount", 0),
                "type": "collected",
            })

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Scan NetEase Cloud Music local data on macOS")
    parser.add_argument("--output", default=None, help="Output JSON file path")
    parser.add_argument("--lang", default="zh", choices=["zh", "en"], help="UI language")
    args = parser.parse_args()

    global LANG
    LANG = args.lang

    if not is_installed():
        result = {
            "source": "netease",
            "installed": False,
            "tracks": [],
            "scanned_at": datetime.now().isoformat(),
        }
        output_result(result, args.output)
        print("NetEase Cloud Music is not installed.", file=sys.stderr)
        return

    print(msg("scanning_netease", LANG), file=sys.stderr)

    all_tracks = []
    all_playlists = []
    scene_tags = []
    uid = ""

    # 1. Essential data
    print("  📂 Reading essential data...", file=sys.stderr)
    essential = scan_essential()
    all_tracks.extend(essential["tracks"])
    all_playlists.extend(essential["playlists"])
    print(f"     {len(essential['tracks'])} tracks, {len(essential['playlists'])} playlists", file=sys.stderr)

    # 2. Home page data
    print("  🏠 Reading home page data...", file=sys.stderr)
    home = scan_home_page()
    all_tracks.extend(home["tracks"])
    all_playlists.extend(home["playlists"])
    scene_tags = home.get("scene_tags", [])
    uid = home.get("uid", "")
    print(f"     {len(home['tracks'])} tracks, {len(home['playlists'])} playlists", file=sys.stderr)

    # 3. FM queue
    print("  📻 Reading FM queue...", file=sys.stderr)
    fm = scan_fm_play()
    all_tracks.extend(fm["tracks"])
    print(f"     {len(fm['tracks'])} tracks", file=sys.stderr)

    # 4. Playing list
    print("  ▶️  Reading playing list...", file=sys.stderr)
    playing = scan_playing_list()
    all_tracks.extend(playing["tracks"])
    print(f"     {len(playing['tracks'])} tracks", file=sys.stderr)

    # 5. Cache.db
    print("  💾 Scanning URL cache...", file=sys.stderr)
    cache = scan_cache_db()
    all_tracks.extend(cache["tracks"])
    all_playlists.extend(cache["playlists"])
    print(f"     {len(cache['tracks'])} tracks, {len(cache['playlists'])} playlists", file=sys.stderr)

    # 6. Public API — user's personal playlists
    if uid:
        user_pl = scan_user_playlists(uid)
        all_tracks.extend(user_pl["tracks"])
        all_playlists.extend(user_pl["playlists"])
        owned_count = user_pl.get("owned_count", 0)
        collected_count = user_pl.get("collected_count", 0)
    else:
        owned_count = 0
        collected_count = 0
        print("  ⚠️  No uid found — skipping personal playlist scan", file=sys.stderr)

    # Deduplicate tracks by name + artist
    seen = set()
    unique_tracks = []
    for t in all_tracks:
        key = (t.get("name", "").lower(), t.get("singer", "").lower())
        if key not in seen and key[0]:
            seen.add(key)
            unique_tracks.append(t)

    # Deduplicate playlists by name
    seen_pl = set()
    unique_playlists = []
    for pl in all_playlists:
        name = pl.get("name", "")
        if name and name not in seen_pl:
            seen_pl.add(name)
            unique_playlists.append(pl)

    # Infer genres from playlist names
    inferred = infer_genres_from_playlists(unique_playlists)

    # Build result
    result = {
        "source": "netease",
        "installed": True,
        "uid": uid,
        "tracks": unique_tracks,
        "playlists": unique_playlists,
        "owned_playlists": owned_count,
        "collected_playlists": collected_count,
        "scene_tags": scene_tags,
        "inferred_genres": inferred.get("genres", {}),
        "inferred_moods": inferred.get("moods", {}),
        "scanned_at": datetime.now().isoformat(),
    }

    output_result(result, args.output)

    print(f"\n✅ NetEase Cloud Music scan complete!", file=sys.stderr)
    print(f"   Tracks: {len(unique_tracks)}", file=sys.stderr)
    print(f"   Playlists: {len(unique_playlists)} ({owned_count} owned, {collected_count} collected)", file=sys.stderr)
    print(f"   Scene tags: {', '.join(scene_tags) if scene_tags else 'none'}", file=sys.stderr)
    if inferred.get("genres"):
        top = sorted(inferred["genres"].items(), key=lambda x: -x[1])[:5]
        print(f"   Inferred genres: {', '.join(f'{g}({c})' for g, c in top)}", file=sys.stderr)
    if not unique_tracks:
        print("   ⚠️  No track data found — app may be newly installed.", file=sys.stderr)
        print("      Use the app more (play songs, browse), then rescan.", file=sys.stderr)


def output_result(result: dict, output_path: str = None):
    """Output result to file or stdout."""
    json_str = json.dumps(result, ensure_ascii=False, indent=2)

    if output_path:
        output_path = os.path.expanduser(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(json_str)
        print(f"Wrote {result.get('track_count', 0)} tracks to {output_path}", file=sys.stderr)
    else:
        print(json_str)


if __name__ == "__main__":
    main()
