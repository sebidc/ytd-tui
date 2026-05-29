<img width="967" height="597" alt="image" src="https://github.com/user-attachments/assets/5e6e9827-127c-43b3-80ce-e22ca2bc546e" />


# ytd-tui

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Release](https://img.shields.io/github/v/release/sebidc/ytd-tui?display_name=tag)](https://github.com/sebidc/ytd-tui/releases/)
[![Platform](https://img.shields.io/badge/platform-macOS%20Terminal-111827)](https://github.com/sebidc/ytd-tui)
[![Homebrew Tap](https://img.shields.io/badge/homebrew-sebidc%2Ftap-fbbf24)](https://github.com/sebidc/homebrew-tap)

`ytd-tui` is a terminal UI for `yt-dlp` that makes search, format selection, platform switching, queueing, and downloads much easier to access from one screen.

It is designed in the same spirit as `check-installs-tui`, Basalt, `btop`, and `bpytop`: full-screen, keyboard-first, dense, and friendly enough that you do not have to memorize `yt-dlp` flags to get work done.


## What's New in v1.0.0

This first stable release ships the full `ytd-tui` terminal workflow:

<img width="1822" height="1082" alt="image" src="https://github.com/user-attachments/assets/64b14b9c-0a54-41b9-9dad-a120b1486d51" />


- Platform picker before the dashboard, with major platforms and a searchable niche-platform list from the `yt-dlp` supported sites database.
- Dynamic platform theming across the dashboard, loading screens, popups, and focus states.
- Inline search, filter, sort, queue, and command preview flow.
- Search results for platforms that support direct discovery and graceful platform-search links where the public web blocks direct extraction.
- Format and location popups for audio/video output selection, title override, prefix, suffix, and destination folder.
- Queue progress with status lines, progress bars, and live downloader activity.
- Thumbnail previews inside the selection panel when available.
- `mpv` playback shortcut from the results panel.
- Homebrew installs a short `ytd-tui` command.

## Supported Platforms

`ytd-tui` is built on top of `yt-dlp`, so it can work with the platforms `yt-dlp` supports.

The first screen includes:

- Major platforms such as YouTube, Instagram, Facebook, X/Twitter, TikTok, Reddit, Twitch, SoundCloud, Vimeo, Pinterest, LinkedIn, and Dailymotion.
- A searchable niche and alternative section generated from `supportedsites.md`.

Search behavior depends on what the public platform surface allows:

- Some platforms return direct result rows in the TUI.
- Some platforms expose search pages publicly but restrict direct result extraction.
- Direct media URLs remain the most reliable path everywhere `yt-dlp` supports.

## Install

### Homebrew

```sh
brew tap sebidc/tap
brew install ytd-tui
brew install yt-dlp ffmpeg
```

### pip

```sh
python3 -m pip install ytd-tui
```

If you install with `pip`, make sure `yt-dlp` and `ffmpeg` are already available on your system.

### From Source

```sh
git clone https://github.com/sebidc/ytd-tui.git
cd ytd-tui
python3 -m pip install -e .
```

## Requirements

For the best experience on macOS:

- `yt-dlp`
- `ffmpeg`
- `mpv` for the play shortcut
- `chafa` for terminal thumbnail previews
- a Nerd Font for icon rendering

Recommended setup:

```sh
brew install yt-dlp ffmpeg mpv chafa
```

Homebrew installs the TUI itself. The interface checks optional tools at runtime and degrades gracefully if they are missing.

## Usage

Run the app:

```sh
ytd-tui
```

The interactive flow is:

1. Pick a platform.
2. Search or paste a URL.
3. Select a result.
4. Confirm format and output location.
5. Download or play.

## Controls

- `/` focuses the search field.
- `Enter` runs search when the search field is focused.
- `j` and `k`, arrow keys, and the mouse wheel move through results.
- `Space` opens the selected result confirmation flow.
- `m` plays the selected item with `mpv`.
- `f` opens the format and location options.
- `p` returns to the platform picker.
- `?` opens the help popup.
- `q` returns to the platform picker from the dashboard.

## Repository

- [Contributing](./CONTRIBUTING.md)
- [Security](./SECURITY.md)
- [MIT License](./LICENSE)
