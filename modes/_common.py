import json
import math
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_RUNMEME_MUSIC = SCRIPT_DIR / "stupidshit.mp3"
AVIIF_KEYFRAME = 0x10
RICECAKE_MARKER = b"00dc"
RICECAKE_IFRAME_CODE = bytes.fromhex("0001B0")
RICECAKE_PFRAME_CODE = bytes.fromhex("0001B6")

# ///////////////////////////////////////////////////////////////////////////////////////////

def _log(msg, kind="info"):
    print(f"@@{kind.upper()}@@ {msg}")
    sys.stdout.flush()

def transcode_to_avi(src: Path, dst: Path, gop: int, qscale: int):
    _log(f"{src} -> {dst} (gop={gop}, qscale={qscale})")
    cmd = ["ffmpeg", "-y", "-i", str(src), "-c:v", "mpeg4", "-vtag", "xvid", "-qscale:v", str(qscale), "-g", str(gop), "-bf", "0", "-an", str(dst),]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    size = dst.stat().st_size if dst.exists() else 0
    _log(f"done, wrote {size} bytes", "ok")

def _read_chunks(data: bytes, start: int, end: int):
    pos = start

    while pos + 8 <= end:
        ckid = data[pos:pos + 4]
        size = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        data_off = pos + 8
        yield ckid, data_off, size
        pos = data_off + size + (size & 1)

def find_chunk(data: bytes, fourcc_or_listtype: bytes, list_only=False):
    pos = 12  # start after avif file header
    end = len(data)

    for ckid, off, size in _read_chunks(data, pos, end):
        if ckid == b"LIST":
            list_type = data[off:off + 4]

            if list_type == fourcc_or_listtype:
                return off + 4, size - 4

        elif not list_only and ckid == fourcc_or_listtype:
            return off, size
    return None

def resolve_movi_base(data: bytes, movi_off: int, entries):
    base_candidates = [movi_off - 4, movi_off, 0]

    for base in base_candidates:
        checked = 0
        valid = True

        for ckid, flags, offset, size in entries:
            pos = base + offset

            if pos < 0 or pos + 8 > len(data):
                valid = False
                break

            if bytes(data[pos:pos + 4]) != ckid:
                valid = False
                break

            stored_size = struct.unpack("<I", data[pos + 4:pos + 8])[0]

            if stored_size != size:
                valid = False
                break
            checked += 1

            if checked >= 8:
                break

        if valid and checked > 0:
            _log(f"resolved movi base = {base} (candidate offset {base - movi_off:+d})", "ok")

            return base
        
    raise RuntimeError("unsupported AVI index or the file is corrupted")

def _load_avi_index(data: bytes):
    _log("searching for movi and idx1 chunks...")

    movi = find_chunk(data, b"movi", list_only=True)
    idx1 = find_chunk(data, b"idx1")

    if movi is None or idx1 is None:  # TODO: do fallback l8r
        raise RuntimeError("AVI is missing movi or idx1 chunks.")

    movi_off, movi_size = movi
    idx1_off, idx1_size = idx1

    _log(f"movi @ {movi_off} ({movi_size} bytes), idx1 @ {idx1_off} ({idx1_size} bytes)")

    n_entries = idx1_size // 16
    _log(f"parsing {n_entries} idx1 entries...")
    entries = []

    for i in range(n_entries):
        base = idx1_off + i * 16
        ckid = bytes(data[base:base + 4])
        flags = struct.unpack("<I", data[base + 4:base + 8])[0]
        offset = struct.unpack("<I", data[base + 8:base + 12])[0]
        size = struct.unpack("<I", data[base + 12:base + 16])[0]
        entries.append([ckid, flags, offset, size])

    index_base = resolve_movi_base(data, movi_off, entries)
    _log(f"loaded {len(entries)} entries", "ok")
    return movi_off, idx1_off, idx1_size, entries, index_base

def write_avi_chunks(data: bytearray, movi_off: int, idx1_off: int, idx1_size: int, new_chunks: list, out_path: Path):
    _log(f"assembling {len(new_chunks)} chunks...")

    movi_data = bytearray()
    new_entries = []

    for ckid, flags, raw_bytes in new_chunks:
        chunk_offset = len(movi_data)
        movi_data += raw_bytes
        if len(raw_bytes) & 1: movi_data += b"\x00"
        size = len(raw_bytes) - 8
        new_entries.append([ckid, flags, chunk_offset, size])

    header = data[:movi_off]
    tail_after_idx1_start = idx1_off + idx1_size
    tail_after_idx1_start += (idx1_size & 1)
    trailer = data[tail_after_idx1_start:]

    new_idx1_payload = bytearray()
    for ckid, flags, offset, size in new_entries:
        new_idx1_payload += ckid
        new_idx1_payload += struct.pack("<III", flags, offset, size)

    out = bytearray()
    out += header
    out += movi_data
    if len(movi_data) & 1: out += b"\x00"
    out += b"idx1"
    out += struct.pack("<I", len(new_idx1_payload))
    out += new_idx1_payload
    out += trailer

    list_size_off = movi_off - 8
    new_list_size = 4 + len(movi_data)
    out[list_size_off:list_size_off + 4] = struct.pack("<I", new_list_size)

    out[4:8] = struct.pack("<I", len(out) - 8)

    Path(out_path).write_bytes(bytes(out))
    _log(f"wrote {len(out)} bytes -> {out_path}", "ok")
    return new_entries

