"""YouTube Music / YouTube からの集中用BGM再生（yt-dlp + FFmpeg）。"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import shlex
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

YTM = "ytmusic"
YOUTUBE = "youtube"

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
SPOTIFY_HOSTS = {"open.spotify.com", "play.spotify.com", "spotify.com"}
SEARCH_EXTRACTORS = {"YoutubeMusicSearchURL", "YoutubeSearch"}

MAX_QUEUE = 100
MAX_PLAYLIST = 50  # 1回で追加するプレイリストの最大曲数

# /music recommend の初期テーマ（勉強向け）
STUDY_THEMES = [
    "lofi hip hop study", "作業用BGM 集中", "chill study beats", "piano study music",
    "jazz cafe study", "ambient focus music", "classical music for studying",
    "rain lofi", "ゲーム音楽 作業用", "acoustic chill",
]

LIST_OPTIONS = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": "in_playlist",
    "playlistend": MAX_PLAYLIST,
    "socket_timeout": 15,
    "retries": 3,
    "source_address": "0.0.0.0",
}

STREAM_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "socket_timeout": 15,
    "retries": 3,
    "source_address": "0.0.0.0",
}

LOOP_MODES = {"off": "➡ ループなし", "single": "🔂 1曲リピート", "all": "🔁 全曲ループ"}


class MusicError(RuntimeError):
    pass


@dataclass
class Track:
    title: str
    page_url: str
    duration: int | None
    is_live: bool
    requested_by: int


@dataclass
class Stream:
    url: str
    is_live: bool
    protocol: str = ""
    headers: dict = field(default_factory=dict)


# ---- 入力の整形 ----------------------------------------------------------
def _host(value: str) -> str:
    return urllib.parse.urlsplit(value).netloc.lower().split(":", 1)[0]


def normalize_youtube_url(value: str) -> str:
    """youtu.be・music.youtube.com・追跡パラメータ付きURLを再生しやすい形にする。

    プレイリストやアルバム（/playlist, /browse）はそのまま残す。
    """
    value = value.strip()
    parsed = urllib.parse.urlsplit(value)
    host = _host(value)
    if host in SHORT_HOSTS:
        video_id = parsed.path.strip("/").split("/", 1)[0]
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"
    if host in YOUTUBE_HOSTS:
        if parsed.path == "/watch":
            video_id = urllib.parse.parse_qs(parsed.query).get("v", [None])[0]
            if video_id:
                return f"https://www.youtube.com/watch?v={video_id}"
        if parsed.path.startswith("/shorts/"):
            video_id = parsed.path.split("/", 2)[2].split("/", 1)[0]
            if video_id:
                return f"https://www.youtube.com/watch?v={video_id}"
    return value


def search_query(text: str, source: str = YTM, count: int = 1) -> str:
    text = text.strip()
    if source == YTM:
        return f"https://music.youtube.com/search?q={urllib.parse.quote_plus(text)}#songs"
    return f"ytsearch{count}:{text}"


def spotify_search_text(url: str) -> str:
    """Spotifyの曲URLから「アーティスト - 曲名」を取り出す（oEmbed）。"""
    request = urllib.request.Request(
        "https://open.spotify.com/oembed?url=" + urllib.parse.quote(url, safe=""),
        headers={"User-Agent": "StudyFocusBot/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            meta = json.load(response)
    except OSError as e:
        raise MusicError("Spotifyの曲情報を取得できませんでした。") from e
    text = " - ".join(p for p in (meta.get("author_name"), meta.get("title")) if p)
    if not text:
        raise MusicError("Spotifyの曲情報を取得できませんでした。")
    return text


def prepare_query(query: str, source: str = YTM) -> str:
    """ユーザー入力をyt-dlpに渡す文字列にする。URL以外は検索として扱う。"""
    query = query.strip()
    if not query:
        raise MusicError("曲名かURLを指定してください。")
    host = _host(query) if query.startswith(("http://", "https://")) else ""
    if host in SPOTIFY_HOSTS:
        return search_query(spotify_search_text(query), source)
    if host in YOUTUBE_HOSTS | SHORT_HOSTS:
        return normalize_youtube_url(query)
    if host:
        return query
    return search_query(query, source)


# ---- yt-dlpの結果 → Track ----------------------------------------------------
def _is_live(info: dict) -> bool:
    return info.get("live_status") == "is_live" or bool(info.get("is_live"))


def _entry_url(entry: dict) -> str | None:
    url = entry.get("webpage_url") or entry.get("original_url") or entry.get("url")
    if (not url or not str(url).startswith("http")) and entry.get("id"):
        url = f"https://www.youtube.com/watch?v={entry['id']}"
    return normalize_youtube_url(url) if url else None


def _track(entry: dict, requested_by: int) -> Track | None:
    if entry.get("live_status") == "is_upcoming":
        return None
    url = _entry_url(entry)
    if not url:
        return None
    duration = entry.get("duration")
    return Track(title=entry.get("title") or "不明なタイトル", page_url=url,
                 duration=int(duration) if duration else None,
                 is_live=_is_live(entry), requested_by=requested_by)


def tracks_from_info(info: dict | None, requested_by: int) -> tuple[list[Track], str | None]:
    """yt-dlpの結果から曲の一覧と、プレイリストならその名前を返す。

    検索結果は先頭の1曲だけ、プレイリスト・アルバムは全曲（最大 MAX_PLAYLIST）。
    """
    if not info:
        raise MusicError("再生できる曲が見つかりませんでした。")
    if info.get("_type") == "playlist" or "entries" in info:
        entries = [e for e in info.get("entries") or [] if e]
        is_search = info.get("extractor_key") in SEARCH_EXTRACTORS
        tracks = [t for e in entries if (t := _track(e, requested_by))]
        if not tracks:
            raise MusicError("再生できる曲が見つかりませんでした。")
        if is_search:
            return tracks[:1], None
        return tracks[:MAX_PLAYLIST], info.get("title") or "プレイリスト"
    if info.get("live_status") == "is_upcoming":
        raise MusicError("このライブ配信はまだ開始されていません。")
    track = _track(info, requested_by)
    if track is None:
        raise MusicError("動画URLを取得できませんでした。")
    return [track], None


def track_from_info(info: dict, requested_by: int) -> Track:
    return tracks_from_info(info, requested_by)[0][0]


# ---- 再生ストリーム ----------------------------------------------------------
def select_stream(info: dict) -> Stream:
    """yt-dlpの情報から再生用の音声URLを選ぶ。ライブはHLSを優先。"""
    live = _is_live(info)
    selected = info
    if live:
        hls = [f for f in info.get("formats", []) if f.get("url")
               and str(f.get("protocol", "")).startswith("m3u8") and f.get("acodec") != "none"]
        audio_only = [f for f in hls if f.get("vcodec") == "none"]
        if audio_only:
            selected = max(audio_only, key=lambda f: f.get("abr") or f.get("tbr") or 0)
        elif hls:
            selected = min(hls, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))
    if not selected.get("url"):
        raise MusicError("音声ストリームを取得できませんでした。")
    headers = {**info.get("http_headers", {}), **selected.get("http_headers", {})}
    return Stream(selected["url"], live, str(selected.get("protocol", "")), headers)


def ffmpeg_options(stream: Stream) -> dict[str, str]:
    before = ("-nostdin -reconnect 1 -reconnect_streamed 1 "
              "-reconnect_on_network_error 1 -reconnect_delay_max 5 -rw_timeout 15000000")
    if stream.is_live and stream.protocol.startswith("m3u8"):
        before += " -live_start_index -2 -http_persistent 0"
    for name, opt in (("User-Agent", "-user_agent"), ("Referer", "-referer")):
        value = stream.headers.get(name)
        if value and "\r" not in value and "\n" not in value:
            before += f" {opt} {shlex.quote(value)}"
    return {"before_options": before, "options": "-vn -sn -dn -loglevel warning"}


_GEO_MESSAGES = ("not made this video available in your country", "blocked it in your country",
                 "not available in your country", "not available from your location")


def error_message(error: BaseException) -> str:
    text = str(error)
    if any(m in text.lower() for m in _GEO_MESSAGES):
        return "この曲は地域制限のため、Botの接続地域では再生できません。別の曲で試してください。"
    return f"取得に失敗しました: {text[:200]}"


def _run_ydl(options: dict, target: str) -> dict:
    import yt_dlp  # 起動を軽くするため遅延import

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            return ydl.extract_info(target, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise MusicError(error_message(e)) from e


async def resolve(query: str, source: str, requested_by: int) -> tuple[list[Track], str | None]:
    """入力（URL・検索語・Spotify URL）を曲の一覧にする。"""
    def work():
        target = prepare_query(query, source)
        return tracks_from_info(_run_ydl(LIST_OPTIONS, target), requested_by)
    return await asyncio.to_thread(work)


async def recommend(theme: str | None, source: str, requested_by: int) -> Track:
    """テーマで検索し、上位からランダムに1曲選ぶ。"""
    text = theme.strip() if theme and theme.strip() else random.choice(STUDY_THEMES)

    def work():
        target = search_query(text, source, count=10)
        info = _run_ydl(LIST_OPTIONS, target)
        entries = [e for e in (info or {}).get("entries") or [] if e]
        tracks = [t for e in entries[:10] if (t := _track(e, requested_by))]
        if not tracks:
            raise MusicError("おすすめ曲が見つかりませんでした。")
        return random.choice(tracks)
    return await asyncio.to_thread(work)


async def extract(url: str) -> dict:
    """再生直前に音声URLを取得する（URLは時間で失効するため毎回取得）。"""
    return await asyncio.to_thread(_run_ydl, STREAM_OPTIONS, url)


# ---- ギルドごとの再生状態 ----------------------------------------------------
@dataclass
class GuildMusic:
    volume: float = 0.15
    loop_mode: str = "off"  # off / single / all
    queue: deque[Track] = field(default_factory=deque)
    current: Track | None = None
    generation: int = 0  # stop/skip後に古いafterコールバックを無視するため

    def enqueue(self, track: Track) -> int:
        if len(self.queue) >= MAX_QUEUE:
            raise MusicError(f"キューは最大{MAX_QUEUE}曲までです。")
        self.queue.append(track)
        return len(self.queue)

    def enqueue_many(self, tracks: list[Track]) -> int:
        """入るだけ追加し、追加した曲数を返す。"""
        room = MAX_QUEUE - len(self.queue)
        if room <= 0:
            raise MusicError(f"キューは最大{MAX_QUEUE}曲までです。")
        added = tracks[:room]
        self.queue.extend(added)
        return len(added)

    def next_track(self) -> Track | None:
        """曲が終わったときの次の曲。1曲リピートなら同じ曲、全曲ループなら末尾に戻す。"""
        if self.loop_mode == "single" and self.current is not None:
            return self.current
        return self.skip()

    def skip(self) -> Track | None:
        """今の曲を飛ばして次へ進む（1曲リピート中でも次の曲へ）。"""
        if self.loop_mode == "all" and self.current is not None:
            self.queue.append(self.current)
        self.current = self.queue.popleft() if self.queue else None
        return self.current

    def shuffle(self) -> None:
        items = list(self.queue)
        random.shuffle(items)
        self.queue = deque(items)

    def clear(self) -> None:
        self.queue.clear()
        self.current = None
        self.generation += 1
