import glob
import os
import shutil
import tempfile
import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from .. import burner
from ..api import track_artist
from ..config import (
    CD_DATA_MAX_BYTES,
    LOG_DIR,
    MP3_BITRATE_KBPS,
    check_dependencies,
    get_iso_tool,
)
from ..i18n import _


class BurnDialog(Gtk.Dialog):
    def __init__(self, parent, playlist, client, config, mode="audio", max_bytes=CD_DATA_MAX_BYTES):
        super().__init__(title=_("Burn CD"), transient_for=parent, modal=True)
        self.set_default_size(500, 400)
        self.playlist = playlist
        self.client = client
        self.config = config
        self.mode = mode
        self.max_bytes = max_bytes
        self.cancelled = False
        self._burning = False
        self.last_log_path = None

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)

        if mode == "mp3":
            disc = _("DVD") if max_bytes > CD_DATA_MAX_BYTES else _("CD")
            mode_text = _("Burning as: MP3 data {disc} ({kbps} kbps)").format(
                disc=disc, kbps=MP3_BITRATE_KBPS
            )
        else:
            mode_text = _("Burning as: Audio CD")
        box.pack_start(
            Gtk.Label(label=f"<b>{mode_text}</b>", use_markup=True, xalign=0),
            False,
            False,
            0,
        )

        box.pack_start(
            Gtk.Label(label=f"<b>{_('Tracks on CD:')}</b>", use_markup=True, xalign=0),
            False,
            False,
            0,
        )

        sw = Gtk.ScrolledWindow()
        sw.set_min_content_height(150)
        tv = Gtk.TextView(editable=False, monospace=True)
        buf = tv.get_buffer()
        lines = "\n".join(
            f"{i+1:2}. {track_artist(t) or '?'} - {t.get('Name','?')}"
            f" ({client.format_duration(t.get('RunTimeTicks', 0))})"
            for i, t in enumerate(playlist)
        )
        buf.set_text(lines)
        sw.add(tv)
        box.pack_start(sw, True, True, 0)

        self.status_label = Gtk.Label(label=_("Ready to burn."), xalign=0)
        self.status_label.set_line_wrap(True)
        box.pack_start(self.status_label, False, False, 0)

        self.progress = Gtk.ProgressBar()
        self.progress.set_show_text(True)
        box.pack_start(self.progress, False, False, 0)

        btn_box = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        btn_box.set_margin_top(4)

        self.log_btn = Gtk.Button(label=_("Show log"))
        self.log_btn.connect("clicked", self._on_show_log)
        self.log_btn.set_sensitive(False)
        btn_box.pack_start(self.log_btn, False, False, 0)

        self.cancel_btn = Gtk.Button(label=_("Cancel"))
        self.cancel_btn.connect("clicked", self._on_cancel)
        btn_box.pack_start(self.cancel_btn, False, False, 0)

        self.burn_btn = Gtk.Button(label=_("Burn now"))
        self.burn_btn.get_style_context().add_class("suggested-action")
        self.burn_btn.connect("clicked", self._on_burn_clicked)
        btn_box.pack_start(self.burn_btn, False, False, 0)

        box.pack_start(btn_box, False, False, 0)
        self.show_all()

    def _on_burn_clicked(self, _btn):
        missing = check_dependencies()
        if missing:
            self._set_status(_("Missing programs: ") + ", ".join(missing))
            return
        if self.mode == "mp3" and not get_iso_tool():
            self._set_status(
                _(
                    "No ISO creation tool found.\nPlease install: sudo apt install xorriso"
                )
            )
            return
        self.burn_btn.set_sensitive(False)
        self.cancel_btn.set_sensitive(False)
        self._burning = True
        threading.Thread(target=self._burn_thread, daemon=True).start()

    def _on_cancel(self, _btn):
        if self._burning:
            self.cancelled = True
        else:
            self.response(Gtk.ResponseType.CANCEL)

    def _on_burn_done(self):
        self._burning = False
        self.cancel_btn.set_label(_("Close"))
        self.cancel_btn.set_sensitive(True)
        self._find_latest_log()
        self.log_btn.set_sensitive(self.last_log_path is not None)

    def _find_latest_log(self):
        try:
            logs = sorted(glob.glob(os.path.join(LOG_DIR, "burn_*.log")))
            self.last_log_path = logs[-1] if logs else None
        except OSError:
            self.last_log_path = None

    def _on_show_log(self, _btn):
        if not self.last_log_path:
            return
        try:
            with open(self.last_log_path) as f:
                content = f.read()
        except OSError as e:
            content = _("Could not read log file: {error}").format(error=e)

        dialog = Gtk.Dialog(
            title=_("Burn log"), transient_for=self, modal=True
        )
        dialog.set_default_size(700, 500)
        dialog.add_button(_("Close"), Gtk.ResponseType.CLOSE)
        area = dialog.get_content_area()

        path_label = Gtk.Label(label=self.last_log_path, xalign=0, selectable=True)
        area.pack_start(path_label, False, False, 4)

        sw = Gtk.ScrolledWindow()
        sw.set_hexpand(True)
        sw.set_vexpand(True)
        tv = Gtk.TextView(editable=False, monospace=True)
        tv.get_buffer().set_text(content)
        sw.add(tv)
        area.pack_start(sw, True, True, 0)

        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def _set_status(self, text):
        GLib.idle_add(self.status_label.set_text, text)

    def _set_progress(self, fraction, text=""):
        def _update():
            self.progress.set_fraction(fraction)
            if text:
                self.progress.set_text(text)

        GLib.idle_add(_update)

    def _burn_thread(self):
        tmpdir = tempfile.mkdtemp(prefix="jellyfin_burn_")
        cb = burner.BurnCallbacks(
            on_status=self._set_status,
            on_progress=self._set_progress,
            is_cancelled=lambda: self.cancelled,
        )
        try:
            if self.mode == "mp3":
                burner.run_mp3_burn(
                    self.playlist,
                    self.client,
                    self.config,
                    tmpdir,
                    cb,
                    max_bytes=self.max_bytes,
                )
            else:
                burner.run_audio_burn(
                    self.playlist, self.client, self.config, tmpdir, cb
                )
        except Exception as e:
            self._set_status(_("Error: {error}").format(error=e))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
            GLib.idle_add(self._on_burn_done)
