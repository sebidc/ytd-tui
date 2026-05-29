from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from html import unescape
from html.parser import HTMLParser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, quote, quote_plus, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from .presets import AUDIO_FORMATS, PRESETS, VIDEO_FORMATS, Preset


DEFAULT_SEARCH_LIMIT = 20

SEARCH_PREFIXES = {
    "youtube": "ytsearch",
    "soundcloud": "scsearch",
    "bilibili": "bilisearch",
    "nicovideo": "nicosearch",
    "rokfin": "rkfnsearch",
    "netverse": "netsearch",
    "prxstories": "prxstories",
    "prxseries": "prxseries",
    "yahoo": "yvsearch",
}

SEARCH_URLS = {
    "dailymotion": "https://www.dailymotion.com/search/{query}/videos",
}

SITE_SEARCH_TEMPLATES = {
    "pornhub": ("https://www.pornhub.com/video/search?search={query_plus}",),
    "redtube": ("https://www.redtube.com/?search={query_plus}",),
    "youporn": ("https://www.youporn.com/search/?query={query_plus}",),
    "xvideos": ("https://www.xvideos.com/?k={query_plus}",),
    "xhamster": ("https://xhamster.com/search/{query_plus}",),
    "vimeo": ("https://vimeo.com/search?q={query_plus}",),
    "reddit": ("https://www.reddit.com/search/?q={query_plus}",),
    "tiktok": ("https://www.tiktok.com/search/video?q={query_plus}",),
    "facebook": ("https://www.facebook.com/search/videos/?q={query_plus}",),
    "x": ("https://x.com/search?q={query_plus}", "https://twitter.com/search?q={query_plus}"),
    "twitter": ("https://twitter.com/search?q={query_plus}", "https://x.com/search?q={query_plus}"),
}

SEARCH_PAGE_TEMPLATES = {
    "pornhub": ("https://www.pornhub.com/video/search?search={query_plus}",),
    "redtube": ("https://www.redtube.com/?search={query_plus}",),
    "youporn": ("https://www.youporn.com/search/?query={query_plus}",),
    "xvideos": ("https://www.xvideos.com/?k={query_plus}",),
    "xhamster": ("https://xhamster.com/search/{query_plus}",),
    "instagram": ("https://www.instagram.com/explore/search/keyword/?q={query_plus}",),
    "facebook": ("https://www.facebook.com/search/videos/?q={query_plus}", "https://www.facebook.com/search/posts/?q={query_plus}"),
    "x": ("https://x.com/search?q={query_plus}&src=typed_query", "https://twitter.com/search?q={query_plus}&src=typed_query"),
    "twitter": ("https://twitter.com/search?q={query_plus}&src=typed_query", "https://x.com/search?q={query_plus}&src=typed_query"),
    "tiktok": ("https://www.tiktok.com/search?q={query_plus}", "https://www.tiktok.com/search/video?q={query_plus}"),
    "reddit": ("https://www.reddit.com/search/?q={query_plus}",),
    "twitch": ("https://www.twitch.tv/search?term={query_plus}",),
    "pinterest": ("https://www.pinterest.com/search/pins/?q={query_plus}",),
    "linkedin": ("https://www.linkedin.com/search/results/content/?keywords={query_plus}",),
    "vimeo": ("https://vimeo.com/search?q={query_plus}",),
}

GENERIC_SITE_SEARCH_TEMPLATES = (
    "https://{domain}/search?q={query_plus}",
    "https://{domain}/search?query={query_plus}",
    "https://{domain}/search?search={query_plus}",
    "https://{domain}/video/search?search={query_plus}",
    "https://{domain}/videos/search?search={query_plus}",
    "https://{domain}/results?search_query={query_plus}",
)

