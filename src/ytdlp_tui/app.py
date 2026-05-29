from __future__ import annotations

import curses
import re
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen

from .ansi_shadow import ansi_shadow_banner
from .commands import DEFAULT_SEARCH_LIMIT, QueueJob, command_preview, default_download_dir, health_checks, item_from_url, looks_like_url, native_search_supported, preset_by_index, search, site_search_supported, web_search_spec
from .presets import AUDIO_FORMATS, PRESETS, VIDEO_FORMATS
from .themes import PLATFORMS, ROLE_PAIR, PlatformTheme, ThemeManager, extractor_platforms, match_platform_from_url, platform_label


LOGO = (
    "██╗   ██╗████████╗██████╗       ████████╗██╗   ██╗██╗",
    "╚██╗ ██╔╝╚══██╔══╝██╔══██╗      ╚══██╔══╝██║   ██║██║",
    " ╚████╔╝    ██║   ██║  ██║█████╗   ██║   ██║   ██║██║",
    "  ╚██╔╝     ██║   ██║  ██║╚════╝   ██║   ██║   ██║██║",
    "   ██║      ██║   ██████╔╝         ██║   ╚██████╔╝██║",
    "   ╚═╝      ╚═╝   ╚═════╝          ╚═╝    ╚═════╝ ╚═╝",
)

THUMB_PAIR_BASE = 32
ANSI_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")


class C:
    accent = ROLE_PAIR["accent"]
    accent_fill = ROLE_PAIR["fill"]
    selected = ROLE_PAIR["selected"]
    muted = ROLE_PAIR["muted"]
    ok = ROLE_PAIR["ok"]
    warn = ROLE_PAIR["warn"]
    error = ROLE_PAIR["error"]
    dim = ROLE_PAIR["muted"]
    border = ROLE_PAIR["border"]
    focus = ROLE_PAIR["focus"]


class Glyphs:
    def __init__(self) -> None:
        self.nerd = not os.environ.get("YTDLP_TUI_ASCII")
        self.run = "\U000f040a" if self.nerd else ">"
        self.ok = "\U000f012c" if self.nerd else "+"
        self.fail = "\U000f0159" if self.nerd else "!"
        self.wait = "\U000f06a5" if self.nerd else "."
        self.queue = "\U000f0423" if self.nerd else "#"

    def preset(self, preset) -> str:
        return preset.icon if self.nerd else preset.ascii_icon


