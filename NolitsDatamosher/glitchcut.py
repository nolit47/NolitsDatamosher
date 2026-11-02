import argparse
import json
import os
import random
import subprocess


def run(cmd):
    subprocess.run(cmd, check=True)

# ///////////////////////////////////////////////////////////////////////////////////////////

def packets(path, stream):  # get packet info from ffprobe


    # our output is gonna be a .json with packets list
    # each packet is a dict with keys:
    # "pts_time" FLOAT, "pos" INT, "size" INT, "flags" STRING, "stream_index" INT

    # TODO: check if the stream exists else return empty list

    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries", "packet=pts_time,pos,size", "-of", "json", path], check=True, capture_output=True, text=True,).stdout
    pk = []


    for p in json.loads(out).get("packets", []):

        if "pos" in p and "pts_time" in p and p["pos"] != "N/A":    # only keep packets with valid pos and pts_time
            pk.append({"t": float(p["pts_time"]),"pos": int(p["pos"]), "size": int(p["size"])}) # append packet info to list

    return pk


def duration(path):     # get duration of video in seconds
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path], check=True, capture_output=True, text=True,).stdout
    try:
        return float(out.strip())
    
    except ValueError:  # if ffprobe fails to get duration we set the time to 5
        # TODO: add try and error system which is gonna repeat to get a few times before fallback
        return 5.0 

# ///////////////////////////////////////////////////////////////////////////////////////////

# calculate the payload relative to the NAL start then overwrite the trailing payload region with zeros bytes.
# we still need to preserve the AVCC length prefix or else this shit breaks

def zero_tail(data, p, keep_fraction, min_keep, skip_prefix):
    body_start = p["pos"] + skip_prefix
    body_end = p["pos"] + p["size"]

    if body_end <= body_start:
        return
    
    keep = max(min_keep, int((body_end - body_start) * keep_fraction))
    cut = min(body_start + keep, body_end)
    data[cut:body_end] = bytes(body_end - cut)


MAX_COUNT = 20
GAP_MIN = 0.3
TAIL = 1.5


def plan_windows(n, start, fixed_len, dur, rng):  # stutter window planner and preserver

    # we have a time budget to fill with x windows and n-1 gaps
    # each time window has a min width and each gap has a min width
    # make a random gen for these gaps
    # SCALE IF they > our budget

    # TODO: add custom fixed_len support

    budget = dur - TAIL - start
    min_w = fixed_len if fixed_len is not None else 0.3
    
    while n > 1 and n * min_w + (n - 1) * GAP_MIN > budget:
        n -= 1

    if fixed_len is not None:
        w = [fixed_len] * n

    else:
        w = [rng.uniform(0.5, 2.0) for _ in range(n)]

    g = [rng.uniform(0.5, 2.0) for _ in range(n - 1)]   # gaps between windows
    room = budget - (n * min_w + (n - 1) * GAP_MIN)     # room left after min
    extra = sum(x - min_w for x in w) + sum(x - GAP_MIN for x in g) # extra time we have in random windows and gaps


    if extra > room and extra > 0:  # if extra is more than room we need to scale fit to budget
        f = max(0.0, room / extra)
        w = [min_w + (x - min_w) * f for x in w]
        g = [GAP_MIN + (x - GAP_MIN) * f for x in g]

    wins = []

    t = start

    for i in range(n): 
        wins.append((round(t, 2), round(t + w[i], 2)))  # append the window start and end time
        t += w[i] + (g[i] if i < n - 1 else 0.0)    # increment t by window length + gap length

    return wins



def stutter_loops(rng, length, start_pos, sr):

    n = rng.randint(1, 2 + int(length))  # longer stutter gens more segments

    bounds = [0.0] + sorted(rng.uniform(0, length) for _ in range(n - 1)) + [length]
    pos = start_pos
    filters = ""
    taken = 0
    produced = 0

    for i in range(n):  # for each seg generate a random slice and loop it to make a stutter
        seg = bounds[i + 1] - bounds[i]
        sl = 10 ** rng.uniform(-3, -1.7)    # 10 x ** -3 = 0.001s to 10 ** -1.7 = 0.02s
        size = max(1, int(sl * sr))
        loops = max(1, int(seg / sl))
        filters += f"aloop=loop={loops}:size={size}:start={pos},"
        pos += (loops + 1) * size
        taken += size
        produced += (loops + 1) * size
        
    return filters, taken, produced




