import argparse
import math
import os
import random
import shutil
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
    pos = 12  # # start after avif file header
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

    raise RuntimeError("Unsupported AVI index format or corrupted file.")

def _load_avi_index(data: bytes):
    _log("locating movi and idx1 chunks...")
    movi = find_chunk(data, b"movi", list_only=True)
    idx1 = find_chunk(data, b"idx1")

    if movi is None or idx1 is None:  # # do fallback l8r
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

def real_datamosh(src_avi: Path, out_avi: Path, start: int, end: int, remove_all: bool, keep_every: int):
    _log(f"reading {src_avi} ({src_avi.stat().st_size} bytes)")
    data = bytearray(Path(src_avi).read_bytes())

    movi_off, idx1_off, idx1_size, entries, index_base = _load_avi_index(data)

    video_indices = [i for i, e in enumerate(entries) if e[0][2:4] == b"dc"]
    _log(f"found {len(video_indices)} video frame chunks")
    if not video_indices:
        raise RuntimeError("No video frame chunks ('??dc') found in idx1.")

    n_keyframes_total = sum(1 for idx in video_indices if entries[idx][1] & AVIIF_KEYFRAME)
    _log(f"{n_keyframes_total} keyframes total, scanning range start={start} end={end} keep_every={keep_every} remove_all={remove_all}")

    to_drop = set()
    for n, idx in enumerate(video_indices):
        flags = entries[idx][1]
        is_keyframe = bool(flags & AVIIF_KEYFRAME)
        if n == 0:
            continue
        if not is_keyframe:
            continue
        if remove_all:
            to_drop.add(idx)
        elif start <= n <= end:
            if keep_every <= 1 or (n % keep_every != 0):
                to_drop.add(idx)

    _log(f"marked {len(to_drop)} keyframes for removal")
    if not to_drop:
        _log("NO KEYFRAMES MATCHED THE RANGE. Output will be the same as input. Check --start --end against the frame count or use --all.", "err")

    new_chunks = []
    for i, e in enumerate(entries):
        ckid, flags, old_offset, size = e
        if i in to_drop:
            continue

        chunk_start = index_base + old_offset
        chunk_header_and_data = bytes(data[chunk_start:chunk_start + 8 + size])
        if len(chunk_header_and_data) < 8 + size or chunk_header_and_data[:4] != ckid:
            raise RuntimeError(f"avif index mismatch at entry {i} ({ckid!r}).")
        new_chunks.append((ckid, flags, chunk_header_and_data))

        if (i + 1) % 500 == 0:
            _log(f"processed {i + 1}/{len(entries)} entries...")

    write_avi_chunks(data, movi_off, idx1_off, idx1_size, new_chunks, out_avi)

    n_dropped = len(to_drop)
    _log(f"real mode: dropped {n_dropped} keyframe out of {len(video_indices)} video frames >>> {out_avi}", "ok")

def stutter_datamosh(src_avi: Path, out_avi: Path, chance: float, dups: int):
    _log(f"reading {src_avi} ({src_avi.stat().st_size} bytes)")
    data = bytearray(Path(src_avi).read_bytes())

    movi_off, idx1_off, idx1_size, entries, index_base = _load_avi_index(data)

    video_indices = [i for i, e in enumerate(entries) if e[0][2:4] == b"dc"]
    _log(f"found {len(video_indices)} video frame chunks, chance={chance} dups={dups}")
    if not video_indices: raise RuntimeError("No videoframe chunks '??dc' found in idx1.")

    new_chunks = []
    frame_copy_counts = []
    pframes_seen = 0
    pframes_duplicated = 0
    iframes = 0

    for i, e in enumerate(entries):
        ckid, flags, old_offset, size = e
        chunk_start = index_base + old_offset
        chunk_header_and_data = bytes(data[chunk_start:chunk_start + 8 + size])

        if len(chunk_header_and_data) < 8 + size or chunk_header_and_data[:4] != ckid: raise RuntimeError(f"Invalid avif index: entry {i} ({ckid!r}) doesnt match the video data.")

        is_video = ckid[2:4] == b"dc"
        is_keyframe = bool(flags & AVIIF_KEYFRAME)

        if is_video:
            if is_keyframe:
                iframes += 1
            else:
                pframes_seen += 1
                if random.random() < chance:
                    pframes_duplicated += 1
                    copies = max(1, dups)
                    for _ in range(copies):
                        new_chunks.append((ckid, flags, chunk_header_and_data))
                    frame_copy_counts.append(copies)
                    continue
                else:
                    frame_copy_counts.append(1)

        new_chunks.append((ckid, flags, chunk_header_and_data))

        if (i + 1) % 500 == 0:
            _log(f"processed {i + 1}/{len(entries)} entries, {pframes_duplicated} duplicated so far...")

    write_avi_chunks(data, movi_off, idx1_off, idx1_size, new_chunks, out_avi)

    _log(f"stutter mode: duplicated {pframes_duplicated}/{pframes_seen} P-frame(s) ({dups}x each) -> {out_avi}", "ok")
    return pframes_seen, pframes_duplicated, dups, iframes, frame_copy_counts

def ricecake_datamosh(src_avi: Path, out_avi: Path, chance: float, dups: int):
    _log(f"reading {src_avi} ({src_avi.stat().st_size} bytes)")
    data = Path(src_avi).read_bytes()

    pieces = data.split(RICECAKE_MARKER)
    _log(f"split into {len(pieces)} raw chunks on marker {RICECAKE_MARKER!r}, chance={chance} dups={dups}")
    if len(pieces) < 2:
        raise RuntimeError(f"Marker {RICECAKE_MARKER!r} not found in transcoded AVI; cannot ricecake this file.")

    iframes = 0
    pframes = 0
    pframes_duplicated = 0
    copies = max(1, int(dups))

    with open(out_avi, "wb") as out:
        for i, piece in enumerate(pieces):
            frame = piece + RICECAKE_MARKER
            code = frame[5:8]

            if code == RICECAKE_IFRAME_CODE:
                iframes += 1
                out.write(frame)
            elif code == RICECAKE_PFRAME_CODE:
                pframes += 1
                if random.random() < chance:
                    pframes_duplicated += 1
                    for _ in range(copies):
                        out.write(frame)
                else:
                    out.write(frame)
            else:
                out.write(frame)

            if (i + 1) % 2000 == 0:
                _log(f"processed {i + 1}/{len(pieces)} chunks, {pframes_duplicated} duplicated so far...")

    _log(f"ricecake mode: duplicated {pframes_duplicated}/{pframes} P-frame(s) ({copies}x each), saw {iframes} I-frame marker(s) -> {out_avi}", "ok")
    return pframes, pframes_duplicated, copies, iframes

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