WEB_SEARCH_SPECS = {
    "instagram": {
        "domains": ("instagram.com",),
        "query": 'site:instagram.com/reel OR site:instagram.com/p OR site:instagram.com/tv "{query}"',
        "queries": ("site:instagram.com/reel {query}", "site:instagram.com/p {query}", "site:instagram.com/tv {query}", "site:instagram.com {query}", "instagram {query}"),
    },
    "facebook": {
        "domains": ("facebook.com", "fb.watch"),
        "query": 'site:facebook.com/watch OR site:fb.watch "{query}"',
        "queries": ("site:facebook.com/watch {query}", "site:fb.watch {query}", "site:facebook.com/reel {query}", "facebook {query}"),
    },
    "x": {
        "domains": ("x.com", "twitter.com"),
        "query": 'site:x.com OR site:twitter.com "{query}"',
        "queries": ("site:x.com {query}", "site:twitter.com {query}", "x {query}", "twitter {query}"),
    },
    "twitter": {
        "domains": ("x.com", "twitter.com"),
        "query": 'site:x.com OR site:twitter.com "{query}"',
        "queries": ("site:twitter.com {query}", "site:x.com {query}", "twitter {query}", "x {query}"),
    },
    "tiktok": {
        "domains": ("tiktok.com",),
        "query": 'site:tiktok.com/@ "{query}"',
        "queries": ("site:tiktok.com/@ {query}", "site:tiktok.com/video {query}", "site:tiktok.com/tag {query}", "site:tiktok.com {query}", "tiktok {query}"),
    },
    "reddit": {
        "domains": ("reddit.com", "redd.it"),
        "query": 'site:reddit.com/r OR site:redd.it "{query}"',
        "queries": ("site:reddit.com/r {query}", "site:redd.it {query}", "reddit {query}"),
    },
    "twitch": {
        "domains": ("twitch.tv",),
        "query": 'site:twitch.tv/videos OR site:twitch.tv/clips "{query}"',
        "queries": ("site:twitch.tv/videos {query}", "site:twitch.tv/clips {query}", "twitch {query}"),
    },
    "vimeo": {
        "domains": ("vimeo.com",),
        "query": 'site:vimeo.com "{query}"',
        "queries": ("site:vimeo.com {query}", "vimeo {query}"),
    },
    "pinterest": {
        "domains": ("pinterest.com", "pin.it"),
        "query": 'site:pinterest.com/pin OR site:pin.it "{query}"',
    },
    "linkedin": {
        "domains": ("linkedin.com",),
        "query": 'site:linkedin.com/posts OR site:linkedin.com/feed/update "{query}"',
    },
}

WEB_DISCOVERY_FIRST = set(WEB_SEARCH_SPECS)
SCRAPED_SEARCH_PLATFORMS = {"pornhub"}


@dataclass
class MediaItem:
    title: str
    url: str
    duration: str = ""
    uploader: str = ""
    source: str = "url"
    content_type: str = "video"
    upload_date: str = ""
    thumbnail: str = ""


@dataclass
class QueueJob:
    item: MediaItem
    preset: Preset
    output_dir: Path
    output_kind: str = "video"
    output_format: str = VIDEO_FORMATS[0]
    title_override: str = ""
    prefix: str = ""
    suffix: str = ""
    status: str = "queued"
    progress: str = ""
    percent: float = 0.0
    speed: str = ""
    last_line: str = ""
    process: subprocess.Popen[str] | None = field(default=None, repr=False)

    def command(self) -> list[str]:
        return build_command(self.item.url, self.preset, self.output_dir, self.output_kind, self.output_format, self.title_override, self.prefix, self.suffix)


def build_command(
    url: str,
    preset: Preset,
    output_dir: Path,
    output_kind: str = "video",
    output_format: str = VIDEO_FORMATS[0],
    title_override: str = "",
    prefix: str = "",
    suffix: str = "",
) -> list[str]:
    base_title = sanitize_filename(title_override) if title_override else "%(title).200B [%(id)s]"
    safe_title = f"{sanitize_filename(prefix)}{base_title}{sanitize_filename(suffix)}"
    template = str(output_dir / f"{safe_title}.%(ext)s")
    if output_kind == "audio":
        args = ["--extract-audio", "--audio-quality", "0", "--audio-format", output_format]
    else:
        args = list(preset.args if preset.name in {"Best video", "1080p video"} else PRESETS[0].args)
        args.extend(("--merge-output-format", output_format))
    return ["yt-dlp", *args, "--paths", str(output_dir), "--output", template, url]


