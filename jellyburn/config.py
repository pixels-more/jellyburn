import glob
import hashlib
import json
import os
import subprocess

REQUIRED_TOOLS = {
    "mpv": "Wiedergabe (mpv)",
    "ffmpeg": "Audio-Konvertierung (ffmpeg)",
}


def _xdg_dir(env_var, fallback):
    # Respect the XDG base-directory spec. This is essential inside a
    # Flatpak sandbox: XDG_CONFIG_HOME/XDG_CACHE_HOME point at the app's
    # persisted per-app directory, whereas a hardcoded ~/.config resolves
    # (via HOME) to a path in the sandbox's *ephemeral* overlay that is
    # wiped on every restart - so settings never persisted there. An
    # unset or non-absolute value falls back to the ~ default, keeping
    # native behavior identical.
    path = os.environ.get(env_var, "")
    return path if path.startswith(os.sep) else os.path.expanduser(fallback)


CONFIG_HOME = _xdg_dir("XDG_CONFIG_HOME", "~/.config")
CACHE_HOME = _xdg_dir("XDG_CACHE_HOME", "~/.cache")

CONFIG_FILE = os.path.join(CONFIG_HOME, "jellyburn.json")

DEFAULT_CONFIG = {
    "server_url": "",
    "username": "",
    "api_key": "",
    "cd_device": "/dev/sr0",
    "burn_speed": 4,
    "cd_text": True,
    "mp3_auto_switch": False,
    "eq_enabled": False,
    "eq_bands": [0.0] * 10,
    "theme": "dark",
    "language": "en",
}

CD_MAX_SECONDS = 74 * 60
CD_DATA_MAX_BYTES = 700_000_000
DVD_DATA_MAX_BYTES = 4_700_000_000
MP3_BITRATE_KBPS = 192


def get_burn_tool():
    """Gibt 'cdrskin' oder 'wodim' zurück, je nachdem was installiert ist."""
    for cmd in ("cdrskin", "wodim"):
        if subprocess.run(["which", cmd], capture_output=True).returncode == 0:
            return cmd
    return None


def get_iso_tool():
    """Gibt das erste verfügbare ISO-Erstellungswerkzeug zurück."""
    for cmd in ("xorriso", "genisoimage", "mkisofs"):
        if subprocess.run(["which", cmd], capture_output=True).returncode == 0:
            return cmd
    return None


def check_dependencies():
    missing = [
        label
        for cmd, label in REQUIRED_TOOLS.items()
        if subprocess.run(["which", cmd], capture_output=True).returncode != 0
    ]
    if get_burn_tool() is None:
        missing.append("CD-Brennen (cdrskin oder wodim)")
    return missing


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        return {**DEFAULT_CONFIG, **cfg}
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


CACHE_DIR = os.path.join(CACHE_HOME, "jellyburn")
LOG_DIR = os.path.join(CACHE_DIR, "logs")
MAX_LOG_FILES = 20


def _prune_old_logs():
    logs = sorted(glob.glob(os.path.join(LOG_DIR, "burn_*.log")))
    for path in logs[:-MAX_LOG_FILES]:
        try:
            os.remove(path)
        except OSError:
            pass


def new_log_path():
    import datetime

    os.makedirs(LOG_DIR, exist_ok=True)
    _prune_old_logs()
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(LOG_DIR, f"burn_{stamp}.log")


def _cache_path(server_url):
    h = hashlib.md5(server_url.encode()).hexdigest()[:10]
    return os.path.join(CACHE_DIR, f"library_{h}.json")


def load_library_cache(server_url):
    path = _cache_path(server_url)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    return None


def save_library_cache(server_url, tracks):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(_cache_path(server_url), "w") as f:
        json.dump(tracks, f)


def detect_cd_devices():
    """Gibt Liste von (dev_path, label) für alle erkannten optischen Laufwerke zurück."""
    devices = []
    for sr in sorted(glob.glob("/sys/block/sr*")):
        name = os.path.basename(sr)
        dev = f"/dev/{name}"
        try:
            vendor = open(f"{sr}/device/vendor").read().strip()
            model = open(f"{sr}/device/model").read().strip()
            label = f"{vendor} {model}  ({dev})"
        except OSError:
            label = dev
        devices.append((dev, label))
    return devices