def _probe_fps(path: Path):
    _log(f"checking fps of {path}")

    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", str(path)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,)
        line = r.stdout.strip().splitlines()[0]
        num, den = line.split("/")
        den_f = float(den)
        fps = float(num) / den_f if den_f else None
        _log(f"fps = {fps}", "ok")
        return fps
    
    except Exception as e:
        _log(f"failed: {e}", "err")
        return None

def source_has_audio(src: Path) -> bool:
    _log(f"checking audiostream in {src}")

    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(src)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,)
        has_audio = bool(result.stdout.strip())
        _log(f"has_audio = {has_audio}", "ok" if has_audio else "err")
        return has_audio
    
    except Exception as e:
        _log(f"failed: {e}", "err")
        return False

def _probe_av(path: Path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "json", str(path)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,)
    has_audio = False
    a_dur = None
    v_dur = None

    for s in json.loads(r.stdout).get("streams", []):
        try:
            d = float(s.get("duration"))

        except (TypeError, ValueError):
            d = None

        if s.get("codec_type") == "audio":
            has_audio = True
            a_dur = d

        elif s.get("codec_type") == "video" and v_dur is None:
            v_dur = d

    return has_audio, a_dur, v_dur

def ensure_audio_stream(path: Path):
    try:
        has_a, a_dur, v_dur = _probe_av(path)

    except Exception as e:
        _log(f"couldn't probe {path.name} ({e}), leaving it as is", "err")
        return
    
    if has_a and a_dur is not None and v_dur is not None and a_dur >= v_dur - 0.03:
        return

    fixed = path.with_suffix(".padaudio.mp4")
    silent = ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-map", "0:v:0", "-map", "1:a:0"]
    padded = ["-filter_complex", "[0:a:0]aresample=44100,apad[a]", "-map", "0:v:0", "-map", "[a]"]
    tail = ["-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest", str(fixed)]
    base = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(path)]

    # no audio at all we silence
    attempts = [silent] if (not has_a or a_dur is None or a_dur < 0.03) else [padded, silent]
    last_err = None

    for extra in attempts:
        try:
            subprocess.run(base + extra + tail, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            path.unlink()
            fixed.rename(path)

            _log(f"{path.name}: source audio ran out, filled with silence", "ok")
            return
        
        except subprocess.CalledProcessError as e:
            last_err = e
            fixed.unlink(missing_ok=True)

    raise last_err

def _probe_duration(path: Path) -> float:
    _log(f"checking duration of {path}")

    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,)
    dur = float(r.stdout.strip())

    _log(f"duration = {dur:.3f}s", "ok")
    return dur