def sanitize_filename(value: str) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"[/:\\\\\\0]", "-", value).strip()
    return cleaned[:200]


def command_preview(command: Iterable[str]) -> str:
    return " ".join(sh_quote(part) for part in command)


def sh_quote(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_@%+=:,./-]+", value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"


def search(query: str, limit: int = DEFAULT_SEARCH_LIMIT, platform_key: str = "youtube", platform_name: str = "YouTube", domains: tuple[str, ...] = ()) -> list[MediaItem]:
    target = query.strip()
    if not target:
        return []
    if not looks_like_url(target) and not re.match(r"^[a-z0-9]+(?:search)?(?:all|[1-9][0-9]*)?:", target, re.I):
        if native_search_supported(platform_key):
            return run_yt_dlp_search(search_target(target, limit, platform_key, platform_name), platform_name, limit)
        scraped = scrape_search_results_from_query(target, limit, platform_key, platform_name, domains)
        if scraped:
            return scraped
        site_errors = []
        for site_target in site_search_targets(target, platform_key, platform_name, domains):
            try:
                items = run_yt_dlp_search(site_target, platform_name, limit)
                if items:
                    return items
            except RuntimeError as exc:
                site_errors.append(str(exc))
        fallback = web_search_spec(platform_key)
        if fallback:
            try:
                return web_search(target, limit, platform_key, platform_name, fallback)
            except RuntimeError:
                pass
        if has_search_page_template(platform_key):
            page_items = search_page_items(target, platform_key, platform_name, domains)
            if page_items:
                return page_items
        detail = f" Tried site search URLs too." if site_errors else ""
        raise RuntimeError(f"{platform_name} text search is not supported by yt-dlp.{detail} Paste a {platform_name} URL instead.")

    if looks_like_url(target) and is_search_page_url(target):
        scraped = scrape_search_results_from_url(target, limit, platform_key, platform_name)
        if scraped:
            return scraped
        return [
            MediaItem(
                title=f"Open {platform_name} search page",
                url=target,
                uploader=display_host_or_owner(target),
                source=f"{platform_name} search",
                content_type="search",
            )
        ]

    return run_yt_dlp_search(target, platform_name, limit)


def run_yt_dlp_search(target: str, platform_name: str, limit: int) -> list[MediaItem]:
    command = [
        "yt-dlp",
        "--dump-json",
        "--flat-playlist",
        "--no-warnings",
        target,
    ]
    try:
        proc = subprocess.run(command, text=True, capture_output=True, check=False, timeout=25)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"yt-dlp timed out while reading {platform_name} search results") from exc
    if proc.returncode != 0 and not proc.stdout:
        raise RuntimeError(proc.stderr.strip() or "yt-dlp search failed")

    items: list[MediaItem] = []
    for line in proc.stdout.splitlines():
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        url = data.get("webpage_url") or data.get("original_url") or data.get("url")
        if not url:
            continue
        if not looks_like_url(url) and data.get("ie_key") == "Youtube":
            url = f"https://www.youtube.com/watch?v={url}"
        items.append(
            MediaItem(
                title=data.get("title") or "Untitled",
                url=url,
                duration=format_duration(data.get("duration")),
                uploader=data.get("uploader") or data.get("channel") or "",
                source=platform_name,
                content_type=infer_content_type(data, url),
                upload_date=str(data.get("upload_date") or data.get("timestamp") or ""),
                thumbnail=best_thumbnail(data),
            )
        )
        if len(items) >= limit:
            break
    return items


def best_thumbnail(data: dict[str, object]) -> str:
    thumbnails = data.get("thumbnails")
    if isinstance(thumbnails, list):
        urls = [thumb.get("url") for thumb in thumbnails if isinstance(thumb, dict) and thumb.get("url")]
        if urls:
            return str(urls[-1])
    thumbnail = data.get("thumbnail")
    return str(thumbnail or "")


