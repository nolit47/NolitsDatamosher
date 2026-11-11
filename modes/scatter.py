import random
import shutil
import subprocess
from pathlib import Path
from ._common import _log, _probe_duration, ensure_audio_stream, source_has_audio

NAME = "scatter"
HELP = 'chop video into random segments and shuffle them'


def add_arguments(p):
    p.add_argument("--chop-min", type=float, default=0.3, help="minimum chop duration in seconds")
    p.add_argument("--chop-max", type=float, default=2.0, help="maximum chop duration in seconds")
    p.add_argument("--resample", action="store_true", help="randomly sample segments with replacement instead of shuffling all")
    p.add_argument("--count", type=int, default=30, help="number of segments to pick when using --resample")
    p.add_argument("--qscale", type=int, default=18, help="libx264 CRF quality")
    p.add_argument("--keep-temp", action="store_true")
    p.add_argument("--no-audio", action="store_true")

# ///////////////////////////////////////////////////////////////////////////////////////////

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

    #_log(f"add_audio = {add_audio} has_audio = {has_audio} chop_min = {chop_min} chop_max = {chop_max} count = {count} resample = {resample} crf = {crf}")

    duration = _probe_duration(src)
    #_log(f"duration = {duration:.3f}s")

    if chop_min >= chop_max:
        raise ValueError(f"chopmin ({chop_min}) must be less than chopmax ({chop_max})")
    
    if chop_max > duration:
        chop_max = duration * 0.5
        _log(f"chopmax clamped to {chop_max:.3f}s", "err")

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
        _log("!! No segments could be built from this clip with these chop sizes", "err")
        return
    
    if resample:
        chosen = [random.choice(pool) for _ in range(count)]
        _log(f"resampling {count} segments")

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

        if has_audio:
            ensure_audio_stream(work_dir / dst_name)

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

run = run_scatter_mode