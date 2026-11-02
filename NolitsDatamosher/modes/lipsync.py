from pathlib import Path
from ._common import SCRIPT_DIR, _log, mux_audio_and_finalize

NAME = "lipsync"
HELP = 'lips gif over media using face recog'


def add_arguments(p):
    p.add_argument("--gif", default="assets/lips.gif", help="path to gif")
    p.add_argument("--intro-dur", type=float, default=2.5, help="before lips")
    p.add_argument("--probe-frames", type=int, default=60, help="how many frames to scan at the start to confirm a face exists")
    p.add_argument("--scale", type=float, default=1.0, help="scale multiplier on top of auto mouth width sizing")
    p.add_argument("--y-offset", type=float, default=0.0, help="vertical offset as fraction of gif height")
    p.add_argument("--detect-every", type=int, default=3, help="rerun face detection every x frames")
    p.add_argument("--qscale", type=int, default=18, help="output CRF quality for final mp4 (default 18)")
    p.add_argument("--no-audio", action="store_true")

# ///////////////////////////////////////////////////////////////////////////////////////////

def run_lipsync_mode(args):
    import cv2
    import numpy as np

    try:
        import face_recognition

    except ImportError:
        raise RuntimeError("face_recognition is not installed! " "Please run: pip install face_recognition in your terminal.")

    _log(f"input={args.input} output={args.output}")

    src = Path(args.input)
    out = Path(args.output)

    gif_path = Path(args.gif)
    if not gif_path.is_absolute():
        gif_path = SCRIPT_DIR / gif_path
    if not gif_path.exists():
        raise RuntimeError(f"GIF not found: {gif_path}")

    # gif extract
    _log(f"loading gif frames from {gif_path}")

    gif_cap = cv2.VideoCapture(str(gif_path))
    gif_frames_rgba = []

    while True:
        ok, gf = gif_cap.read()

        if not ok:
            break

        # opencv reads gif as bgr without alpha channel
        # we must reload it with PIL for real RGBA on our media
        gif_frames_rgba = None  # flag: use PIL below
        break

    gif_cap.release()

    # use Pillow for proper RGBA
    try:
        from PIL import Image as PILImage
        pil_gif = PILImage.open(str(gif_path))
        gif_frames_rgba = []

        try:
            while True:
                frame_rgba = pil_gif.convert("RGBA")
                gif_frames_rgba.append(np.array(frame_rgba))
                pil_gif.seek(pil_gif.tell() + 1)

        except EOFError:
            pass
        _log(f"loaded {len(gif_frames_rgba)} GIF frame(s) via Pillow", "ok")

    except ImportError:
        raise RuntimeError("Pillow is required for proper gif loading! Please run: pip install Pillow")

    if not gif_frames_rgba:
        raise RuntimeError("GIF has no frames.")


    # ///////////////////////////////////////////////////////////////////////////////////////////
    # open source video media
    
    cap = cv2.VideoCapture(str(src))

    if not cap.isOpened():
        raise RuntimeError(f"Could not open {src}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    _log(f"{w}x{h} @ {fps}fps, ~{total} frames")

    tmp_video = out.with_name(out.stem + ".lipsync_raw" + out.suffix)
    fourcc = cv2.VideoWriter_fourcc(*("mp4v" if str(tmp_video).endswith(".mp4") else "XVID"))
    writer = cv2.VideoWriter(str(tmp_video), fourcc, fps, (w, h))

    scale = args.scale
    y_offset = args.y_offset
    every_n = max(1, args.detect_every)
    intro_frames = int(round(args.intro_dur * fps))
    probe_frames = max(1, args.probe_frames)
    gif_idx = 0
    frame_idx = 0
    last_mouth_xy = None

    #_log(f"scale = {scale} y_offset = {y_offset} detect_every = {every_n} intro_frames = {intro_frames}")

    _log("starting processing...")

    def _overlay_gif_on_frame(bgr_frame, gif_rgba, cx, cy, scale, y_offset):
        gh, gw = gif_rgba.shape[:2]
        tw = max(1, int(gw * scale))
        th = max(1, int(gh * scale))
        resized = cv2.resize(gif_rgba, (tw, th), interpolation=cv2.INTER_LANCZOS4)

        cx_adj = cx
        cy_adj = cy + int(y_offset * th)

        x1 = cx_adj - tw // 2
        y1 = cy_adj - th // 2
        x2 = x1 + tw
        y2 = y1 + th

        # clip to frame bounds
        fx1 = max(0, x1);  fy1 = max(0, y1)
        fx2 = min(w, x2);  fy2 = min(h, y2)
        gx1 = fx1 - x1;   gy1 = fy1 - y1
        gx2 = gx1 + (fx2 - fx1)
        gy2 = gy1 + (fy2 - fy1)

        if fx2 <= fx1 or fy2 <= fy1:
            return

        roi = bgr_frame[fy1:fy2, fx1:fx2]
        patch = resized[gy1:gy2, gx1:gx2]

        alpha = patch[:, :, 3:4].astype(np.float32) / 255.0
        patch_bgr = cv2.cvtColor(patch[:, :, :3], cv2.COLOR_RGB2BGR)
        blended = (patch_bgr.astype(np.float32) * alpha + roi.astype(np.float32) * (1.0 - alpha))
        bgr_frame[fy1:fy2, fx1:fx2] = np.clip(blended, 0, 255).astype(np.uint8)

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        if frame_idx >= intro_frames and frame_idx % every_n == 0:

            small_scale = 0.5
            small = cv2.resize(frame, (0, 0), fx=small_scale, fy=small_scale)
            rgb_small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)

            try:
                landmarks_list = face_recognition.face_landmarks(rgb_small, model="large")
            except Exception:
                landmarks_list = []

            if landmarks_list:  # pick first face detected
                lm = landmarks_list[0]
                mouth_pts = lm.get("top_lip", []) + lm.get("bottom_lip", [])

                if mouth_pts:
                    xs = [p[0] for p in mouth_pts]
                    ys = [p[1] for p in mouth_pts]

                    cx = int(sum(xs) / len(xs) / small_scale)
                    cy = int(sum(ys) / len(ys) / small_scale)

                    mouth_w = (max(xs) - min(xs)) / small_scale
                    last_mouth_xy = (cx, cy, mouth_w)

        # add gif if we have a mouthpos
        if last_mouth_xy is not None and frame_idx >= intro_frames:
            cx, cy, mouth_w = last_mouth_xy
            gif_frame_rgba = gif_frames_rgba[gif_idx % len(gif_frames_rgba)]


            # autoscale make gif 2x the detected mouth size and apply transforms
    
            gw_native = gif_frame_rgba.shape[1]
            #gw_native = gif_frame_rgba.shape[mouth_w]
            auto_scale = (mouth_w * 2.0 / gw_native) if gw_native > 0 else 1.0
            effective_scale = auto_scale * scale

            _overlay_gif_on_frame(frame, gif_frame_rgba, cx, cy, effective_scale, y_offset)

            gif_idx += 1

        writer.write(frame)
        frame_idx += 1

        if frame_idx % 100 == 0:
            pct = f" ({100 * frame_idx / total:.1f}%)" if total else ""
            _log(f"processed {frame_idx} frames{pct}...")

    cap.release()
    writer.release()

    _log(f"lipsyncmode: wrote {frame_idx} frames to {tmp_video}", "ok")

    add_audio = not args.no_audio

    _log("Mixing audio and finalizing..." if add_audio else "Finalizing output...")

    try:
        mux_audio_and_finalize(src, tmp_video, out, add_audio, crf=args.qscale)

    finally:

        if tmp_video.exists():
            _log(f"cleaning up {tmp_video}")
            tmp_video.unlink()
            
    _log(f"Done! {out}", "ok")

run = run_lipsync_mode