def native_search_supported(platform_key: str) -> bool:
    key = platform_key.lower()
    root_key = key.split("-", 1)[0]
    return key in SEARCH_PREFIXES or root_key in SEARCH_PREFIXES or key in SEARCH_URLS or root_key in SEARCH_URLS


def web_search_spec(platform_key: str) -> dict[str, object] | None:
    key = platform_key.lower()
    return WEB_SEARCH_SPECS.get(key) or WEB_SEARCH_SPECS.get(key.split("-", 1)[0])


def site_search_supported(platform_key: str, platform_name: str = "", domains: tuple[str, ...] = ()) -> bool:
    return bool(site_search_targets("test", platform_key, platform_name, domains) or search_page_targets("test", platform_key, platform_name, domains))


def site_search_targets(query: str, platform_key: str, platform_name: str = "", domains: tuple[str, ...] = ()) -> list[str]:
    key = platform_key.lower()
    root_key = key.split("-", 1)[0]
    if key in WEB_DISCOVERY_FIRST or root_key in WEB_DISCOVERY_FIRST:
        return []
    query_plus = quote_plus(query)
    query_path = quote(query)
    values = {"query_plus": query_plus, "query_path": query_path}
    targets: list[str] = []
    for template in (*SITE_SEARCH_TEMPLATES.get(key, ()), *SITE_SEARCH_TEMPLATES.get(root_key, ())):
        target = template.format(**values)
        if target not in targets:
            targets.append(target)
    for domain in search_domains(platform_key, platform_name, domains):
        for template in GENERIC_SITE_SEARCH_TEMPLATES:
            target = template.format(domain=domain, **values)
            if target not in targets:
                targets.append(target)
    return targets


def search_page_items(query: str, platform_key: str, platform_name: str, domains: tuple[str, ...]) -> list[MediaItem]:
    targets = search_page_targets(query, platform_key, platform_name, domains)
    if not targets:
        return []
    return [
        MediaItem(
            title=f"Open {platform_name} search: {query}",
            url=targets[0],
            uploader=platform_name,
            source=f"{platform_name} search",
            content_type="search",
        )
    ]


def search_page_targets(query: str, platform_key: str, platform_name: str = "", domains: tuple[str, ...] = ()) -> list[str]:
    key = platform_key.lower()
    root_key = key.split("-", 1)[0]
    query_plus = quote_plus(query)
    query_path = quote(query)
    values = {"query_plus": query_plus, "query_path": query_path}
    targets: list[str] = []
    for template in (*SEARCH_PAGE_TEMPLATES.get(key, ()), *SEARCH_PAGE_TEMPLATES.get(root_key, ())):
        target = template.format(**values)
        if target not in targets:
            targets.append(target)
    if targets:
        return targets
    for domain in search_domains(platform_key, platform_name, domains):
        target = f"https://{domain}/search?q={query_plus}"
        if target not in targets:
            targets.append(target)
    return targets[:2]


def scrape_search_results_from_query(query: str, limit: int, platform_key: str, platform_name: str, domains: tuple[str, ...]) -> list[MediaItem]:
    for target in search_page_targets(query, platform_key, platform_name, domains):
        items = scrape_search_results_from_url(target, limit, platform_key, platform_name)
        if items:
            return items
    return []


def scrape_search_results_from_url(url: str, limit: int, platform_key: str, platform_name: str) -> list[MediaItem]:
    key = platform_key.lower().split("-", 1)[0]
    if key == "pornhub" or "pornhub.com" in urlparse(url).netloc.lower():
        return scrape_pornhub_search(url, limit)
    return []


