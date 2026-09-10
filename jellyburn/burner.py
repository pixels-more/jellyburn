import datetime
import os
import resource
import subprocess

from .api import track_artist
from .config import (
    CD_DATA_MAX_BYTES,
    MP3_BITRATE_KBPS,
    get_burn_tool,
    get_iso_tool,
    new_log_path,
)
from .i18n import _
from .playlists import sanitize_name


class BurnPrereqError(Exception):
    pass


class BurnLogger:
    """Writes a full, untruncated record of a burn attempt to disk.

    The UI only ever shows short status snippets, so this is what you
    check after a failure - it keeps the complete ffmpeg/wodim output,
    not just the last few hundred characters.
    """

    def __init__(self):
        self.path = new_log_path()
        self._f = open(self.path, "w")

    def log(self, msg):
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        self._f.write(f"[{stamp}] {msg}\n")
        self._f.flush()

    def log_command(self, cmd, returncode, output):
        self.log(f"$ {' '.join(cmd)}")
        self.log(f"exit code: {returncode}")
        if output:
            self.log(output)

    def close(self):
        self._f.close()


class BurnCallbacks:
    """Bundle of UI-side callbacks the burn pipeline reports through.

    Keeps this module free of any GTK import - the dialog decides how
    on_status/on_progress get marshaled onto the main thread.
    """

    def __init__(self, on_status, on_progress, is_cancelled):
        self.on_status = on_status
        self.on_progress = on_progress
        self.is_cancelled = is_cancelled


def _cue_escape(text):
    return (text or "").replace('"', "'")


def _frames_to_mmssff(sample_frames, sample_rate=44100):
    """PCM sample count -> CD cue sheet MM:SS:FF (75 frames/sec)."""
    cd_frames = round(sample_frames / sample_rate * 75)
    ff = cd_frames % 75
    total_seconds = cd_frames // 75
    return total_seconds // 60, total_seconds % 60, ff


def concat_wavs_for_cue(wav_files, combined_path):
    """Concatenates per-track WAVs into one file, returns each track's start offset in samples.

    cdrskin's cue sheet parser (unlike cdrecord/wodim) only accepts a single
    FILE clause per cue sheet, so per-track WAV files can't be referenced
    directly - everything has to live in one file addressed by INDEX times.
    """
    import wave

    offsets = []
    total_frames = 0
    with wave.open(combined_path, "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(44100)
        for wav_path in wav_files:
            offsets.append(total_frames)
            with wave.open(wav_path, "rb") as inp:
                out.writeframes(inp.readframes(inp.getnframes()))
                total_frames += inp.getnframes()
    return offsets


def build_cue_sheet(playlist, combined_wav_name, offsets, track_artist):
    album = playlist[0].get("Album", "") if playlist else ""
    album_artist = track_artist(playlist[0]) if playlist else ""
    lines = [
        f'PERFORMER "{_cue_escape(album_artist)}"',
        f'TITLE "{_cue_escape(album)}"',
        f'FILE "{combined_wav_name}" WAVE',
    ]
    for i, (track, offset) in enumerate(zip(playlist, offsets)):
        mm, ss, ff = _frames_to_mmssff(offset)
        lines.append(f"  TRACK {i+1:02d} AUDIO")
        lines.append(f'    TITLE "{_cue_escape(track.get("Name", ""))}"')
        lines.append(f'    PERFORMER "{_cue_escape(track_artist(track))}"')
        lines.append(f"    INDEX 01 {mm:02d}:{ss:02d}:{ff:02d}")
    return "\n".join(lines) + "\n"


def resolve_sg_device(sr_device):
    """Löst /dev/srX in das passende /dev/sgX auf (für wodim nötig)."""
    try:
        name = os.path.basename(sr_device)  # z.B. "sr0"
        sg_dir = f"/sys/block/{name}/device/scsi_generic"
        sg_name = os.listdir(sg_dir)[0]  # z.B. "sg1"
        return f"/dev/{sg_name}"
    except Exception:
        return sr_device  # Fallback: original behalten


def download_track(client, track, index, tmpdir, logger=None):
    url = client.get_download_url(track["Id"])
    if logger:
        logger.log(f"Downloading track {index+1}: {url}")
    resp = client.session.get(url, stream=True)
    resp.raise_for_status()
    src_path = os.path.join(tmpdir, f"track_{index+1:02d}_src")
    size = 0
    with open(src_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)
            size += len(chunk)
    if logger:
        logger.log(f"Downloaded {size} bytes to {src_path}")
    return src_path


def probe_codec(path):
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "csv=p=0",
            path,
        ],
        capture_output=True,
        text=True,
    )
    # ffprobe's csv writer can leave a trailing separator even with a
    # single field - strip it so the caller's "== 'mp3'" check matches.
    return probe.stdout.strip().strip(",").lower()


