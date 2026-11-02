import shutil
import subprocess
from pathlib import Path

from ._common import _log, _probe_duration, mux_audio_and_finalize, source_has_audio

# base template for custom modes 

NAME = "template"
HELP = "moshes something"

def add_arguments(p):
    p.add_argument("--amount", type=float, default=1.0, help="example option")
    p.add_argument("--qscale", type=int, default=18, help="libx264 CRF quality (default 18)")
    p.add_argument("--keep-temp", action="store_true")
    p.add_argument("--no-audio", action="store_true")


def run(args):
    src = Path(args.input)
    out = Path(args.output)

    work_dir = out.with_name(out.stem + "_template_tmp")
    work_dir.mkdir(parents=True, exist_ok=True)

    _log(f"input={src} output={out} amount={args.amount}")
    
    duration = _probe_duration(src)

    silent = work_dir / "silent.mp4"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-an", "-c:v", "libx264", "-crf", str(args.qscale), "-pix_fmt", "yuv420p", str(silent)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    mux_audio_and_finalize(src, silent, out, not args.no_audio, crf=args.qscale)    # mux_audio_and_finalize() will copy the audio from src to silent.mp4 and then move it to out.mp4

    if not args.keep_temp:
        shutil.rmtree(work_dir, ignore_errors=True)
    _log(f"Done! {out}", "ok")