def _build_frame_stutter_filter_complex(frame_copy_counts, fps: float, speed_factor: float):
    _log(f"building filter_complex for {len(frame_copy_counts)} frames, fps={fps}, speed_factor={speed_factor:.3f}")
    frame_dur = 1.0 / fps
    n = len(frame_copy_counts)

    parts = []
    concat_inputs = []
    seg_idx = 0
    i = 0
    while i < n:
        count = frame_copy_counts[i]
        if count <= 1:
            j = i
            while j < n and frame_copy_counts[j] <= 1:
                j += 1
            start = i * frame_dur
            end = j * frame_dur
            label = f"seg{seg_idx}"
            parts.append(f"[1:a]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS[{label}]")
            concat_inputs.append(f"[{label}]")
            seg_idx += 1
            i = j
        else:
            start = i * frame_dur
            end = (i + 1) * frame_dur
            label = f"seg{seg_idx}"
            parts.append(f"[1:a]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS[{label}]")
            split_labels = [f"{label}_{k}" for k in range(count)]
            split_outs = "".join(f"[{l}]" for l in split_labels)
            parts.append(f"[{label}]asplit={count}{split_outs}")
            concat_inputs.extend(f"[{l}]" for l in split_labels)
            seg_idx += 1
            i += 1

    total_n = len(concat_inputs)
    parts.append("".join(concat_inputs) + f"concat=n={total_n}:v=0:a=1[stuttered]")

    outlabel = "stuttered"
    if speed_factor and speed_factor != 1.0:
        remaining = speed_factor
        atempo_chain = []
        while remaining > 2.0:
            atempo_chain.append("atempo=2.0")
            remaining /= 2.0
        while remaining < 0.5:
            atempo_chain.append("atempo=0.5")
            remaining /= 0.5
        atempo_chain.append(f"atempo={remaining:.6f}")
        parts.append(f"[stuttered]{','.join(atempo_chain)}[aout]")
        outlabel = "aout"

    _log(f"built {seg_idx} segments, {total_n} concat inputs, outlabel={outlabel}", "ok")
    return ";".join(parts), outlabel

def run_stutter_mode(args):
    _log(f"input={args.input} output={args.output}")
    src = Path(args.input)
    out = Path(args.output)
    tmp_avi = out.with_suffix(".source.avi")
    stuttered_avi = out.with_suffix(".stuttered.avi")

    add_audio = not args.no_audio
    apply_speed_fix = not args.no_speed_fix
    audio_stutter = getattr(args, "audio_stutter", False)
    _log(f"add_audio={add_audio} speed_fix={apply_speed_fix} audio_stutter={audio_stutter}")

    _log("Transcoding to MPEG4 AVI...")
    transcode_to_avi(src, tmp_avi, gop=args.gop, qscale=args.qscale)

    fps = None
    try:
        pframes_seen, pframes_dup, dups, iframes, frame_copy_counts = stutter_datamosh(tmp_avi, stuttered_avi, args.chance, args.dups)
        if audio_stutter:
            fps = _probe_fps(tmp_avi)
    finally:
        if tmp_avi.exists() and not args.keep_temp:
            _log(f"cleaning up {tmp_avi}")
            tmp_avi.unlink()

    if apply_speed_fix and pframes_seen > 0:
        speed_factor = (dups * args.chance * pframes_seen / (pframes_seen + iframes))
        speed_factor = max(speed_factor, 1.0)
    else:
        speed_factor = 1.0
    _log(f"computed speed_factor={speed_factor:.3f}")

    if apply_speed_fix and speed_factor > 1.0:
        _log(f"Applying speed correction (factor {speed_factor:.3f})...")
        sped_avi = out.with_suffix(".sped.avi")
        cmd = ["ffmpeg", "-y", "-i", str(stuttered_avi), "-vf", f"setpts=(1/{speed_factor})*PTS", "-an", str(sped_avi),]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stuttered_avi.unlink()
        video_for_mux = sped_avi
        _log(f"speed correction done -> {sped_avi}", "ok")
    else:
        video_for_mux = stuttered_avi

    audio_filter_complex = None
    audio_filter_complex_label = None

    if audio_stutter and add_audio:
        if fps is None:
            _log("Could not determine Framerate! falling back to speed matched audio", "err")
        elif not source_has_audio(src):
            _log("Source has no audio track! Audio stutter will be skipped", "err")
        else:
            applied_speed = speed_factor if apply_speed_fix else 1.0
            audio_filter_complex, audio_filter_complex_label = _build_frame_stutter_filter_complex(frame_copy_counts, fps, applied_speed)

    _log("Mixing audio and finalizing..." if add_audio else "Finalizing output...")
    mux_audio_and_finalize(src, video_for_mux, out, add_audio, speed_factor=speed_factor if apply_speed_fix else 1.0, audio_filter_complex=audio_filter_complex, audio_filter_complex_label=audio_filter_complex_label, crf=args.qscale)
    _log(f"Done! {out}", "ok")

def source_has_audio(src: Path) -> bool:
    _log(f"checking audio track in {src}")
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(src)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,)
        has_audio = bool(result.stdout.strip())
        _log(f"has_audio = {has_audio}", "ok" if has_audio else "err")
        return has_audio
    except Exception as e:
        _log(f"failed: {e}", "err")
        return False

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
    _log(f"has_audio={has_audio} use_filter_complex={use_filter_complex} ext={ext}")

    audio_filters = []
    if not use_filter_complex and speed_factor != 1.0:
        remaining = speed_factor
        while remaining > 2.0:
            audio_filters.append("atempo=2.0")
            remaining /= 2.0
        while remaining < 0.5:
            audio_filters.append("atempo=0.5")
            remaining /= 0.5
        audio_filters.append(f"atempo={remaining:.6f}")

    af_args = (["-af", ",".join(audio_filters)] if audio_filters else [])

    if not has_audio:
        if ext == ".mp4":
            _log("no audio, encoding video-only mp4...")
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

def run_real_mode(args):
    _log(f"input={args.input} output={args.output}")
    src = Path(args.input)
    out = Path(args.output)
    tmp_avi = out.with_suffix(".source.avi")
    moshed_avi = out.with_suffix(".moshed.avi")

    _log("Transcoding to MPEG4 AVI...")
    transcode_to_avi(src, tmp_avi, gop=args.gop, qscale=args.qscale)

    try:
        real_datamosh(tmp_avi, moshed_avi, args.start, args.end, args.all, args.keep_every)
    finally:
        if tmp_avi.exists() and not args.keep_temp:
            _log(f"cleaning up {tmp_avi}")
            tmp_avi.unlink()

    add_audio = not args.no_audio
    _log("Mixing audio and finalizing..." if add_audio else "Finalizing output...")
    mux_audio_and_finalize(src, moshed_avi, out, add_audio, crf=args.qscale)
    _log(f"Done! {out}", "ok")