def convert_to_wav(src, dst, logger=None):
    cmd = ["ffmpeg", "-y", "-i", src, "-ar", "44100", "-ac", "2", "-f", "wav", dst]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if logger:
        logger.log_command(cmd, result.returncode, result.stderr.strip())
    if result.returncode != 0:
        return False, result.stderr.strip()[-400:]
    return True, ""


def convert_to_mp3(src, dst, logger=None):
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        src,
        "-map",
        "0:a:0",
        "-vn",
        "-codec:a",
        "libmp3lame",
        "-b:a",
        f"{MP3_BITRATE_KBPS}k",
        dst,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if logger:
        logger.log_command(cmd, result.returncode, result.stderr.strip())
    if result.returncode != 0:
        return False, result.stderr.strip()[-400:]
    return True, ""


def resolve_burn_prereqs(config):
    device = resolve_sg_device(config.get("cd_device", "/dev/sr0"))
    speed = config.get("burn_speed", 4)
    burn_tool = get_burn_tool()
    if not burn_tool:
        raise BurnPrereqError(
            _("No burn program found.\nPlease install: sudo apt install cdrskin")
        )
    return device, speed, burn_tool


def build_iso(cd_root, iso_path, logger=None):
    iso_tool = get_iso_tool()
    if not iso_tool:
        return False, _(
            "No ISO creation tool found.\nPlease install: sudo apt install xorriso"
        )
    if iso_tool == "xorriso":
        iso_cmd = [
            "xorriso",
            "-as",
            "mkisofs",
            "-J",
            "-R",
            "-V",
            "JELLYBURN",
            "-o",
            iso_path,
            cd_root,
        ]
    else:
        iso_cmd = [iso_tool, "-J", "-R", "-V", "JELLYBURN", "-o", iso_path, cd_root]
    result = subprocess.run(iso_cmd, capture_output=True, text=True)
    if logger:
        logger.log_command(iso_cmd, result.returncode, result.stderr.strip())
    if result.returncode != 0:
        return False, _("ISO creation failed:\n{error}").format(
            error=result.stderr.strip()[-400:]
        )
    return True, ""


def _raise_memlock():
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_MEMLOCK)
        if hard == resource.RLIM_INFINITY:
            resource.setrlimit(
                resource.RLIMIT_MEMLOCK,
                (resource.RLIM_INFINITY, resource.RLIM_INFINITY),
            )
        elif hard > soft:
            resource.setrlimit(resource.RLIMIT_MEMLOCK, (hard, hard))
    except Exception:
        pass


def run_burn_process(cmd, on_output_line, logger=None, cwd=None):
    if logger:
        logger.log(f"$ {' '.join(cmd)}" + (f"  (cwd={cwd})" if cwd else ""))
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        preexec_fn=_raise_memlock,
        cwd=cwd,
    )
    output_lines = []
    for line in proc.stdout:
        line = line.strip()
        output_lines.append(line)
        if logger:
            logger.log(line)
        if "%" in line or "Track" in line or "Writing" in line:
            on_output_line(line)
    proc.wait()
    if logger:
        logger.log(f"exit code: {proc.returncode}")
    return proc.returncode, output_lines


