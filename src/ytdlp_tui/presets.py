from __future__ import annotations

from dataclasses import dataclass


VIDEO_FORMATS = ("mp4", "webm", "mkv", "mov")
AUDIO_FORMATS = ("mp3", "m4a", "opus", "flac", "wav", "aac")


@dataclass(frozen=True)
class Preset:
    name: str
    icon: str
    ascii_icon: str
    args: tuple[str, ...]
    description: str


PRESETS: tuple[Preset, ...] = (
    Preset(
        name="Best video",
        icon="\U000f03d0",
        ascii_icon="V",
        args=("--format", "bv*+ba/b"),
        description="Best available video and audio, merged to selected container.",
    ),
    Preset(
        name="1080p video",
        icon="\U000f04f9",
        ascii_icon="H",
        args=("--format", "bv*[height<=1080]+ba/b[height<=1080]/b"),
        description="Cap downloads at 1080p and merge to selected container.",
    ),
    Preset(
        name="Audio",
        icon="\U000f075a",
        ascii_icon="A",
        args=("--extract-audio", "--audio-quality", "0"),
        description="Extract high-quality audio using selected audio format.",
    ),
    Preset(
        name="Subtitles",
        icon="\U000f0a16",
        ascii_icon="S",
        args=("--skip-download", "--write-subs", "--write-auto-subs", "--sub-langs", "all"),
        description="Download subtitles and automatic subtitles without media.",
    ),
)
