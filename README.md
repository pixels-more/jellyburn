# jellyburn

A GTK3 desktop app for Linux to browse your Jellyfin music library, build playlists, and burn them directly to audio CD.

![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Platform](https://img.shields.io/badge/platform-Linux-lightgrey)
![Status](https://img.shields.io/badge/status-alpha-orange)

<img width="1327" height="723" alt="jellyburn" src="https://github.com/user-attachments/assets/df65fc5d-e16f-480a-9d80-68ea98204baa" />

## Features

- Connects to any Jellyfin server via API key or username/password
- iTunes-style column browser — filter by artist, then album, then tracks
- Click any column header (artist, album, track #, title, length, …) to sort
- Track number column, search by title, artist or album
- Album art display fetched directly from Jellyfin
- Playback via `mpv` with now-playing info, progress bar and scrubbing
- 10-band graphic equalizer (31 Hz–16 kHz) with presets, live while playing
- Collapse to a compact mini player that stays on top while you use other apps
- Playlist builder with drag-and-drop reordering
- Right-click an album to add it to the playlist or burn it directly
- Save and manage multiple named playlists (separate "Editor" / "Saved" tabs), auto-saved as you go; JSON import/export still available as backup
- Delete tracks from playlist with the Delete key or right-click
- Real-time CD capacity bar (green → yellow → red, max. 74 min)
- Burn directly to audio CD in Disc At Once mode — no extra steps
- Optional CD-Text (album/track info written to the disc)
- Automatic fallback to an MP3 data CD when a playlist is too long for audio (192 kbps, ~8h capacity)
- Auto-detects optical drives, shown as a dropdown in settings
- Library cached locally for instant startup, refreshed in the background
- Checks for missing system dependencies on startup with clear instructions
- UI language switchable between English and German (Settings → Language)

## Requirements

**System packages** (Debian/Ubuntu/Mint):

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-gdkpixbuf-2.0 mpv ffmpeg cdrskin xorriso
```

> `cdrskin` is the recommended burn backend. `wodim` is supported as a fallback but may require extra permissions on modern kernels:
> ```bash
> sudo setcap cap_ipc_lock+ep $(which wodim)
> ```

> `xorriso` (or `genisoimage`/`mkisofs`) is only needed for the MP3 data CD fallback (long playlists). Audio CD burning and CD-Text work without it.

**Python:** 3.10 or newer. The only Python dependency (`requests`) is installed automatically via pip.

**Your user must be in the `cdrom` group** to access the optical drive without root:

```bash
sudo usermod -aG cdrom $USER
# log out and back in for the change to take effect
```

## Installation

```bash
pip install jellyburn
```

**Debian 12/13, Ubuntu 23.04+ and other distros with PEP 668:** plain `pip install` fails with
`error: externally-managed-environment`. Use `pipx` instead. The
`--system-site-packages` flag is required so the apt-provided `python3-gi` is visible:

```bash
sudo apt install pipx
pipx ensurepath          # once, then reopen the terminal
pipx install --system-site-packages jellyburn
```

Upgrade later with `pipx upgrade jellyburn`.

Without `--system-site-packages` you will get `ModuleNotFoundError: No module named 'gi'`.

Or run from source:

```bash
git clone https://github.com/pixels-more/jellyburn
cd jellyburn
pip install -e .
jellyburn
```

## Desktop integration (optional)

After installing via pip, add Jellyburn to your application menu:

```bash
# Icon
mkdir -p ~/.local/share/icons/hicolor/scalable/apps
curl -o ~/.local/share/icons/hicolor/scalable/apps/jellyburn.svg \
  https://raw.githubusercontent.com/pixels-more/jellyburn/main/jellyburn/icons/jellyburn.svg

# Desktop entry
mkdir -p ~/.local/share/applications
cat > ~/.local/share/applications/jellyburn.desktop << 'EOF'
[Desktop Entry]
Name=Jellyburn
Comment=Browse your Jellyfin music library and burn audio CDs
Exec=jellyburn
Icon=jellyburn
Terminal=false
Type=Application
Categories=AudioVideo;Audio;Music;
EOF

update-desktop-database ~/.local/share/applications/
```

## Setup

1. Click the settings icon (⚙) in the top right
2. Enter your Jellyfin server URL, e.g. `https://jellyfin.example.com`
3. Enter an API key — Jellyfin Dashboard → Administration → API Keys → New Key
4. Select your CD drive from the dropdown (auto-detected)
5. Set burn speed (default: 4×)
6. Choose your preferred language (English or Deutsch)
7. Optionally toggle CD-Text and auto-switch-to-MP3-CD behavior
8. Save — the app connects and loads your library

Config is stored in `~/.config/jellyburn.json`. Passwords are never saved — only the API token obtained after login.
Library cache is stored in `~/.cache/jellyburn/`. Saved playlists live in `~/.config/jellyburn_playlists/` as individual JSON files.

## Usage

| Action | How |
|---|---|
| Browse | Click an artist → albums update; click an album → tracks filter |
| Sort | Click any column header (also works in the browser and track list) |
| Search | Type in the search bar — filters title, artist and album live |
| Play | Double-click a track, or select it and press Play |
| Equalizer | Click „EQ" next to the playback controls |
| Scrub | Click or drag the progress bar to seek within a track |
| Mini player | Click the collapse button in the header; click restore to return |
| Add to playlist | Select tracks (Ctrl+click for multiple) → „+ Add selection", or right-click a track/album → „Add to Playlist" |
| Burn an album directly | Right-click an album → „Burn Album" |
| Reorder playlist | Drag and drop rows |
| Remove from playlist | Select rows and press Delete, or right-click → remove |
| Manage saved playlists | „Saved" tab: switch, rename, delete; „Editor" tab: current playlist, auto-saved as you edit |
| Burn | Click „● BURN CD" — tracks are downloaded, converted and burned |

The CD capacity bar turns yellow above 85 % and red when the playlist exceeds 74 minutes.

## Burn process

**Audio CD** (playlist ≤ 74 min):
1. Tracks are downloaded from Jellyfin one by one
2. Each track is converted to WAV (44100 Hz, 16-bit stereo) via `ffmpeg`
3. If CD-Text is enabled, a cue sheet with album/track metadata is generated
4. All WAV files are written to CD as an audio disc in DAO mode via `cdrskin` (or `wodim`)

**MP3 data CD** (playlist too long for an audio CD, ~700 MB capacity):
1. Tracks are downloaded; files already in MP3 format are kept as-is, everything else is transcoded to MP3 (192 kbps) via `ffmpeg`
2. An ISO9660 data disc image is built via `xorriso` (or `genisoimage`/`mkisofs`)
3. The image is burned via `cdrskin` (or `wodim`) in data mode

Depending on the setting, this MP3 fallback is offered automatically or applied silently when a playlist exceeds 74 minutes.

Temporary files in `/tmp/jellyfin_burn_*/` are cleaned up automatically after burning.

## Contributing

Open an issue before starting larger changes. PRs welcome.

## License

MIT — see [LICENSE](LICENSE)