def interpret_burn_result(returncode, output_lines, log_path=None):
    if returncode == 0:
        return True, _("CD burned successfully!")
    full = "\n".join(output_lines[-20:])
    log_hint = _("\n\nFull log: {path}").format(path=log_path) if log_path else ""
    if "RLIMIT_MEMLOCK" in full or "mmap" in full:
        hint = _(
            "Burn error (code {code}) – memory lock problem.\n\n"
            "Fix: install cdrskin (recommended):\n"
            "  sudo apt install cdrskin\n\n"
            "Or set permissions for wodim:\n"
            "  sudo setcap cap_ipc_lock+ep $(which wodim)\n\n"
            "Output:\n{output}{log_hint}"
        ).format(code=returncode, output=full, log_hint=log_hint)
        return False, hint
    return False, _("Burn error (code {code}):\n{output}{log_hint}").format(
        code=returncode, output=full, log_hint=log_hint
    )


def run_audio_burn(playlist, client, config, tmpdir, cb):
    logger = BurnLogger()
    logger.log(f"Starting audio burn, {len(playlist)} tracks")
    wav_files = []
    total = len(playlist)
    for i, track in enumerate(playlist):
        if cb.is_cancelled():
            logger.close()
            return
        name = track.get("Name", f"track_{i+1}")
        artist = track_artist(track)
        cb.on_status(
            _("Downloading: {artist} - {name} ({i}/{total})").format(
                artist=artist, name=name, i=i + 1, total=total
            )
        )
        cb.on_progress(
            i / total / 2, _("Download {i}/{total}").format(i=i + 1, total=total)
        )

        try:
            src_path = download_track(client, track, i, tmpdir, logger)
        except Exception as e:
            logger.log(f"Download failed: {e}")
            cb.on_status(
                _("Download failed: {name}\n{error}\n\nFull log: {log}").format(
                    name=name, error=e, log=logger.path
                )
            )
            logger.close()
            return

        wav_path = os.path.join(tmpdir, f"track_{i+1:02d}.wav")
        cb.on_status(_("Converting: {name}").format(name=name))
        ok, err = convert_to_wav(src_path, wav_path, logger)
        if not ok:
            cb.on_status(
                _("Conversion failed: {name}\n{error}\n\nFull log: {log}").format(
                    name=name, error=err, log=logger.path
                )
            )
            logger.close()
            return
        wav_files.append(wav_path)
        os.unlink(src_path)
        cb.on_progress(
            (i + 1) / total / 2,
            _("Converted {i}/{total}").format(i=i + 1, total=total),
        )

    if cb.is_cancelled():
        logger.close()
        return

    cb.on_status(_("Starting burn – please do not cancel…"))
    cb.on_progress(0.5, _("Burning…"))

    try:
        device, speed, burn_tool = resolve_burn_prereqs(config)
    except BurnPrereqError as e:
        cb.on_status(str(e))
        logger.close()
        return

    if config.get("cd_text", True):
        combined_wav = os.path.join(tmpdir, "cd_audio.wav")
        offsets = concat_wavs_for_cue(wav_files, combined_wav)
        logger.log(f"Combined {len(wav_files)} WAVs into {combined_wav} for cue sheet")
        cue_text = build_cue_sheet(
            playlist, os.path.basename(combined_wav), offsets, track_artist
        )
        cue_path = os.path.join(tmpdir, "burn.cue")
        with open(cue_path, "w") as f:
            f.write(cue_text)
        cmd = [
            burn_tool,
            f"dev={device}",
            f"speed={speed}",
            "-v",
            "-dao",
            "-pad",
            f"-cuefile={cue_path}",
        ]
    else:
        cmd = [
            burn_tool,
            f"dev={device}",
            f"speed={speed}",
            "-v",
            "-dao",
            "-audio",
            "-pad",
        ] + wav_files

    returncode, output_lines = run_burn_process(cmd, cb.on_status, logger, cwd=tmpdir)
    success, message = interpret_burn_result(returncode, output_lines, logger.path)
    cb.on_status(message)
    logger.close()
    if success:
        cb.on_progress(1.0, _("Done!"))