def run_sim_mode(args):
    import cv2
    import numpy as np

    _log(f"input={args.input} output={args.output} strength={args.strength} threshold={args.threshold}")
    src = Path(args.input)
    out = Path(args.output)
    tmp_video = out.with_name(out.stem + ".sim_raw" + out.suffix)

    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open {args.input}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    _log(f"{w}x{h} @ {fps}fps, ~{total_frames} frames")

    fourcc = cv2.VideoWriter_fourcc(*("mp4v" if str(tmp_video).endswith(".mp4") else "XVID"))
    writer = cv2.VideoWriter(str(tmp_video), fourcc, fps, (w, h))

    canvas = None
    prev_gray = None
    frame_idx = 0

    strength = args.strength
    thresh = args.threshold

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        if canvas is None:
            canvas = frame.astype(np.float32)
            prev_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            writer.write(frame)
            frame_idx += 1
            continue

        in_range = args.start <= frame_idx <= args.end
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        if in_range:
            diff = cv2.absdiff(gray, prev_gray)
            _, motion_mask = cv2.threshold(diff, thresh, 255, cv2.THRESH_BINARY)
            motion_mask = cv2.dilate(motion_mask, np.ones((5, 5), np.uint8))
            motion_mask = motion_mask.astype(np.float32) / 255.0
            alpha = motion_mask * (1.0 - strength) + motion_mask * 0
            update_weight = np.clip(motion_mask + (1.0 - strength) * 0.05, 0, 1)
            update_weight_3 = cv2.merge([update_weight] * 3)
            canvas = canvas * (1 - update_weight_3) + frame.astype(np.float32) * update_weight_3
        else:
            canvas = frame.astype(np.float32)

        out_frame = np.clip(canvas, 0, 255).astype(np.uint8)
        writer.write(out_frame)
        prev_gray = gray
        frame_idx += 1

        if frame_idx % 100 == 0:
            pct = f" ({100 * frame_idx / total_frames:.1f}%)" if total_frames else ""
            _log(f"processed {frame_idx} frames{pct}...")

    cap.release()
    writer.release()
    _log(f"sim mode: wrote {frame_idx} frames (silent) to {tmp_video}", "ok")

    add_audio = not args.no_audio
    _log("Mixing audio and finalizing..." if add_audio else "Finalizing output...")
    try:
        mux_audio_and_finalize(src, tmp_video, out, add_audio, crf=args.qscale)
    finally:
        if tmp_video.exists():
            _log(f"cleaning up {tmp_video}")
            tmp_video.unlink()
    _log(f"Done! {out}", "ok")

def run_ricecake_mode(args):
    _log(f"input={args.input} output={args.output}")
    src = Path(args.input)
    out = Path(args.output)
    tmp_avi = out.with_suffix(".source.avi")
    ricecake_avi = out.with_suffix(".ricecake.avi")

    add_audio = not args.no_audio
    apply_speed_fix = not args.no_speed_fix
    _log(f"add_audio={add_audio} speed_fix={apply_speed_fix}")

    _log("Transcoding to MPEG4 AVI...")
    transcode_to_avi(src, tmp_avi, gop=args.gop, qscale=args.qscale)

    try:
        pframes, pframes_dup, dups, iframes = ricecake_datamosh(tmp_avi, ricecake_avi, args.chance, args.dups)
    finally:
        if tmp_avi.exists() and not args.keep_temp:
            _log(f"cleaning up {tmp_avi}")
            tmp_avi.unlink()

    if apply_speed_fix and pframes > 0:
        speed_factor = (dups * args.chance * pframes / (pframes + iframes))
        speed_factor = max(speed_factor, 1.0)
    else:
        speed_factor = 1.0
    _log(f"computed speed_factor={speed_factor:.3f}")

    if apply_speed_fix and speed_factor > 1.0:
        _log(f"Applying speed correction (factor {speed_factor:.3f})...")
        sped_avi = out.with_suffix(".sped.avi")
        cmd = ["ffmpeg", "-y", "-i", str(ricecake_avi), "-vf", f"setpts=(1/{speed_factor})*PTS", "-an", str(sped_avi),]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        ricecake_avi.unlink()
        video_for_mux = sped_avi
        _log(f"speed correction done -> {sped_avi}", "ok")
    else:
        video_for_mux = ricecake_avi

    _log("Mixing audio and finalizing..." if add_audio else "Finalizing output...")
    mux_audio_and_finalize(src, video_for_mux, out, add_audio, speed_factor=speed_factor if apply_speed_fix else 1.0, crf=args.qscale)
    _log(f"Done! {out}", "ok")

def _ytp_build_points(duration: float, iterations: int, chop_min: float = None, chop_max: float = None):
    iterations = max(1, iterations)
    points = []
    cursor = 0.1
    inc = duration / iterations
    use_bounds = chop_min is not None and chop_max is not None

    for _ in range(iterations * 2):
        if use_bounds:
            seg_dur = random.uniform(chop_min, chop_max)
        else:
            seg_dur = random.uniform(1, 6) * random.uniform(0.1, random.uniform(0.1, random.uniform(0.2, 0.6)) * random.uniform(random.uniform(0, min(10, duration / 16)), min(10, duration / 6)),)
        start = random.uniform(cursor, cursor + inc * 2)
        if start + seg_dur > duration:
            break
        points.append((start, seg_dur))
        cursor = start + seg_dur

    points.sort()
    return points

