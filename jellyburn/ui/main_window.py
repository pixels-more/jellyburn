import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GdkPixbuf

from ..config import (
    CD_MAX_SECONDS,
    CD_DATA_MAX_BYTES,
    DVD_DATA_MAX_BYTES,
    MP3_BITRATE_KBPS,
    load_config,
    save_config,
)
from ..i18n import _
from ..player import Player
from ..util import seconds_to_mmss
from .burn_dialog import BurnDialog
from .dialogs import show_error
from .library_pane import LibraryPane
from .mini_player import MiniPlayer
from .now_playing import NowPlayingBox
from .playlist_pane import PlaylistPane
from .settings_dialog import SettingsDialog
from .style import ThemeManager


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(
            title="Jellyburn", default_width=900, default_height=650, **kwargs
        )
        self.config = load_config()
        self.player = Player()
        self.player.set_eq(
            self.config.get("eq_bands", [0.0] * 10),
            self.config.get("eq_enabled", False),
        )
        self._build_ui()
        self.theme = ThemeManager(self.get_screen(), self.config)

        self.mini = MiniPlayer(
            self.player,
            on_play=self.now_playing.toggle_play_pause,
            on_stop=self.now_playing.stop,
            on_restore=self._restore_from_mini,
        )
        self.now_playing.set_mini(self.mini)
        self.connect("delete-event", self._on_close)

        if self.config.get("server_url"):
            self.library.connect_to_server()

    def _on_close(self, *_):
        self.playlist.autosave()
        self.player.stop()
        self.mini.destroy()

    def _build_ui(self):
        header = Gtk.HeaderBar(show_close_button=True)
        header.set_title("Jellyburn")
        header.set_subtitle("")
        self.set_titlebar(header)
        self._load_icon()

        btn_settings = Gtk.Button.new_from_icon_name(
            "preferences-system-symbolic", Gtk.IconSize.BUTTON
        )
        btn_settings.set_tooltip_text(_("Settings"))
        btn_settings.connect("clicked", self._open_settings)
        header.pack_end(btn_settings)

        btn_mini = Gtk.Button.new_from_icon_name(
            "view-restore-symbolic", Gtk.IconSize.BUTTON
        )
        btn_mini.set_tooltip_text(_("Mini Player"))
        btn_mini.connect("clicked", self._toggle_mini)
        header.pack_end(btn_mini)

        btn_connect = Gtk.Button.new_from_icon_name(
            "network-transmit-receive-symbolic", Gtk.IconSize.BUTTON
        )
        btn_connect.set_tooltip_text(_("Reconnect"))
        btn_connect.connect("clicked", lambda _b: self.library.connect_to_server())
        header.pack_end(btn_connect)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(520)
        self.add(paned)

        # ── Linke Seite: Bibliothek ──
        self.library = LibraryPane(
            self.config,
            on_play_track=lambda tid, label, track: self.now_playing.play_track(
                tid, label, track
            ),
            on_add_tracks=lambda tracks: self.playlist.add_tracks(tracks),
            on_burn_album=self._burn_album_tracks,
        )
        paned.pack1(self.library, resize=True, shrink=False)

        # ── Rechte Seite: Playlist + Now Playing + Burn ──
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right.get_style_context().add_class("panel-right")

        self.playlist = PlaylistPane(
            self.config,
            get_client=lambda: self.library.client,
            get_library_selection=self.library.get_selected_tracks,
            on_burn_requested=lambda: self._start_burn(None),
        )
        right.pack_start(self.playlist, True, True, 0)

        right.pack_start(Gtk.Separator(), False, False, 4)

        # ── Now Playing ──
        self.now_playing = NowPlayingBox(
            self.player,
            self.config,
            get_client=lambda: self.library.client,
            get_selection=self._get_play_selection,
        )
        right.pack_start(self.now_playing, False, False, 0)

        paned.pack2(right, resize=False, shrink=False)

    def _load_icon(self):
        import os

        icon_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "icons", "jellyburn.svg")
        )
        if os.path.exists(icon_path):
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_size(icon_path, 64, 64)
                self.set_icon(pb)
            except Exception:
                pass

    # ── Wiedergabe ──
    def _get_play_selection(self):
        sel = self.library.get_selected_track()
        if sel:
            return sel
        if self.library.client:
            return self.playlist.get_selected_track()
        return None

    def _toggle_mini(self, _btn):
        self.hide()
        self.mini.show()

    def _restore_from_mini(self):
        self.show()
        self.present()

    # ── Playlist ──
    def _burn_album_tracks(self, tracks, playlist_name):
        self.playlist.replace_with(tracks, playlist_name)
        self._start_burn(None)

    # ── Einstellungen ──
    def _open_settings(self, _btn):
        dlg = SettingsDialog(self, self.config)
        response = dlg.run()
        vals = dlg.get_values()
        lang_changed = vals.get("language") != self.config.get("language", "en")
        # Only fields that actually affect the server connection warrant a
        # reconnect - switching the theme, burn speed, etc. shouldn't
        # trigger one (and a non-empty password always means the user is
        # actively trying to (re-)authenticate right now).
        connection_changed = bool(vals.get("password")) or any(
            vals.get(key) != self.config.get(key)
            for key in ("server_url", "username", "api_key")
        )
        dlg.destroy()
        if response == Gtk.ResponseType.OK:
            self.config.update(vals)
            save_config({k: v for k, v in self.config.items() if k != "password"})
            self.theme.update()
            if lang_changed:
                info = Gtk.MessageDialog(
                    transient_for=self,
                    modal=True,
                    message_type=Gtk.MessageType.INFO,
                    buttons=Gtk.ButtonsType.OK,
                    text=_("Language changed"),
                )
                info.format_secondary_text(
                    _(
                        "Please restart Jellyburn for the language change to take effect."
                    )
                )
                info.run()
                info.destroy()
            elif connection_changed:
                self.library.connect_to_server()

    # ── Brennen ──
    def _start_burn(self, _btn):
        playlist_tracks = self.playlist.playlist_tracks
        if not playlist_tracks:
            return
        total_s = self.playlist.total_seconds()
        mode = "audio"
        max_bytes = CD_DATA_MAX_BYTES
        if total_s > CD_MAX_SECONDS:
            est_bytes = total_s * (MP3_BITRATE_KBPS * 1000 // 8)
            if est_bytes > DVD_DATA_MAX_BYTES:
                show_error(
                    self,
                    _(
                        "Playlist is too long even for an MP3 DVD (~{mb} MB estimated, limit ~4700 MB)."
                    ).format(mb=est_bytes // 1_000_000),
                )
                return

            # Fits on a CD-sized MP3 disc (~700 MB) or needs the bigger
            # ~4.7 GB DVD budget - either way we don't detect what's
            # actually in the drive, just tell the user which blank to use.
            needs_dvd = est_bytes > CD_DATA_MAX_BYTES
            max_bytes = DVD_DATA_MAX_BYTES if needs_dvd else CD_DATA_MAX_BYTES

            if self.config.get("mp3_auto_switch"):
                mode = "mp3"
                if needs_dvd:
                    info = Gtk.MessageDialog(
                        transient_for=self,
                        modal=True,
                        message_type=Gtk.MessageType.INFO,
                        buttons=Gtk.ButtonsType.OK,
                        text=_("This playlist needs a DVD, not a CD"),
                    )
                    info.format_secondary_text(
                        _(
                            "The MP3s add up to more than a CD-sized data disc"
                            " holds (~700 MB) - insert a blank DVD instead."
                        )
                    )
                    info.run()
                    info.destroy()
            else:
                dlg = Gtk.MessageDialog(
                    transient_for=self,
                    modal=True,
                    message_type=Gtk.MessageType.WARNING,
                    buttons=Gtk.ButtonsType.NONE,
                    text=_("Playlist too long!"),
                )
                secondary = _(
                    "The playlist is {duration} long – a CD holds only 74:00."
                ).format(duration=seconds_to_mmss(total_s))
                if needs_dvd:
                    secondary += "\n\n" + _(
                        "It also exceeds a CD-sized MP3 disc (~700 MB) -"
                        " insert a blank DVD instead of a CD."
                    )
                dlg.format_secondary_text(secondary)
                dlg.add_button(
                    _("Burn as MP3 DVD") if needs_dvd else _("Burn as MP3 data CD"),
                    Gtk.ResponseType.OK,
                )
                dlg.add_button(_("Audio CD anyway"), Gtk.ResponseType.APPLY)
                dlg.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
                dlg.set_default_response(Gtk.ResponseType.OK)
                resp = dlg.run()
                dlg.destroy()
                if resp == Gtk.ResponseType.OK:
                    mode = "mp3"
                elif resp == Gtk.ResponseType.APPLY:
                    mode = "audio"
                else:
                    return

        dlg = BurnDialog(
            self,
            playlist_tracks,
            self.library.client,
            self.config,
            mode=mode,
            max_bytes=max_bytes,
        )
        dlg.run()
        dlg.destroy()