def scrape_pornhub_search(url: str, limit: int) -> list[MediaItem]:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 ytd-tui/1.0"})
    with urlopen(request, timeout=15) as response:
        html = response.read().decode("utf-8", errors="replace")
    blocks = re.findall(r'<li\b(?=[^>]*\bvideoblock\b)[\s\S]*?</li>', html, re.I)
    items: list[MediaItem] = []
    seen: set[str] = set()
    for block in blocks:
        href_match = re.search(r'href="([^"]*view_video\.php\?viewkey=[^"]+)"', block, re.I)
        if not href_match:
            continue
        video_url = urljoin("https://www.pornhub.com", unescape(href_match.group(1)))
        if video_url in seen:
            continue
        title_match = re.search(r'<a\b[^>]*href="[^"]*view_video\.php\?viewkey=[^"]+"[^>]*\btitle="([^"]+)"', block, re.I)
        if not title_match:
            title_match = re.search(r'<img\b[^>]*\balt="([^"]+)"', block, re.I)
        title = clean_title(title_match.group(1) if title_match else "PornHub video")
        duration_match = re.search(r'<var\b[^>]*class="duration"[^>]*>([^<]+)</var>', block, re.I)
        uploader_match = re.search(r'<div class="usernameWrap"[\s\S]*?<a\b[^>]*\btitle="([^"]+)"', block, re.I)
        thumbnail_match = re.search(r'\bdata-image="([^"]+)"', block, re.I) or re.search(r'<img\b[^>]*\bsrc="([^"]+)"', block, re.I)
        seen.add(video_url)
        items.append(
            MediaItem(
                title=title,
                url=video_url,
                duration=clean_text(duration_match.group(1)) if duration_match else "",
                uploader=clean_text(uploader_match.group(1)) if uploader_match else "PornHub",
                source="PornHub",
                content_type="video",
                thumbnail=unescape(thumbnail_match.group(1)) if thumbnail_match else "",
            )
        )
        if len(items) >= limit:
            break
    return items


def has_search_page_template(platform_key: str) -> bool:
    key = platform_key.lower()
    root_key = key.split("-", 1)[0]
    return key in SEARCH_PAGE_TEMPLATES or root_key in SEARCH_PAGE_TEMPLATES


def search_domains(platform_key: str, platform_name: str, domains: tuple[str, ...]) -> tuple[str, ...]:
    found: list[str] = []
    for domain in domains:
        clean = domain.lower().removeprefix("www.")
        if clean and "." in clean and clean not in found:
            found.append(clean)
    for candidate in (platform_key, platform_key.split("-", 1)[0], platform_name):
        slug = re.sub(r"[^a-z0-9]+", "", candidate.lower())
        if slug and len(slug) > 2:
            domain = f"{slug}.com"
            if domain not in found:
                found.append(domain)
    return tuple(found[:3])


class DuckDuckGoHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[tuple[str, str]] = []
        self._href = ""
        self._text: list[str] = []
        self._inside_result = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = values.get("class", "")
        if tag == "a" and "result__a" in classes and values.get("href"):
            self._inside_result = True
            self._href = values["href"] or ""
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._inside_result:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._inside_result:
            title = clean_title(" ".join(self._text))
            if self._href and title:
                self.results.append((title, self._href))
            self._inside_result = False
            self._href = ""
            self._text = []


def web_search(query: str, limit: int, platform_key: str, platform_name: str, spec: dict[str, object]) -> list[MediaItem]:
    domains = tuple(str(domain).lower() for domain in spec["domains"])
    items: list[MediaItem] = []
    seen: set[str] = set()
    for search_query in web_search_queries(query, spec, domains):
        for provider in (duckduckgo_search_results, bing_search_results):
            try:
                results = provider(search_query)
            except Exception:
                continue
            for title, raw_url in results:
                url = normalize_search_result_url(raw_url)
                if not url or url in seen or not domain_allowed(url, domains) or low_value_result_url(url, platform_key):
                    continue
                seen.add(url)
                items.append(
                    MediaItem(
                        title=title,
                        url=url,
                        uploader=display_host_or_owner(url),
                        source=f"{platform_name} web",
                        content_type=infer_content_type({}, url),
                    )
                )
                if len(items) >= limit:
                    return items
    if not items:
        raise RuntimeError(f"No {platform_name} URLs found. Paste a direct {platform_name} URL or try a more specific query.")
    return items