def mux_audio_and_finalize(src_for_audio: Path, moshed_video: Path, final_out: Path, add_audio: bool, speed_factor: float = 1.0, audio_filter_complex: str = None, audio_filter_complex_label: str = None, crf: int = 18):
    _log(f"moshed_video={moshed_video} -> final_out={final_out} add_audio={add_audio} speed_factor={speed_factor:.3f} crf={crf}")

    has_audio = add_audio and source_has_audio(src_for_audio)
    ext = final_out.suffix.lower()

    if final_out.exists():
        _log(f"removing existing {final_out}")
        final_out.unlink()

    use_filter_complex = has_audio and audio_filter_complex is not None
    _log(f"has_audio = {has_audio} use_filter_complex = {use_filter_complex} ext={ext}")

    audio_filters = []
    if not use_filter_complex and speed_factor != 1.0:
        remaining = speed_factor
        while remaining > 2.0:
            audio_filters.append("atempo=2.0")
            remaining /= 2.0
        while remaining < 0.5:
            audio_filters.append("atempo=0.5")
            remaining /= 0.5
        audio_filters.append(f"atempo = {remaining:.6f}")

    af_args = (["-af", ",".join(audio_filters)] if audio_filters else [])

    if not has_audio:

        if ext == ".mp4":
            _log("no audio, encoding video only MPEG-4...")
            cmd = ["ffmpeg", "-y", "-i", str(moshed_video), "-c:v", "libx264", "-preset", "fast", "-crf", str(crf), "-pix_fmt", "yuv420p", "-an", str(final_out),]

            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            moshed_video.unlink()

        else:
            _log("no audio, renaming raw output...")

            moshed_video.replace(final_out)

        _log(f"done -> {final_out}", "ok")
        return

    fc_script_path = None

    if use_filter_complex:
        _log("writing filter_complex script to temp file...")

        fc_fd, fc_name = tempfile.mkstemp(suffix=".txt", prefix="datamosh_filtercomplex_")
        fc_script_path = Path(fc_name)

        with os.fdopen(fc_fd, "w", encoding="utf-8") as fh:
            fh.write(audio_filter_complex)

        fc_args = ["-filter_complex_script", str(fc_script_path)]
        map_args = ["-map", "0:v:0", "-map", f"[{audio_filter_complex_label}]"]

    else:
        fc_args = []
        map_args = ["-map", "0:v:0", "-map", "1:a:0"]

    if ext == ".mp4":
        cmd = ["ffmpeg", "-y", "-i", str(moshed_video), "-i", str(src_for_audio),] + fc_args + map_args + ["-c:v", "libx264", "-preset", "fast", "-crf", str(crf), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",] + af_args + ["-shortest", str(final_out),]
    else:
        cmd = ["ffmpeg", "-y", "-i", str(moshed_video), "-i", str(src_for_audio),] + fc_args + map_args + ["-c:v", "copy", "-c:a", "mp3", "-b:a", "192k",] + af_args + ["-shortest", str(final_out),]

    _log("running ffmpeg mux command...")

    try:
        subprocess.run(cmd, check=True, text=True, capture_output=True,)

    except subprocess.CalledProcessError as e:
        _log("FFMPEG STDERR", "err")
        _log(e.stderr, "err")

        raise

    finally:
        if fc_script_path is not None and fc_script_path.exists():
            _log(f"cleaning up {fc_script_path}")

            fc_script_path.unlink()

    moshed_video.unlink()

    _log(f"done -> {final_out}", "ok")

def freeze_last_frame(src_clip: Path, dst_path: Path, freeze_dur: float, has_audio: bool):
    _log(f"creating {freeze_dur:.3f}s freeze from last frame of {src_clip.name}")

    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", str(src_clip)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,)
        fps_str = r.stdout.strip().splitlines()[0]
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) else 30.0

    except Exception:
        fps = 30.0
    _log(f"source fps = {fps:.3f}")

    frame_path = dst_path.with_suffix(".freeze_frame.png")
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-sseof", "-1", "-i", str(src_clip), "-update", "1", "-q:v", "2", str(frame_path)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,)

    silent_fill = False

    if has_audio:
        try:
            silent_fill = not _probe_av(src_clip)[0]
        except Exception:
            silent_fill = False

    if has_audio and silent_fill:
        _log(f"{src_clip.name} has no audio track, filling the freeze with silence", "err")
        cmd_freeze = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-framerate", str(fps), "-i", str(frame_path), "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-map", "0:v:0", "-map", "1:a:0", "-t", str(freeze_dur), "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", "-vsync", "cfr", "-video_track_timescale", "90000", "-c:a", "aac", "-ar", "44100", "-ac", "2", str(dst_path),]
    
    elif has_audio:
        tail_dur = max(2.0 / fps, 0.07)
        loop_count = math.ceil(freeze_dur / tail_dur) + 1
        audio_filter = (f"[1:a]atrim=0:{tail_dur},asetpts=PTS-STARTPTS," f"aloop=loop={loop_count}:size=2147483647," f"atrim=0:{freeze_dur},asetpts=PTS-STARTPTS[aout]")
        cmd_freeze = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-framerate", str(fps), "-i", str(frame_path), "-sseof", f"-{tail_dur + 0.5}", "-i", str(src_clip), "-filter_complex", audio_filter, "-map", "0:v:0", "-map", "[aout]", "-t", str(freeze_dur), "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", "-vsync", "cfr", "-video_track_timescale", "90000", "-c:a", "aac", "-ar", "44100", "-ac", "2", str(dst_path),]
    
    else:
        cmd_freeze = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-framerate", str(fps), "-i", str(frame_path), "-t", str(freeze_dur), "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", "-vsync", "cfr", "-video_track_timescale", "90000", "-an", str(dst_path),]

    subprocess.run(cmd_freeze, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frame_path.unlink(missing_ok=True)
    _log(f"done -> {dst_path.name}", "ok")