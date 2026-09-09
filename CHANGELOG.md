# Changelog

All notable changes to Jellyburn are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [0.4.3] - 2026-09-09

### Fixed
- Login failing with HTTP 400 against Jellyfin servers that dropped the
  legacy `X-Emby-Authorization` header (Jellyfin 10.11+). Jellyburn now
  also sends the standard `Authorization` header with the `MediaBrowser`
  scheme. (#33)

## [0.4.2] - 2026-07-13
### Fixed
- Audio CD burn aborting with CD-Text enabled (missing conversion log,
  wrong working directory, cdrskin multi-FILE cue limitation). (#32)
- Config/cache/playlists now stored under XDG dirs so they persist
  correctly under Flatpak.
- Dark mode forced to a dark base theme under Flatpak (previously showed
  a half-dark UI).
- System dark mode now detected via the XDG portal instead of guessing
  from the GTK theme name.

### Changed
- English is now the explicit default language in `DEFAULT_CONFIG`.
- Flatpak app-id renamed to `de.pixelsandmore.Jellyburn`.

## [0.4.1] - 2026-07-11
### Added
- About dialog.

### Fixed
- Mini-player play/pause icon not syncing with playback state.
- App logo missing in the About dialog; Flatpak build artifacts
  accidentally included in the source distribution.

### Changed
- Rebranded to Pixels and More.

## [0.4.0] - 2026-07-09
### Added
- Multi-playlist management: save, load, and switch between playlists.
- CD-Text writing for audio CDs.
- Automatic MP3 (data CD) fallback for playlists too long for an audio CD.
- Audio equalizer.
- Right-click an album to burn it directly.
- Local Flatpak packaging (manifest, mpv/ffmpeg/cdrskin/xorriso build).
- Theme setting (light/dark).

### Fixed
- App freezing/getting killed on reconnect after sorting a large track
  list.
- Stale API key blocking re-authentication and blocking playback behind
  a network call on the UI thread.
- Freshly-obtained API key not persisted when a library cache already
  existed, causing repeated auth failures.
- Settings save no longer triggers a reconnect for unrelated changes
  (e.g. switching the theme).
- Play button now toggles pause/resume instead of restarting the track.
- Mini player Stop button crash (wrong callback arity).

### Changed
- Monolithic modules split into focused ones: `ui/style.py`,
  `ui/dialogs.py`, `ui/now_playing.py`, `ui/playlist_pane.py`,
  `ui/library_pane.py`, `burner.py` + `ui/burn_dialog.py`.

## [0.3.2] - 2026-07-01
### Added
- Desktop entry and icon now auto-installed on first run.

### Fixed
- Settings dialog not destroyed before showing the language-change info
  dialog.
- `_` parameter shadowing the gettext translation function `_()`.

## [0.3.1] - 2026-06-30
### Added
- i18n via gettext; English default, German translation.

## [0.3.0] - 2026-06-30
### Added
- App icon (CD with flame).
- `.desktop` file and desktop integration instructions.
- Track number (`#`) column in the library view.
- Configurable track list columns via header right-click.

### Fixed
- CD capacity bar color not showing.
- Column header right-click menu not appearing / misdetected.
- Header bar subtitle removed, shows only "Jellyburn".

## [0.2.0] - 2026-06-29
### Added
- UI overhaul: dark theme, retro hi-fi aesthetic.
- Album art display from Jellyfin.
- Now Playing section with real progress bar and time display.
- CD capacity bar with green→yellow→red gradient.
- Responsive layout for different window sizes.
- Playlist save/load as JSON.
- `main()` entry point for the console script.
- Robust error handling for missing dependencies, connection issues, and
  burns.

### Changed
- Monolithic `__main__.py` split into modules
  (`api.py`, `player.py`, `burner.py`, `ui/`).

## [0.1.0] - 2026-06-29
### Added
- Initial release: browse and play Jellyfin music, build playlists, burn
  to audio CD via `wodim`.