def main():
    ap = argparse.ArgumentParser()

    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--start", type=float, default=None, help="seconds of video without mosh before the stutter")
    ap.add_argument("--stutter", type=float, default=None, help="length of the stutter window in seconds")
    ap.add_argument("--count", type=int, default=1, help=f"how many separate stutters in the video (max {MAX_COUNT}).")
    ap.add_argument("--qscale", type=int, default=20, help="output quality (x264 CRF) of the final encode. 1 = hq, 20 = default, 51 = lq")
    ap.add_argument("--seed", type=int, default=None)

    a = ap.parse_args()

    if not 1 <= a.count <= MAX_COUNT:
        ap.error(f"--count must be between 1 and {MAX_COUNT}")

    if not 0 <= a.qscale <= 51:
        ap.error("--qscale must be between 0 and 51")

    if a.seed is None:
        a.seed = random.randrange(1_000_000)


    rng = random.Random(a.seed)
    dur = duration(a.input)
    lo = min(2.0, dur * 0.2)
    requested = a.count


    if a.count == 1:
        if a.stutter is None:
            a.stutter = round(rng.uniform(1.0, min(4.0, max(1.0, dur - lo - 1.0))), 2)  # random stutter length between 1-4s

        if a.start is None:
            hi = max(lo, dur - a.stutter - 1.5)

            if dur > 10:
                hi = min(hi, 3.67)  # vids that are >10s have glitchcut start early

            a.start = round(rng.uniform(lo, hi), 2)

        end = a.start + a.stutter
        windows = [(a.start, end)]
        lengths = [a.stutter]

    else:
        #if a.stutter is None:
        #    a.stutter = round(rng.uniform(0.5, min(2.0, max(0.5, dur / 4))), 2)

        if a.start is None:
            hi = max(lo, min(dur * 0.25, 3.67 if dur > 10 else dur))
            a.start = round(rng.uniform(lo, hi), 2)

        windows = plan_windows(a.count, a.start, a.stutter, dur, rng)
        a.count = len(windows)

        if a.count < requested:
            print(f"clip is too short for {requested} stutters, making {a.count}.")

        end = windows[-1][1]
        lengths = [round(e - s, 2) for s, e in windows]

    tmp = a.output + ".tmp.mp4"
    bad = a.output + ".corrupt.mp4"

    keyframes = []  # force keyframes at start of each stutter window so that we could cut audiostream with sync

    if len(windows) > 1:
        keyframes = ["-force_key_frames", ",".join(str(e) for _, e in windows[:-1])]

    run(["ffmpeg", "-y", "-i", a.input,"-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-g", "9999", "-keyint_min", "9999", "-sc_threshold", "0", "-bf", "0", *keyframes, "-af", f"atrim=end={end}", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-t", str(end + 3.5), tmp])

    vid = packets(tmp, "v:0")
    #vid = [p for p in vid if p["size"] > 0]

    with open(tmp, "rb") as f:
        data = bytearray(f.read())

    for p in vid:
        if p["t"] < a.start:
            continue
        if p["t"] < end:
            if any(s <= p["t"] < e for s, e in windows):
                if rng.random() < 0.5:
                    zero_tail(data, p, rng.uniform(0.15, 0.7), 24, 4)
        else:
            zero_tail(data, p, 0.0, 16, 4)

    with open(bad, "wb") as f:
        f.write(data)

# ///////////////////////////////////////////////////////////////////////////////////////////

    # audio stutter chain

    sr = 48000
    chain = f"aresample={sr},"

    for j, ((s, e), length) in enumerate(zip(windows, lengths)):
        loops, taken, produced = stutter_loops(rng, length, int(s * sr), sr)
        chain += loops

        if j < len(windows) - 1:
            edge = int(e * sr)
            grown = produced - taken
            chain += (f"asplit=2[ka{j}][kb{j}];" f"[ka{j}]atrim=end_sample={edge},asetpts=PTS-STARTPTS[pa{j}];" f"[kb{j}]atrim=start_sample={edge + grown},asetpts=PTS-STARTPTS[pb{j}];" f"[pa{j}][pb{j}]concat=n=2:v=0:a=1[m{j}];[m{j}]")

    if len(windows) == 1:
        en = f"gte(t,{a.start})"

    else:
        # distort only inside the stutters
        en = "+".join(f"between(t,{s},{e})" for s, e in windows[:-1])
        en += f"+gte(t,{windows[-1][0]})"

    af = (f"{chain}"
          f"volume=12:enable='{en}',"
          f"asoftclip=type=tanh:enable='{en}',"
          f"volume=6:enable='{en}',"
          f"asoftclip=type=tanh:enable='{en}',"
          f"lowpass=f=6000:enable='{en}',"
          f"volume=0.7:enable='{en}',"
          f"atrim=end={end}")   # wip


    # if our output is corrupted then reencode by running ffmpeg here
    run(["ffmpeg", "-y", "-err_detect", "ignore_err", "-i", bad, "-fps_mode", "cfr", "-af", af, "-vf", f"drawbox=x=0:y=0:w=iw:h=ih:color=0x0b3d0b@1:t=fill:enable='gte(t,{end})'", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(a.qscale), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", a.output])

    os.remove(tmp)
    os.remove(bad)

    if len(windows) == 1:
        print(f"Wrote {a.output}  (glitch at {a.start:.2f}s for {a.stutter:.2f}s, seed {a.seed}; " f"add --seed {a.seed} to repeat this exact glitch)")
    else:
        print(f"Wrote {a.output}  (glitch at {a.start:.2f}s for {end - a.start:.2f}s " f"in {len(windows)} stutters, seed {a.seed};")


if __name__ == "__main__":
    main()