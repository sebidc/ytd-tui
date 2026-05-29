from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .commands import command_preview, default_download_dir, search
from .presets import AUDIO_FORMATS, PRESETS, VIDEO_FORMATS
from .app import run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ytd-tui",
        description="A keyboard-first terminal UI and friendly command surface for yt-dlp.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("tui", help="Open the interactive terminal cockpit.")

    search_parser = subparsers.add_parser("search", help="Search without remembering yt-dlp search syntax.")
    search_parser.add_argument("query", nargs="+", help="Search terms.")
    search_parser.add_argument("-n", "--limit", type=int, default=20, help="Maximum results to show.")

    command_parser = subparsers.add_parser("command", help="Build a yt-dlp command from a preset.")
    command_parser.add_argument("url", help="URL to download.")
    command_parser.add_argument(
        "-p",
        "--preset",
        choices=("best", "1080p", "audio", "mp3", "subs"),
        default="best",
        help="Download preset.",
    )
    command_parser.add_argument("--kind", choices=("video", "audio"), help="Output kind.")
    command_parser.add_argument("--format", dest="output_format", help="Output format, e.g. mp4 or mp3.")
    command_parser.add_argument("-o", "--output-dir", default=str(default_download_dir()), help="Download folder.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command in (None, "tui"):
        run()
        return

    if args.command == "search":
        query = " ".join(args.query)
        try:
            results = search(query, args.limit)[: args.limit]
        except Exception as exc:
            print(f"search failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        for idx, item in enumerate(results, start=1):
            meta = " | ".join(part for part in (item.duration, item.uploader) if part)
            suffix = f" [{meta}]" if meta else ""
            print(f"{idx:02d}. {item.title}{suffix}\n    {item.url}")
        return

    if args.command == "command":
        preset_index = {"best": 0, "1080p": 1, "audio": 2, "mp3": 2, "subs": 3}[args.preset]
        from .commands import build_command

        output_kind = args.kind or ("audio" if args.preset in {"audio", "mp3"} else "video")
        default_format = AUDIO_FORMATS[0] if output_kind == "audio" else VIDEO_FORMATS[0]
        print(command_preview(build_command(args.url, PRESETS[preset_index], Path(args.output_dir), output_kind, args.output_format or default_format)))


if __name__ == "__main__":
    main()
