from __future__ import annotations

import curses
import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from .supported_sites import SUPPORTED_SITES


@dataclass(frozen=True)
class PlatformTheme:
    key: str
    name: str
    tier: str
    domains: tuple[str, ...]
    colors: dict[str, str]
    description: str = ""


ROLE_NAMES = ("border", "focus", "accent", "highlight", "selected", "muted", "ok", "warn", "error", "fill")
ROLE_PAIR = {role: index + 1 for index, role in enumerate(ROLE_NAMES)}
HOST_TOKEN_STOPWORDS = {"www", "m", "mobile", "com", "net", "org", "co", "tv", "io", "app", "me", "ly"}


PLATFORMS: tuple[PlatformTheme, ...] = (
    PlatformTheme("youtube", "YouTube", "major", ("youtube.com", "youtu.be"), {"border": "#FF0033", "focus": "#FF0033", "accent": "#FF0033", "highlight": "#FFFFFF", "selected": "#FF0033", "muted": "#8FA3AD", "ok": "#2BA640", "warn": "#F2C94C", "error": "#FF0033", "fill": "#FF0033"}),
    PlatformTheme("instagram", "Instagram", "major", ("instagram.com",), {"border": "#E4405F", "focus": "#F77737", "accent": "#E4405F", "highlight": "#FCAF45", "selected": "#E4405F", "muted": "#A7B0C0", "ok": "#2BA640", "warn": "#FCAF45", "error": "#E4405F", "fill": "#E4405F"}),
    PlatformTheme("facebook", "Facebook", "major", ("facebook.com", "fb.watch"), {"border": "#1877F2", "focus": "#1877F2", "accent": "#1877F2", "highlight": "#FFFFFF", "selected": "#1877F2", "muted": "#A7B0C0", "ok": "#42B72A", "warn": "#F7B928", "error": "#FA383E", "fill": "#1877F2"}),
    PlatformTheme("x", "Twitter/X", "major", ("x.com", "twitter.com"), {"border": "#1D9BF0", "focus": "#1D9BF0", "accent": "#1D9BF0", "highlight": "#FFFFFF", "selected": "#1D9BF0", "muted": "#8899A6", "ok": "#00BA7C", "warn": "#FFD400", "error": "#F4212E", "fill": "#1D9BF0"}),
    PlatformTheme("tiktok", "TikTok", "major", ("tiktok.com",), {"border": "#00F2EA", "focus": "#FF0050", "accent": "#00F2EA", "highlight": "#FFFFFF", "selected": "#FF0050", "muted": "#9BA7B4", "ok": "#00F2EA", "warn": "#F7C948", "error": "#FF0050", "fill": "#00F2EA"}),
    PlatformTheme("reddit", "Reddit", "major", ("reddit.com", "redd.it"), {"border": "#FF4500", "focus": "#FF4500", "accent": "#FF4500", "highlight": "#FFFFFF", "selected": "#FF4500", "muted": "#A7B0C0", "ok": "#46D160", "warn": "#FFD635", "error": "#FF4500", "fill": "#FF4500"}),
    PlatformTheme("twitch", "Twitch", "major", ("twitch.tv",), {"border": "#9146FF", "focus": "#9146FF", "accent": "#9146FF", "highlight": "#FFFFFF", "selected": "#9146FF", "muted": "#B8A7D9", "ok": "#00F593", "warn": "#FFCA5F", "error": "#EB0400", "fill": "#9146FF"}),
    PlatformTheme("soundcloud", "SoundCloud", "major", ("soundcloud.com",), {"border": "#FF5500", "focus": "#FF5500", "accent": "#FF5500", "highlight": "#FFFFFF", "selected": "#FF5500", "muted": "#A7B0C0", "ok": "#2BA640", "warn": "#F2C94C", "error": "#FF5500", "fill": "#FF5500"}),
    PlatformTheme("vimeo", "Vimeo", "major", ("vimeo.com",), {"border": "#1AB7EA", "focus": "#1AB7EA", "accent": "#1AB7EA", "highlight": "#FFFFFF", "selected": "#1AB7EA", "muted": "#A7B0C0", "ok": "#2BA640", "warn": "#F2C94C", "error": "#D0021B", "fill": "#1AB7EA"}),
    PlatformTheme("pinterest", "Pinterest", "major", ("pinterest.com", "pin.it"), {"border": "#E60023", "focus": "#E60023", "accent": "#E60023", "highlight": "#FFFFFF", "selected": "#E60023", "muted": "#A7B0C0", "ok": "#2BA640", "warn": "#F2C94C", "error": "#E60023", "fill": "#E60023"}),
    PlatformTheme("linkedin", "LinkedIn", "major", ("linkedin.com",), {"border": "#0A66C2", "focus": "#0A66C2", "accent": "#0A66C2", "highlight": "#FFFFFF", "selected": "#0A66C2", "muted": "#A7B0C0", "ok": "#057642", "warn": "#F5C75D", "error": "#CC1016", "fill": "#0A66C2"}),
    PlatformTheme("dailymotion", "Dailymotion", "major", ("dailymotion.com", "dai.ly"), {"border": "#00AEEF", "focus": "#00AEEF", "accent": "#00AEEF", "highlight": "#FFFFFF", "selected": "#00AEEF", "muted": "#A7B0C0", "ok": "#2BA640", "warn": "#F2C94C", "error": "#D0021B", "fill": "#00AEEF"}),
    PlatformTheme("bandcamp", "Bandcamp", "niche", ("bandcamp.com",), {"border": "#629AA9", "focus": "#629AA9", "accent": "#629AA9", "highlight": "#FFFFFF", "selected": "#629AA9", "muted": "#A7B0C0", "ok": "#2BA640", "warn": "#F2C94C", "error": "#D0021B", "fill": "#629AA9"}),
    PlatformTheme("bilibili", "Bilibili", "niche", ("bilibili.com",), {"border": "#00A1D6", "focus": "#00A1D6", "accent": "#00A1D6", "highlight": "#FFFFFF", "selected": "#00A1D6", "muted": "#A7B0C0", "ok": "#2BA640", "warn": "#F2C94C", "error": "#FB7299", "fill": "#00A1D6"}),
    PlatformTheme("odysee", "Odysee", "niche", ("odysee.com",), {"border": "#EF1970", "focus": "#EF1970", "accent": "#EF1970", "highlight": "#FFFFFF", "selected": "#EF1970", "muted": "#A7B0C0", "ok": "#2BA640", "warn": "#F2C94C", "error": "#EF1970", "fill": "#EF1970"}),
    PlatformTheme("rumble", "Rumble", "niche", ("rumble.com",), {"border": "#85C742", "focus": "#85C742", "accent": "#85C742", "highlight": "#FFFFFF", "selected": "#85C742", "muted": "#A7B0C0", "ok": "#85C742", "warn": "#F2C94C", "error": "#D0021B", "fill": "#85C742"}),
    PlatformTheme("archive", "Internet Archive", "niche", ("archive.org",), {"border": "#666666", "focus": "#999999", "accent": "#999999", "highlight": "#FFFFFF", "selected": "#666666", "muted": "#A7B0C0", "ok": "#2BA640", "warn": "#F2C94C", "error": "#D0021B", "fill": "#666666"}),
)

