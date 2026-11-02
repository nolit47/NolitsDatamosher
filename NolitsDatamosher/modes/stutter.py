import random
import subprocess
from pathlib import Path
from ._common import AVIIF_KEYFRAME, _load_avi_index, _log, _probe_fps, mux_audio_and_finalize, source_has_audio, transcode_to_avi, write_avi_chunks

NAME = "stutter"
HELP = 'random pframe duplication'


def add_arguments(p):
    p.add_argument("--chance", type=float, default=0.5)
    p.add_argument("--dups", type=int, default=5)
    p.add_argument("--gop", type=int, default=30)
    p.add_argument("--qscale", type=int, default=3)
    p.add_argument("--keep-temp", action="store_true")
    p.add_argument("--no-audio", action="store_true")
    p.add_argument("--no-speed-fix", action="store_true", help="dont speed the output back up leave it slowed by dupe")
    p.add_argument("--audio-stutter", action="store_true", help="apply stutter to sound")

# ///////////////////////////////////////////////////////////////////////////////////////////

def stutter_datamosh(src_avi: Path, out_avi: Path, chance: float, dups: int):
    _log(f"reading {src_avi} ({src_avi.stat().st_size} bytes)")

    data = bytearray(Path(src_avi).read_bytes())

    movi_off, idx1_off, idx1_size, entries, index_base = _load_avi_index(data)

    video_indices = [i for i, e in enumerate(entries) if e[0][2:4] == b"dc"]

    _log(f"found {len(video_indices)} video frame chunks. chance = {chance} dups = {dups}")

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
            _log(f"processed {i + 1}/{len(entries)} entries, {pframes_duplicated} duplicated...")

    write_avi_chunks(data, movi_off, idx1_off, idx1_size, new_chunks, out_avi)

    _log(f"stutter: duplicated {pframes_duplicated}/{pframes_seen} pframes... ({dups}x each) -> {out_avi}", "ok")
    return pframes_seen, pframes_duplicated, dups, iframes, frame_copy_counts




def _build_frame_stutter_filter_complex(frame_copy_counts, fps: float, speed_factor: float):

    _log(f"building filter_complex for {len(frame_copy_counts)} frames, fps = {fps}, speed_factor = {speed_factor:.3f}")

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
            parts.append(f"[1:a]atrim=start={start:.6f}:end = {end:.6f},asetpts = PTS-STARTPTS[{label}]")
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
            atempo_chain.append("atempo = 2.0")
            remaining /= 2.0

        while remaining < 0.5:
            atempo_chain.append("atempo = 0.5")
            remaining /= 0.5

        atempo_chain.append(f"atempo = {remaining:.6f}")
        parts.append(f"[stuttered]{','.join(atempo_chain)}[aout]")
        outlabel = "aout"

    _log(f"built {seg_idx} segments, {total_n} concat inputs, outlabel = {outlabel}", "ok")

    return ";".join(parts), outlabel

def run_stutter_mode(args):
    _log(f"input= {args.input} output = {args.output}")
    
    src = Path(args.input)
    out = Path(args.output)
    tmp_avi = out.with_suffix(".source.avi")
    stuttered_avi = out.with_suffix(".stuttered.avi")

    add_audio = not args.no_audio
    apply_speed_fix = not args.no_speed_fix
    audio_stutter = getattr(args, "audio_stutter", False)

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

    if apply_speed_fix and speed_factor > 1.0:
        _log(f"applying speed correction. factor {speed_factor:.3f}")
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
            _log("!! couldnt determine framerate. the output is fallingback to audiospeed", "err")
        elif not source_has_audio(src):
            _log("!! input has no audio. audio stutter will be skipped", "err")
        else:
            applied_speed = speed_factor if apply_speed_fix else 1.0
            audio_filter_complex, audio_filter_complex_label = _build_frame_stutter_filter_complex(frame_copy_counts, fps, applied_speed)

    _log("Mixing audio and finalizing..." if add_audio else "Finalizing output...")
    mux_audio_and_finalize(src, video_for_mux, out, add_audio, speed_factor=speed_factor if apply_speed_fix else 1.0, audio_filter_complex=audio_filter_complex, audio_filter_complex_label=audio_filter_complex_label, crf=args.qscale)
    _log(f"Done! {out}", "ok")

run = run_stutter_mode