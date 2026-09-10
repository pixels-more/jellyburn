import os

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio, GLib

# Inside a Flatpak sandbox the host GTK theme's files are usually not
# available, so GTK falls back to the runtime's light "Default" theme,
# which ignores gtk-application-prefer-dark-theme. Widgets our custom
# CSS doesn't explicitly cover (menus, entries, dialogs, combos) then
# render light on top of the dark skin ("half-dark" look). We detect the
# sandbox to pin a guaranteed-dark base there.
_IN_FLATPAK = os.path.exists("/.flatpak-info")

DARK_CSS = """
window, .main-box {
    background-color: #12121a;
    color: #d8d8e0;
}
headerbar, headerbar * {
    background-color: #1a1a2e;
    border-bottom: 1px solid #0a0a14;
    color: #d8d8e0;
}
headerbar button {
    background: transparent;
    border: none;
    color: #9090b0;
    padding: 4px 6px;
}
headerbar button:hover { color: #e94560; }
searchentry {
    background-color: #1e1e30;
    border: 1px solid #2a2a40;
    border-radius: 4px;
    color: #d8d8e0;
    padding: 4px 8px;
}
searchentry:focus { border-color: #e94560; }
treeview {
    background-color: #12121a;
    color: #d8d8e0;
}
treeview:selected {
    background-color: #e94560;
    color: #ffffff;
}
treeview header button {
    background-color: #1a1a2e;
    color: #7070a0;
    border-bottom: 1px solid #0a0a14;
    font-size: 11px;
    letter-spacing: 0.05em;
    padding: 3px 6px;
}
separator { background-color: #222236; }
.lib-status {
    font-size: 11px;
    color: #6060a0;
    padding: 2px 6px;
}
.panel-right {
    background-color: #16162a;
    border-left: 1px solid #222236;
}
.panel-right treeview { background-color: #16162a; }
.cd-counter {
    font-family: monospace;
    font-size: 12px;
    color: #7070a0;
    padding: 0 8px;
}
.cd-counter.over-limit { color: #e94560; font-weight: bold; }
progressbar trough {
    background-color: #1e1e30;
    border-radius: 3px;
    min-height: 6px;
}
progressbar progress {
    background-image: none;
    background-color: #3dc47e;
    border-radius: 3px;
    min-height: 6px;
}
progressbar.cd-bar progress {
    background-image: none;
    background-color: #3dc47e;
}
progressbar.cd-yellow progress {
    background-image: none;
    background-color: #e8a838;
}
progressbar.cd-red progress {
    background-image: none;
    background-color: #e94560;
}
.cd-marker {
    min-width: 2px;
    background-color: #d8d8e0;
    opacity: 0.6;
}
button {
    background-color: #1e1e30;
    border: 1px solid #2a2a40;
    border-radius: 3px;
    color: #d8d8e0;
    padding: 4px 10px;
}
button:hover {
    background-color: #2a2a40;
    border-color: #e94560;
}
.add-btn {
    background-color: #1e1e30;
    border: 1px solid #2a2a40;
    color: #9090b0;
    font-size: 12px;
}
.add-btn:hover { border-color: #e94560; color: #e94560; }
.burn-btn {
    background-color: #e94560;
    border: none;
    border-radius: 4px;
    color: #ffffff;
    font-weight: bold;
    font-size: 13px;
    padding: 8px 0;
    letter-spacing: 0.04em;
}
.burn-btn:hover { background-color: #c73652; }
.burn-btn:disabled { background-color: #2a2a40; color: #5050a0; }
.now-playing-box {
    background-color: #1a1a2e;
    border-top: 1px solid #222236;
    padding: 8px;
}
.now-playing-title {
    font-weight: bold;
    font-size: 13px;
    color: #d8d8e0;
}
.now-playing-sub {
    font-size: 11px;
    color: #7070a0;
}
scale.playback trough {
    background-color: #2a2a40;
    min-height: 4px;
    border-radius: 2px;
}
scale.playback highlight {
    background-color: #e94560;
    min-height: 4px;
    border-radius: 2px;
}
scale.playback slider {
    background-color: #e94560;
    border: none;
    border-radius: 50%;
    min-width: 12px;
    min-height: 12px;
}
scale.playback slider:hover {
    background-color: #ff6080;
}
.art-placeholder {
    background-color: #1e1e30;
    border: 1px solid #2a2a40;
    border-radius: 3px;
    color: #3a3a60;
    font-size: 32px;
}
dialog { background-color: #1a1a2e; }
dialog .dialog-action-area button { font-size: 12px; }
.mini-player {
    background-color: #1a1a2e;
    border: 1px solid #222236;
}
paned separator {
    background-color: #222236;
    min-width: 1px;
    min-height: 1px;
}
notebook, notebook > stack {
    background-color: #16162a;
    border: none;
}
notebook > header {
    background-color: #1a1a2e;
    border: none;
    border-bottom: 1px solid #0a0a14;
    box-shadow: none;
}
notebook > header tabs tab {
    background-color: transparent;
    border: none;
    box-shadow: none;
    color: #7070a0;
    padding: 6px 14px;
}
notebook > header tabs tab:checked {
    color: #e94560;
    border-bottom: 2px solid #e94560;
}
.eq-window {
    background-color: #12121a;
    color: #d8d8e0;
}
.eq-window scale trough {
    background-color: #2a2a40;
    min-width: 4px;
    border-radius: 2px;
}
.eq-window scale highlight {
    background-color: #e94560;
    min-width: 4px;
    border-radius: 2px;
}
.eq-window scale slider {
    background-color: #e94560;
    border: none;
    border-radius: 50%;
    min-width: 14px;
    min-height: 14px;
}
.eq-window scale slider:hover {
    background-color: #ff6080;
}
"""