def run_mp3_burn(playlist, client, config, tmpdir, cb, max_bytes=CD_DATA_MAX_BYTES):
    logger = BurnLogger()
    logger.log(
        f"Starting MP3 data-disc burn, {len(playlist)} tracks, "
        f"max_bytes={max_bytes}"
    )
    cd_root = os.path.join(tmpdir, "cd_root")
    os.makedirs(cd_root, exist_ok=True)
    total = len(playlist)
    total_bytes = 0

    for i, track in enumerate(playlist):
        if cb.is_cancelled():
            logger.close()
            return
        name = track.get("Name", f"track_{i+1}")
        artist = track_artist(track)
        cb.on_status(
            _("Downloading: {artist} - {name} ({i}/{total})").format(
                artist=artist, name=name, i=i + 1, total=total
            )
        )
        cb.on_progress(
            i / total / 2, _("Download {i}/{total}").format(i=i + 1, total=total)
        )

        try:
            src_path = download_track(client, track, i, tmpdir, logger)
        except Exception as e:
            logger.log(f"Download failed: {e}")
            cb.on_status(
                _("Download failed: {name}\n{error}\n\nFull log: {log}").format(
                    name=name, error=e, log=logger.path
                )
            )
            logger.close()
            return

        album = track.get("Album") or _("Unknown Album")
        track_num = track.get("IndexNumber") or (i + 1)
        album_dir = os.path.join(cd_root, sanitize_name(f"{artist} - {album}"))
        os.makedirs(album_dir, exist_ok=True)
        dst_name = sanitize_name(f"{track_num:02d} - {name}") + ".mp3"
        dst_path = os.path.join(album_dir, dst_name)
        if os.path.exists(dst_path):
            # Same album + track number can happen with multi-disc albums
            # or duplicate track numbers - keep both instead of overwriting.
            dst_path = os.path.join(
                album_dir, sanitize_name(f"{track_num:02d} - {name} ({i+1})") + ".mp3"
            )

        codec = probe_codec(src_path)
        logger.log(f"Probed codec for {name}: {codec or '(unknown)'}")
        if codec == "mp3":
            os.rename(src_path, dst_path)
        else:
            cb.on_status(_("Converting: {name}").format(name=name))
            ok, err = convert_to_mp3(src_path, dst_path, logger)
            if not ok:
                cb.on_status(
                    _("Conversion failed: {name}\n{error}\n\nFull log: {log}").format(
                        name=name, error=err, log=logger.path
                    )
                )
                logger.close()
                return
            os.unlink(src_path)

        total_bytes += os.path.getsize(dst_path)
        if total_bytes > max_bytes:
            cb.on_status(
                _("Playlist exceeds disc capacity ({mb} MB). Aborting.").format(
                    mb=max_bytes // 1_000_000
                )
            )
            logger.close()
            return

        cb.on_progress(
            (i + 1) / total / 2,
            _("Converted {i}/{total}").format(i=i + 1, total=total),
        )

    if cb.is_cancelled():
        logger.close()
        return

    cb.on_status(_("Creating disc image…"))
    cb.on_progress(0.5, _("Building ISO…"))

    iso_path = os.path.join(tmpdir, "image.iso")
    ok, msg = build_iso(cd_root, iso_path, logger)
    if not ok:
        cb.on_status(msg + "\n\n" + _("Full log: {log}").format(log=logger.path))
        logger.close()
        return

    if cb.is_cancelled():
        logger.close()
        return

    cb.on_status(_("Starting burn – please do not cancel…"))
    cb.on_progress(0.75, _("Burning…"))

    try:
        device, speed, burn_tool = resolve_burn_prereqs(config)
    except BurnPrereqError as e:
        cb.on_status(str(e))
        logger.close()
        return

    cmd = [burn_tool, f"dev={device}", f"speed={speed}", "-v", "-data", iso_path]
    returncode, output_lines = run_burn_process(cmd, cb.on_status, logger)
    success, message = interpret_burn_result(returncode, output_lines, logger.path)
    cb.on_status(message)
    logger.close()
    if success:
        cb.on_progress(1.0, _("Done!"))
