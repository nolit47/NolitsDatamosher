from pathlib import Path
from ._common import AVIIF_KEYFRAME, _load_avi_index, _log, mux_audio_and_finalize, transcode_to_avi, write_avi_chunks

NAME = "real"
HELP = 'the true authentic I-frame removal. the output will always be corrupted'


def add_arguments(p):
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--end", type=int, default=10**9)
    p.add_argument("--all", action="store_true")
    p.add_argument("--keep-every", type=int, default=1)
    p.add_argument("--gop", type=int, default=30)
    p.add_argument("--qscale", type=int, default=3)
    p.add_argument("--keep-temp", action="store_true")
    p.add_argument("--no-audio", action="store_true")


def real_datamosh(src_avi: Path, out_avi: Path, start: int, end: int, remove_all: bool, keep_every: int):
    
    _log(f"reading {src_avi} ({src_avi.stat().st_size} bytes)")
    data = bytearray(Path(src_avi).read_bytes())

    movi_off, idx1_off, idx1_size, entries, index_base = _load_avi_index(data)

    video_indices = [i for i, e in enumerate(entries) if e[0][2:4] == b"dc"]
    _log(f"found {len(video_indices)} video frame chunks")

    if not video_indices:
        raise RuntimeError("no video frame chunks [??dc] found in idx1")

    n_keyframes_total = sum(1 for idx in video_indices if entries[idx][1] & AVIIF_KEYFRAME) # count keyframes in the video frame indices

    _log(f"found {n_keyframes_total} keyframes in the video frame chunks")

    if n_keyframes_total == 0:
        raise RuntimeError("no keyframes found in the video frame chunks.")
    
    _log(f"{n_keyframes_total} keyframes total scanning range start = {start} end = {end} keep_every = {keep_every} remove_all = {remove_all}")

    to_drop = set()

    for n, idx in enumerate(video_indices):
        flags = entries[idx][1]
        is_keyframe = bool(flags & AVIIF_KEYFRAME)
        
        if n == 0:
            continue
        if not is_keyframe:
            continue
        if remove_all:
            to_drop.add(idx)

        elif start <= n <= end:
            if keep_every <= 1 or (n % keep_every != 0):
                to_drop.add(idx)

    _log(f"marked {len(to_drop)} keyframes for removal")

    if not to_drop:
        _log("NO KEYFRAMES MATCHED THE RANGE! output will be the same as input... check --start --end against the frame count or use --all", "err")

    new_chunks = []

    for i, e in enumerate(entries):
        ckid, flags, old_offset, size = e

        if i in to_drop:
            continue

        chunk_start = index_base + old_offset
        chunk_header_and_data = bytes(data[chunk_start:chunk_start + 8 + size])

        if len(chunk_header_and_data) < 8 + size or chunk_header_and_data[:4] != ckid:
            raise RuntimeError(f"avif index mismatch at entry {i} ({ckid!r}).")
        
        new_chunks.append((ckid, flags, chunk_header_and_data))

        if (i + 1) % 500 == 0:
            _log(f"processed {i + 1}/{len(entries)} entries...")

    write_avi_chunks(data, movi_off, idx1_off, idx1_size, new_chunks, out_avi)

    n_dropped = len(to_drop)
    _log(f"realmode: dropped {n_dropped} keyframe out of {len(video_indices)} video frames >>> {out_avi}", "ok")

def run_real_mode(args):
    _log(f"input = {args.input} output = {args.output}")
    
    src = Path(args.input)
    out = Path(args.output)

    tmp_avi = out.with_suffix(".source.avi")
    moshed_avi = out.with_suffix(".moshed.avi")

    _log("Transcoding to MPEG4 AVI...")

    transcode_to_avi(src, tmp_avi, gop=args.gop, qscale=args.qscale)

    try:
        real_datamosh(tmp_avi, moshed_avi, args.start, args.end, args.all, args.keep_every)
    finally:
        if tmp_avi.exists() and not args.keep_temp:

            _log(f"cleaning up {tmp_avi}")
            tmp_avi.unlink()

    add_audio = not args.no_audio
    
    _log("Mixing audio and finalizing..." if add_audio else "Finalizing output...")
    mux_audio_and_finalize(src, moshed_avi, out, add_audio, crf=args.qscale)
    _log(f"Done! {out}", "ok")

run = run_real_mode
