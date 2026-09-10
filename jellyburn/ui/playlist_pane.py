import json
from datetime import datetime

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Pango

from ..api import track_artist
from ..config import (
    CD_DATA_MAX_BYTES,
    CD_MAX_SECONDS,
    DVD_DATA_MAX_BYTES,
    MP3_BITRATE_KBPS,
)
from ..i18n import _
from ..playlists import (
    list_playlists_info,
    load_playlist as pl_load,
    save_playlist as pl_save,
    delete_playlist as pl_delete,
    rename_playlist as pl_rename,
)
from ..util import seconds_to_mmss
from .dialogs import prompt_text, show_error

CD_MAX_LABEL = seconds_to_mmss(CD_MAX_SECONDS)


class PlaylistPane(Gtk.Box):
    """Playlist editor (current playlist + saved-playlists collection),
    CD capacity bar, and the burn button."""

    def __init__(self, config, get_client, get_library_selection, on_burn_requested):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.config = config
        self._get_client = get_client
        self._get_library_selection = get_library_selection
        self._on_burn_requested = on_burn_requested

        self.playlist_tracks = []
        self.playlist_name = None
        self._ignore_store_signals = False

        self.get_style_context().add_class("panel-right")

        section_label = Gtk.Label(
            xalign=0, margin_start=8, margin_top=8, margin_bottom=2
        )
        section_label.set_markup(
            f'<span font_desc="11" weight="bold" color="#9090b0">{_("Playlists").upper()}</span>'
        )
        self.pack_start(section_label, False, False, 0)

        self.notebook = Gtk.Notebook()

        # ── Tab 1: aktuelle Playlist (zum Bearbeiten/Brennen) ──
        tab_playlist = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        pl_header = Gtk.Box(spacing=4, margin=8)
        self.pl_title_label = Gtk.Label(xalign=0)
        pl_header.pack_start(self.pl_title_label, True, True, 0)

        for icon, tip, cb in [
            ("list-add-symbolic", _("New playlist"), self._new_playlist),
            (
                "document-open-symbolic",
                _("Load playlist") + " (JSON)",
                self._load_playlist,
            ),
            (
                "document-save-symbolic",
                _("Save playlist") + " (JSON)",
                self._save_playlist,
            ),
        ]:
            b = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.SMALL_TOOLBAR)
            b.set_tooltip_text(tip)
            b.connect("clicked", cb)
            pl_header.pack_start(b, False, False, 0)

        btn_clear = Gtk.Button(label=_("Clear"))
        btn_clear.connect("clicked", self._on_clear_clicked)
        pl_header.pack_start(btn_clear, False, False, 0)
        tab_playlist.pack_start(pl_header, False, False, 0)
        self._set_playlist_title()

        cd_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            margin_start=8,
            margin_end=8,
            margin_bottom=4,
            spacing=2,
        )
        self.cd_counter = Gtk.Label(label=f"0:00 / {CD_MAX_LABEL}", xalign=0)
        self.cd_counter.get_style_context().add_class("cd-counter")
        self.cd_bar = Gtk.ProgressBar()
        self.cd_bar.get_style_context().add_class("cd-bar")
        self.cd_bar.connect("size-allocate", self._on_cd_bar_allocate)
        # Thin vertical line overlaid on the bar marking the 700 MB CD-sized
        # data disc capacity once the bar has rescaled to the 4.7 GB DVD
        # budget - lets you see at a glance whether a CD still suffices.
        self._cd_marker_fraction = None
        self.cd_marker = Gtk.Box()
        self.cd_marker.get_style_context().add_class("cd-marker")
        self.cd_marker.set_halign(Gtk.Align.START)
        self.cd_marker.set_valign(Gtk.Align.FILL)
        self.cd_marker.hide()
        cd_overlay = Gtk.Overlay()
        cd_overlay.add(self.cd_bar)
        cd_overlay.add_overlay(self.cd_marker)
        cd_box.pack_start(self.cd_counter, False, False, 0)
        cd_box.pack_start(cd_overlay, False, False, 0)
        tab_playlist.pack_start(cd_box, False, False, 0)
        tab_playlist.pack_start(Gtk.Separator(), False, False, 0)

        sw2 = Gtk.ScrolledWindow()
        self.pl_store = Gtk.ListStore(str, str, str, str, str)
        self.pl_view = Gtk.TreeView(model=self.pl_store, headers_visible=False)
        self.pl_view.set_rules_hint(True)
        self.pl_view.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)

        rend_num = Gtk.CellRendererText(xalign=1.0)
        rend_num.set_property("foreground", "#5050a0")
        col_num = Gtk.TreeViewColumn("", rend_num, text=1)
        col_num.set_min_width(28)
        self.pl_view.append_column(col_num)

        for col_idx, expand in [(2, True), (3, True), (4, False)]:
            r = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
            c = Gtk.TreeViewColumn("", r, text=col_idx)
            c.set_expand(expand)
            self.pl_view.append_column(c)

        self.pl_view.set_reorderable(True)
        self.pl_view.connect("button-press-event", self._on_pl_right_click)
        self.pl_view.connect("key-press-event", self._on_pl_key)
        self.pl_store.connect("row-deleted", self._sync_playlist_from_store)
        sw2.add(self.pl_view)
        tab_playlist.pack_start(sw2, True, True, 0)

        btn_add = Gtk.Button(label=_("+ Add selection"))
        btn_add.set_margin_start(8)
        btn_add.set_margin_end(8)
        btn_add.set_margin_top(4)
        btn_add.get_style_context().add_class("add-btn")
        btn_add.connect(
            "clicked", lambda _b: self.add_tracks(self._get_library_selection())
        )
        tab_playlist.pack_start(btn_add, False, False, 0)

        self.notebook.append_page(tab_playlist, Gtk.Label(label=_("Editor")))

        # ── Tab 2: Playlist-Sammlung ──
        tab_collection = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        coll_toolbar = Gtk.Box(spacing=4, margin=8)
        self.pl_sort_combo = Gtk.ComboBoxText()
        self.pl_sort_combo.append("az", _("A–Z"))
        self.pl_sort_combo.append("newest", _("Newest"))
        self.pl_sort_combo.set_active_id("az")
        self.pl_sort_combo.connect(
            "changed", lambda _c: self._refresh_playlist_collection()
        )
        coll_toolbar.pack_start(self.pl_sort_combo, True, True, 0)

        for icon, tip, cb in [
            ("list-add-symbolic", _("New playlist"), self._new_playlist),
            ("insert-text-symbolic", _("Rename playlist"), self._rename_playlist),
            ("edit-delete-symbolic", _("Delete playlist"), self._delete_playlist),
        ]:
            b = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.SMALL_TOOLBAR)
            b.set_tooltip_text(tip)
            b.connect("clicked", cb)
            coll_toolbar.pack_start(b, False, False, 0)
        tab_collection.pack_start(coll_toolbar, False, False, 0)

        coll_sw = Gtk.ScrolledWindow()
        # cols: 0=Name  1=Tracks  2=Modified
        self.pl_collection_store = Gtk.ListStore(str, str, str)
        self.pl_collection_view = Gtk.TreeView(model=self.pl_collection_store)
        self.pl_collection_view.set_rules_hint(True)
        for title, col, expand in [
            (_("Name"), 0, True),
            (_("Tracks"), 1, False),
            (_("Modified"), 2, False),
        ]:
            r = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
            c = Gtk.TreeViewColumn(title, r, text=col)
            c.set_expand(expand)
            self.pl_collection_view.append_column(c)
        self.pl_collection_view.connect(
            "row-activated", self._on_collection_row_activated
        )
        coll_sw.add(self.pl_collection_view)
        tab_collection.pack_start(coll_sw, True, True, 0)

        self.notebook.append_page(tab_collection, Gtk.Label(label=_("Saved")))
        self.notebook.connect("switch-page", self._on_notebook_switch_page)

        self.pack_start(self.notebook, True, True, 0)
        self._refresh_playlist_collection()

        self.pack_start(Gtk.Separator(), False, False, 4)

        self.burn_btn = Gtk.Button(label=_("● BURN CD"))
        self.burn_btn.set_margin_start(8)
        self.burn_btn.set_margin_end(8)
        self.burn_btn.set_margin_bottom(8)
        self.burn_btn.set_margin_top(4)
        self.burn_btn.get_style_context().add_class("burn-btn")
        self.burn_btn.connect("clicked", lambda _b: self._on_burn_requested())
        self.burn_btn.set_sensitive(False)
        self.pack_start(self.burn_btn, False, False, 0)

    # ── Public API ──
    def get_selected_track(self):
        sel = self.pl_view.get_selection()
        model, paths = sel.get_selected_rows()
        if not paths:
            return None
        row = model[paths[0]]
        track = next((t for t in self.playlist_tracks if t["Id"] == row[0]), None)
        if not track:
            return None
        return row[0], f"{row[3]} - {row[2]}", track

    def add_tracks(self, tracks):
        for track in tracks:
            if any(t["Id"] == track["Id"] for t in self.playlist_tracks):
                continue
            self._add_track_row(track)
        self._update_cd_counter()

    def replace_with(self, tracks, name):
        self._autosave_current_playlist()
        self._clear_playlist()
        for track in tracks:
            self._add_track_row(track)
        self.playlist_name = name
        self._set_playlist_title()
        self._update_cd_counter()
        self._refresh_playlist_collection()

    def autosave(self):
        self._autosave_current_playlist()

    def total_seconds(self):
        client = self._get_client()
        if not client:
            return 0
        return sum(
            client.ticks_to_seconds(t.get("RunTimeTicks", 0))
            for t in self.playlist_tracks
        )

    # ── internal helpers ──
    def _add_track_row(self, track):
        self.playlist_tracks.append(track)
        client = self._get_client()
        dur = client.format_duration(track.get("RunTimeTicks", 0)) if client else ""
        self.pl_store.append(
            [
                track["Id"],
                str(len(self.playlist_tracks)),
                track.get("Name", ""),
                track_artist(track),
                dur,
            ]
        )

    def _on_pl_right_click(self, widget, event):
        if event.button == 3:
            menu = Gtk.Menu()
            item_remove = Gtk.MenuItem(label=_("Remove from playlist"))
            item_remove.connect("activate", self._remove_from_playlist)
            menu.append(item_remove)
            menu.show_all()
            menu.popup_at_pointer(event)

    def _sync_playlist_from_store(self, *_):
        if self._ignore_store_signals:
            return
        id_to_track = {t["Id"]: t for t in self.playlist_tracks}
        self.playlist_tracks = [
            id_to_track[row[0]] for row in self.pl_store if row[0] in id_to_track
        ]
        self._renumber_playlist()
        self._update_cd_counter()

    def _on_pl_key(self, widget, event):
        from gi.repository import Gdk

        if event.keyval in (Gdk.KEY_Delete, Gdk.KEY_KP_Delete):
            self._remove_from_playlist(None)
            return True

    def _remove_from_playlist(self, _btn):
        self._ignore_store_signals = True
        sel = self.pl_view.get_selection()
        model, paths = sel.get_selected_rows()
        for path in reversed(paths):
            track_id = model[path][0]
            self.playlist_tracks = [
                t for t in self.playlist_tracks if t["Id"] != track_id
            ]
            model.remove(model.get_iter(path))
        self._ignore_store_signals = False
        self._renumber_playlist()
        self._update_cd_counter()

    def _renumber_playlist(self):
        for i, row in enumerate(self.pl_store):
            row[1] = str(i + 1)

    def _clear_playlist(self):
        self._ignore_store_signals = True
        self.playlist_tracks = []
        self.pl_store.clear()
        self._ignore_store_signals = False
        self._update_cd_counter()

    # ── Playlist-Verwaltung (mehrere gespeicherte Playlists) ──
    def _set_playlist_title(self):
        name = self.playlist_name or _("Untitled")
        self.pl_title_label.set_markup(
            f'<span font_desc="11" weight="bold" color="#9090b0">{GLib.markup_escape_text(name.upper())}</span>'
        )

    def _on_clear_clicked(self, _btn):
        self._clear_playlist()
        self.playlist_name = None
        self._set_playlist_title()

    def _generate_untitled_name(self):
        base = _("Untitled")
        existing = {info["name"] for info in list_playlists_info()}
        if base not in existing:
            return base
        i = 2
        while f"{base} ({i})" in existing:
            i += 1
        return f"{base} ({i})"

    def _autosave_current_playlist(self):
        if not self.playlist_tracks:
            return
        if not self.playlist_name:
            self.playlist_name = self._generate_untitled_name()
            self._set_playlist_title()
        pl_save(self.playlist_name, self.playlist_tracks)

    def _refresh_playlist_collection(self):
        infos = list_playlists_info()
        if self.pl_sort_combo.get_active_id() == "newest":
            infos.sort(key=lambda i: -i["mtime"])
        else:
            infos.sort(key=lambda i: i["name"].lower())
        self.pl_collection_store.clear()
        for info in infos:
            modified = (
                datetime.fromtimestamp(info["mtime"]).strftime("%d.%m.%Y %H:%M")
                if info["mtime"]
                else ""
            )
            self.pl_collection_store.append(
                [info["name"], str(info["count"]), modified]
            )

    def _on_notebook_switch_page(self, notebook, page, page_num):
        if page_num == 1:
            self._refresh_playlist_collection()

    def _on_collection_row_activated(self, treeview, path, col):
        name = treeview.get_model()[path][0]
        self._load_named_playlist(name)

    def _load_named_playlist(self, name):
        if not name or name == self.playlist_name:
            return
        self._autosave_current_playlist()
        self._clear_playlist()
        for track in pl_load(name):
            if not isinstance(track, dict) or "Id" not in track:
                continue
            self._add_track_row(track)
        self.playlist_name = name
        self._set_playlist_title()
        self._update_cd_counter()
        self._switch_to_playlist_tab()

    def _switch_to_playlist_tab(self):
        self.notebook.set_current_page(0)

    def _get_selected_collection_name(self):
        model, it = self.pl_collection_view.get_selection().get_selected()
        return model[it][0] if it else None

    def _new_playlist(self, _btn):
        toplevel = self.get_toplevel()
        name = prompt_text(toplevel, _("New playlist"))
        if not name:
            return
        self._autosave_current_playlist()
        self._clear_playlist()
        self.playlist_name = name
        self._set_playlist_title()
        pl_save(name, [])
        self._update_cd_counter()
        self._refresh_playlist_collection()
        self._switch_to_playlist_tab()

    def _rename_playlist(self, _btn):
        old_name = self._get_selected_collection_name()
        if not old_name:
            return
        toplevel = self.get_toplevel()
        new_name = prompt_text(toplevel, _("Rename playlist"), default=old_name)
        if not new_name or new_name == old_name:
            return
        pl_rename(old_name, new_name)
        if self.playlist_name == old_name:
            self.playlist_name = new_name
            self._set_playlist_title()
        self._refresh_playlist_collection()

    def _delete_playlist(self, _btn):
        name = self._get_selected_collection_name()
        if not name:
            return
        toplevel = self.get_toplevel()
        dlg = Gtk.MessageDialog(
            transient_for=toplevel,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=_('Delete playlist "{name}"?').format(name=name),
        )
        resp = dlg.run()
        dlg.destroy()
        if resp != Gtk.ResponseType.OK:
            return
        pl_delete(name)
        if self.playlist_name == name:
            self.playlist_name = None
            self._clear_playlist()
            self._set_playlist_title()
        self._refresh_playlist_collection()

    def _save_playlist(self, _btn):
        if not self.playlist_tracks:
            return
        toplevel = self.get_toplevel()
        dlg = Gtk.FileChooserDialog(
            title=_("Save playlist"),
            transient_for=toplevel,
            action=Gtk.FileChooserAction.SAVE,
        )
        dlg.add_buttons(
            _("Cancel"), Gtk.ResponseType.CANCEL, _("Save"), Gtk.ResponseType.OK
        )
        dlg.set_current_name("playlist.json")
        dlg.set_do_overwrite_confirmation(True)
        ff = Gtk.FileFilter()
        ff.set_name(_("JSON files"))
        ff.add_pattern("*.json")
        dlg.add_filter(ff)
        if dlg.run() == Gtk.ResponseType.OK:
            path = dlg.get_filename()
            if not path.endswith(".json"):
                path += ".json"
            try:
                with open(path, "w") as f:
                    json.dump(self.playlist_tracks, f, indent=2)
            except OSError as e:
                show_error(toplevel, _("Save failed: {error}").format(error=e))
        dlg.destroy()

    def _load_playlist(self, _btn):
        toplevel = self.get_toplevel()
        dlg = Gtk.FileChooserDialog(
            title=_("Load playlist"),
            transient_for=toplevel,
            action=Gtk.FileChooserAction.OPEN,
        )
        dlg.add_buttons(
            _("Cancel"), Gtk.ResponseType.CANCEL, _("Open"), Gtk.ResponseType.OK
        )
        ff = Gtk.FileFilter()
        ff.set_name(_("JSON files"))
        ff.add_pattern("*.json")
        dlg.add_filter(ff)
        if dlg.run() == Gtk.ResponseType.OK:
            path = dlg.get_filename()
            try:
                with open(path) as f:
                    tracks = json.load(f)
                if not isinstance(tracks, list):
                    raise ValueError(_("Invalid format"))
                self._clear_playlist()
                self.playlist_name = None
                self._set_playlist_title()
                for track in tracks:
                    if not isinstance(track, dict) or "Id" not in track:
                        continue
                    if any(t["Id"] == track["Id"] for t in self.playlist_tracks):
                        continue
                    self._add_track_row(track)
                self._update_cd_counter()
            except (OSError, json.JSONDecodeError, ValueError) as e:
                show_error(toplevel, _("Load failed: {error}").format(error=e))
        dlg.destroy()

    def _on_cd_bar_allocate(self, widget, allocation):
        if self._cd_marker_fraction is None:
            return
        x = int(allocation.width * self._cd_marker_fraction)
        self.cd_marker.set_margin_start(x)

    def _update_cd_counter(self):
        total_s = self.total_seconds()

        ctx = self.cd_bar.get_style_context()
        ctx.remove_class("cd-yellow")
        ctx.remove_class("cd-red")
        ctr_ctx = self.cd_counter.get_style_context()
        ctr_ctx.remove_class("over-limit")

        if total_s > CD_MAX_SECONDS:
            # Won't fit an audio CD - this is the same threshold at which
            # burning switches to an MP3 data disc (see
            # MainWindow._start_burn). Below the 700 MB CD-sized data disc
            # budget, show that; above it, rescale the whole bar to the
            # 4.7 GB DVD budget with a marker at the 700 MB mark, so it's
            # clear a CD no longer suffices.
            est_bytes = total_s * (MP3_BITRATE_KBPS * 1000 // 8)
            needs_dvd = est_bytes > CD_DATA_MAX_BYTES
            scale_max = DVD_DATA_MAX_BYTES if needs_dvd else CD_DATA_MAX_BYTES
            fraction = min(est_bytes / scale_max, 1.0)
            self.cd_bar.set_fraction(fraction)

            if needs_dvd:
                self._cd_marker_fraction = CD_DATA_MAX_BYTES / DVD_DATA_MAX_BYTES
                self.cd_marker.show()
                self._on_cd_bar_allocate(self.cd_bar, self.cd_bar.get_allocation())
            else:
                self._cd_marker_fraction = None
                self.cd_marker.hide()

            mb = est_bytes // 1_000_000
            max_mb = scale_max // 1_000_000
            disc = "MP3-DVD" if needs_dvd else "MP3-CD"
            if est_bytes > scale_max:
                ctx.add_class("cd-red")
                ctr_ctx.add_class("over-limit")
                self.cd_counter.set_text(
                    f"~{mb} / {max_mb} MB ({disc})  ⚠ " + _("TOO LONG")
                )
            else:
                if fraction > 0.85:
                    ctx.add_class("cd-yellow")
                self.cd_counter.set_text(f"~{mb} / {max_mb} MB ({disc})")
        else:
            self._cd_marker_fraction = None
            self.cd_marker.hide()
            fraction = min(total_s / CD_MAX_SECONDS, 1.0)
            self.cd_bar.set_fraction(fraction)
            if fraction > 0.85:
                ctx.add_class("cd-yellow")
            self.cd_counter.set_text(f"{seconds_to_mmss(total_s)} / {CD_MAX_LABEL}")

        self.burn_btn.set_sensitive(len(self.playlist_tracks) > 0)