def web_search_queries(query: str, spec: dict[str, object], domains: tuple[str, ...]) -> list[str]:
    raw_templates = spec.get("queries", (spec["query"],))
    if isinstance(raw_templates, str):
        raw_templates = (raw_templates,)
    queries: list[str] = []
    for template in raw_templates:
        rendered = str(template).format(query=query).strip()
        for candidate in (rendered, rendered.replace(f'"{query}"', query)):
            if candidate and candidate not in queries:
                queries.append(candidate)
    for domain in domains:
        candidate = f"site:{domain} {query}"
        if candidate not in queries:
            queries.append(candidate)
    return queries


def bing_search_results(search_query: str) -> list[tuple[str, str]]:
    params = urlencode({"q": search_query, "format": "rss"})
    request = Request(
        f"https://www.bing.com/search?{params}",
        headers={
            "User-Agent": "Mozilla/5.0 ytd-tui/1.0",
            "Accept": "application/rss+xml,application/xml,text/xml",
        },
    )
    with urlopen(request, timeout=10) as response:
        xml = response.read().decode("utf-8", errors="replace")
    root = ET.fromstring(xml)
    results: list[tuple[str, str]] = []
    for item in root.findall("./channel/item"):
        title = clean_title(item.findtext("title") or "")
        link = item.findtext("link") or ""
        if title and link:
            results.append((title, link))
    return results


def duckduckgo_search_results(search_query: str) -> list[tuple[str, str]]:
    params = urlencode({"q": search_query, "kl": "us-en"})
    headers = {
        "User-Agent": "Mozilla/5.0 ytd-tui/1.0",
        "Accept": "text/html,application/xhtml+xml",
    }
    for base in ("https://html.duckduckgo.com/html/", "https://duckduckgo.com/html/"):
        try:
            request = Request(f"{base}?{params}", headers=headers)
            with urlopen(request, timeout=10) as response:
                html = response.read().decode("utf-8", errors="replace")
            parser = DuckDuckGoHTMLParser()
            parser.feed(html)
            if parser.results:
                return parser.results
        except Exception:
            continue
    return []


def normalize_search_result_url(raw_url: str) -> str:
    url = unescape(raw_url)
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            url = target
            parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return ""
    return parsed._replace(fragment="").geturl()