class Cockpit:
    def __init__(self, screen) -> None:
        self.screen = screen
        self.g = Glyphs()
        self.theme = ThemeManager()
        self.platform: PlatformTheme = PLATFORMS[0]
        self.results = []
        self.result_offset = 0
        self.jobs: list[QueueJob] = []
        self.selected = 0
        self.last_query = ""
        self.search_text = ""
        self.search_focused = False
        self.searching = False
        self.search_token = 0
        self.search_limit = DEFAULT_SEARCH_LIMIT
        self.preset_index = 0
        self.output_kind = "video"
        self.output_format = VIDEO_FORMATS[0]
        self.needs_redraw = True
        self.output_dir = default_download_dir()
        self.notice = "Press / to search, u for URL, Space to queue, Enter to download."
        self.messages: queue.Queue[object] = queue.Queue()
        self.running = True
        self.ignore_global_q_until = 0.0
        self.health_cache = health_checks(self.g.nerd)
        self.focus_order = ("yt-dlp", "ffmpeg", "terminal", "symbols", "search", "results", "filters", "selection", "queue")
        self.focus_index = 4
        self.filter_dimensions = ("all", "title", "channel", "type")
        self.sort_dimensions = ("relevance", "date", "duration", "type")
        self.filter_index = 0
        self.sort_index = 0
        self.prefix = ""
        self.suffix = ""
        self.thumbnail_url = ""
        self.thumbnail_lines: list[list[tuple[str, int | None, int | None]]] = []
        self.thumbnail_status = ""
        self.thumbnail_thread: threading.Thread | None = None
        self.thumbnail_pairs: dict[tuple[int, int], int] = {}
        self.next_thumbnail_pair = THUMB_PAIR_BASE

    def output_choices(self) -> tuple[Path, ...]:
        defaults = (
            default_download_dir(),
            Path.home() / "Downloads",
            Path.home() / "Desktop",
            Path.cwd(),
        )
        if self.output_dir not in defaults:
            return (self.output_dir, *defaults)
        return defaults

    @property
    def preset(self):
        return preset_by_index(self.preset_index)

    @property
    def video_format(self) -> str:
        return self.output_format if self.output_kind == "video" else "-"

    @property
    def audio_format(self) -> str:
        return self.output_format if self.output_kind == "audio" else "-"

    @property
    def load_more_index(self) -> int | None:
        return len(self.displayed_indices()) if self.results and self.last_query else None

    @property
    def selectable_count(self) -> int:
        return len(self.displayed_indices()) + (1 if self.load_more_index is not None else 0)

    def run(self) -> None:
        try:
            curses.set_escdelay(5)
        except (AttributeError, curses.error):
            pass
        self.cursor(0)
        self.screen.nodelay(True)
        self.screen.keypad(True)
        self.screen.timeout(0)
        self.screen.scrollok(False)
        self.screen.idlok(False)
        self.colors()
        self.enable_mouse_tracking()
        selected_platform = self.platform_selector()
        if not selected_platform or not self.running:
            return
        self.platform = selected_platform
        self.screen.nodelay(True)
        self.theme.apply(self.platform)
        self.loading()
        while self.running:
            self.drain()
            self.handle_pending_keys()
            self.autostart()
            if self.searching or (self.thumbnail_thread and self.thumbnail_thread.is_alive()):
                self.needs_redraw = True
            if self.needs_redraw:
                self.draw()
                self.needs_redraw = False
            time.sleep(0.005)

    def colors(self) -> None:
        self.theme.apply(self.platform)

    def platform_selector(self) -> PlatformTheme | None:
        query = ""
        cursor = 0
        while True:
            matches = self.platform_matches(query)
            if not matches:
                cursor = 0
            else:
                cursor = max(0, min(cursor, len(matches) - 1))
            if matches:
                self.theme.apply(matches[cursor])
            self.draw_platform_selector(query, matches, cursor)
            key = self.read_key(blocking=True)
            if key in (10, 13) and matches:
                return matches[cursor]
            if key in (ord("j"), curses.KEY_DOWN, -1002):
                next_cursor = self.move_platform_cursor(cursor, 1, len(matches))
                if key == -1002 and next_cursor == cursor:
                    self.flush_pending_wheel_events()
                cursor = next_cursor
            elif key in (ord("k"), curses.KEY_UP, -1001):
                next_cursor = self.move_platform_cursor(cursor, -1, len(matches))
                if key == -1001 and next_cursor == cursor:
                    self.flush_pending_wheel_events()
                cursor = next_cursor
            elif key == curses.KEY_NPAGE:
                cursor = self.move_platform_cursor(cursor, 10, len(matches))
            elif key == curses.KEY_PPAGE:
                cursor = self.move_platform_cursor(cursor, -10, len(matches))
            elif key == curses.KEY_MOUSE:
                delta = self.mouse_wheel_delta()
                if delta:
                    next_cursor = self.move_platform_cursor(cursor, delta, len(matches))
                    if next_cursor == cursor:
                        self.flush_pending_wheel_events()
                    cursor = next_cursor
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                query = query[:-1]
            elif key in (ord("q"), ord("Q"), 3):
                if self.confirm_quit_popup():
                    self.running = False
                    return None
            elif 32 <= key <= 126:
                query += chr(key)

    def move_platform_cursor(self, cursor: int, delta: int, count: int) -> int:
        if count <= 0:
            return 0
        return max(0, min(cursor + delta, count - 1))

    def reopen_platform_selector(self) -> None:
        previous = self.platform
        selected = self.platform_selector()
        if not selected:
            self.theme.apply(previous)
            self.needs_redraw = True
            return
        self.platform = selected
        self.theme.apply(selected)
        self.results = []
        self.selected = 0
        self.result_offset = 0
        self.last_query = ""
        self.search_text = ""
        self.searching = False
        self.notice = f"Platform changed to {selected.name}. Press / to search."
        self.needs_redraw = True

    def platform_matches(self, query: str) -> list[PlatformTheme]:
        normalized = query.lower().strip()
        if "://" in normalized or "." in normalized:
            matched = match_platform_from_url(normalized, PLATFORMS + extractor_platforms())
            if matched:
                return [matched]
        base = list(PLATFORMS)
        if len(normalized) >= 2:
            base.extend(extractor_platforms())
        return [
            p
            for p in base
            if not normalized
            or normalized in p.name.lower()
            or normalized in p.key.lower()
            or normalized in p.description.lower()
            or any(normalized in d for d in p.domains)
        ]

    def draw_platform_selector(self, query: str, matches: list[PlatformTheme], cursor: int) -> None:
        self.screen.erase()
        h, w = self.screen.getmaxyx()
        panel_w = min(92, max(54, w - 8))
        panel_h = min(max(20, h - 6), 34)
        x = max(0, (w - panel_w) // 2)
        y = max(0, (h - panel_h) // 2)
        self.box(y, x, panel_h, panel_w, " platform ")
        banner_y = y + 2
        if query:
            label = "select source"
            self.add(banner_y, x + max(2, (panel_w - len(label)) // 2), label, C.accent)
        else:
            logo_w = max(len(line) for line in LOGO)
            if panel_w > logo_w + 4:
                for row, line in enumerate(LOGO):
                    self.add(banner_y + row, x + (panel_w - logo_w) // 2, line, C.accent)
                banner_y += len(LOGO)
            else:
                self.add(banner_y, x + max(2, (panel_w - 9) // 2), " ytd-tui ", C.accent)
        self.add(banner_y + 1, x + max(2, (panel_w - 18) // 2), "powered by ytd-tui", C.dim)
        search_y = banner_y + 3
        self.add(search_y, x + 3, " " * (panel_w - 6), C.accent_fill)
        self.add(search_y, x + 5, cut("Search: " + (query or "major platforms, or type for yt-dlp sites"), panel_w - 10), C.accent_fill)
        list_y = search_y + 2
        list_h = max(4, y + panel_h - list_y - 3)
        start = max(0, min(max(0, len(matches) - list_h), cursor - list_h + 1))
        visible = matches[start : start + list_h]
        row = list_y
        last_tier = ""
        for absolute, platform in enumerate(visible, start):
            if platform.tier != last_tier and row < y + panel_h - 2:
                label = "Major platforms" if platform.tier == "major" else "Niche / alternative platforms"
                self.add(row, x + 3, label, C.accent)
                row += 1
                last_tier = platform.tier
            if row >= y + panel_h - 2:
                break
            marker = ">" if absolute == cursor else " "
            detail = ", ".join(platform.domains[:2]) or platform.description
            text = cut(f"{marker} {platform.name:<30} {detail}", panel_w - 10)
            if absolute == cursor:
                self.add(row, x + 4, f" {text}".ljust(panel_w - 8), C.accent, curses.A_REVERSE, curses.A_BOLD)
            else:
                self.add(row, x + 5, text, C.muted)
            row += 1
        if len(matches) > list_h:
            thumb_h = max(1, int(list_h * list_h / len(matches)))
            thumb_y = list_y + int(start * max(1, list_h - thumb_h) / max(1, len(matches) - list_h))
            for yy in range(list_y, min(y + panel_h - 2, list_y + list_h)):
                char = "█" if thumb_y <= yy < thumb_y + thumb_h else "│"
                self.add(yy, x + panel_w - 4, char, C.accent if char == "█" else C.dim)
        if not matches:
            self.add(list_y, x + 5, "No matching yt-dlp extractor.", C.warn)
        self.add(y + panel_h - 2, x + 3, "Enter selects   type filters   j/k moves   q exits", C.dim)
        self.screen.refresh()

    def loading(self) -> None:
        self.health_cache = health_checks(self.g.nerd)
        steps = [
            ("checking yt-dlp", "downloader engine"),
            ("checking ffmpeg", "merge and conversion support"),
            ("loading presets", f"{len(PRESETS)} presets"),
            ("loading icons", "nerd font" if self.g.nerd else "ascii"),
            ("starting cockpit", str(self.output_dir)),
        ]
        for index, (label, detail) in enumerate(steps, 1):
            self.draw_loading(index, len(steps), label, detail)
            if self.wait(0.2):
                return
        self.draw_loading(len(steps), len(steps), "ready", "press / to search")
        self.wait(0.35)

    def draw_loading(self, done: int, total: int, label: str, detail: str) -> None:
        self.screen.erase()
        h, w = self.screen.getmaxyx()
        bw = min(74, max(44, w - 8))
        banner = ansi_shadow_banner(platform_label(self.platform))
        y = max(1, (h - 20) // 2)
        banner_w = max(len(line) for line in banner) if banner else 0
        banner_x = max(0, (w - banner_w) // 2)
        for row, line in enumerate(banner):
            self.add(y + row, banner_x, line.ljust(banner_w), C.accent)
        self.add(y + len(banner) + 2, max(0, (w - 18) // 2), "powered by ytd-tui", C.dim)
        text_y = y + len(banner) + 4

        center = max(0, (w - bw) // 2)
        self.add(text_y, center + max(0, (bw - 10) // 2), "[] ytd-tui", C.dim)
        self.add(text_y + 2, center + max(0, (bw - len(label) - 5) // 2), f">_ {label}...", C.dim)

        bar_w = bw
        fill = max(1, int(bar_w * done / total))
        self.add(text_y + 4, center, "⣿" * bar_w, C.accent)
        self.add(text_y + 4, center, " " * min(fill, bar_w), C.accent_fill)
        percent = int(done * 100 / total)
        self.add(text_y + 5, center + max(0, (bw - 4) // 2), f"{percent:>3}%", C.dim)
        self.add(text_y + 7, center + max(0, (bw - 30) // 2), f"{done:02d}/{total:02d} checks      {detail}", C.dim)
        self.screen.refresh()

    def draw(self) -> None:
        self.screen.erase()
        h, w = self.screen.getmaxyx()
        if h < 28 or w < 100:
            self.add(0, 0, "Resize terminal to at least 100x28.", C.warn)
            self.screen.refresh()
            return
        info_h = 6
        search_h = 4
        foot = 4
        body_y = info_h + search_h
        body_h = h - body_y - foot
        right_min = 46
        left = min(max(58, int(w * 0.64)), w - right_min)
        right_w = w - left
        details_h = max(9, body_h // 2)
        queue_h = body_h - details_h
        self.dashboard_blocks(0, 0, info_h, w)
        self.box(info_h, 0, search_h, w, " Search ", self.focused("search"))
        self.box(body_y, 0, body_h, left, " Results ", self.focused("results"))
        self.box(body_y, left, details_h, right_w, " Selection ", self.focused("selection"))
        self.box(body_y + details_h, left, queue_h, right_w, f" {self.g.queue} Queue ", self.focused("queue"))
        self.box(h - foot, 0, foot, w, " actions ")
        self.search_bar(info_h + 1, 2, w - 4)
        self.result_list(body_y + 1, 2, body_h - 4, left - 4)
        self.filter_sort_bar(body_y + body_h - 2, 2, left - 4)
        self.selection_panel(body_y + 1, left + 2, details_h - 2, right_w - 4)
        self.queue_list(body_y + details_h + 1, left + 2, queue_h - 2, right_w - 4)
        self.footer(h - foot + 1, 2, w - 4)
        self.screen.noutrefresh()
        curses.doupdate()

    def dashboard_blocks(self, y: int, x: int, height: int, width: int) -> None:
        block_w = max(20, width // 4)
        labels = (" yt-dlp ", " FFmpeg ", " terminal/shell ", " symbols ")
        focus_names = ("yt-dlp", "ffmpeg", "terminal", "symbols")
        for idx, label in enumerate(labels):
            bx = x + idx * block_w
            bw = width - bx if idx == 3 else block_w
            self.box(y, bx, height, bw, label, self.focused(focus_names[idx]))
        self.dashboard(y + 1, x + 2, width - 4, block_w)

    def dashboard(self, y: int, x: int, width: int, block_w: int) -> None:
        checks = self.health_cache
        for idx, (name, state, detail) in enumerate(checks[:4]):
            mark = self.g.ok if state == "ok" else self.g.fail
            color = C.ok if state == "ok" else C.warn
            col = x + idx * block_w
            self.add(y, col, cut(f"{mark} {name}", block_w - 4), color)
            self.add(y + 1, col, cut(str(detail), block_w - 4), C.dim)
            if idx == 0:
                self.add(y + 2, col, cut(f"platform: {self.platform.name}", block_w - 4), C.accent)

    def search_bar(self, y: int, x: int, width: int) -> None:
        cursor = "█" if self.search_focused else ""
        count = f"{len(self.results)}/{self.search_limit}"
        if self.searching:
            spinner = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[int(time.monotonic() * 12) % 10]
            label = f"{spinner} searching {self.platform.name}: {self.last_query}"
        elif self.search_text or self.search_focused:
            label = self.search_text
        else:
            label = f"press / to search · {self.search_mode_hint()}"
        field_w = max(10, width - len(count) - 4)
        field = f"⌕ {label}{cursor}"
        self.add(y, x, " " * width, C.accent_fill)
        self.add(y, x + 2, cut(field, field_w), C.accent_fill)
        self.add(y, x + width - len(count) - 1, count, C.accent_fill)

    def search_mode_hint(self) -> str:
        if native_search_supported(self.platform.key):
            return f"{self.platform.name} native search"
        if site_search_supported(self.platform.key, self.platform.name, self.platform.domains):
            return f"{self.platform.name} site search"
        if web_search_spec(self.platform.key):
            return f"{self.platform.name} web URL search"
        return f"{self.platform.name} URL only"

    def health(self, y: int, x: int, width: int) -> None:
        for row, (name, state, value) in enumerate(self.health_cache):
            mark = self.g.ok if state == "ok" else self.g.fail
            color = C.ok if state == "ok" else C.warn
            self.add(y + row, x, cut(f"{mark} {name:<9} {value}", width), color)

    def result_list(self, y: int, x: int, height: int, width: int) -> None:
        active = self.displayed_indices()
        if not active:
            if self.searching:
                spinner = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[int(time.monotonic() * 12) % 10]
                self.add(y, x, cut(f"{spinner} Searching {self.platform.name} for {self.last_query!r}...", width), C.accent)
                self.add(y + 1, x, cut("This can take a moment for web-backed platforms.", width), C.muted)
                return
            self.add(y, x, cut("No results yet. Press / to search or u to paste a URL.", width), C.muted)
            return
        list_height = max(1, height - 2)
        self.clamp_result_view(list_height)
        total_rows = len(active) + (1 if self.load_more_index is not None else 0)
        visible_indexes = range(self.result_offset, min(total_rows, self.result_offset + list_height))
        num_w = max(2, len(str(max(1, len(active)))))
        scroll_w = 3 if total_rows > list_height else 0
        table_w = width - scroll_w
        type_w = 9
        channel_w = min(28, max(16, table_w // 4))
        type_x = x + num_w + 3
        title_x = type_x + type_w + 2
        title_w = max(12, table_w - num_w - type_w - channel_w - 8)
        channel_x = title_x + title_w + 2
        self.add(y, x + 1, f"{'#':>{num_w}}", C.dim)
        self.add(y, type_x, "TYPE", C.dim)
        self.add(y, title_x, "TITLE", C.dim)
        self.add(y, channel_x, "CHANNEL", C.dim)
        visible_count = 0
        for row, index in enumerate(visible_indexes):
            visible_count += 1
            if self.load_more_index is not None and index == self.load_more_index:
                prefix = ">" if index == self.selected else " "
                text = f"{prefix}{'':>{num_w}} + load 10 more results"
                self.add(y + row + 1, x, cut(text, table_w), C.selected if index == self.selected else C.accent)
                continue
            item = self.results[active[index]]
            prefix = ">" if index == self.selected else " "
            badge = cut(item.content_type.upper(), type_w)
            title = cut(item.title, title_w)
            channel = cut(item.uploader or "-", channel_w)
            line = f"{prefix}{index + 1:>{num_w}} {badge:<{type_w}}  {title:<{title_w}}  {channel}"
            self.add(y + row + 1, x, cut(line, table_w), C.selected if index == self.selected else 0)
        scroll = f"showing {self.result_offset + 1}-{self.result_offset + visible_count} of {total_rows}"
        self.add(y + height - 1, x, cut(scroll, table_w), C.accent)
        if scroll_w:
            self.draw_scrollbar(y + 1, x + width - 2, list_height, total_rows, self.result_offset)

    def filter_sort_bar(self, y: int, x: int, width: int) -> None:
        filter_label = self.filter_dimensions[self.filter_index]
        sort_label = self.sort_dimensions[self.sort_index]
        focus = self.focused("filters")
        text = f"Filter: {filter_label}  < / > cycles     Sort: {sort_label}  s cycles"
        self.add(y, x, cut(text, width), C.selected if focus else C.accent)

    def queue_list(self, y: int, x: int, height: int, width: int) -> None:
        if not self.jobs:
            for row in range(height):
                self.add(y + row, x, " " * width)
            self.add(y, x, cut("Queue is empty. Space queues, Enter queues and starts.", width), C.muted)
            return
        for row in range(height):
            self.add(y + row, x, " " * width)
        row = 0
        for job in self.jobs[-max(1, height // 2):]:
            if row >= height:
                break
            color = {"done": C.ok, "failed": C.error, "running": C.warn}.get(job.status, C.muted)
            bar_w = max(10, min(32, width - 18))
            bar = self.progress_bar(job.percent if job.status != "done" else 100.0, bar_w)
            percent = f"{job.percent:5.1f}%" if job.status == "running" else ("100.0%" if job.status == "done" else "  ---%")
            speed = cut(job.speed or job.status, 10)
            title = cut(job.item.title, max(10, width - 10))
            self.add(y + row, x, cut(f"{job.status:<7} {title}", width), color)
            if row + 1 < height:
                self.add(y + row + 1, x + 2, cut(f"{bar} {percent} {speed}", max(0, width - 2)), color)
            row += 2

    def progress_bar(self, percent: float, width: int) -> str:
        value = max(0.0, min(percent, 100.0))
        filled = int(width * value / 100)
        return "[" + ("█" * filled).ljust(width, "░") + "]"

    def selection_panel(self, y: int, x: int, height: int, width: int) -> None:
        item = self.current()
        if not item:
            if self.load_more_index is not None and self.selected == self.load_more_index:
                lines = [
                    "Load more results.",
                    "",
                    "Press Enter or Space to fetch 10 more.",
                ]
            else:
                lines = [
                    "No selection yet.",
                    "",
                    "Search with /, then use j/k, arrows, or wheel.",
                ]
        else:
            self.ensure_thumbnail(item, width, max(0, height - 8))
            lines = [
                f"title   : {item.title}",
                f"source  : {item.source}",
                f"uploader: {item.uploader or '-'}",
                f"duration: {item.duration or '-'}",
                f"preset  : {self.preset.name}",
                f"output  : {self.output_kind} {self.output_format}",
            ]
        for row, line in enumerate(lines[:height]):
            color = C.accent if row == 0 and item else C.muted
            self.add(y + row, x, cut(line, width), color)
        if item:
            thumb_y = y + min(len(lines) + 1, max(0, height - 2))
            thumb_h = max(0, height - (thumb_y - y) - 1)
            self.thumbnail_panel(thumb_y, x, thumb_h, width)
        hint_y = y + height - 1
        if height > 2:
            self.add(hint_y, x, cut("m play with mpv  Space/Enter confirm  c command", width), C.dim)

    def thumbnail_panel(self, y: int, x: int, height: int, width: int) -> None:
        if height <= 0:
            return
        if self.thumbnail_lines:
            for row, segments in enumerate(self.thumbnail_lines[:height]):
                self.add_thumbnail_line(y + row, x, segments, width)
            return
        if self.thumbnail_status:
            self.add(y, x, cut(self.thumbnail_status, width), C.muted)

    def add_thumbnail_line(self, y: int, x: int, segments: list[tuple[str, int | None, int | None]], width: int) -> None:
        written = 0
        for text, fg, bg in segments:
            if written >= width:
                break
            part = text[: width - written]
            self.add_attr(y, x + written, part, self.thumbnail_attr(fg, bg))
            written += len(part)

    def thumbnail_attr(self, fg: int | None, bg: int | None) -> int:
        if self.theme.mono or not curses.has_colors() or curses.COLORS < 256:
            return self.attr(C.muted)
        color_fg = clamp_ansi_color(fg if fg is not None else 250)
        color_bg = clamp_ansi_color(bg) if bg is not None else -1
        key = (color_fg, color_bg)
        pair = self.thumbnail_pairs.get(key)
        if pair is None:
            max_pairs = getattr(curses, "COLOR_PAIRS", 256)
            if self.next_thumbnail_pair >= max_pairs:
                return self.thumbnail_attr(color_fg, None) if color_bg != -1 else self.attr(C.muted)
            pair = self.next_thumbnail_pair
            self.next_thumbnail_pair += 1
            try:
                curses.init_pair(pair, color_fg, color_bg)
            except curses.error:
                return self.thumbnail_attr(color_fg, None) if color_bg != -1 else self.attr(C.muted)
            self.thumbnail_pairs[key] = pair
        return curses.color_pair(pair)

    def footer(self, y: int, x: int, width: int) -> None:
        item = self.current()
        preview = command_preview(self.preview_job(item).command()) if item else ""
        status_color = C.warn if self.notice.lower().startswith(("search failed", "load more failed")) else (C.accent if self.searching else C.muted)
        self.add(y, x, cut(self.notice, width), status_color)
        self.add(y + 1, x, cut(preview or "Command preview appears after selecting a result.", width), C.muted)
        keys = "[?] help  [p] platform  [/] search  [m] play  [f] formats/location  [j/k/wheel] move  [Space/Enter] confirm  [q] quit"
        self.add(y + 2, x, cut(keys, width), C.accent)

    def handle_pending_keys(self) -> None:
        handled = 0
        while handled < 60:
            key = self.read_key()
            if key == -1:
                return
            self.keys(key)
            self.needs_redraw = True
            handled += 1

    def keys(self, key: int) -> None:
        if self.search_focused:
            self.search_keys(key)
            return
        if key == 9:
            self.focus_index = (self.focus_index + 1) % len(self.focus_order)
            self.needs_redraw = True
            return
        if key in (ord("q"), ord("Q")) and time.monotonic() < self.ignore_global_q_until:
            return
        if key in (ord("q"), ord("Q")):
            self.reopen_platform_selector()
        elif key == 3:
            self.running = False
        elif key == 27:
            self.notice = "Press q to return to platform selection."
        elif key in (ord("j"), curses.KEY_DOWN):
            self.move_selection(1)
        elif key in (ord("k"), curses.KEY_UP):
            self.move_selection(-1)
        elif key == curses.KEY_NPAGE:
            self.move_selection(10)
        elif key == curses.KEY_PPAGE:
            self.move_selection(-10)
        elif key == curses.KEY_MOUSE:
            self.handle_curses_mouse()
        elif key == -1001:
            self.move_selection(-1)
        elif key == -1002:
            self.move_selection(1)
        elif key == ord("?"):
            self.help_popup()
        elif key == ord("p"):
            self.reopen_platform_selector()
        elif self.focused("filters") and key in (curses.KEY_RIGHT, ord("l")):
            self.filter_index = (self.filter_index + 1) % len(self.filter_dimensions)
            self.selected = 0
            self.result_offset = 0
        elif self.focused("filters") and key in (curses.KEY_LEFT, ord("h")):
            self.filter_index = (self.filter_index - 1) % len(self.filter_dimensions)
            self.selected = 0
            self.result_offset = 0
        elif self.focused("filters") and key == ord("s"):
            self.sort_index = (self.sort_index + 1) % len(self.sort_dimensions)
            self.selected = 0
            self.result_offset = 0
        elif key in (ord("f"), ord("o")):
            self.options_popup()
        elif key == ord("/"):
            self.search_focused = True
            self.notice = "Type search terms, Enter to search, q/Esc to leave search."
        elif key == ord("u"):
            value = self.prompt("Paste URL")
            if value:
                self.apply_platform_from_url(value)
                self.results.insert(0, item_from_url(value))
                self.selected = 0
                self.notice = "URL added."
        elif key in (ord("1"), ord("2"), ord("3"), ord("4")):
            self.preset_index = key - ord("1")
            self.notice = f"Preset changed to {self.preset.name}."
        elif key == ord("v"):
            self.cycle_output("video")
        elif key == ord("a"):
            self.cycle_output("audio")
        elif key == ord(" "):
            if self.is_load_more_selected():
                self.load_more_results()
                return
            self.confirm_selected(start_after=False)
        elif key in (10, 13, ord("d")):
            if self.is_load_more_selected():
                self.load_more_results()
                return
            self.confirm_selected(start_after=True)
        elif key == ord("c"):
            item = self.current()
            if item and item.content_type == "search":
                self.notice = item.url
            else:
                self.notice = command_preview(self.preview_job(item).command()) if item else "No item selected."
        elif key == ord("m"):
            self.play_current()
        elif key == ord("x"):
            self.jobs = [job for job in self.jobs if job.status not in {"done", "failed"}]
            self.notice = "Cleared completed jobs."
    def confirm_selected(self, start_after: bool) -> None:
        item = self.current()
        if not item:
            self.notice = "Nothing selected."
            return
        if item.content_type == "search":
            self.open_url(item.url)
            self.notice = f"Opened search page: {item.url}"
            self.needs_redraw = True
            return
        cursor = 0
        title_override = item.title
        while True:
            h, w = self.screen.getmaxyx()
            bw = min(86, max(58, w - 10))
            bh = 16
            y = max(1, (h - bh) // 2)
            x = max(0, (w - bw) // 2)
            self.draw()
            self.box(y, x, bh, bw, " confirm download ")
            lines = [
                ("Title", f"title   : {title_override}", True),
                ("Output", f"output  : {self.output_kind} {self.output_format}", True),
                ("Folder", f"folder  : {self.output_dir}", True),
                ("Channel", f"channel : {item.uploader or '-'}", False),
                ("Duration", f"duration: {item.duration or '-'}", False),
                ("Preset", f"preset  : {self.preset.name}", False),
                ("Blank", "", False),
                ("Help", "Enter edits selected   y downloads   m plays   q/Esc cancels", False),
                ("Help", "t title   o output format   f folder", False),
            ]
            selectable = [idx for idx, (_, _, can_select) in enumerate(lines) if can_select]
            cursor = max(0, min(cursor, len(selectable) - 1))
            selected_line = selectable[cursor]
            for row, (_, line, can_select) in enumerate(lines):
                marker = ">" if row == selected_line else " "
                text = f"{marker} {line}" if can_select else f"  {line}"
                color = C.selected if row == selected_line else (C.accent if can_select else C.muted)
                self.add(y + 2 + row, x + 3, cut(text, bw - 6), color)
            self.screen.refresh()
            key = self.read_key(blocking=True)
            if key in (ord("q"), ord("Q"), 27):
                self.close_modal_guard()
                self.notice = "Download cancelled."
                self.screen.nodelay(True)
                return
            if key in (ord("j"), curses.KEY_DOWN):
                cursor = min(cursor + 1, len(selectable) - 1)
                continue
            if key in (ord("k"), curses.KEY_UP):
                cursor = max(cursor - 1, 0)
                continue
            if key == ord("t"):
                new_title = self.prompt("Output title")
                if new_title:
                    title_override = new_title
                continue
            if key == ord("o"):
                self.output_popup()
                continue
            if key == ord("f"):
                self.folder_popup()
                continue
            if key == ord("m"):
                self.play_item(item)
                self.screen.nodelay(True)
                return
            if key in (10, 13):
                selected_name = lines[selected_line][0]
                if selected_name == "Title":
                    new_title = self.prompt("Output title")
                    if new_title:
                        title_override = new_title
                elif selected_name == "Output":
                    self.output_popup()
                elif selected_name == "Folder":
                    self.folder_popup()
                continue
            if key in (ord("y"), ord("Y")):
                self.queue_item(item, title_override)
                if start_after:
                    self.autostart()
                self.screen.nodelay(True)
                return

    def output_popup(self) -> None:
        options = [("video", fmt) for fmt in VIDEO_FORMATS] + [("audio", fmt) for fmt in AUDIO_FORMATS]
        cursor = next((idx for idx, (kind, fmt) in enumerate(options) if kind == self.output_kind and fmt == self.output_format), 0)
        while True:
            h, w = self.screen.getmaxyx()
            bw = min(52, max(34, w - 10))
            bh = min(len(options) + 5, h - 4)
            y = max(1, (h - bh) // 2)
            x = max(0, (w - bw) // 2)
            self.draw()
            self.box(y, x, bh, bw, " output format ")
            visible_h = bh - 4
            start = max(0, min(cursor - visible_h + 1, max(0, len(options) - visible_h)))
            for row, (kind, fmt) in enumerate(options[start : start + visible_h]):
                absolute = start + row
                active = kind == self.output_kind and fmt == self.output_format
                marker = ">" if absolute == cursor else " "
                check = "*" if active else " "
                self.add(y + 2 + row, x + 3, cut(f"{marker} [{check}] {kind} {fmt}", bw - 6), C.selected if absolute == cursor else C.muted)
            self.add(y + bh - 2, x + 3, cut("Enter selects   q/Esc cancels", bw - 6), C.dim)
            self.screen.refresh()
            key = self.read_key(blocking=True)
            if key in (ord("q"), ord("Q"), 27):
                self.close_modal_guard()
                return
            if key in (ord("j"), curses.KEY_DOWN):
                cursor = min(cursor + 1, len(options) - 1)
            elif key in (ord("k"), curses.KEY_UP):
                cursor = max(cursor - 1, 0)
            elif key in (10, 13):
                self.output_kind, self.output_format = options[cursor]
                self.notice = f"Output: {self.output_kind} {self.output_format}"
                self.needs_redraw = True
                return

    def folder_popup(self) -> None:
        cursor = 0
        while True:
            choices = list(self.output_choices()) + ["Custom path..."]
            h, w = self.screen.getmaxyx()
            bw = min(76, max(44, w - 10))
            bh = min(len(choices) + 5, h - 4)
            y = max(1, (h - bh) // 2)
            x = max(0, (w - bw) // 2)
            self.draw()
            self.box(y, x, bh, bw, " output folder ")
            visible_h = bh - 4
            start = max(0, min(cursor - visible_h + 1, max(0, len(choices) - visible_h)))
            for row, choice in enumerate(choices[start : start + visible_h]):
                absolute = start + row
                label = str(choice)
                active = label == str(self.output_dir)
                marker = ">" if absolute == cursor else " "
                check = "*" if active else " "
                self.add(y + 2 + row, x + 3, cut(f"{marker} [{check}] {label}", bw - 6), C.selected if absolute == cursor else C.muted)
            self.add(y + bh - 2, x + 3, cut("Enter selects   c custom   q/Esc cancels", bw - 6), C.dim)
            self.screen.refresh()
            key = self.read_key(blocking=True)
            if key in (ord("q"), ord("Q"), 27):
                self.close_modal_guard()
                return
            if key in (ord("j"), curses.KEY_DOWN):
                cursor = min(cursor + 1, len(choices) - 1)
            elif key in (ord("k"), curses.KEY_UP):
                cursor = max(cursor - 1, 0)
            elif key == ord("c"):
                self.set_custom_output()
                return
            elif key in (10, 13):
                choice = choices[cursor]
                if isinstance(choice, str):
                    self.set_custom_output()
                else:
                    self.output_dir = choice
                    self.notice = f"Output folder: {self.output_dir}"
                    self.needs_redraw = True
                return

    def options_popup(self) -> None:
        cursor = 0
        fields = ("Preset", "Output", "Folder", "Prefix", "Suffix")
        while True:
            h, w = self.screen.getmaxyx()
            bw = min(86, max(62, w - 10))
            bh = 13
            y = max(1, (h - bh) // 2)
            x = max(0, (w - bw) // 2)
            self.draw()
            self.box(y, x, bh, bw, " formats / location ")
            values = (
                self.preset.name,
                f"{self.output_kind} {self.output_format}",
                str(self.output_dir),
                self.prefix or "-",
                self.suffix or "-",
            )
            for row, (field, value) in enumerate(zip(fields, values)):
                selected = row == cursor
                marker = ">" if selected else " "
                text = f"{marker} {field:<8}: {value}"
                self.add(y + 2 + row, x + 3, cut(text, bw - 6), C.selected if selected else C.muted)
            self.add(y + 9, x + 3, cut("Enter edits selected field", bw - 6), C.dim)
            self.add(y + 10, x + 3, cut("p preset   o output   f folder   q/Esc exits", bw - 6), C.dim)
            self.screen.refresh()
            key = self.read_key(blocking=True)
            if key in (ord("q"), ord("Q"), 27):
                self.close_modal_guard()
                self.screen.nodelay(True)
                return
            if key in (ord("j"), curses.KEY_DOWN):
                cursor = min(cursor + 1, len(fields) - 1)
            elif key in (ord("k"), curses.KEY_UP):
                cursor = max(cursor - 1, 0)
            elif key == ord("p"):
                self.preset_popup()
            elif key == ord("o"):
                self.output_popup()
            elif key == ord("f"):
                self.folder_popup()
            elif key in (10, 13):
                field = fields[cursor]
                if field == "Preset":
                    self.preset_popup()
                elif field == "Output":
                    self.output_popup()
                elif field == "Folder":
                    self.folder_popup()
                elif field == "Prefix":
                    value = self.prompt("Filename prefix")
                    if value or value == "":
                        self.prefix = value
                elif field == "Suffix":
                    value = self.prompt("Filename suffix")
                    if value or value == "":
                        self.suffix = value
                self.needs_redraw = True

    def preset_popup(self) -> None:
        cursor = self.preset_index
        while True:
            h, w = self.screen.getmaxyx()
            bw = min(52, max(34, w - 10))
            bh = min(len(PRESETS) + 5, h - 4)
            y = max(1, (h - bh) // 2)
            x = max(0, (w - bw) // 2)
            self.draw()
            self.box(y, x, bh, bw, " preset ")
            for row, preset in enumerate(PRESETS[: bh - 4]):
                selected = row == cursor
                check = "*" if row == self.preset_index else " "
                self.add(y + 2 + row, x + 3, cut(f"{'>' if selected else ' '} [{check}] {preset.name}", bw - 6), C.selected if selected else C.muted)
            self.add(y + bh - 2, x + 3, cut("Enter selects   q/Esc cancels", bw - 6), C.dim)
            self.screen.refresh()
            key = self.read_key(blocking=True)
            if key in (ord("q"), ord("Q"), 27):
                self.close_modal_guard()
                return
            if key in (ord("j"), curses.KEY_DOWN):
                cursor = min(cursor + 1, len(PRESETS) - 1)
            elif key in (ord("k"), curses.KEY_UP):
                cursor = max(cursor - 1, 0)
            elif key in (10, 13):
                self.preset_index = cursor
                self.needs_redraw = True
                return

    def option_active(self, group: str, label: str) -> bool:
        if group == "Preset":
            return label == self.preset.name
        if group == "Output":
            return label == f"{self.output_kind} {self.output_format}"
        if group == "Location":
            return label == str(self.output_dir)
        return False

    def set_custom_output(self) -> None:
        value = self.prompt("Custom output folder")
        if value:
            self.output_dir = Path(value).expanduser()
            self.notice = f"Output folder: {self.output_dir}"
            self.needs_redraw = True

    def do_search(self) -> None:
        if self.searching:
            self.notice = "Search already running..."
            self.needs_redraw = True
            return
        value = self.search_text.strip()
        if not value:
            self.search_focused = True
            self.notice = "Type search terms, Enter to search, q/Esc to leave search."
            return
        self.search_focused = False
        self.apply_platform_from_url(value)
        self.last_query = value
        self.search_limit = DEFAULT_SEARCH_LIMIT
        mode = self.search_mode_hint()
        self.notice = f"Searching {self.platform.name} for {value!r} ({mode})..."
        self.results = []
        self.selected = 0
        self.result_offset = 0
        self.searching = True
        self.search_token += 1
        token = self.search_token
        platform_key = self.platform.key
        platform_name = self.platform.name
        domains = self.platform.domains
        limit = self.search_limit
        threading.Thread(target=self.search_worker, args=(token, value, limit, platform_key, platform_name, domains), daemon=True).start()
        self.needs_redraw = True

    def search_worker(self, token: int, value: str, limit: int, platform_key: str, platform_name: str, domains: tuple[str, ...]) -> None:
        try:
            items = search(value, limit, platform_key, platform_name, domains)
            self.messages.put(("search_done", token, items, platform_name))
        except Exception as exc:
            self.messages.put(("search_error", token, str(exc)))

    def apply_platform_from_url(self, value: str) -> None:
        if not looks_like_url(value):
            return
        candidates = tuple(list(PLATFORMS) + list(extractor_platforms()))
        platform = match_platform_from_url(value, candidates)
        if platform:
            self.platform = platform
            self.theme.apply(platform)
            self.needs_redraw = True

    def search_keys(self, key: int) -> None:
        if key in (10, 13):
            self.do_search()
            return
        if key == 27:
            self.search_focused = False
            self.notice = "Search cancelled."
            return
        if key in (ord("q"), ord("Q")):
            self.search_focused = False
            self.notice = "Left search."
            self.ignore_global_q_until = time.monotonic() + 0.3
            return
        if key == 3 and not self.search_text:
            self.running = False
            return
        if key in (curses.KEY_BACKSPACE, 127, 8):
            self.search_text = self.search_text[:-1]
            return
        if key == curses.KEY_MOUSE:
            self.handle_curses_mouse()
            return
        if key in (-1001, -1002):
            return
        if 32 <= key <= 126:
            self.search_text += chr(key)

    def prompt(self, label: str) -> str:
        self.cursor(1)
        self.screen.nodelay(False)
        h, w = self.screen.getmaxyx()
        box_w = max(40, w - 8)
        y = max(1, h // 3)
        x = max(0, (w - box_w) // 2)
        self.box(y, x, 5, box_w, f" {label} ")
        self.add(y + 2, x + 3, f"{label}: ", C.accent)
        curses.echo()
        try:
            return self.screen.getstr(y + 2, x + len(label) + 5, box_w - len(label) - 8).decode(errors="ignore").strip()
        finally:
            curses.noecho()
            self.cursor(0)
            self.screen.nodelay(True)

    def queue_selected(self) -> None:
        item = self.current()
        if not item:
            self.notice = "Nothing selected."
            return
        self.queue_item(item, item.title)

    def play_current(self) -> None:
        item = self.current()
        if not item:
            self.notice = "No item selected to play."
            self.needs_redraw = True
            return
        self.play_item(item)

    def play_item(self, item) -> None:
        if item.content_type == "search":
            self.open_url(item.url)
            self.notice = f"Opened search page: {item.url}"
            self.needs_redraw = True
            return
        mpv = shutil.which("mpv")
        if not mpv:
            self.notice = "mpv is not installed or not on PATH."
            self.needs_redraw = True
            return
        subprocess.Popen([mpv, "--force-window=yes", item.url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.notice = f"Playing with mpv: {item.title}"
        self.needs_redraw = True

    def open_url(self, url: str) -> None:
        if sys.platform == "darwin":
            command = ["open", url]
        elif shutil.which("xdg-open"):
            command = ["xdg-open", url]
        else:
            self.notice = f"Open this URL: {url}"
            self.needs_redraw = True
            return
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    def ensure_thumbnail(self, item, width: int, height: int) -> None:
        if self.thumbnail_url == item.thumbnail:
            return
        self.thumbnail_url = item.thumbnail
        self.thumbnail_lines = []
        self.thumbnail_pairs = {}
        self.next_thumbnail_pair = THUMB_PAIR_BASE
        if not item.thumbnail:
            self.thumbnail_status = "No thumbnail available."
            return
        if not shutil.which("chafa"):
            self.thumbnail_status = "Install chafa to show thumbnails."
            return
        self.thumbnail_status = "Loading thumbnail..."
        cols = max(16, min(width, 54))
        rows = max(6, min(height, 16))
        self.thumbnail_thread = threading.Thread(target=self.thumbnail_worker, args=(item.thumbnail, cols, rows), daemon=True)
        self.thumbnail_thread.start()

    def thumbnail_worker(self, url: str, cols: int, rows: int) -> None:
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0 ytd-tui/1.0"})
            with urlopen(request, timeout=12) as response:
                data = response.read()
            with tempfile.NamedTemporaryFile(suffix=".jpg") as file:
                file.write(data)
                file.flush()
                proc = subprocess.run(
                    [
                        "chafa",
                        "--format",
                        "symbols",
                        "--colors",
                        "full" if self.theme.tier == "truecolor" else "256",
                        "--symbols",
                        "vhalf",
                        "--dither",
                        "none",
                        "--color-space",
                        "din99d",
                        "--font-ratio",
                        "1/2",
                        "--polite",
                        "on",
                        "--relative",
                        "off",
                        "--animate",
                        "off",
                        "--size",
                        f"{cols}x{rows}",
                        file.name,
                    ],
                    text=True,
                    capture_output=True,
                    timeout=12,
                    check=False,
                )
            if self.thumbnail_url == url:
                self.thumbnail_lines = [parse_ansi_thumbnail_line(line.rstrip()) for line in proc.stdout.splitlines() if strip_control_sequences(line).strip()]
                self.thumbnail_status = "" if self.thumbnail_lines else "Thumbnail render failed."
                self.needs_redraw = True
        except Exception as exc:
            if self.thumbnail_url == url:
                self.thumbnail_status = f"Thumbnail failed: {exc}"
                self.needs_redraw = True

    def queue_item(self, item, title_override: str = "") -> None:
        if item.content_type == "search":
            self.open_url(item.url)
            self.notice = f"Opened search page: {item.url}"
            self.needs_redraw = True
            return
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.jobs.append(self.preview_job(item, title_override))
        self.notice = f"Queued: {item.title}"
        self.needs_redraw = True

    def preview_job(self, item, title_override: str = "") -> QueueJob:
        return QueueJob(item, self.preset, self.output_dir, self.output_kind, self.output_format, title_override, self.prefix, self.suffix)

    def autostart(self) -> None:
        if any(job.status == "running" for job in self.jobs):
            return
        for job in self.jobs:
            if job.status == "queued":
                self.start(job)
                break

    def start(self, job: QueueJob) -> None:
        job.status = "running"
        job.process = subprocess.Popen(job.command(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        threading.Thread(target=self.watch, args=(job,), daemon=True).start()
        self.needs_redraw = True

    def watch(self, job: QueueJob) -> None:
        assert job.process and job.process.stdout
        for line in job.process.stdout:
            clean = line.strip()
            job.last_line = clean
            if "[download]" in clean and "%" in clean:
                match = re.search(r"(\d+(?:\.\d+)?)%", clean)
                if match:
                    job.percent = float(match.group(1))
                    job.progress = f"{job.percent:.1f}%"
                    self.needs_redraw = True
                parts = clean.split()
                job.speed = next((part for part in parts if "/s" in part), job.speed)
        code = job.process.wait()
        job.status = "done" if code == 0 else "failed"
        if job.status == "done":
            job.percent = 100.0
            job.progress = "100.0%"
        self.messages.put(f"{job.status.upper()}: {job.item.title}")

    def drain(self) -> None:
        while True:
            try:
                message = self.messages.get_nowait()
                if isinstance(message, tuple) and message and message[0] == "search_done":
                    _, token, items, platform_name = message
                    if token != self.search_token:
                        continue
                    self.results = items
                    self.selected = 0
                    self.result_offset = 0
                    self.searching = False
                    self.notice = f"Found {len(items)} {platform_name} result{'s' if len(items) != 1 else ''}."
                elif isinstance(message, tuple) and message and message[0] == "search_error":
                    _, token, error = message
                    if token != self.search_token:
                        continue
                    self.results = []
                    self.selected = 0
                    self.result_offset = 0
                    self.searching = False
                    self.notice = f"Search failed: {error}"
                else:
                    self.notice = str(message)
                self.needs_redraw = True
            except queue.Empty:
                return

    def current(self):
        active = self.displayed_indices()
        if not active:
            return None
        if self.load_more_index is not None and self.selected == self.load_more_index:
            return None
        selected = max(0, min(self.selected, len(active) - 1))
        return self.results[active[selected]]

    def displayed_indices(self) -> list[int]:
        query = self.last_query.lower().strip()
        dimension = self.filter_dimensions[self.filter_index]
        indices = list(range(len(self.results)))
        if query and dimension != "all":
            def matches(index: int) -> bool:
                item = self.results[index]
                if dimension == "title":
                    return query in item.title.lower()
                if dimension == "channel":
                    return query in item.uploader.lower()
                if dimension == "type":
                    return query in item.content_type.lower()
                return True
            indices = [index for index in indices if matches(index)]
        sort_key = self.sort_dimensions[self.sort_index]
        if sort_key == "type":
            indices.sort(key=lambda index: self.results[index].content_type)
        elif sort_key == "duration":
            indices.sort(key=lambda index: duration_seconds(self.results[index].duration), reverse=True)
        elif sort_key == "date":
            indices.sort(key=lambda index: self.results[index].upload_date, reverse=True)
        return indices

    def is_load_more_selected(self) -> bool:
        return self.load_more_index is not None and self.selected == self.load_more_index

    def move_selection(self, delta: int) -> None:
        if not self.results:
            return
        self.selected = max(0, min(self.selected + delta, self.selectable_count - 1))
        h, _ = self.screen.getmaxyx()
        visible_height = max(1, h - 6 - 4 - 4 - 2)
        self.clamp_result_view(visible_height)
        self.needs_redraw = True

    def cycle_output(self, kind: str) -> None:
        formats = VIDEO_FORMATS if kind == "video" else AUDIO_FORMATS
        if self.output_kind == kind and self.output_format in formats:
            index = (formats.index(self.output_format) + 1) % len(formats)
        else:
            index = 0
        self.output_kind = kind
        self.output_format = formats[index]
        self.notice = f"Output: {self.output_kind} {self.output_format}"
        self.needs_redraw = True

    def clamp_result_view(self, visible_height: int) -> None:
        padding = min(4, max(1, visible_height // 4))
        if self.selected < self.result_offset + padding:
            self.result_offset = self.selected - padding
        elif self.selected >= self.result_offset + visible_height - padding:
            self.result_offset = self.selected - visible_height + padding + 1
        max_offset = max(0, self.selectable_count - visible_height)
        self.result_offset = max(0, min(self.result_offset, max_offset))

    def draw_scrollbar(self, y: int, x: int, height: int, total: int, offset: int) -> None:
        if height <= 0 or total <= height:
            return
        thumb_h = max(1, int(height * height / total))
        max_offset = max(1, total - height)
        thumb_y = y + int((height - thumb_h) * offset / max_offset)
        self.add(y, x, "↑", C.accent)
        self.add(y + height - 1, x, "↓", C.accent)
        for row in range(1, max(1, height - 1)):
            color = C.accent if thumb_y <= y + row < thumb_y + thumb_h else C.dim
            self.add(y + row, x, "┃", color)

    def load_more_results(self) -> None:
        if not self.last_query:
            self.notice = "Search first, then select the load-more row."
            return
        self.search_limit += 10
        self.notice = f"Loading {self.search_limit} {self.platform.name} results for {self.last_query!r}..."
        self.draw()
        try:
            current_selected = self.selected
            self.results = search(self.last_query, self.search_limit, self.platform.key, self.platform.name, self.platform.domains)
            self.selected = min(current_selected, max(0, len(self.results) - 1))
            self.notice = f"Loaded {len(self.results)} {self.platform.name} result{'s' if len(self.results) != 1 else ''}."
            self.needs_redraw = True
        except Exception as exc:
            self.search_limit -= 10
            self.notice = f"Load more failed: {exc}"
            self.needs_redraw = True

    def help_popup(self) -> None:
        h, w = self.screen.getmaxyx()
        lines = [
            "YTD-TUI commands",
            "",
            "/      focus inline search",
            "Enter  search when the search field is active",
            "q/Esc  leave search field",
            "p      reopen social media picker",
            "m      play selected item with mpv",
            "f/o    open formats and location popup",
            "u      paste URL",
            "j/k    move selection",
            "wheel  scroll results",
            "1-4    choose preset",
            "v/a    quick-cycle video/audio formats",
            "Space  confirm selected item",
            "Enter  confirm selected item and start",
            "d      start queue",
            "c      show generated yt-dlp command",
            "x      clear completed jobs",
            "q      quit",
            "",
            "Press any key to close.",
        ]
        bw = min(max(len(line) for line in lines) + 6, max(40, w - 4))
        bh = min(len(lines) + 4, max(10, h - 2))
        y = max(0, (h - bh) // 2)
        x = max(0, (w - bw) // 2)
        self.box(y, x, bh, bw, " help ")
        for row, line in enumerate(lines[: bh - 4]):
            color = C.accent if row == 0 else C.muted
            self.add(y + 2 + row, x + 3, cut(line, bw - 6), color)
        self.screen.refresh()
        self.screen.nodelay(False)
        try:
            key = self.read_key(blocking=True)
            if key in (ord("q"), ord("Q"), 3):
                self.running = False
        finally:
            self.screen.nodelay(True)

    def focused(self, name: str) -> bool:
        return self.focus_order[self.focus_index] == name

    def confirm_quit_popup(self) -> bool:
        cursor = 1
        options = ("Quit", "Cancel")
        while True:
            h, w = self.screen.getmaxyx()
            bw = min(58, max(40, w - 6))
            bh = 9
            y = max(1, (h - bh) // 2)
            x = max(0, (w - bw) // 2)
            self.box(y, x, bh, bw, " quit ytd-tui? ")
            self.add(y + 2, x + 3, cut("Are you sure you want to quit?", bw - 6), C.accent)
            self.add(y + 3, x + 3, cut("Unsaved queue activity will stop.", bw - 6), C.muted)
            option_w = 14
            total_w = option_w * len(options) + 2
            start_x = x + max(3, (bw - total_w) // 2)
            for index, option in enumerate(options):
                selected = index == cursor
                text = f" {option.center(option_w - 2)} "
                self.add(y + 5, start_x + index * (option_w + 2), text, C.accent if selected else C.muted, curses.A_REVERSE if selected else 0, curses.A_BOLD if selected else 0)
            self.add(y + 7, x + 3, cut("Left/Right selects   Enter confirms", bw - 6), C.dim)
            self.screen.refresh()
            key = self.read_key(blocking=True)
            if key in (curses.KEY_LEFT, ord("h"), curses.KEY_RIGHT, ord("l"), 9):
                cursor = 1 - cursor
            elif key in (ord("y"), ord("Y")):
                return True
            elif key in (ord("n"), ord("N"), ord("q"), ord("Q"), 27):
                return False
            elif key in (10, 13):
                return cursor == 0

    def close_modal_guard(self) -> None:
        self.ignore_global_q_until = time.monotonic() + 1.0
        try:
            curses.flushinp()
        except curses.error:
            pass

    def box(self, y: int, x: int, h: int, w: int, title: str, focused: bool = False) -> None:
        try:
            win = self.screen.derwin(h, w, y, x)
            win.scrollok(False)
            win.idlok(False)
            border_attr = self.attr(C.focus if focused else C.border) | (curses.A_BOLD if focused else 0)
            win.attron(border_attr)
            win.box()
            win.attroff(border_attr)
            for row in range(1, max(1, h - 1)):
                win.addnstr(row, 1, " " * max(0, w - 2), max(0, w - 2))
            win.addstr(0, 2, cut(title, max(0, w - 4)), self.attr(C.focus if focused else C.accent))
        except curses.error:
            pass

    def add(self, y: int, x: int, text: str, color: int = 0, *styles: int) -> None:
        try:
            h, w = self.screen.getmaxyx()
            if y < 0 or y >= h or x < 0 or x >= w:
                return
            attr = self.attr(color)
            for style in styles:
                attr |= style
            self.screen.addnstr(y, x, text, max(0, w - x - 1), attr)
        except curses.error:
            pass

    def add_attr(self, y: int, x: int, text: str, attr: int) -> None:
        try:
            h, w = self.screen.getmaxyx()
            if y < 0 or y >= h or x < 0 or x >= w:
                return
            self.screen.addnstr(y, x, text, max(0, w - x - 1), attr)
        except curses.error:
            pass

    def attr(self, pair_id: int) -> int:
        if pair_id == 0:
            return 0
        if self.theme.mono:
            if pair_id in {C.accent, C.focus, C.selected}:
                return curses.A_BOLD
            if pair_id in {C.dim, C.muted}:
                return curses.A_DIM
            return 0
        return curses.color_pair(pair_id)

    def cursor(self, state: int) -> None:
        try:
            curses.curs_set(state)
        except curses.error:
            pass

    def enable_mouse_tracking(self) -> None:
        try:
            curses.mousemask(curses.ALL_MOUSE_EVENTS)
        except curses.error:
            pass
        sys.stdout.write("\x1b[?1003l\x1b[?1002l\x1b[?1000h\x1b[?1006h")
        sys.stdout.flush()

    def consume_mouse(self) -> None:
        try:
            curses.getmouse()
        except curses.error:
            pass

    def handle_curses_mouse(self) -> None:
        delta = self.mouse_wheel_delta()
        if delta < 0:
            self.move_selection(-1)
        elif delta > 0:
            self.move_selection(1)

    def mouse_wheel_delta(self) -> int:
        try:
            _, _, _, _, state = curses.getmouse()
        except curses.error:
            return 0
        if hasattr(curses, "BUTTON4_PRESSED") and state & curses.BUTTON4_PRESSED:
            return -1
        if hasattr(curses, "BUTTON5_PRESSED") and state & curses.BUTTON5_PRESSED:
            return 1
        return 0

    def flush_pending_wheel_events(self) -> None:
        self.screen.nodelay(True)
        while True:
            key = self.screen.getch()
            if key == -1:
                break
            if key == curses.KEY_MOUSE:
                self.consume_mouse()
                continue
            if key != 27:
                continue
            deadline = time.monotonic() + 0.01
            while time.monotonic() < deadline:
                next_key = self.screen.getch()
                if next_key == -1:
                    break

    def read_key(self, blocking: bool = False) -> int:
        if blocking:
            self.screen.nodelay(False)
        try:
            key = self.screen.getch()
            if key == 27:
                return self.read_escape_sequence()
            return key
        finally:
            if blocking:
                self.screen.nodelay(True)

    def read_escape_sequence(self) -> int:
        self.screen.nodelay(True)
        chars = ["\x1b"]
        deadline = time.monotonic() + 0.012
        while time.monotonic() < deadline:
            try:
                key = self.screen.getch()
            except curses.error:
                break
            if key == -1:
                time.sleep(0.001)
                continue
            char = chr(key) if 0 <= key < 256 else ""
            chars.append(char)
            seq = "".join(chars)
            if re.match(r"\x1b\[<\d+;\d+;\d+[mM]$", seq):
                break
            deadline = time.monotonic() + 0.004
        seq = "".join(chars)
        if len(chars) > 1 and not seq.startswith("\x1b["):
            next_key = ord(chars[1])
            if next_key in (ord("q"), ord("Q"), 3):
                return next_key
        match = re.match(r"\x1b\[<(?P<button>\d+);\d+;\d+[mM]", seq)
        if match:
            button = int(match.group("button"))
            if button == 64:
                return -1001
            if button == 65:
                return -1002
            return -1
        return 27

    def wait(self, seconds: float) -> bool:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            key = self.read_key()
            if key in (ord("q"), ord("Q"), 3):
                self.running = False
                return True
            if key == curses.KEY_MOUSE:
                self.consume_mouse()
            time.sleep(0.02)
        return False


def cut(value: object, width: int) -> str:
    text = str(value)
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    return text[: max(0, width - 1)] + "…"


def strip_control_sequences(value: str) -> str:
    return re.sub(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|[PX^_].*?\x1b\\)", "", value)


def parse_ansi_thumbnail_line(value: str) -> list[tuple[str, int | None, int | None]]:
    segments: list[tuple[str, int | None, int | None]] = []
    fg: int | None = None
    bg: int | None = None
    cursor = 0
    for match in ANSI_SGR_RE.finditer(value):
        if match.start() > cursor:
            segments.append((value[cursor : match.start()], fg, bg))
        fg, bg = apply_sgr_codes(match.group(1), fg, bg)
        cursor = match.end()
    if cursor < len(value):
        segments.append((value[cursor:], fg, bg))
    return [(text, seg_fg, seg_bg) for text, seg_fg, seg_bg in segments if text]


def apply_sgr_codes(raw: str, fg: int | None, bg: int | None) -> tuple[int | None, int | None]:
    codes = [0] if raw == "" else [int(part) if part.isdigit() else 0 for part in raw.split(";")]
    index = 0
    while index < len(codes):
        code = codes[index]
        if code == 0:
            fg = None
            bg = None
        elif code == 39:
            fg = None
        elif code == 49:
            bg = None
        elif 30 <= code <= 37:
            fg = code - 30
        elif 90 <= code <= 97:
            fg = code - 90 + 8
        elif 40 <= code <= 47:
            bg = code - 40
        elif 100 <= code <= 107:
            bg = code - 100 + 8
        elif code in {38, 48} and index + 2 < len(codes):
            if codes[index + 1] == 5:
                if code == 38:
                    fg = codes[index + 2]
                else:
                    bg = codes[index + 2]
                index += 2
            elif codes[index + 1] == 2 and index + 4 < len(codes):
                color = rgb_to_ansi_256(codes[index + 2], codes[index + 3], codes[index + 4])
                if code == 38:
                    fg = color
                else:
                    bg = color
                index += 4
        index += 1
    return fg, bg


def clamp_ansi_color(code: int) -> int:
    return max(0, min(255, code))


def rgb_to_ansi_256(red: int, green: int, blue: int) -> int:
    target = (clamp_channel(red), clamp_channel(green), clamp_channel(blue))
    return min(range(16, 256), key=lambda code: color_distance(target, ansi_256_rgb_local(code)))


def clamp_channel(value: int) -> int:
    return max(0, min(255, value))


def ansi_256_rgb_local(code: int) -> tuple[int, int, int]:
    if code < 16:
        base = (
            (0, 0, 0), (128, 0, 0), (0, 128, 0), (128, 128, 0),
            (0, 0, 128), (128, 0, 128), (0, 128, 128), (192, 192, 192),
            (128, 128, 128), (255, 0, 0), (0, 255, 0), (255, 255, 0),
            (0, 0, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255),
        )
        return base[code]
    if code <= 231:
        shifted = code - 16
        steps = (0, 95, 135, 175, 215, 255)
        return steps[shifted // 36], steps[(shifted % 36) // 6], steps[shifted % 6]
    level = 8 + (code - 232) * 10
    return level, level, level


def color_distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> int:
    return sum((a - b) ** 2 for a, b in zip(left, right))


def duration_seconds(value: str) -> int:
    if not value:
        return 0
    total = 0
    for part in value.split(":"):
        if not part.isdigit():
            return 0
        total = total * 60 + int(part)
    return total


def run() -> None:
    sys.stdout.write("\x1b[?1049h\x1b[2J\x1b[H")
    sys.stdout.flush()
    try:
        curses.wrapper(lambda screen: Cockpit(screen).run())
    finally:
        sys.stdout.write("\x1b[?1006l\x1b[?1002l\x1b[?1000l\x1b[?1049l")
        sys.stdout.flush()
