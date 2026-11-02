import random
import shutil
import subprocess
from pathlib import Path
from ._common import _log, _probe_duration, ensure_audio_stream, freeze_last_frame, source_has_audio
from .stutter import stutter_datamosh
from .ytp import _ytp_build_points

NAME = "ytpstutter"
HELP = 'splices with pframe stutter on loop segments'


def add_arguments(p):
    p.add_argument("--iterations", type=int, default=6)
    p.add_argument("--chop-min", type=float, default=None, help="minimum chop duration in seconds")
    p.add_argument("--chop-max", type=float, default=None, help="maximum chop duration in seconds")
    p.add_argument("--freeze-chance", type=float, default=0.0, help="probability (0.0-1.0) of freezing last frame after a chop")
    p.add_argument("--freeze-dur", type=float, default=0.4, help="duration in seconds to hold the freeze frame (default 0.4)")
    p.add_argument("--chance", type=float, default=0.5)
    p.add_argument("--dups", type=int, default=4)
    p.add_argument("--gop", type=int, default=30)
    p.add_argument("--qscale", type=int, default=3, help="mpeg4 qscale for stutter segments; also used as CRF for x264 output (default 3)")
    p.add_argument("--keep-temp", action="store_true")
    p.add_argument("--no-audio", action="store_true")

# ///////////////////////////////////////////////////////////////////////////////////////////

def run_ytpstutter_mode(args):
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

    duration = _probe_duration(src)

    chop_min = getattr(args, "chop_min", None)
    chop_max = getattr(args, "chop_max", None)
    if chop_min is not None and chop_max is not None:
        _log(f"chop duration range: {chop_min:.3f}s - {chop_max:.3f}s")


    points = _ytp_build_points(duration, args.iterations, chop_min=chop_min, chop_max=chop_max)
    _log(f"generated {len(points)} stutter point")

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
            muxed = (work_dir / b_stutter_name).with_suffix(".muxed.mp4")
            cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(work_dir / b_stutter_name), "-i", str(work_dir / b_name), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2", "-shortest", str(muxed)]
            
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            (work_dir / b_stutter_name).unlink()
            muxed.rename(work_dir / b_stutter_name)

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

run = run_ytpstutter_mode