PLATFORM_ABBREVIATIONS = {
    "youtube": "yt",
    "instagram": "ig",
    "facebook": "fb",
    "x": "x",
    "tiktok": "tt",
    "reddit": "rd",
    "twitch": "tw",
    "soundcloud": "sc",
    "vimeo": "vm",
    "pinterest": "pin",
    "linkedin": "li",
    "dailymotion": "dm",
}

_EXTRACTOR_CACHE: tuple[PlatformTheme, ...] | None = None


def platform_label(platform: PlatformTheme) -> str:
    return f"{PLATFORM_ABBREVIATIONS.get(platform.key, platform.key[:4])}-dl"


def extractor_platforms() -> tuple[PlatformTheme, ...]:
    global _EXTRACTOR_CACHE
    if _EXTRACTOR_CACHE is not None:
        return _EXTRACTOR_CACHE
    existing = {platform.key for platform in PLATFORMS}
    platforms: list[PlatformTheme] = []
    generic_colors = {"border": "#629AA9", "focus": "#8AB4BF", "accent": "#8AB4BF", "highlight": "#FFFFFF", "selected": "#629AA9", "muted": "#A7B0C0", "ok": "#2BA640", "warn": "#F2C94C", "error": "#D0021B", "fill": "#629AA9"}
    for key, name, description in SUPPORTED_SITES:
        if not key or key in existing:
            continue
        platforms.append(PlatformTheme(key, name, "niche", inferred_domains(name, description), generic_colors, description))
    _EXTRACTOR_CACHE = tuple(platforms)
    return _EXTRACTOR_CACHE


