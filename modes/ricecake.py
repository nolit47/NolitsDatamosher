import random
import subprocess
from pathlib import Path
from ._common import RICECAKE_IFRAME_CODE, RICECAKE_MARKER, RICECAKE_PFRAME_CODE, _log, mux_audio_and_finalize, transcode_to_avi

NAME = "ricecake"
HELP = 'naive raw byte-split P-frame duplication. a parody of the peter griffin ricecake datamosh video'


def add_arguments(p):
    p.add_argument("--chance", type=float, default=1.0)
    p.add_argument("--dups", type=int, default=5)
    p.add_argument("--gop", type=int, default=30)
    p.add_argument("--qscale", type=int, default=3)
    p.add_argument("--keep-temp", action="store_true")
    p.add_argument("--no-audio", action="store_true")
    p.add_argument("--no-speed-fix", action="store_true", help="dont speed the output back up leave it slowed by dupe")

# ///////////////////////////////////////////////////////////////////////////////////////////

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

run = run_ricecake_mode
