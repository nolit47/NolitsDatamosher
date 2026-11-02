import shutil
import subprocess
from pathlib import Path
from ._common import DEFAULT_RUNMEME_MUSIC, SCRIPT_DIR, _log, _probe_duration

NAME = "runmeme"
HELP = 'that one fucking i dont remember'


def add_arguments(p):
    p.add_argument("--music", default=str(DEFAULT_RUNMEME_MUSIC), help="path to music file to mix")
    p.add_argument("--chop-dur", type=float, default=0.5, help="duration of each fwd and rev chop in seconds")
    p.add_argument("--loop-reps", type=int, default=4, help="how many fwd+rev pairs per beat")
    p.add_argument("--jump", type=float, default=2.0, help="how far to jump in source video between beats in seconds")
    p.add_argument("--beats", type=int, default=3, help="how many beat loops to produce")
    p.add_argument("--qscale", type=int, default=18, help="libx264 CRF quality")
    p.add_argument("--keep-temp", action="store_true")

# ///////////////////////////////////////////////////////////////////////////////////////////

def run_runmeme_mode(args):
    _log(f"input={args.input} output={args.output}")
    
    src = Path(args.input)
    out = Path(args.output)
    music = Path(args.music)
    work_dir = out.with_name(out.stem + "_runmeme_tmp")

    if not music.exists():
        raise RuntimeError(f"Music file not found: {music}\n")

    if work_dir.exists():
        shutil.rmtree(work_dir)

    work_dir.mkdir(parents=True)

    chop_dur = args.chop_dur
    loop_reps = args.loop_reps
    jump = args.jump
    beats = args.beats
    crf = getattr(args, "qscale", 18)

    _log(f"chop = {chop_dur}s reps = {loop_reps} jump = {jump}s beats = {beats} crf = {crf}")

    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", str(src)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,)
        fps_str = r.stdout.strip().splitlines()[0]
        num, den = fps_str.split("/")
        fps = float(num) / float(den) if float(den) else 30.0

    except Exception:
        fps = 30.0
    #_log(f"fps is {fps:.3f}")

    duration = _probe_duration(src)
    #_log(f"source duration = {duration:.3f}s")

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

run = run_runmeme_mode