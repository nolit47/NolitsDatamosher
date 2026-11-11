import argparse
import shutil
import subprocess
import sys

from modes import load_modes
from modes._common import _log


def main():     
    p = argparse.ArgumentParser(description="DatamosheRRR")
    sub = p.add_subparsers(dest="mode", required=True)

    loaded = load_modes()   # load all modes from modes folder

    for name, mod in loaded.items():
        sp = sub.add_parser(name, help=mod.HELP)
        sp.add_argument("input")
        sp.add_argument("output")
        mod.add_arguments(sp)
        sp.set_defaults(func=mod.run)

    args = p.parse_args()

    _log(f"mode = {args.mode} args = {vars(args)}")

    needs_ffmpeg = getattr(loaded[args.mode], "needs_ffmpeg", True)

    if callable(needs_ffmpeg):
        needs_ffmpeg = needs_ffmpeg(args)

    if needs_ffmpeg:
        for tool in ("ffmpeg", "ffprobe"):
            if shutil.which(tool) is None:
                _log(f"{tool} not found in PATH", "err")
                sys.exit(1)

    try:
        args.func(args)

    except subprocess.CalledProcessError as e:
        err = e.stderr.decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        cmd_text = " ".join(str(c) for c in e.cmd) if isinstance(e.cmd, (list, tuple)) else str(e.cmd)

        _log(f"command failed (exit {e.returncode}): {cmd_text[:300]}", "err")

        if err.strip():
            _log("ffmpeg said:\n" + err.strip()[-1200:], "err")
        sys.exit(1)

if __name__ == "__main__":
    main()