def freeze_last_frame(src_clip: Path, dst_path: Path, freeze_dur: float, has_audio: bool):
    _log(f"creating {freeze_dur:.3f}s freeze from last frame of {src_clip.name}")

    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", str(src_clip)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,)
        fps_str = r.stdout.strip().splitlines()[0]
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) else 30.0
    except Exception:
        fps = 30.0
    _log(f"source fps={fps:.3f}")

    frame_path = dst_path.with_suffix(".freeze_frame.png")
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-sseof", "-1", "-i", str(src_clip), "-update", "1", "-q:v", "2", str(frame_path)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,)

    if has_audio:
        tail_dur = max(2.0 / fps, 0.07)
        loop_count = math.ceil(freeze_dur / tail_dur) + 1
        audio_filter = (f"[1:a]atrim=0:{tail_dur},asetpts=PTS-STARTPTS," f"aloop=loop={loop_count}:size=2147483647," f"atrim=0:{freeze_dur},asetpts=PTS-STARTPTS[aout]")
        cmd_freeze = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-framerate", str(fps), "-i", str(frame_path), "-sseof", f"-{tail_dur + 0.5}", "-i", str(src_clip), "-filter_complex", audio_filter, "-map", "0:v:0", "-map", "[aout]", "-t", str(freeze_dur), "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", "-vsync", "cfr", "-video_track_timescale", "90000", "-c:a", "aac", "-ar", "44100", "-ac", "2", str(dst_path),]
    else:
        cmd_freeze = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-framerate", str(fps), "-i", str(frame_path), "-t", str(freeze_dur), "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", "-vsync", "cfr", "-video_track_timescale", "90000", "-an", str(dst_path),]

    subprocess.run(cmd_freeze, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    frame_path.unlink(missing_ok=True)
    _log(f"done -> {dst_path.name}", "ok")

def run_ytp_mode(args):
    _log(f"input={args.input} output={args.output}")
    src = Path(args.input)
    out = Path(args.output)
    work_dir = out.with_name(out.stem + "_ytp_tmp")

    if work_dir.exists():
        _log(f"clearing stale work dir {work_dir}")
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    add_audio = not args.no_audio
    has_audio = add_audio and source_has_audio(src)
    freeze_chance = max(0.0, min(1.0, getattr(args, "freeze_chance", 0.0)))
    freeze_dur = max(0.05, getattr(args, "freeze_dur", 0.4))
    crf = getattr(args, "qscale", 18)
    _log(f"add_audio={add_audio} has_audio={has_audio} iterations={args.iterations} crf={crf} freeze_chance={freeze_chance} freeze_dur={freeze_dur}")

    duration = _probe_duration(src)
    _log(f"duration={duration:.3f}s")

    chop_min = getattr(args, "chop_min", None)
    chop_max = getattr(args, "chop_max", None)
    if chop_min is not None and chop_max is not None:
        _log(f"chop duration range: {chop_min:.3f}s - {chop_max:.3f}s")
    points = _ytp_build_points(duration, args.iterations, chop_min=chop_min, chop_max=chop_max)
    _log(f"generated {len(points)} stutter point(s)")
    if not points:
        _log("No stutter points fit in this clip at the requested iteration count ", "err")

    def cut(start, to=None, dur=None, dst_name="seg.mp4"):
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-ss", str(start)]
        cmd += ["-to", str(to)] if to is not None else ["-t", str(dur)]
        cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", str(crf), "-vsync", "cfr", "-video_track_timescale", "90000"]
        if add_audio:
            cmd += ["-c:a", "aac", "-ar", "44100", "-ac", "2"]
        else:
            cmd += ["-an"]
        cmd += [str(work_dir / dst_name)]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    playlist_entries = []
    cursor = 0.0

    for idx, (start, seg_dur) in enumerate(points):
        a_name, b_name, r_name = f"a{idx}.mp4", f"b{idx}.mp4", f"r{idx}.mp4"
        _log(f"segment {idx}: normal {cursor:.3f}->{start:.3f}, loop {start:.3f}->{start + seg_dur:.3f} ({seg_dur:.3f}s)")

        cut(cursor, to=start, dst_name=a_name)
        cut(start, to=start + seg_dur, dst_name=b_name)

        rev_cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(work_dir / b_name), "-vf", "reverse", "-c:v", "libx264", "-preset", "fast", "-crf", str(crf), "-vsync", "cfr", "-video_track_timescale", "90000"]
        if has_audio:
            rev_cmd += ["-af", "areverse", "-c:a", "aac", "-ar", "44100", "-ac", "2"]
        else:
            rev_cmd += ["-an"]
        rev_cmd += [str(work_dir / r_name)]
        subprocess.run(rev_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        playlist_entries += [a_name, b_name, r_name, b_name]

        if freeze_chance > 0.0 and random.random() < freeze_chance:
            f_name = f"f{idx}.mp4"
            freeze_last_frame(work_dir / b_name, work_dir / f_name, freeze_dur, has_audio)
            playlist_entries.append(f_name)
            _log(f"segment {idx}: freeze triggered -> {f_name}")

        cursor = start + seg_dur

    tail_name = "e.mp4"
    tail_dur = max(0.0, duration - cursor)
    _log(f"tail segment: {cursor:.3f} -> end ({tail_dur:.3f}s)")
    if tail_dur > 0.05:
        cut(cursor, dur=tail_dur, dst_name=tail_name)
        playlist_entries.append(tail_name)

    playlist_path = work_dir / "playlist.txt"
    with open(playlist_path, "w", encoding="utf-8") as fh:
        for name in playlist_entries:
            fh.write(f"file '{name}'\n")

    _log(f"concatenating {len(playlist_entries)} segments...")
    concat_cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(playlist_path), "-c", "copy", str(out)]
    subprocess.run(concat_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if not args.keep_temp:
        _log(f"cleaning up {work_dir}")
        shutil.rmtree(work_dir, ignore_errors=True)

    _log(f"Done! {out}", "ok")

def run_ytpstutter_mode(args):
    _log(f"input={args.input} output={args.output}")
    src = Path(args.input)
    out = Path(args.output)
    work_dir = out.with_name(out.stem + "_ytpstutter_tmp")

    if work_dir.exists():
        _log(f"clearing stale work dir {work_dir}")
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    add_audio = not args.no_audio
    has_audio = add_audio and source_has_audio(src)
    freeze_chance = max(0.0, min(1.0, getattr(args, "freeze_chance", 0.0)))
    freeze_dur = max(0.05, getattr(args, "freeze_dur", 0.4))
    crf = getattr(args, "qscale", 18)
    _log(f"add_audio={add_audio} has_audio={has_audio} iterations={args.iterations} crf={crf} freeze_chance={freeze_chance} freeze_dur={freeze_dur}")

    duration = _probe_duration(src)
    _log(f"duration={duration:.3f}s")

    chop_min = getattr(args, "chop_min", None)
    chop_max = getattr(args, "chop_max", None)
    if chop_min is not None and chop_max is not None:
        _log(f"chop duration range: {chop_min:.3f}s - {chop_max:.3f}s")
    points = _ytp_build_points(duration, args.iterations, chop_min=chop_min, chop_max=chop_max)
    _log(f"generated {len(points)} stutter point(s)")
    if not points:
        _log("No stutter points fit in this clip at the requested iteration count; ", "err")

    def cut(start, to=None, dur=None, dst_name="seg.mp4"):
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-ss", str(start)]
        cmd += ["-to", str(to)] if to is not None else ["-t", str(dur)]
        cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", str(crf), "-vsync", "cfr", "-video_track_timescale", "90000"]
        if add_audio:
            cmd += ["-c:a", "aac", "-ar", "44100", "-ac", "2"]
        else:
            cmd += ["-an"]
        cmd += [str(work_dir / dst_name)]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def stutter_segment(seg_path: Path, dst_path: Path):
        tmp_avi = dst_path.with_suffix(".stutter_src.avi")
        out_avi = dst_path.with_suffix(".stutter_out.avi")
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(seg_path), "-c:v", "mpeg4", "-vtag", "xvid", "-qscale:v", str(args.qscale), "-g", str(args.gop), "-bf", "0", "-an", str(tmp_avi)]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stutter_datamosh(tmp_avi, out_avi, args.chance, args.dups)
        tmp_avi.unlink()
        cmd2 = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(out_avi), "-c:v", "libx264", "-preset", "fast", "-crf", str(crf), "-vsync", "cfr", "-video_track_timescale", "90000", "-an", str(dst_path)]
        subprocess.run(cmd2, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out_avi.unlink()

    playlist_entries = []
    cursor = 0.0

    for idx, (start, seg_dur) in enumerate(points):
        a_name = f"a{idx}.mp4"
        b_name = f"b{idx}.mp4"
        b_stutter_name = f"bs{idx}.mp4"
        r_name = f"r{idx}.mp4"

        _log(f"segment {idx}: normal {cursor:.3f}->{start:.3f}, loop {start:.3f}->{start + seg_dur:.3f} ({seg_dur:.3f}s)")

        cut(cursor, to=start, dst_name=a_name)
        cut(start, to=start + seg_dur, dst_name=b_name)

        _log(f"stuttering segment {idx}...")
        stutter_segment(work_dir / b_name, work_dir / b_stutter_name)

        rev_cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(work_dir / b_stutter_name), "-vf", "reverse", "-c:v", "libx264", "-preset", "fast", "-crf", str(crf), "-vsync", "cfr", "-video_track_timescale", "90000"]
        if has_audio:
            rev_cmd += ["-af", "areverse", "-c:a", "aac", "-ar", "44100", "-ac", "2"]
        else:
            rev_cmd += ["-an"]
        rev_cmd += [str(work_dir / r_name)]
        subprocess.run(rev_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if has_audio:
            for seg_name, orig_start, orig_end in [(a_name, cursor, start), (b_stutter_name, start, start + seg_dur),]:
                muxed = (work_dir / seg_name).with_suffix(".muxed.mp4")
                cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(work_dir / seg_name), "-ss", str(orig_start), "-to", str(orig_end), "-i", str(src), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest", str(muxed)]
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                (work_dir / seg_name).unlink()
                muxed.rename(work_dir / seg_name)

        playlist_entries += [a_name, b_stutter_name, r_name, b_stutter_name]

        if freeze_chance > 0.0 and random.random() < freeze_chance:
            f_name = f"f{idx}.mp4"
            freeze_last_frame(work_dir / b_stutter_name, work_dir / f_name, freeze_dur, has_audio)
            playlist_entries.append(f_name)
            _log(f"segment {idx}: freeze triggered -> {f_name}")

        cursor = start + seg_dur

    tail_name = "e.mp4"
    tail_dur = max(0.0, duration - cursor)
    _log(f"tail segment: {cursor:.3f} -> end ({tail_dur:.3f}s)")
    if tail_dur > 0.05:
        cut(cursor, dur=tail_dur, dst_name=tail_name)
        playlist_entries.append(tail_name)

    playlist_path = work_dir / "playlist.txt"
    with open(playlist_path, "w", encoding="utf-8") as fh:
        for name in playlist_entries:
            fh.write(f"file '{name}'\n")

    _log(f"concatenating {len(playlist_entries)} segments...")
    concat_cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(playlist_path), "-c", "copy", str(out)]
    subprocess.run(concat_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if not args.keep_temp:
        _log(f"cleaning up {work_dir}")
        shutil.rmtree(work_dir, ignore_errors=True)

    _log(f"Done! {out}", "ok")

def run_scatter_mode(args):
    _log(f"input={args.input} output={args.output}")
    src = Path(args.input)
    out = Path(args.output)
    work_dir = out.with_name(out.stem + "_scatter_tmp")

    if work_dir.exists():
        _log(f"clearing stale work dir {work_dir}")
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    add_audio = not args.no_audio
    has_audio = add_audio and source_has_audio(src)
    resample = args.resample
    chop_min = args.chop_min
    chop_max = args.chop_max
    count = args.count
    crf = getattr(args, "qscale", 18)

    _log(f"add_audio={add_audio} has_audio={has_audio} chop_min={chop_min} chop_max={chop_max} count={count} resample={resample} crf={crf}")

    duration = _probe_duration(src)
    _log(f"duration={duration:.3f}s")

    if chop_min >= chop_max:
        raise ValueError(f"chop-min ({chop_min}) must be less than chop-max ({chop_max})")
    if chop_max > duration:
        chop_max = duration * 0.5
        _log(f"chop-max clamped to {chop_max:.3f}s (half of duration)", "err")
    _log("building segment pool...")
    pool = []
    cursor = 0.0
    seg_idx = 0
    while cursor < duration - 0.05:
        seg_dur = random.uniform(chop_min, chop_max)
        seg_dur = min(seg_dur, duration - cursor)
        if seg_dur < 0.05:
            break
        pool.append((cursor, seg_dur))
        cursor += seg_dur
        seg_idx += 1

    _log(f"pool has {len(pool)} segments")
    if not pool:
        _log("No segments could be built from this clip with these chop sizes.", "err")
        return
    if resample:
        chosen = [random.choice(pool) for _ in range(count)]
        _log(f"resampling {count} segments randomly (with replacement)")
    else:
        chosen = pool[:]
        random.shuffle(chosen)
        _log(f"shuffling all {len(chosen)} segments")

    def cut(start, dur, dst_name):
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-ss", str(start), "-t", str(dur), "-c:v", "libx264", "-preset", "fast", "-crf", str(crf), "-pix_fmt", "yuv420p", "-vsync", "cfr", "-video_track_timescale", "90000"]
        if has_audio:
            cmd += ["-c:a", "aac", "-ar", "44100", "-ac", "2"]
        else:
            cmd += ["-an"]
        cmd += [str(work_dir / dst_name)]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    _log(f"cutting {len(chosen)} segments...")
    seg_files = []
    for i, (start, dur) in enumerate(chosen):
        name = f"s{i}.mp4"
        cut(start, dur, name)
        seg_files.append(name)
        if (i + 1) % 20 == 0:
            _log(f"cut {i + 1}/{len(chosen)} segments...")

    playlist_path = work_dir / "playlist.txt"
    with open(playlist_path, "w", encoding="utf-8") as fh:
        for name in seg_files:
            fh.write(f"file '{name}'\n")

    _log(f"concatenating {len(seg_files)} segments...")
    concat_cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(playlist_path), "-c", "copy", str(out)]
    subprocess.run(concat_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if not args.keep_temp:
        _log(f"cleaning up {work_dir}")
        shutil.rmtree(work_dir, ignore_errors=True)

    _log(f"Done! {out}", "ok")

def run_runmeme_mode(args):
    _log(f"input={args.input} output={args.output}")
    src = Path(args.input)
    out = Path(args.output)
    music = Path(args.music)
    work_dir = out.with_name(out.stem + "_runmeme_tmp")

    if not music.exists():
        raise RuntimeError(
            f"Music file not found: {music}\n"
            f"  Either drop a file named 'stupidshit.mp3' next to datamosh.py ({SCRIPT_DIR}), "
            f"or pass --music <path> to point at a specific track."
        )

    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    chop_dur  = args.chop_dur
    loop_reps = args.loop_reps
    jump      = args.jump
    beats     = args.beats
    crf       = getattr(args, "qscale", 18)

    _log(f"chop={chop_dur}s reps={loop_reps} jump={jump}s beats={beats} crf={crf}")

    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", str(src)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,)
        fps_str = r.stdout.strip().splitlines()[0]
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) else 30.0
    except Exception:
        fps = 30.0
    _log(f"source fps={fps:.3f}")

    duration = _probe_duration(src)
    _log(f"source duration={duration:.3f}s")

    seg_idx = 0
    playlist_entries = []

    for beat in range(beats):
        src_pos = beat * jump
        src_pos = min(src_pos, max(0.0, duration - chop_dur))
        _log(f"beat {beat}: cutting {chop_dur}s from source @ {src_pos:.3f}s")
        fwd_name = f"fwd_{beat}.mp4"
        cmd_fwd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-ss", str(src_pos), "-t", str(chop_dur), "-c:v", "libx264", "-preset", "fast", "-crf", str(crf), "-pix_fmt", "yuv420p", "-vsync", "cfr", "-video_track_timescale", "90000", "-an", str(work_dir / fwd_name),]
        subprocess.run(cmd_fwd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        fwd_path = work_dir / fwd_name
        if not fwd_path.exists() or fwd_path.stat().st_size < 1024:
            _log(f"beat {beat}: fwd clip too short or empty, skipping beat", "err")
            continue
        rev_name = f"rev_{beat}.mp4"
        cmd_rev = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(work_dir / fwd_name), "-vf", "reverse", "-c:v", "libx264", "-preset", "fast", "-crf", str(crf), "-pix_fmt", "yuv420p", "-vsync", "cfr", "-video_track_timescale", "90000", "-an", str(work_dir / rev_name),]
        subprocess.run(cmd_rev, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for rep in range(loop_reps):
            playlist_entries.append(fwd_name)
            playlist_entries.append(rev_name)

        seg_idx += 1
    playlist_path = work_dir / "playlist.txt"
    with open(playlist_path, "w", encoding="utf-8") as fh:
        for name in playlist_entries:
            fh.write(f"file '{name}'\n")

    silent_path = work_dir / "silent.mp4"
    _log(f"concatenating {len(playlist_entries)} segments...")
    concat_cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(playlist_path), "-c", "copy", str(silent_path),]
    subprocess.run(concat_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _log(f"mixing music from {music}...")
    mix_cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(silent_path), "-i", str(music), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest", str(out),]
    subprocess.run(mix_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if not args.keep_temp:
        shutil.rmtree(work_dir, ignore_errors=True)

    _log(f"Done! {out}", "ok")

def _rot_build_chop_points(duration, min_chop=0.12, max_chop=0.9):
    points = []
    cursor = 0.0
    while cursor < duration - 0.05:
        seg_dur = random.uniform(min_chop, max_chop) * random.uniform(0.3, 1.0)
        seg_dur = min(seg_dur, duration - cursor)
        if seg_dur < 0.04:
            break
        points.append((cursor, seg_dur))
        cursor += seg_dur
    return points

def chaotic_rot_tail(tail_raw: Path, work: Path, gop, mosh_qscale, crf, stutter_chance, stutter_dups, has_audio, src_for_audio, intro_dur, distort_gain=6.0):
    tail_dur = _probe_duration(tail_raw)
    chops = _rot_build_chop_points(tail_dur)
    _log(f"chaotic rot: {len(chops)} chopped segment(s) over {tail_dur:.3f}s")

    seg_video_infos = []

    for idx, (start, seg_dur) in enumerate(chops):
        raw_seg = work / f"rot_raw_{idx}.mp4"
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(tail_raw), "-ss", str(start), "-t", str(seg_dur), "-c:v", "libx264", "-preset", "fast", "-crf", str(crf), "-pix_fmt", "yuv420p", "-vsync", "cfr", "-an", str(raw_seg)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        avi_seg = work / f"rot_{idx}.avi"
        transcode_to_avi(raw_seg, avi_seg, gop=gop, qscale=mosh_qscale)

        mosh_seg = work / f"rot_mosh_{idx}.avi"
        try:
            real_datamosh(avi_seg, mosh_seg, start=1, end=10**9, remove_all=True, keep_every=1)
        except RuntimeError:
            shutil.copy(str(avi_seg), str(mosh_seg))

        stutter_seg = work / f"rot_stutter_{idx}.avi"
        try:
            stutter_datamosh(mosh_seg, stutter_seg, chance=stutter_chance,
                             dups=max(1, random.randint(max(1, stutter_dups - 3), stutter_dups + 3)))
        except RuntimeError:
            shutil.copy(str(mosh_seg), str(stutter_seg))

        seg_mp4 = work / f"rot_seg_{idx}.mp4"
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(stutter_seg), "-c:v", "libx264", "-preset", "fast", "-crf", str(crf), "-pix_fmt", "yuv420p", "-vsync", "cfr", "-an", str(seg_mp4)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        play_reversed = random.random() < 0.5
        if play_reversed:
            seg_final = work / f"rot_final_{idx}.mp4"
            subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(seg_mp4), "-vf", "reverse", "-c:v", "libx264", "-preset", "fast", "-crf", str(crf), "-pix_fmt", "yuv420p", "-an", str(seg_final)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        else:
            seg_final = seg_mp4

        freeze_dur = random.uniform(0.1, 0.35) if random.random() < 0.2 else None
        seg_video_infos.append((seg_final, play_reversed, freeze_dur))
        _log(f"rot segment {idx}: orig={seg_dur:.3f}s reversed={play_reversed} freeze={freeze_dur}")

    silent_seg_paths = []
    for idx, (seg_final, play_reversed, freeze_dur) in enumerate(seg_video_infos):
        silent_seg_paths.append(seg_final.resolve())
        if freeze_dur is not None:
            freeze_silent = work / f"rot_freeze_silent_{idx}.mp4"
            freeze_last_frame(seg_final, freeze_silent, freeze_dur, has_audio=False)
            silent_seg_paths.append(freeze_silent.resolve())

    silent_playlist = work / "rot_silent_playlist.txt"
    with open(silent_playlist, "w", encoding="utf-8") as fh:
        for p in silent_seg_paths:
            fh.write(f"file '{p}'\n")

    silent_video = work / "rot_tail_silent.mp4"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(silent_playlist), "-c", "copy", str(silent_video)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    final_video_dur = _probe_duration(silent_video)
    _log(f"chaotic rot: silent tail assembled, final video dur={final_video_dur:.3f}s (orig tail={tail_dur:.3f}s)", "ok")

    if not has_audio:
        _log("no audio — returning silent tail video")
        return silent_video

    src_total_dur = _probe_duration(src_for_audio)
    audio_tail_start = intro_dur
    audio_tail_end   = min(audio_tail_start + tail_dur, src_total_dur)
    actual_audio_tail_dur = max(audio_tail_end - audio_tail_start, 0.0)

    if actual_audio_tail_dur < 0.05:
        _log("tail audio window is too short or past source end — returning silent video", "err")
        return silent_video

    stretch_factor = final_video_dur / actual_audio_tail_dur
    _log(f"audio stretch factor: {stretch_factor:.4f}  ({actual_audio_tail_dur:.3f}s -> {final_video_dur:.3f}s)")
    playback_speed = actual_audio_tail_dur / final_video_dur  # reciprocal: <1 = slow down
    atempo_chain_parts = []
    remaining = playback_speed
    while remaining < 0.5:
        atempo_chain_parts.append("atempo=0.5")
        remaining /= 0.5
    while remaining > 2.0:
        atempo_chain_parts.append("atempo=2.0")
        remaining /= 2.0
    atempo_chain_parts.append(f"atempo={remaining:.6f}")
    atempo_chain = ",".join(atempo_chain_parts)

    distorted_audio = work / "rot_tail_audio.aac"
    af = (f"atrim=start={audio_tail_start:.6f}:end={audio_tail_end:.6f}," f"asetpts=PTS-STARTPTS," f"volume={distort_gain:.2f}," f"aecho=0.6:0.4:25|50:0.3|0.15," f"{atempo_chain}")
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src_for_audio), "-vn", "-af", af, "-c:a", "aac", "-b:a", "192k", "-ar", "44100", str(distorted_audio)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _log("tail audio distorted+stretched", "ok")

    rot_out = work / "rot_tail_final.mp4"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(silent_video), "-i", str(distorted_audio), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(rot_out)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _log(f"chaotic rot tail assembled -> {rot_out}", "ok")
    return rot_out

def run_rotting_mode(args):
    _log(f"input={args.input} output={args.output} intro={args.intro_dur}s")
    src  = Path(args.input)
    out  = Path(args.output)
    stem = out.stem
    work = out.parent / f"_rotting_tmp_{stem}"
    work.mkdir(exist_ok=True)

    try:
        add_audio = not args.no_audio
        intro_dur = args.intro_dur
        total_dur = _probe_duration(src)
        fps       = _probe_fps(src) or 30.0
        _log(f"total_dur={total_dur:.3f}s fps={fps}")

        if intro_dur >= total_dur:
            _log("intro_dur >= video length, nothing to rot — copying as-is.", "err")
            shutil.copy(str(src), str(out))
            return
        intro_mp4 = work / "intro.mp4"
        _log(f"cutting intro {intro_dur}s...")
        subprocess.run(["ffmpeg", "-y", "-i", str(src), "-t", str(intro_dur), "-c:v", "libx264", "-preset", "fast", "-crf", str(args.qscale), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(intro_mp4),], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _log("intro cut done", "ok")

        tail_raw = work / "tail_raw.mp4"
        _log(f"cutting tail from {intro_dur}s ...")
        subprocess.run(["ffmpeg", "-y", "-i", str(src), "-ss", str(intro_dur), "-c:v", "libx264", "-preset", "fast", "-crf", str(args.qscale), "-pix_fmt", "yuv420p", "-an", str(tail_raw),], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _log("tail cut done", "ok")

        has_audio = add_audio and source_has_audio(src)
        _log("rot on tail...")
        tail_final = chaotic_rot_tail(tail_raw, work, gop=args.gop, mosh_qscale=args.mosh_qscale, crf=args.qscale, stutter_chance=args.stutter_chance, stutter_dups=args.stutter_dups, has_audio=has_audio, src_for_audio=src, intro_dur=intro_dur, distort_gain=args.distort_gain)
        _log("tail rotted", "ok")

        _log("concatenating intro + rotten tail...")
        playlist = work / "concat.txt"
        with open(playlist, "w") as fh:
            fh.write(f"file '{intro_mp4.resolve()}'\n")
            fh.write(f"file '{tail_final.resolve()}'\n")

        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(playlist), "-c:v", "libx264", "-preset", "fast", "-crf", str(args.qscale), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(out),], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _log(f"done -> {out}", "ok")

    finally:
        if not args.keep_temp:
            shutil.rmtree(work, ignore_errors=True)
            _log("temp files cleaned")

    _log(f"Done! {out}", "ok")


def main():
    p = argparse.ArgumentParser(description="DatamosheRRR")
    sub = p.add_subparsers(dest="mode", required=True)

    real = sub.add_parser("real", help="pretty much authentic I-frame removal")
    real.add_argument("input")
    real.add_argument("output")
    real.add_argument("--start", type=int, default=0)
    real.add_argument("--end", type=int, default=10**9)
    real.add_argument("--all", action="store_true")
    real.add_argument("--keep-every", type=int, default=1)
    real.add_argument("--gop", type=int, default=30)
    real.add_argument("--qscale", type=int, default=3)
    real.add_argument("--keep-temp", action="store_true")
    real.add_argument("--no-audio", action="store_true")
    real.set_defaults(func=run_real_mode)

    sim = sub.add_parser("sim", help="OpenCV frame-bleed simulation")
    sim.add_argument("input")
    sim.add_argument("output")
    sim.add_argument("--start", type=int, default=0)
    sim.add_argument("--end", type=int, default=10**9)
    sim.add_argument("--strength", type=float, default=0.85)
    sim.add_argument("--threshold", type=int, default=18)
    sim.add_argument("--qscale", type=int, default=18, help="output CRF quality for final mp4 (default 18)")
    sim.add_argument("--no-audio", action="store_true")
    sim.set_defaults(func=run_sim_mode)

    stutter = sub.add_parser("stutter", help="random p-frame duplication")
    stutter.add_argument("input")
    stutter.add_argument("output")
    stutter.add_argument("--chance", type=float, default=0.5)
    stutter.add_argument("--dups", type=int, default=5)
    stutter.add_argument("--gop", type=int, default=30)
    stutter.add_argument("--qscale", type=int, default=3)
    stutter.add_argument("--keep-temp", action="store_true")
    stutter.add_argument("--no-audio", action="store_true")
    stutter.add_argument("--no-speed-fix", action="store_true", help="dont speed the output back up leave it slowed by dupe")
    stutter.add_argument("--audio-stutter", action="store_true", help="apply stutter to sound")
    stutter.set_defaults(func=run_stutter_mode)

    ricecake = sub.add_parser("ricecake", help="naive raw byte-split P-frame duplication (ricecake style)")
    ricecake.add_argument("input")
    ricecake.add_argument("output")
    ricecake.add_argument("--chance", type=float, default=1.0)
    ricecake.add_argument("--dups", type=int, default=5)
    ricecake.add_argument("--gop", type=int, default=30)
    ricecake.add_argument("--qscale", type=int, default=3)
    ricecake.add_argument("--keep-temp", action="store_true")
    ricecake.add_argument("--no-audio", action="store_true")
    ricecake.add_argument("--no-speed-fix", action="store_true", help="dont speed the output back up leave it slowed by dupe")
    ricecake.set_defaults(func=run_ricecake_mode)

    ytp = sub.add_parser("ytp", help="random forward/reverse stutter-loop splices (YouTube Poop style)")
    ytp.add_argument("input")
    ytp.add_argument("output")
    ytp.add_argument("--iterations", type=int, default=6, help="roughly how many stutter-loops to splice in")
    ytp.add_argument("--chop-min", type=float, default=None, help="minimum chop duration in seconds (overrides organic randomness)")
    ytp.add_argument("--chop-max", type=float, default=None, help="maximum chop duration in seconds (overrides organic randomness)")
    ytp.add_argument("--freeze-chance", type=float, default=0.0, help="probability (0.0-1.0) of freezing last frame after a chop")
    ytp.add_argument("--freeze-dur", type=float, default=0.4, help="duration in seconds to hold the freeze frame (default 0.4)")
    ytp.add_argument("--qscale", type=int, default=18, help="libx264 CRF quality (0=lossless, 51=worst, default 18)")
    ytp.add_argument("--keep-temp", action="store_true")
    ytp.add_argument("--no-audio", action="store_true")
    ytp.set_defaults(func=run_ytp_mode)

    ytpstutter = sub.add_parser("ytpstutter", help="YTP splices with P-frame stutter on loop segments")
    ytpstutter.add_argument("input")
    ytpstutter.add_argument("output")
    ytpstutter.add_argument("--iterations", type=int, default=6)
    ytpstutter.add_argument("--chop-min", type=float, default=None, help="minimum chop duration in seconds")
    ytpstutter.add_argument("--chop-max", type=float, default=None, help="maximum chop duration in seconds")
    ytpstutter.add_argument("--freeze-chance", type=float, default=0.0, help="probability (0.0-1.0) of freezing last frame after a chop")
    ytpstutter.add_argument("--freeze-dur", type=float, default=0.4, help="duration in seconds to hold the freeze frame (default 0.4)")
    ytpstutter.add_argument("--chance", type=float, default=0.5)
    ytpstutter.add_argument("--dups", type=int, default=4)
    ytpstutter.add_argument("--gop", type=int, default=30)
    ytpstutter.add_argument("--qscale", type=int, default=3, help="mpeg4 qscale for stutter segments; also used as CRF for x264 output (default 3)")
    ytpstutter.add_argument("--keep-temp", action="store_true")
    ytpstutter.add_argument("--no-audio", action="store_true")
    ytpstutter.set_defaults(func=run_ytpstutter_mode)

    scatter = sub.add_parser("scatter", help="chop video into random segments and shuffle them")
    scatter.add_argument("input")
    scatter.add_argument("output")
    scatter.add_argument("--chop-min", type=float, default=0.3, help="minimum chop duration in seconds (default 0.3)")
    scatter.add_argument("--chop-max", type=float, default=2.0, help="maximum chop duration in seconds (default 2.0)")
    scatter.add_argument("--resample", action="store_true", help="randomly sample segments with replacement instead of shuffling all (some parts repeat, some skip)")
    scatter.add_argument("--count", type=int, default=30, help="number of segments to pick when using --resample (default 30)")
    scatter.add_argument("--qscale", type=int, default=18, help="libx264 CRF quality (0=lossless, 51=worst, default 18)")
    scatter.add_argument("--keep-temp", action="store_true")
    scatter.add_argument("--no-audio", action="store_true")
    scatter.set_defaults(func=run_scatter_mode)

    runmeme = sub.add_parser("runmeme", help="3-beat fwd/rev loop meme with music mix (stupidshit.mp3 style)")
    runmeme.add_argument("input")
    runmeme.add_argument("output")
    runmeme.add_argument("--music", default=str(DEFAULT_RUNMEME_MUSIC), help="path to music file to mix in (default: stupidshit.mp3 next to this script)")
    runmeme.add_argument("--chop-dur", type=float, default=0.5, help="duration of each fwd/rev chop in seconds (default 0.5)")
    runmeme.add_argument("--loop-reps", type=int, default=4, help="how many fwd+rev pairs per beat, each beat = loop_reps * chop_dur * 2 seconds (default 4 → 4s per beat)")
    runmeme.add_argument("--jump", type=float, default=2.0, help="how far to jump in source video between beats in seconds (default 2.0)")
    runmeme.add_argument("--beats", type=int, default=3, help="how many beat loops to produce (default 3)")
    runmeme.add_argument("--qscale", type=int, default=18, help="libx264 CRF quality (0=lossless, 51=worst, default 18)")
    runmeme.add_argument("--keep-temp", action="store_true")
    runmeme.set_defaults(func=run_runmeme_mode)

    rotting = sub.add_parser("rotting", help="clean intro then datamosh rot with stuttering + blown-out distorted audio")
    rotting.add_argument("input")
    rotting.add_argument("output")
    rotting.add_argument("--intro-dur", type=float, default=3.0, help="seconds of clean video before rot kicks in (default 3.0)")
    rotting.add_argument("--gop", type=int, default=30, help="group of pictures for AVI transcode (default 30)")
    rotting.add_argument("--mosh-qscale", type=int, default=3, help="qscale for the internal AVI transcode (default 3, lower = better)")
    rotting.add_argument("--qscale", type=int, default=18, help="libx264 CRF for final mp4 output (default 18)")
    rotting.add_argument("--stutter-chance", type=float, default=0.6, help="P-frame duplication probability (default 0.6)")
    rotting.add_argument("--stutter-dups", type=int, default=6, help="P-frame duplicate count per stuttered frame (default 6)")
    rotting.add_argument("--distort-gain", type=float, default=8.0, help="pre-distortion volume gain, higher = more clipping (default 8.0)")
    rotting.add_argument("--no-audio", action="store_true")
    rotting.add_argument("--keep-temp", action="store_true")
    rotting.set_defaults(func=run_rotting_mode)

    args = p.parse_args()
    _log(f"mode={args.mode} args={vars(args)}")

    needs_ffmpeg = args.mode in ("real", "stutter", "ricecake", "ytp", "ytpstutter", "scatter", "runmeme", "rotting")
    if args.mode == "sim":
        out_ext = Path(args.output).suffix.lower()
        if not args.no_audio or out_ext == ".mp4":
            needs_ffmpeg = True

    if needs_ffmpeg and shutil.which("ffmpeg") is None:
        _log("FFmpeg not found", "err")
        sys.exit(1)

    args.func(args)

if __name__ == "__main__":
    main()