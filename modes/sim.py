from pathlib import Path
from ._common import _log, mux_audio_and_finalize

NAME = "sim"
HELP = 'OpenCV framebleed simulation'


def needs_ffmpeg(args):
    return (not args.no_audio) or Path(args.output).suffix.lower() == ".mp4"


def add_arguments(p):
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--end", type=int, default=10**9)
    p.add_argument("--strength", type=float, default=0.85)
    p.add_argument("--threshold", type=int, default=18)
    p.add_argument("--qscale", type=int, default=18, help="output CRF quality for final mp4 (default 18)")
    p.add_argument("--no-audio", action="store_true")

# ///////////////////////////////////////////////////////////////////////////////////////////

def run_sim_mode(args):
    import cv2
    import numpy as np
  
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

    _log(f"sim: wrote {frame_idx} frames to {tmp_video}", "ok")

    add_audio = not args.no_audio
    
    _log("Mixing audio and finalizing..." if add_audio else "Finalizing output...")
    try:
        mux_audio_and_finalize(src, tmp_video, out, add_audio, crf=args.qscale)

    finally:
        if tmp_video.exists():
            _log(f"cleaning up {tmp_video}")
            tmp_video.unlink()
            
    _log(f"Done! {out}", "ok")

run = run_sim_mode