def inferred_domains(name: str, description: str) -> tuple[str, ...]:
    domains: list[str] = []
    for text in (name, description):
        for match in re.findall(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b", text.lower()):
            if match not in domains:
                domains.append(match)
    return tuple(domains[:4])


def match_platform_from_url(url: str, candidates: tuple[PlatformTheme, ...] = PLATFORMS) -> PlatformTheme | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    if not host:
        return None
    for platform in candidates:
        for domain in platform.domains:
            normalized = domain.lower().removeprefix("www.")
            if host == normalized or host.endswith("." + normalized):
                return platform
    host_tokens = {token for token in re.split(r"[^a-z0-9]+", host) if token and token not in HOST_TOKEN_STOPWORDS}
    for platform in candidates:
        key_tokens = {token for token in re.split(r"[^a-z0-9]+", platform.key.lower()) if token and token not in HOST_TOKEN_STOPWORDS}
        name_tokens = {token for token in re.split(r"[^a-z0-9]+", platform.name.lower()) if token and token not in HOST_TOKEN_STOPWORDS}
        if host_tokens & (key_tokens | name_tokens):
            return platform
    return None


def detect_color_tier() -> str:
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") in {"dumb", ""}:
        return "mono"
    if os.environ.get("COLORTERM", "").lower() in {"truecolor", "24bit"}:
        return "truecolor"
    try:
        if curses.has_colors() and curses.COLORS >= 256:
            return "256"
        if curses.has_colors() and curses.COLORS >= 16:
            return "16"
    except curses.error:
        return "mono"
    return "mono"


def parse_hex(value: str) -> tuple[int, int, int]:
    raw = value.strip().lstrip("#")
    return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)


def nearest_ansi_256(hex_value: str) -> int:
    target = parse_hex(hex_value)
    best = 0
    best_distance = 10**9
    for code in range(16, 256):
        rgb = ansi_256_rgb(code)
        distance = sum((a - b) ** 2 for a, b in zip(target, rgb))
        if distance < best_distance:
            best = code
            best_distance = distance
    return best


def ansi_256_rgb(code: int) -> tuple[int, int, int]:
    if 16 <= code <= 231:
        code -= 16
        r = code // 36
        g = (code % 36) // 6
        b = code % 6
        steps = (0, 95, 135, 175, 215, 255)
        return steps[r], steps[g], steps[b]
    level = 8 + (code - 232) * 10
    return level, level, level


ANSI_16 = {
    curses.COLOR_BLACK: (0, 0, 0),
    curses.COLOR_RED: (205, 49, 49),
    curses.COLOR_GREEN: (13, 188, 121),
    curses.COLOR_YELLOW: (229, 229, 16),
    curses.COLOR_BLUE: (36, 114, 200),
    curses.COLOR_MAGENTA: (188, 63, 188),
    curses.COLOR_CYAN: (17, 168, 205),
    curses.COLOR_WHITE: (229, 229, 229),
}


def nearest_ansi_16(hex_value: str) -> int:
    target = parse_hex(hex_value)
    return min(ANSI_16, key=lambda color: sum((a - b) ** 2 for a, b in zip(target, ANSI_16[color])))


class ThemeManager:
    def __init__(self) -> None:
        self.tier = detect_color_tier()
        self.platform = PLATFORMS[0]
        self.mono = self.tier == "mono"

    def apply(self, platform: PlatformTheme) -> None:
        self.platform = platform
        self.mono = self.tier == "mono" or not curses.has_colors()
        if self.mono:
            return
        curses.start_color()
        curses.use_default_colors()
        for role, pair_id in ROLE_PAIR.items():
            fg = self.color_number(platform.colors[role], pair_id)
            bg = -1
            if role in {"selected", "fill"}:
                bg = fg
                fg = curses.COLOR_BLACK if self.tier == "16" else 16
            curses.init_pair(pair_id, fg, bg)

    def color_number(self, hex_value: str, pair_id: int) -> int:
        if self.tier == "truecolor" and curses.can_change_color() and curses.COLORS >= 256:
            color_id = min(255, 32 + pair_id)
            r, g, b = parse_hex(hex_value)
            curses.init_color(color_id, int(r / 255 * 1000), int(g / 255 * 1000), int(b / 255 * 1000))
            return color_id
        if self.tier in {"truecolor", "256"} and curses.COLORS >= 256:
            return nearest_ansi_256(hex_value)
        return nearest_ansi_16(hex_value)

    def attr(self, role: str, *styles: int) -> int:
        attr = 0
        if not self.mono:
            attr |= curses.color_pair(ROLE_PAIR[role])
        for style in styles:
            attr |= style
        if self.mono and role in {"focus", "selected", "accent", "highlight"}:
            attr |= curses.A_BOLD
        if self.mono and role == "muted":
            attr |= curses.A_DIM
        return attr
