from __future__ import annotations

import curses
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

from .commands import (
    MediaItem,
    QueueJob,
    command_preview,
    default_download_dir,
    health_checks,
    item_from_url,
    preset_by_index,
    search,
)
from .presets import PRESETS, Preset


class Palette:
    border = 1
    title = 2
    selected = 3
    muted = 4
    ok = 5
    warn = 6
    error = 7
    accent = 8
    boot = 9


class Icons:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.search = "\U000f0349" if enabled else "?"
        self.link = "\U000f0337" if enabled else "@"
        self.queue = "\U000f0423" if enabled else "#"
        self.done = "\U000f012c" if enabled else "+"
        self.fail = "\U000f0159" if enabled else "!"
        self.run = "\U000f040a" if enabled else ">"
        self.wait = "\U000f06a5" if enabled else "."

    def preset(self, preset: Preset) -> str:
        return preset.icon if self.enabled else preset.ascii_icon


class App:
    def __init__(self, screen: "curses._CursesWindow") -> None:
        self.screen = screen
        self.icons = Icons(enabled=not os.environ.get("YTDLP_TUI_ASCII"))
        self.results: list[MediaItem] = []
        self.selected = 0
        self.preset_index = 0
        self.output_dir = default_download_dir()
        self.jobs: list[QueueJob] = []
        self.messages: queue.Queue[str] = queue.Queue()
        self.notice = "Press / to search, u for URL, Space to queue, Enter to download."
        self.running = True

    @property
    def preset(self) -> Preset:
        return preset_by_index(self.preset_index)

    def run(self) -> None:
        curses.curs_set(0)
        self.screen.nodelay(True)
        self.setup_colors()
        self.show_loading_screen()
        while self.running:
            self.drain_messages()
            self.draw()
            self.handle_key()
            self.poll_jobs()
            time.sleep(0.05)

    def setup_colors(self) -> None:
        if not curses.has_colors():
            return
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(Palette.border, curses.COLOR_RED, -1)
        curses.init_pair(Palette.title, curses.COLOR_RED, -1)
        curses.init_pair(Palette.selected, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(Palette.muted, curses.COLOR_WHITE, -1)
        curses.init_pair(Palette.ok, curses.COLOR_GREEN, -1)
        curses.init_pair(Palette.warn, curses.COLOR_YELLOW, -1)
        curses.init_pair(Palette.error, curses.COLOR_RED, -1)
        curses.init_pair(Palette.accent, curses.COLOR_RED, -1)
        curses.init_pair(Palette.boot, curses.COLOR_WHITE, curses.COLOR_RED)

    def show_loading_screen(self) -> None:
        steps = [
            ("checking yt-dlp", "yt-dlp"),
            ("checking ffmpeg", "ffmpeg"),
            ("loading presets", f"{len(PRESETS)} presets"),
            ("loading icon mode", "nerd font" if self.icons.enabled else "ascii"),
            ("arming queue", str(self.output_dir)),
        ]
        for index, (label, detail) in enumerate(steps, start=1):
            self.draw_loading(index, len(steps), label, detail)
            time.sleep(0.18)
        self.draw_loading(len(steps), len(steps), "ready", "press / to search")
        time.sleep(0.35)

    def draw_loading(self, done: int, total: int, label: str, detail: str) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        title = "YTD-TUI"
        subtitle = "yt-dlp command cockpit"
        box_w = min(68, max(36, width - 6))
        box_h = 13
        y = max(0, (height - box_h) // 2)
        x = max(0, (width - box_w) // 2)
        self.box(y, x, box_h, box_w, " loading ")

        self.add(y + 2, x + 4, title, Palette.boot)
        self.add(y + 3, x + 4, subtitle, Palette.accent)
        self.add(y + 5, x + 4, f"{self.icons.run} {label}", Palette.title)
        self.add(y + 6, x + 4, truncate(detail, box_w - 8), Palette.muted)

        bar_w = box_w - 8
        fill = int(bar_w * done / max(1, total))
        bar = "█" * fill + "░" * (bar_w - fill) if self.icons.enabled else "#" * fill + "." * (bar_w - fill)
        self.add(y + 8, x + 4, bar, Palette.error)

        checks = health_checks(self.icons.enabled)
        check_y = y + 10
        for offset, (name, state, value) in enumerate(checks[:2]):
            color = Palette.ok if state == "ok" else Palette.warn
            mark = self.icons.done if state == "ok" else self.icons.fail
            self.add(check_y + offset, x + 4, truncate(f"{mark} {name}: {value}", box_w - 8), color)
        self.screen.refresh()

    def draw(self) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        if height < 24 or width < 82:
            self.add(0, 0, "Resize terminal to at least 82x24.", Palette.warn)
            self.screen.refresh()
            return

        top_h = 7
        mid_h = height - top_h - 5
        left_w = max(42, width // 2)
        right_w = width - left_w

        self.box(0, 0, top_h, left_w, f" {self.icons.search} Search / URL ")
        self.box(0, left_w, top_h, right_w, " Health ")
        self.box(top_h, 0, mid_h, left_w, " Results ")
        self.box(top_h, left_w, mid_h, right_w, f" {self.icons.queue} Download Queue ")
        self.box(height - 5, 0, 5, width, " Command Cockpit ")

        self.draw_search_panel(1, 2, left_w - 4)
        self.draw_health_panel(1, left_w + 2, right_w - 4)
        self.draw_results(top_h + 1, 2, mid_h - 2, left_w - 4)
        self.draw_queue(top_h + 1, left_w + 2, mid_h - 2, right_w - 4)
        self.draw_footer(height - 4, 2, width - 4)
        self.screen.refresh()

    def draw_search_panel(self, y: int, x: int, width: int) -> None:
        self.add(y, x, f"Preset: {self.icons.preset(self.preset)} {self.preset.name}", Palette.accent)
        self.add(y + 1, x, truncate(self.preset.description, width), Palette.muted)
        self.add(y + 3, x, f"Output: {self.output_dir}", Palette.muted)
        self.add(y + 4, x, truncate(self.notice, width), Palette.warn if "failed" in self.notice.lower() else Palette.ok)

    def draw_health_panel(self, y: int, x: int, width: int) -> None:
        for idx, (name, state, detail) in enumerate(health_checks(self.icons.enabled)[:5]):
            color = Palette.ok if state == "ok" else Palette.warn
            mark = self.icons.done if state == "ok" else self.icons.fail
            self.add(y + idx, x, f"{mark} {name:<9} {truncate(detail, width - 14)}", color)

    def draw_results(self, y: int, x: int, height: int, width: int) -> None:
        if not self.results:
            self.add(y, x, "No results yet. Press / to search or u to paste a URL.", Palette.muted)
            return
        for row, item in enumerate(self.results[:height]):
            color = Palette.selected if row == self.selected else 0
            prefix = ">" if row == self.selected else " "
            meta = " | ".join(part for part in (item.duration, item.uploader) if part)
            line = f"{prefix} {row + 1:02d} {item.title}"
            if meta:
                line += f"  [{meta}]"
            self.add(y + row, x, truncate(line, width), color)

    def draw_queue(self, y: int, x: int, height: int, width: int) -> None:
        if not self.jobs:
            self.add(y, x, "Queue is empty. Space queues, Enter queues and starts.", Palette.muted)
            return
        for row, job in enumerate(self.jobs[-height:]):
            color = {
                "done": Palette.ok,
                "failed": Palette.error,
                "running": Palette.warn,
                "queued": Palette.muted,
            }.get(job.status, 0)
            icon = {
                "done": self.icons.done,
                "failed": self.icons.fail,
                "running": self.icons.run,
                "queued": self.icons.wait,
            }.get(job.status, " ")
            detail = job.progress or job.speed or job.status
            line = f"{icon} {job.status:<7} {detail:<10} {job.item.title}"
            self.add(y + row, x, truncate(line, width), color)

    def draw_footer(self, y: int, x: int, width: int) -> None:
        selected = self.current_item()
        cmd = ""
        if selected:
            cmd = command_preview(QueueJob(selected, self.preset, self.output_dir).command())
        self.add(y, x, truncate(cmd or "Command preview appears here after selecting a result.", width), Palette.muted)
        keys = "[/] search  [u] url  [1-4] preset  [Space] queue  [Enter/d] download  [c] command  [x] clear  [q] quit"
        self.add(y + 2, x, truncate(keys, width), Palette.title)

    def handle_key(self) -> None:
        try:
            key = self.screen.getch()
        except curses.error:
            return
        if key == -1:
            return
        if key in (ord("q"), 27):
            self.running = False
        elif key in (ord("j"), curses.KEY_DOWN):
            self.selected = min(self.selected + 1, max(0, len(self.results) - 1))
        elif key in (ord("k"), curses.KEY_UP):
            self.selected = max(0, self.selected - 1)
        elif key == ord("/"):
            self.prompt_search()
        elif key == ord("u"):
            self.prompt_url()
        elif key in (ord("1"), ord("2"), ord("3"), ord("4")):
            self.preset_index = key - ord("1")
            self.notice = f"Preset changed to {self.preset.name}."
        elif key == ord(" "):
            self.queue_selected()
        elif key in (10, 13, ord("d")):
            self.queue_selected()
            self.start_next()
        elif key == ord("c"):
            self.show_command()
        elif key == ord("x"):
            before = len(self.jobs)
            self.jobs = [job for job in self.jobs if job.status not in {"done", "failed"}]
            self.notice = f"Cleared {before - len(self.jobs)} finished jobs."

    def prompt_search(self) -> None:
        value = self.prompt("Search YouTube")
        if not value:
            return
        self.notice = f"Searching for {value!r}..."
        self.draw()
        try:
            self.results = search(value)
            self.selected = 0
            self.notice = f"Found {len(self.results)} results for {value!r}."
        except Exception as exc:
            self.notice = f"Search failed: {exc}"

    def prompt_url(self) -> None:
        value = self.prompt("Paste URL")
        if not value:
            return
        self.results.insert(0, item_from_url(value))
        self.selected = 0
        self.notice = "URL added to results."

    def prompt(self, label: str) -> str:
        curses.curs_set(1)
        self.screen.nodelay(False)
        height, width = self.screen.getmaxyx()
        y = height - 2
        self.add(y, 2, " " * (width - 4))
        self.add(y, 2, f"{label}: ", Palette.title)
        curses.echo()
        try:
            raw = self.screen.getstr(y, len(label) + 4, width - len(label) - 6)
            return raw.decode(errors="ignore").strip()
        finally:
            curses.noecho()
            curses.curs_set(0)
            self.screen.nodelay(True)

    def queue_selected(self) -> None:
        item = self.current_item()
        if not item:
            self.notice = "Nothing selected yet."
            return
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.jobs.append(QueueJob(item=item, preset=self.preset, output_dir=self.output_dir))
        self.notice = f"Queued: {item.title}"

    def start_next(self) -> None:
        if any(job.status == "running" for job in self.jobs):
            return
        for job in self.jobs:
            if job.status == "queued":
                self.start_job(job)
                return

    def start_job(self, job: QueueJob) -> None:
        job.status = "running"
        command = job.command()
        job.process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self.watch_job, args=(job,), daemon=True).start()
        self.notice = f"Started: {job.item.title}"

    def watch_job(self, job: QueueJob) -> None:
        assert job.process and job.process.stdout
        for line in job.process.stdout:
            clean = line.strip()
            job.last_line = clean
            if "[download]" in clean and "%" in clean:
                parts = clean.split()
                job.progress = next((part for part in parts if part.endswith("%")), job.progress)
                job.speed = next((part for part in parts if "/s" in part), job.speed)
        code = job.process.wait()
        job.status = "done" if code == 0 else "failed"
        self.messages.put(f"{job.status.upper()}: {job.item.title}")

    def poll_jobs(self) -> None:
        if not any(job.status == "running" for job in self.jobs):
            self.start_next()

    def drain_messages(self) -> None:
        while True:
            try:
                self.notice = self.messages.get_nowait()
            except queue.Empty:
                return

    def show_command(self) -> None:
        item = self.current_item()
        if not item:
            self.notice = "Select an item before previewing a command."
            return
        self.notice = command_preview(QueueJob(item, self.preset, self.output_dir).command())

    def current_item(self) -> MediaItem | None:
        if not self.results:
            return None
        return self.results[max(0, min(self.selected, len(self.results) - 1))]

    def box(self, y: int, x: int, height: int, width: int, title: str) -> None:
        try:
            win = self.screen.derwin(height, width, y, x)
            win.attron(curses.color_pair(Palette.border))
            win.box()
            win.attroff(curses.color_pair(Palette.border))
            win.addstr(0, 2, truncate(title, max(0, width - 4)), curses.color_pair(Palette.title))
        except curses.error:
            pass

    def add(self, y: int, x: int, text: str, color: int = 0) -> None:
        try:
            attr = curses.color_pair(color) if color else 0
            self.screen.addstr(y, x, text, attr)
        except curses.error:
            pass


def truncate(value: object, width: int) -> str:
    text = str(value)
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    return text[: max(0, width - 1)] + "…"


def run() -> None:
    curses.wrapper(lambda screen: App(screen).run())
