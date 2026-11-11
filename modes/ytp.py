import random
import shutil
import subprocess
from pathlib import Path
from ._common import _log, _probe_duration, ensure_audio_stream, freeze_last_frame, source_has_audio

NAME = "ytp"
HELP = 'random forward and reverse stutter loop splices'


def add_arguments(p):
    p.add_argument("--iterations", type=int, default=6, help="roughly how many stutter-loops to splice in")
    p.add_argument("--chop-min", type=float, default=None, help="minimum chop duration in seconds")
    p.add_argument("--chop-max", type=float, default=None, help="maximum chop duration in seconds")
    p.add_argument("--freeze-chance", type=float, default=0.0, help="probability of freezing last frame after a chop")
    p.add_argument("--freeze-dur", type=float, default=0.4, help="duration in seconds to hold the freeze frame")
    p.add_argument("--qscale", type=int, default=18, help="libx264 CRF quality")
    p.add_argument("--keep-temp", action="store_true")
    p.add_argument("--no-audio", action="store_true")

# ///////////////////////////////////////////////////////////////////////////////////////////

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



def run_ytp_mode(args):
    _log(f"input = {args.input} output = {args.output}")

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

    _log(f"add_audio = {add_audio} has_audio = {has_audio} iterations = {args.iterations} crf = {crf} freeze_chance = {freeze_chance} freeze_dur = {freeze_dur}")

    duration = _probe_duration(src)
    _log(f"duration={duration:.3f}s")

    chop_min = getattr(args, "chop_min", None)
    chop_max = getattr(args, "chop_max", None)

    if chop_min is not None and chop_max is not None:
        _log(f"chop duration range: {chop_min:.3f}s - {chop_max:.3f}s")

    points = _ytp_build_points(duration, args.iterations, chop_min=chop_min, chop_max=chop_max)
    _log(f"generated {len(points)} stutter point")

    if not points:
        _log("!! couldnt fit stutter point at this clip at the requested itercount", "err")



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

        if has_audio:
            ensure_audio_stream(work_dir / dst_name)

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

    _log(f"concatenating {len(playlist_entries)} segments")

    concat_cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(playlist_path), "-c", "copy", str(out)]

    subprocess.run(concat_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if not args.keep_temp:
        _log(f"cleaning up {work_dir}")
        shutil.rmtree(work_dir, ignore_errors=True)

    _log(f"Done! {out}", "ok")

run = run_ytp_mode