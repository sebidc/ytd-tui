from pathlib import Path

from ytdlp_tui.__main__ import build_parser
from ytdlp_tui.commands import build_command, command_preview, format_duration, looks_like_url
from ytdlp_tui.presets import PRESETS


def test_build_command_includes_output_path_and_url() -> None:
    command = build_command("https://example.com/watch?v=1", PRESETS[0], Path("/tmp/downloads"))

    assert command[0] == "yt-dlp"
    assert "--paths" in command
    assert "/tmp/downloads" in command
    assert command[-1] == "https://example.com/watch?v=1"


def test_command_preview_quotes_spaces() -> None:
    preview = command_preview(["yt-dlp", "--paths", "/tmp/my downloads", "https://example.com"])

    assert "'/tmp/my downloads'" in preview


def test_duration_formatting() -> None:
    assert format_duration(65) == "1:05"
    assert format_duration(3661) == "1:01:01"
    assert format_duration(None) == ""


def test_url_detection() -> None:
    assert looks_like_url("https://example.com")
    assert not looks_like_url("lofi beats")


def test_parser_supports_direct_search_command() -> None:
    args = build_parser().parse_args(["search", "lofi", "beats"])

    assert args.command == "search"
    assert args.query == ["lofi", "beats"]