class ThemeManager:
    def __init__(self, screen, config):
        self._screen = screen
        self._config = config
        self._dark_css_provider = Gtk.CssProvider()
        self._dark_css_provider.load_from_data(DARK_CSS.encode())
        self._dark_css_active = False
        settings = Gtk.Settings.get_default()
        # Remember the host theme name so we can restore it when leaving
        # dark mode inside the sandbox (see update()).
        self._original_theme_name = (
            settings.get_property("gtk-theme-name") if settings else None
        )
        self.update()

    @staticmethod
    def _portal_color_scheme():
        # Query the XDG Settings portal for the desktop's preferred
        # color scheme. Returns 1 (dark), 2 (light), 0 (no preference),
        # or None if the portal is unavailable. This is the reliable
        # cross-environment signal - crucially it works inside a Flatpak
        # sandbox, where the host GTK theme name is not always exposed
        # (and even when it is, its name may not contain "dark").
        try:
            proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop",
                "org.freedesktop.portal.Settings",
                None,
            )
            result = proxy.call_sync(
                "Read",
                GLib.Variant("(ss)", ("org.freedesktop.appearance", "color-scheme")),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
            )
            return result.unpack()[0]
        except Exception:
            return None

    def update(self):
        # Jellyburn's custom CSS is a dark-only design (not
        # theme-adaptive) - "light" skips it entirely and lets the
        # default GTK theme render; "system" follows the desktop's
        # preferred color scheme; "dark" always forces it.
        theme = self._config.get("theme", "dark")
        settings = Gtk.Settings.get_default()

        if theme == "light":
            want_dark = False
        elif theme == "dark":
            want_dark = True
        else:  # system
            scheme = self._portal_color_scheme()
            if scheme in (1, 2):
                want_dark = scheme == 1
            else:
                # Portal unavailable - fall back to a theme-name heuristic
                # ("gtk-application-prefer-dark-theme" is only an app-side
                # request, not a readout of the active scheme).
                theme_name = (settings.get_property("gtk-theme-name") or "").lower()
                want_dark = "dark" in theme_name

        if settings is not None:
            # Inside the sandbox, pin GTK's built-in Adwaita (its dark
            # variant is always present and honors prefer-dark) as a
            # reliable dark base for the widgets our CSS doesn't cover;
            # restore the host theme name when not dark. Native runs keep
            # the host theme untouched.
            if _IN_FLATPAK:
                settings.set_property(
                    "gtk-theme-name",
                    "Adwaita" if want_dark else self._original_theme_name,
                )
            settings.set_property("gtk-application-prefer-dark-theme", want_dark)

        if want_dark and not self._dark_css_active:
            Gtk.StyleContext.add_provider_for_screen(
                self._screen,
                self._dark_css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
            self._dark_css_active = True
        elif not want_dark and self._dark_css_active:
            Gtk.StyleContext.remove_provider_for_screen(
                self._screen, self._dark_css_provider
            )
            self._dark_css_active = False
