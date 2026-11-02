import random
import shutil
import subprocess
from pathlib import Path
from ._common import _log, _probe_duration, _probe_fps, freeze_last_frame, source_has_audio, transcode_to_avi
from .real import real_datamosh
from .stutter import stutter_datamosh

NAME = "rotting"
HELP = 'datamosh rot with stuttering'


def add_arguments(p):
    p.add_argument("--intro-dur", type=float, default=3.0, help="before rot kicks in")
    p.add_argument("--gop", type=int, default=30, help="group of pictures for AVI transcode")
    p.add_argument("--mosh-qscale", type=int, default=3, help="qscale for the internal AVI transcode")
    p.add_argument("--qscale", type=int, default=18, help="libx264 CRF for final mp4 output")
    p.add_argument("--stutter-chance", type=float, default=0.6, help="P-frame duplication probability")
    p.add_argument("--stutter-dups", type=int, default=6, help="P-frame duplicate count per stuttered frame")
    p.add_argument("--distort-gain", type=float, default=8.0, help="pre-distortion volume gain, higher = more clipping")
    p.add_argument("--no-audio", action="store_true")
    p.add_argument("--keep-temp", action="store_true")

# ///////////////////////////////////////////////////////////////////////////////////////////

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

def fucked_rot_tail(tail_raw: Path, work: Path, gop, mosh_qscale, crf, stutter_chance, stutter_dups, has_audio, src_for_audio, intro_dur, distort_gain=6.0):
    tail_dur = _probe_duration(tail_raw)
    chops = _rot_build_chop_points(tail_dur)

    _log(f"rot: {len(chops)} chopped segment over {tail_dur:.3f}s")

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
            stutter_datamosh(mosh_seg, stutter_seg, chance=stutter_chance, dups=max(1, random.randint(max(1, stutter_dups - 3), stutter_dups + 3)))

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

        _log(f"rot segment {idx}: orig = {seg_dur:.3f}s reversed = {play_reversed} freeze = {freeze_dur}")

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
    _log(f"rot: final video dur = {final_video_dur:.3f}s (orig tail = {tail_dur:.3f}s)", "ok")

    if not has_audio:
        _log("no audio - returning silent tail video")
        return silent_video

    src_total_dur = _probe_duration(src_for_audio)
    audio_tail_start = intro_dur
    audio_tail_end   = min(audio_tail_start + tail_dur, src_total_dur)
    actual_audio_tail_dur = max(audio_tail_end - audio_tail_start, 0.0)

    if actual_audio_tail_dur < 0.05:
        _log("our tail audio window is too short to end.; return to silent video")
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
    _log("audio fucked", "ok")

    rot_out = work / "rot_tail_final.mp4"

    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(silent_video), "-i", str(distorted_audio), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(rot_out)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    _log(f"chaotic rot tail assembled -> {rot_out}", "ok")
    return rot_out

# ///////////////////////////////////////////////////////////////////////////////////////////

def run_rotting_mode(args):
    _log(f"input = {args.input} output = {args.output} intro = {args.intro_dur}s")

    src  = Path(args.input)
    out  = Path(args.output)
    stem = out.stem
    work = out.parent / f"_rotting_tmp_{stem}"
    work.mkdir(exist_ok=True)

    try:
        add_audio = not args.no_audio
        intro_dur = args.intro_dur
        total_dur = _probe_duration(src)
        fps = _probe_fps(src) or 30.0
        
        _log(f"total_dur = {total_dur:.3f}s fps = {fps}")

        if intro_dur >= total_dur:
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
        tail_final = fucked_rot_tail(tail_raw, work, gop=args.gop, mosh_qscale=args.mosh_qscale, crf=args.qscale, stutter_chance=args.stutter_chance, stutter_dups=args.stutter_dups, has_audio=has_audio, src_for_audio=src, intro_dur=intro_dur, distort_gain=args.distort_gain)
        _log("tail rotted", "ok")

        _log("concatenating intro...")
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

run = run_rotting_mode