def domain_allowed(url: str, domains: tuple[str, ...]) -> bool:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def low_value_result_url(url: str, platform_key: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    root = platform_key.lower().split("-", 1)[0]
    if not path:
        return True
    blocked_paths = {
        "instagram": {"/", "/p/signin", "/accounts/emailsignup", "/accounts/login"},
        "facebook": {"/", "/login.php", "/r.php"},
        "tiktok": {"/", "/login", "/signup", "/foryou", "/en", "/fil-PH"},
        "reddit": {"/"},
        "vimeo": {"/", "/watch"},
        "twitch": {"/"},
        "x": {"/", "/i/flow/login"},
        "twitter": {"/", "/i/flow/login"},
    }
    if path in blocked_paths.get(root, set()):
        return True
    if root == "x" and host == "x.com" and path.startswith("/i/"):
        return True
    if root == "twitter" and "twitter.com" in host and path.startswith("/i/"):
        return True
    return False


def is_search_page_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    query_keys = {key.lower() for key in parse_qs(parsed.query)}
    if any(part in path for part in ("/search", "/video/search", "/videos/search", "/results/search")):
        return True
    return bool(query_keys & {"search", "q", "query", "k", "keywords", "term", "search_query"})


def display_host_or_owner(url: str) -> str:
    parsed = urlparse(url)
    path_parts = [part for part in parsed.path.split("/") if part]
    for part in path_parts:
        if part.startswith("@"):
            return part
    if path_parts and parsed.netloc.lower().endswith("reddit.com"):
        return "/".join(path_parts[:2])
    return parsed.netloc.removeprefix("www.")


def clean_title(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", unescape(value)).strip()
    return cleaned.replace(" | Instagram", "").replace(" | TikTok", "").replace(" | Facebook", "")


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(value)).strip()


def search_target(query: str, limit: int, platform_key: str, platform_name: str) -> str:
    key = platform_key.lower()
    root_key = key.split("-", 1)[0]
    if key in SEARCH_PREFIXES or root_key in SEARCH_PREFIXES:
        return f"{SEARCH_PREFIXES.get(key, SEARCH_PREFIXES[root_key])}{limit}:{query}"
    if key in SEARCH_URLS or root_key in SEARCH_URLS:
        return SEARCH_URLS.get(key, SEARCH_URLS[root_key]).format(query=quote(query))
    if key == "instagram" or key.startswith("instagram-"):
        tag = normalized_single_tag(query)
        if tag:
            return f"https://www.instagram.com/explore/tags/{tag}/"
        raise RuntimeError("Instagram text search is not supported by yt-dlp. Paste an Instagram URL or search a single #tag.")
    if key == "tiktok" or key.startswith("tiktok-"):
        tag = normalized_single_tag(query)
        if tag:
            return f"https://www.tiktok.com/tag/{tag}"
        raise RuntimeError("TikTok text search is not supported by yt-dlp. Paste a TikTok URL or search a single #tag.")
    raise RuntimeError(f"{platform_name} text search is not supported by yt-dlp. Paste a {platform_name} URL instead.")


def normalized_single_tag(query: str) -> str:
    tag = query.strip().removeprefix("#")
    if tag and re.fullmatch(r"[A-Za-z0-9_.-]+", tag):
        return tag
    return ""


def item_from_url(url: str) -> MediaItem:
    clean = url.strip()
    return MediaItem(title=clean, url=clean, source="url", content_type=infer_content_type({}, clean))


def infer_content_type(data: dict[str, object], url: str) -> str:
    raw_type = str(data.get("_type") or data.get("ie_key") or "").lower()
    webpage = str(data.get("webpage_url") or url).lower()
    title = str(data.get("title") or "").lower()
    duration = data.get("duration")
    if "playlist" in raw_type or "playlist" in webpage or "list=" in webpage:
        return "playlist"
    if "album" in raw_type or "/album/" in webpage:
        return "album"
    if "/reel/" in webpage or "reel" in raw_type:
        return "reel"
    if "/stories/" in webpage or "story" in raw_type:
        return "story"
    if "/live/" in webpage or "live" in title or "is_live" in data:
        return "live"
    if "/shorts/" in webpage or "short" in raw_type:
        return "short"
    if "profile" in raw_type or re.search(r"/(user|channel|c|@)[^/?#]+/?$", webpage):
        return "profile"
    if "soundcloud" in webpage or "bandcamp" in webpage or data.get("acodec") != "none" and data.get("vcodec") == "none":
        return "audio"
    return "video"


def looks_like_url(value: str) -> bool:
    return value.startswith(("http://", "https://", "ftp://")) or "://" in value


def format_duration(value: object) -> str:
    if not isinstance(value, (int, float)):
        return ""
    seconds = int(value)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def health_checks(use_icons: bool) -> list[tuple[str, str, str]]:
    icon_mode = "Nerd Font" if use_icons else "ASCII"
    checks = [
        ("yt-dlp", "ok" if shutil.which("yt-dlp") else "missing", yt_dlp_version()),
        ("ffmpeg", "ok" if shutil.which("ffmpeg") else "warn", ffmpeg_version()),
        ("terminal", "ok" if os.environ.get("TERM") else "warn", os.environ.get("TERM", "unknown")),
        ("icons", "ok", icon_mode),
    ]
    return checks


def yt_dlp_version() -> str:
    if not shutil.which("yt-dlp"):
        return "install yt-dlp"
    proc = subprocess.run(["yt-dlp", "--version"], text=True, capture_output=True, check=False)
    return proc.stdout.strip() or "available"


def ffmpeg_version() -> str:
    if not shutil.which("ffmpeg"):
        return "needed for merging/conversion"
    proc = subprocess.run(["ffmpeg", "-version"], text=True, capture_output=True, check=False)
    first = proc.stdout.splitlines()[0] if proc.stdout else "available"
    return first.replace("ffmpeg version ", "")


def default_download_dir() -> Path:
    return Path.home() / "Downloads" / "yt-dlp"


def preset_by_index(index: int) -> Preset:
    return PRESETS[index % len(PRESETS)]
