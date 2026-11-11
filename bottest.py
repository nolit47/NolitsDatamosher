# 11.11.2026

import asyncio
import importlib
import importlib.util
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from urllib.parse import urlparse

# ///////////////////////////////////////////////////////////////////////////////////////////
# autoinstall shit it needs
# ///////////////////////////////////////////////////////////////////////////////////////////

Autoinstall_RequiredPKG = {
    "discord": "discord.py",
    "psutil": "psutil",
    "dotenv": "python-dotenv",
    "yt_dlp": "yt-dlp",
}


# installing required packages for this repo
def pip_install(packages: list[str], upgrade: bool = False) -> bool:
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"] + (["-U"] if upgrade else []) + packages

    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    attempts = [cmd] if in_venv else [cmd, cmd + ["--break-system-packages"]]


    for attempt in attempts:
        try:
            subprocess.check_call(attempt)
            return True

        except (subprocess.CalledProcessError, OSError):
            continue

    return False


def packages_checkexist():  # check if our python packages exist
    missing = [pip for mod, pip in Autoinstall_RequiredPKG.items() if importlib.util.find_spec(mod) is None]

    if missing:
        print(f"installing missing packages: {', '.join(missing)}")

        if not pip_install(missing):
            sys.exit(f"couldn't install {', '.join(missing)}. run: {sys.executable} -m pip install {' '.join(missing)}")
        importlib.invalidate_caches()


packages_checkexist()


# ///////////////////////////////////////////////////////////////////////////////////////////


import discord
import psutil
from discord.ext import commands
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent


# loader

load_dotenv(BASE_DIR / ".env")
load_dotenv()

# ///////////////////////////////////////////////////////////////////////////////////////////
# CONFIG
# ///////////////////////////////////////////////////////////////////////////////////////////

def env_str(name: str, default: str = "") -> str:
    v = os.getenv(name)

    return v.strip() if v and v.strip() else default


def env_int(name: str, default: int) -> int:
    raw = env_str(name)

    if not raw:
        return default

    try:
        return int(raw)

    except ValueError:
        print(f"config: {name}={raw!r} is not a whole number, using {default}")
        return default


def env_float(name: str, default: float) -> float:
    raw = env_str(name)

    if not raw:
        return default

    try:
        return float(raw)

    except ValueError:
        print(f"config: {name}={raw!r} is not a number, using {default}")
        return default


def env_bool(name: str, default: bool) -> bool:
    raw = env_str(name).lower()

    if not raw:
        return default

    return raw in ("1", "true", "yes", "on", "y")


def env_id_set(name: str) -> set[int]:
    ids = set()

    for part in env_str(name).replace(";", ",").split(","):
        part = part.strip()

        if part.isdigit():
            ids.add(int(part))

        elif part:
            print(f"config: {name} has `{part}` which is not a discord id, ignoring it")

    return ids


def env_exts(name: str, default: set[str]) -> set[str]:     # comma separated file extensions
    items = {x.strip().lower() for x in env_str(name).replace(";", ",").split(",") if x.strip()}
    items = {x if x.startswith(".") else "." + x for x in items}

    return items or default


# ///////////////////////////////////////////////////////////////////////////////////////////

# bot
TOKEN = os.getenv("DISCORD_TOKEN")
COMMAND_PREFIX = env_str("MOSH_PREFIX", "!")
ALLOWED_CHANNELS = env_id_set("MOSH_ALLOWED_CHANNELS")
BLOCKED_USERS = env_id_set("MOSH_BLOCKED_USERS")
USER_COOLDOWN_S = env_float("MOSH_USER_COOLDOWN_S", 0.0)
MAX_CONCURRENT_JOBS = max(1, env_int("MOSH_MAX_CONCURRENT_JOBS", 2))
HISTORY_SEARCH_LIMIT = env_int("MOSH_HISTORY_SEARCH_LIMIT", 25)

# limits
MAX_INPUT_MB = env_float("MOSH_MAX_INPUT_MB", 100)
MAX_DURATION_S = env_float("MOSH_MAX_DURATION_S", 120)
DISCORD_UPLOAD_LIMIT_MB = env_float("MOSH_UPLOAD_LIMIT_MB", 24)
JOB_TIMEOUT_S = env_int("MOSH_JOB_TIMEOUT_S", 600)  # a mosh script running longer than this gets killed
VIDEO_EXTS = env_exts("MOSH_VIDEO_EXTS", {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"})

# performance
MOSH_CPU_CORES = env_int("MOSH_CPU_CORES", 0)
MOSH_HEARTBEAT_INTERVAL_S = env_float("MOSH_HEARTBEAT_INTERVAL_S", 10)

# links
LINKS_ENABLED = env_bool("MOSH_LINKS_ENABLED", True)
MOSH_DOWNLOAD_TIMEOUT_S = env_int("MOSH_DOWNLOAD_TIMEOUT_S", 180)
MOSH_MAX_DOWNLOAD_HEIGHT = env_int("MOSH_MAX_DOWNLOAD_HEIGHT", 720)

# yt
MOSH_YTDLP_COOKIES = env_str("MOSH_YTDLP_COOKIES") or None
YTDLP_EXTRA_ARGS = shlex.split(env_str("MOSH_YTDLP_EXTRA_ARGS"))
UPDATE_YTDLP = env_bool("MOSH_UPDATE_YTDLP", False)

# files
WORK_ROOT = Path(env_str("MOSH_WORKDIR", str(Path(tempfile.gettempdir()) / "moshbot_jobs")))
KEEP_JOBS = env_str("MOSH_KEEP_JOBS", "never").lower()
SHOW_WORKDIR = env_bool("MOSH_SHOW_WORKDIR", True)
SHOW_STATS = env_bool("MOSH_SHOW_STATS", True)

# ///////////////////////////////////////////////////////////////////////////////////////////

if KEEP_JOBS not in ("never", "failed", "always"):
    print(f"MOSH_KEEP_JOBS = {KEEP_JOBS!r} must be never/failed/always")
    KEEP_JOBS = "never"

SCRIPT_PATH = BASE_DIR / "datamosh.py"
GLITCHCUT_PATH = BASE_DIR / "glitchcut.py"
DEFAULT_RUNMEME_MUSIC = str(BASE_DIR / "stupidshit.mp3")

WORK_ROOT.mkdir(parents=True, exist_ok=True)

job_slots = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
user_last_job: dict[int, float] = {}

# ///////////////////////////////////////////////////////////////////////////////////////////

def startup_checks():
    
    if UPDATE_YTDLP:
        print("updating yt-dlp")
        pip_install(["yt-dlp"], upgrade=True)

    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            print(f"!! {tool} not found in PATH. you will have to install ffmpeg yourself")


def should_keep_job(job_ok: bool) -> bool:
    return KEEP_JOBS == "always" or (KEEP_JOBS == "failed" and not job_ok)


def saved_note() -> str:
    if should_keep_job(False):
        return "saved on the host machine at:"

    return "not kept (set MOSH_KEEP_JOBS = failed to keep it). it was at:"


def workfolder_note(job_dir: Path) -> str:
    return "workfolder: `" + str(job_dir) + "`\n" if SHOW_WORKDIR else ""


def cooldown_remaining(user_id: int) -> float:
    if USER_COOLDOWN_S <= 0:
        return 0.0

    last = user_last_job.get(user_id)

    if last is None:
        return 0.0

    return max(0.0, USER_COOLDOWN_S - (time.monotonic() - last))


MODE_OPTIONS = {
    "real": {
        "start": ("--start", int, 0),
        "end": ("--end", int, "10**9 (whole video)"),
        "all": ("--all", "flag", False),
        "keepevery": ("--keep-every", int, 1),
        "gop": ("--gop", int, 30),
        "qscale": ("--qscale", int, 3),
        "keeptemp": ("--keep-temp", "flag", False),
        "noaudio": ("--no-audio", "flag", False),
    },
    "sim": {
        "start": ("--start", int, 0),
        "end": ("--end", int, "10**9 (whole video)"),
        "strength": ("--strength", float, 0.85),
        "threshold": ("--threshold", int, 18),
        "qscale": ("--qscale", int, 18),
        "noaudio": ("--no-audio", "flag", False),
    },
    "stutter": {
        "chance": ("--chance", float, 0.5),
        "dups": ("--dups", int, 5),
        "gop": ("--gop", int, 30),
        "qscale": ("--qscale", int, 3),
        "keeptemp": ("--keep-temp", "flag", False),
        "noaudio": ("--no-audio", "flag", False),
        "nospeedfix": ("--no-speed-fix", "flag", False),
        "audiostutter": ("--audio-stutter", "flag", False),
    },
    "ricecake": {
        "chance": ("--chance", float, 1.0),
        "dups": ("--dups", int, 5),
        "gop": ("--gop", int, 30),
        "qscale": ("--qscale", int, 3),
        "keeptemp": ("--keep-temp", "flag", False),
        "noaudio": ("--no-audio", "flag", False),
        "nospeedfix": ("--no-speed-fix", "flag", False),
    },
    "ytp": {
        "iterations": ("--iterations", int, 6),
        "chopmin": ("--chop-min", float, "auto"),
        "chopmax": ("--chop-max", float, "auto"),
        "freezechance": ("--freeze-chance", float, 0.0),
        "freezedur": ("--freeze-dur", float, 0.4),
        "qscale": ("--qscale", int, 18),
        "keeptemp": ("--keep-temp", "flag", False),
        "noaudio": ("--no-audio", "flag", False),
    },
    "ytpstutter": {
        "iterations": ("--iterations", int, 6),
        "chopmin": ("--chop-min", float, "auto"),
        "chopmax": ("--chop-max", float, "auto"),
        "freezechance": ("--freeze-chance", float, 0.0),
        "freezedur": ("--freeze-dur", float, 0.4),
        "chance": ("--chance", float, 0.5),
        "dups": ("--dups", int, 4),
        "gop": ("--gop", int, 30),
        "qscale": ("--qscale", int, 3),
        "keeptemp": ("--keep-temp", "flag", False),
        "noaudio": ("--no-audio", "flag", False),
    },
    "scatter": {
        "chopmin": ("--chop-min", float, 0.3),
        "chopmax": ("--chop-max", float, 2.0),
        "resample": ("--resample", "flag", False),
        "count": ("--count", int, 30),
        "qscale": ("--qscale", int, 18),
        "keeptemp": ("--keep-temp", "flag", False),
        "noaudio": ("--no-audio", "flag", False),
    },
    "runmeme": {
        "music": ("--music", str, DEFAULT_RUNMEME_MUSIC),
        "chopdur": ("--chop-dur", float, 0.5),
        "loopreps": ("--loop-reps", int, 4),
        "jump": ("--jump", float, 2.0),
        "beats": ("--beats", int, 3),
        "qscale": ("--qscale", int, 18),
        "keeptemp": ("--keep-temp", "flag", False),
    },
    "rotting": {
        "introdur": ("--intro-dur", float, 3.0),
        "stutterchance": ("--stutter-chance", float, 0.6),
        "stutterdups": ("--stutter-dups", int, 6),
        "gop": ("--gop", int, 30),
        "moshqscale": ("--mosh-qscale", int, 3),
        "qscale": ("--qscale", int, 18),
        "distortgain": ("--distort-gain", float, 8.0),
        "noaudio": ("--no-audio", "flag", False),
        "keeptemp": ("--keep-temp", "flag", False),
    },
    "glitchcut": {
        "start": ("--start", float, "random"),
        "stutter": ("--stutter", float, "random 1-4"),
        "count": ("--count", int, 1),
        "seed": ("--seed", int, "random"),
        "qscale": ("--qscale", int, 20),
    },
    "lipsync": {
        "gif": ("--gif", str, "assets/lips.gif"),
        "introdur": ("--intro-dur", float, 2.5),
        "probeframes": ("--probe-frames", int, 60),
        "scale": ("--scale", float, 1.0),
        "yoffset": ("--y-offset", float, 0.0),
        "detectevery": ("--detect-every", int, 3),
        "qscale": ("--qscale", int, 18),
        "noaudio": ("--no-audio", "flag", False),
    },
}

MODE_DESCRIPTIONS = {
    "real":       "I-frame removal",
    "sim":        "OpenCV framebleed simulation",
    "stutter":    "randomly duplicate pframes",
    "ricecake":   "naive raw bytesplit P-frame duplication",
    "ytp":        "random forward and reverse stutter loops",
    "ytpstutter": "splices with P-frame stutter on looped segments",
    "scatter":    "chop video into random segments and shuffle them",
    "runmeme":    "that one running meme",
    "rotting":    "rot with stutter decayed and stretched glitchy audio",
    "glitchcut":  "clean intro then the video breaks apart stutters with fuzzed audio and cuts to green",
    "lipsync":    "overlays the mouth gif",
}

PARAM_HELP = {
    "real": {
        "start": "frame to start removing keyframes at",
        "end": "frame to stop removing keyframes at",
        "all": "flag to remove every keyframe in the video",
        "keepevery": "only remove every nth keyframe",
        "gop": "group of pictures size for the avi step",
        "qscale": "output quality. higher number means lower quality",
        "keeptemp": "flag to keep the temp files",
        "noaudio": "flag to remove the audio",
    },
    "sim": {
        "start": "frame to start the bleed at",
        "end": "frame to stop the bleed at",
        "strength": "how strong the bleed is. near 1 means frames stay longer",
        "threshold": "how much motion it takes to refresh pixels",
        "qscale": "output quality. higher number means lower quality",
        "noaudio": "flag to remove the audio",
    },
    "stutter": {
        "chance": "chance a pframe gets copied",
        "dups": "how many copies to make",
        "gop": "group of pictures size for the avi step",
        "qscale": "output quality. higher number means lower quality",
        "keeptemp": "flag to keep the temp files",
        "noaudio": "flag to remove the audio",
        "nospeedfix": "flag to skip the speed fix. the video stays slow from the copies",
        "audiostutter": "flag to stutter the audio too",
    },
    "ricecake": {
        "chance": "chance a pframe gets copied",
        "dups": "how many copies to make",
        "gop": "group of pictures size for the avi step",
        "qscale": "output quality. higher number means lower quality",
        "keeptemp": "flag to keep the temp files",
        "noaudio": "flag to remove the audio",
        "nospeedfix": "flag to keep the video slow from the copies",
    },
    "ytp": {
        "iterations": "about how many stutter loops to add",
        "chopmin": "shortest chunk in seconds",
        "chopmax": "longest chunk in seconds",
        "freezechance": "chance a chunk freezes on its last frame",
        "freezedur": "how long a freeze lasts in seconds",
        "qscale": "output quality. higher number means lower quality",
        "keeptemp": "flag to keep the temp files",
        "noaudio": "flag to remove the audio",
    },
    "ytpstutter": {
        "iterations": "about how many stutter loops to add",
        "chopmin": "shortest chunk in seconds",
        "chopmax": "longest chunk in seconds",
        "freezechance": "chance a chunk freezes on its last frame",
        "freezedur": "how long a freeze lasts in seconds",
        "chance": "chance a loop also gets pframe copies",
        "dups": "how many pframe copies to make",
        "gop": "group of pictures size for the loops",
        "qscale": "quality of the loops and the final video",
        "keeptemp": "flag to keep the temp files",
        "noaudio": "flag to remove the audio",
    },
    "scatter": {
        "chopmin": "shortest random chunk in seconds",
        "chopmax": "longest random chunk in seconds",
        "resample": "flag to pick random chunks with repeats. some repeat and some get skipped",
        "count": "how many chunks to pick when resample is on",
        "qscale": "output quality. higher number means lower quality",
        "keeptemp": "flag to keep the temp files",
        "noaudio": "flag to remove the audio",
    },
    "runmeme": {
        "music": "!! indev !! path to the music file",
        "chopdur": "length of each forward and reverse chop in seconds",
        "loopreps": "forward and reverse pairs per beat. more makes longer beats",
        "jump": "how far to jump ahead between beats in seconds",
        "beats": "how many beats to make",
        "qscale": "output quality. higher number means lower quality",
        "keeptemp": "flag to keep the temp files",
    },
    "glitchcut": {
        "start": "seconds of clean video before the glitch. random if unset",
        "stutter": "how long each stutter lasts in seconds. the last one ends in green. random if unset",
        "count": "how many stutters to make. the video recovers between them. only the last one ends in green",
        "seed": "whole number. reuse it with count to get the same glitch",
        "qscale": "output quality from 0 to 51. higher means smaller file and lower quality",
    },
    "lipsync": {
        "gif": "path to the transparent gif to put on mouths",
        "introdur": "seconds of clean video before the gif shows",
        "probeframes": "how many frames to check for a face. fails fast if none",
        "scale": "size multiplier. 1.0 is auto fit",
        "yoffset": "move it up or down as a share of gif height. positive goes down",
        "detectevery": "find the face every N frames. higher is faster but lags on movement",
        "qscale": "output quality. higher number means lower quality",
        "noaudio": "flag to remove the audio",
    },
    "rotting": {
        "introdur": "seconds of clean video before the rot starts",
        "stutterchance": "chance a pframe gets copied once the rot starts",
        "stutterdups": "how many copies to make",
        "gop": "group of pictures size for the rot part",
        "moshqscale": "quality of the avi step",
        "qscale": "quality of the stutter parts and the final video",
        "distortgain": "how much the audio gets overdriven",
        "noaudio": "flag to remove the audio",
        "keeptemp": "flag to keep the temp files",
    },
}

# ///////////////////////////////////////////////////////////////////////////////////////////

def extract_cpucores_override(tokens: list[str]) -> tuple[list[str], int | None, str | None]:   # pulls cpucores override from tokens

    remaining = []
    override = None
    error = None

    for tok in tokens:
        if not tok.lower().startswith("cpucores="):
            remaining.append(tok)
            continue

        _, _, val = tok.partition("=")

        try:
            override = int(val)

            if override < 0:
                error = "!! cpucores must be 0 or a positive number."

        except ValueError:
            error = f"!! cpucores expects a whole number, got `{val}`."

    return remaining, override, error



def parse_kv_args(tokens: list[str], schema: dict) -> tuple[list[str], list[str]]:   # turns key = value tokens into cli args
    cli_args = []
    errors = []

    for tok in tokens:
        key, _, val = tok.partition("=")
        has_value = "=" in tok
        key = key.strip().lower()

        if key not in schema:   # unknown option
            errors.append(f"!! Unknown option `{key}` for this mode.")
            continue

        flag, typ, _default = schema[key]

        if typ == "flag":   # FLAG. doesnt have val
            cli_args.append(flag)
            continue

        if not has_value:   # if cmd the user submitted has no value its an error
            errors.append(f"!! Option `{key}` needs a value, e.g. `{key} = 10`.")
            continue

        try:
            typ(val)
        except ValueError:
            errors.append(f"!! Option `{key}` expects a {typ.__name__}, got `{val}`.")
            continue

        cli_args += [flag, val]

    return cli_args, errors



def build_help_embed(mode: str | None = None) -> discord.Embed:   # builds the help embed
    if mode is None:
        mode_list = "\n".join(f"**{m}** - {desc}" for m, desc in MODE_DESCRIPTIONS.items())

        return discord.Embed(
            title = "help",

            description = (
                f"attach a video and run `{COMMAND_PREFIX} mosh <MODE> [options]`.\n\n"
                f"{mode_list}\n\n"
                f"Run `{COMMAND_PREFIX} mosh help <MODE>` for that mode's options."
            ),

            color = discord.Color.purple(), # purpleslop
        )

    if mode not in MODE_OPTIONS:

        return discord.Embed(
            title="!! unknown mode",
            description=f"!! valid modes: {', '.join(MODE_OPTIONS)}",
            color=discord.Color.red(),
        )

    lines = []

    for key, (_flag, typ, default) in MODE_OPTIONS[mode].items():

        typename = "flag" if typ == "flag" else typ.__name__
        line = f"`{key}` ({typename}, default `{default}`)"
        explainer = PARAM_HELP.get(mode, {}).get(key)

        if explainer:
            line += f"\n  {explainer}"

        lines.append(line)

    embed = discord.Embed(
        title=f"Options for `{mode}`",
        description=MODE_DESCRIPTIONS[mode] + "\n\n" + "\n".join(lines),
        color=discord.Color.purple(),
    )

    example_opts = [
        f"{key} = {default}"
        for key, (_flag, typ, default) in list(MODE_OPTIONS[mode].items())[:2]
        if typ != "flag"
    ]

    embed.set_footer(text=f"example: {COMMAND_PREFIX} mosh {mode} " + " ".join(example_opts))

    return embed



def system_stats_line() -> str:     # cpu and ram usage data #OPSECDOXXING
    if not SHOW_STATS:
        return ""

    cpu = psutil.cpu_percent(interval=None)
    ram = psutil.virtual_memory().percent

    return f"CPU : {cpu:.0f}% /// RAM : {ram:.0f}%"


intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents, help_command=None)




# ///////////////////////////////////////////////////////////////////////////////////////////

@bot.event
async def on_ready():
    psutil.cpu_percent(interval=None)

    print(f"PYTHON: {sys.executable}")
    print(f"LOGGED IN AS {bot.user} (id = {bot.user.id})")
    print(f"PREFIX: {COMMAND_PREFIX}   SCRIPT: {SCRIPT_PATH}")
    print(f"LIMITS: {MAX_INPUT_MB:g}MB in /// {MAX_DURATION_S:g}s /// {DISCORD_UPLOAD_LIMIT_MB:g}MB out /// {MAX_CONCURRENT_JOBS} job(s) at once /// cooldown {USER_COOLDOWN_S:g}s")
    print(f"LINKS: {'on' if LINKS_ENABLED else 'off'} /// KEEP_JOBS: {KEEP_JOBS} /// CHANNELS: {sorted(ALLOWED_CHANNELS) or 'all'} /// BLOCKED: {len(BLOCKED_USERS)}")

    #if not SCRIPT_PATH.exists():
    #    print(f"datamosh.py not found at {SCRIPT_PATH}")
    #if not GLITCHCUT_PATH.exists():
    #    print(f"glitchcut.py not found at {GLITCHCUT_PATH}")


# ///////////////////////////////////////////////////////////////////////////////////////////
# LINKS
# ///////////////////////////////////////////////////////////////////////////////////////////

LINK_RE = re.compile(r"<?(https?://[^\s<>|]+?)(?=[)\].,!?;:]*(?:\s|>|\||$))>?", re.IGNORECASE)

websites_yt = ("youtube.com", "youtu.be")
websites_twitter = ("twitter.com", "x.com")
websites_twitter_altsites = ("fxtwitter.com", "vxtwitter.com", "fixupx.com")


def webhost_matches(host: str, domains: tuple) -> bool: # check if matches
    return any(host == d or host.endswith("." + d) for d in domains)


def normalize_link(url: str) -> tuple[str, str] | None: # turns bad links into ok
    try:
        parsed = urlparse(url)
    except ValueError:
        return None

    host = (parsed.hostname or "").lower()

    if webhost_matches(host, websites_yt):
        return url, "youtube"

    if webhost_matches(host, websites_twitter):
        return url, "twitter"

    if webhost_matches(host, websites_twitter_altsites):
        return parsed._replace(netloc="x.com").geturl(), "twitter"

    return None


def pop_video_url(raw_opts: str) -> tuple[tuple[str, str] | None, str, bool]:   # pull first supported link out of options
    found = None
    unsupported = False

    for m in LINK_RE.finditer(raw_opts):
        link = normalize_link(m.group(1))

        if link is None:
            unsupported = True
        elif found is None:
            found = link

    cleaned = LINK_RE.sub(" ", raw_opts).strip()    # clean from bs

    return found, cleaned, unsupported and found is None


async def find_reply_link(ctx: commands.Context) -> tuple[tuple[str, str] | None, str | None]:     # link inside the message you replied to
    ref = ctx.message.reference

    if ref is None:
        return None, None

    replied_msg = ref.cached_message

    if replied_msg is None:
        try:
            replied_msg = await ctx.fetch_message(ref.message_id)

        except discord.HTTPException:
            return None, None

    # in our case attachments will always win links as the user mightve intended to use file instead of a link as it may be accidental
    if pick_video_attachment(replied_msg.attachments) is not None:
        return None, None

    for m in LINK_RE.finditer(replied_msg.content or ""):
        link = normalize_link(m.group(1))

        if link is not None:
            return link, "the message you replied to"

    return None, None

# ///////////////////////////////////////////////////////////////////////////////////////////
# ytp-dl logic
# ///////////////////////////////////////////////////////////////////////////////////////////

async def download_link(url: str, job_dir: Path) -> tuple[Path | None, str]:
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--no-playlist", "--playlist-items", "1",
        "--max-filesize", f"{int(MAX_INPUT_MB)}M",
        "--match-filter", f"duration<=?{int(MAX_DURATION_S)}",  # skip vidoes that are over MAX_DURATION_S
        "-f", f"bv*[height<={MOSH_MAX_DOWNLOAD_HEIGHT}]+ba/b[height<={MOSH_MAX_DOWNLOAD_HEIGHT}]/b",
        "--merge-output-format", "mp4",
        "-o", str(job_dir / "input.%(ext)s"),
    ]

    if MOSH_YTDLP_COOKIES:
        cmd += ["--cookies", MOSH_YTDLP_COOKIES]

    cmd += YTDLP_EXTRA_ARGS
    cmd.append(url)

    proc = await asyncio.create_subprocess_exec(*cmd, cwd=str(job_dir), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)

    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=MOSH_DOWNLOAD_TIMEOUT_S)

    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return None, "download timed out"

    log = stdout.decode(errors="replace")
    files = [f for f in job_dir.glob("input.*") if f.suffix not in (".part", ".ytdl")]

    if proc.returncode != 0 or not files:
        return None, log

    return files[0], log



def pick_video_attachment(attachments) -> "discord.Attachment | None":      # picks the first recent video
    for a in attachments:
        if Path(a.filename).suffix.lower() in VIDEO_EXTS:
            return a
    return None


# find video by checking if its a replied message or if its a recent message
async def find_video_attachment(ctx: commands.Context, history_search_limit: int = HISTORY_SEARCH_LIMIT) -> tuple["discord.Attachment | None", str | None, bool]:

    if ctx.message.attachments:
        direct = pick_video_attachment(ctx.message.attachments)
        
        if direct is not None:
            return direct, None, False
        
        return None, None, True

    ref = ctx.message.reference

    if ref is not None:
        replied_msg = ref.cached_message

        if replied_msg is None:
            try:
                replied_msg = await ctx.fetch_message(ref.message_id)

            except discord.HTTPException:
                replied_msg = None

        if replied_msg is not None:
            found = pick_video_attachment(replied_msg.attachments)

            if found is not None:
                return found, "the message you replied to", False
    if history_search_limit <= 0:
        return None, None, False

    try:
        async for msg in ctx.channel.history(limit=history_search_limit, before=ctx.message):
            found = pick_video_attachment(msg.attachments)

            if found is not None:
                source = f"the most recent video in this channel (from {msg.author.display_name})"
                return found, source, False 
            
    except discord.HTTPException:
        pass

    return None, None, False

# ///////////////////////////////////////////////////////////////////////////////////////////
# MOSH
# ///////////////////////////////////////////////////////////////////////////////////////////

@bot.command(name="mosh")
async def mosh(ctx: commands.Context, mode: str = None, *, raw_opts: str = ""):
    if mode is None or mode.lower() == "help":

        sub = raw_opts.strip().split()[0] if raw_opts.strip() else None     # get the first word after !mosh help as the subcommand
        await ctx.reply(embed=build_help_embed(sub))

        return

    mode = mode.lower()

    if mode not in MODE_OPTIONS:

        await ctx.reply(f"!! unknown mode `{mode}` valid modes: {', '.join(MODE_OPTIONS)}.\n" f"run `{COMMAND_PREFIX} mosh help` for details")
        return

    wait = cooldown_remaining(ctx.author.id)

    if wait > 0:
        await ctx.reply(f"!! Too much requests! you can start another job in {wait:.0f}s")
        return

    link, raw_opts, unsupported_link = pop_video_url(raw_opts)
    link_source = None

    if (link is not None or unsupported_link) and not LINKS_ENABLED:
        await ctx.reply("!! links are turned off on this bot. attach a video instead.")
        return

    if unsupported_link:
        await ctx.reply("!! only yt and twitter links are supported")
        return



    if link is None and LINKS_ENABLED and not ctx.message.attachments:
        link, link_source = await find_reply_link(ctx)  # or a link in the message you replied to
    attachment, attachment_source, wrong_format = None, link_source, False

    if link is None:
        attachment, attachment_source, wrong_format = await find_video_attachment(ctx)  # find a video in the message or replied message or recent message


    if attachment is None and link is None:
        if wrong_format:
            await ctx.reply(f"!! invalid video format: {', '.join(sorted(VIDEO_EXTS))}")
        else:
            await ctx.reply("!! couldnt find a video. attach one to your message or reply to a message that has one or make sure one was posted recently in this channel.")
        return

    if attachment is not None:

        source_name = attachment.filename
        size_mb = attachment.size / (1024 * 1024)

        if size_mb > MAX_INPUT_MB:
            await ctx.reply(f"!! that file is too large! ({size_mb:.1f} MB). I can only process {MAX_INPUT_MB:.0f} MB limit")
            return
    else:
        source_name = f"{link[1]}.mp4"  # size is checked after the download

    tokens = shlex.split(raw_opts) if raw_opts else []
    tokens, cpucores_override, cpucores_error = extract_cpucores_override(tokens)


    if cpucores_error:
        await ctx.reply(f"!! couldn't parse options: \n- {cpucores_error}")
        return
    cpucores = cpucores_override if cpucores_override is not None else MOSH_CPU_CORES


    cli_args, errors = parse_kv_args(tokens, MODE_OPTIONS[mode])


    if errors:
        await ctx.reply(f"!! couldn't parse options: \n- {errors}")
        return


    script_path = GLITCHCUT_PATH if mode == "glitchcut" else SCRIPT_PATH
    if not script_path.exists():
        await ctx.reply(f"!! {script_path.name} not found at `{script_path}`.")
        return


    user_last_job[ctx.author.id] = time.monotonic()     # cooldown starts when the job is accepted


    job_dir = Path(tempfile.mkdtemp(prefix=f"mosh_{mode}_", dir=WORK_ROOT))
    in_path = job_dir / f"input{Path(source_name).suffix.lower()}"
    out_path = job_dir / "output.mp4"

    source_note = f"using video from {attachment_source}\n" if attachment_source else ""
    job_started_at = time.monotonic()



    status_text = f"{source_note}" f"downloading `{source_name}`...\n" f"{workfolder_note(job_dir)}" f"{system_stats_line()}"
    queued = job_slots.locked()     # all job slots are busy so this one waits

    status_msg = await ctx.reply(f"queued. {MAX_CONCURRENT_JOBS} job(s) running right now...\n{workfolder_note(job_dir)}" if queued else status_text)

    await job_slots.acquire()   # released in the finally below
    job_ok = False

    if queued:
        await safe_status_update(status_msg, status_text)


    # /////////////////////////////////////////////////////////////////////////////////////////////

    # ACTION!
    try:
        if attachment is not None:
            await attachment.save(in_path)

        else:   # youtube links
            in_path, dl_log = await download_link(link[0], job_dir)

            if in_path is None:
                tail = dl_log[-1200:].strip() or "( no output captured )"
                await status_msg.edit(content=(f"!! Unable to download the video.\n" f"```\n{tail}\n```"))
                return

            link_mb = in_path.stat().st_size / (1024 * 1024)

            if link_mb > MAX_INPUT_MB:
                await status_msg.edit(content=f"!! that video is too large! ({link_mb:.1f} MB). I can only process {MAX_INPUT_MB:.0f} MB limit")
                return

        # duration limit

        duration = await probe_duration(in_path)
        if duration is not None and duration > MAX_DURATION_S:
            await status_msg.edit(content=(f"!! that clip is {duration:.1f}s long, over the {MAX_DURATION_S:.0f}s limit\n" f"{workfolder_note(job_dir)}" f"{system_stats_line()}"))
            return


        # glitchcut

        if mode == "glitchcut":
            full_args = [sys.executable, str(script_path), str(in_path), str(out_path)] + cli_args  # glitchcut script takes i/o paths as arguments
        else:
            full_args = [sys.executable, str(script_path), mode, str(in_path), str(out_path)] + cli_args

        cpu_note = f"CPU limit: {cpucores} core(s)" if cpucores > 0 else "CPU limit: none"

        await status_msg.edit(content=(f"running `{mode}` mosh... this can take a bit.\n" f"{workfolder_note(job_dir)}" f"{cpu_note}\n" f"{system_stats_line()}"))

        rc, log_tail = await run_datamosh(full_args, job_dir, status_msg=status_msg, mode=mode, job_dir=job_dir, cpucores=cpucores,)    # mosh script runner


        # mosh script exit code check

        if rc != 0 or not out_path.exists():    # mosh failed
            tail = log_tail[-1500:] if log_tail else "( no output captured from the script )"

            await status_msg.edit(content=(f"!! mosh failed! ( exit code {rc}).\n" f"{workfolder_note(job_dir)}" f"{system_stats_line()}\n" f"```\n{tail}\n```"))
            return


        # discord output size limit checker

        out_mb = out_path.stat().st_size / (1024 * 1024)

        if out_mb > DISCORD_UPLOAD_LIMIT_MB:
            await status_msg.edit(content=(f"!! done, but the result is {out_mb:.1f}MB which is over this server's " f"{DISCORD_UPLOAD_LIMIT_MB:.0f}MB upload limit. It's {saved_note()}\n" f"{workfolder_note(job_dir)}" f"{system_stats_line()}"))
            return
        
        await status_msg.edit(content=(f"!! done! `{mode}` mosh of `{source_name}`:\n" f"{workfolder_note(job_dir)}" f"{system_stats_line()}"))

        elapsed_s = time.monotonic() - job_started_at   # elapsed time for the job
        seed_note = build_seed_note(log_tail) if mode == "glitchcut" else ""    # builds the glitchcut repeat seed note
        out_filename = f"mosh_{mode}_{Path(source_name).stem}.mp4" # output filename


        # success. upload result
        try:
            await ctx.reply(

                content=f"Done! `{out_filename}`, job took {elapsed_s:.1f}s{seed_note}",

                file=discord.File(str(out_path), filename=out_filename),
            )

            job_ok = True

        # upload failed. report error but keep the file on the host
        # TODO: add a download link to the file on the host if possible

        except discord.HTTPException as upload_err:
            await safe_status_update(

                status_msg,
                f"!! done moshing, but Discord rejected the upload ({upload_err.status} "
                f"{upload_err.text}). File is {out_mb:.1f}MB and {saved_note()}\n"
                f"{workfolder_note(job_dir)}"
                f"{system_stats_line()}",
            )

    except Exception as e:
        traceback.print_exc()

        await safe_status_update(
            status_msg,
            f"!! Unexpected error: `{e}`\n"
            f"{workfolder_note(job_dir)}"
            f"{system_stats_line()}",
        )

    finally:
        job_slots.release()

        if should_keep_job(job_ok):
            print(f"keeping job folder: {job_dir}")

        else:
            cleanup_job_dir(job_dir)    # clean job


# ///////////////////////////////////////////////////////////////////////////////////////////

def build_seed_note(log_tail: str | None) -> str:   # builds the glitchcut repeat seed note
    
    pattern = (
        r"glitch at ([\d.]+)s for ([\d.]+)s(?: in (\d+) stutters)?, seed (\d+)"
        r"(?:; add --seed \d+ --count (\d+))?"
    )

    m = re.search(pattern, log_tail or "")  # search for the pattern in the log tail

    if not m:
        return ""

    start, length, stutter_count, seed, count = m.groups()
    repeat = f"seed = {seed}" + (f" count = {count}" if count else "")
    stutters = f", {stutter_count} stutters" if stutter_count else ""
    return f" (glitch at {start}s for {length}s{stutters}, `{repeat}` to repeat)"


async def safe_status_update(status_msg, content: str):   # edits status message without crashing
    try:
        await status_msg.edit(content=content)
    except discord.HTTPException:
        print(f"couldn't update status message, content was:\n{content}")


async def probe_duration(path: Path) -> float | None:   # gets video length with ffprobe
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)]

    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)   # run
        stdout, _ = await proc.communicate()

        return float(stdout.decode().strip())
    except Exception:
        return None


def apply_cpu_limit(pid: int, cpucores: int) -> str | None:   # pins process to first x cores
    if cpucores <= 0:
        return None
    
    try:
        proc = psutil.Process(pid)  # get the process by PID
        total_cores = psutil.cpu_count() or 1   # get total number of cpu cores
        proc.cpu_affinity(list(range(min(cpucores, total_cores))))  # set cpu affinity to the first x cores
        return None
    
    except (psutil.NoSuchProcess, psutil.AccessDenied, NotImplementedError) as e:
        return f"couldn't apply CPU limit ({e})"


# RUN MOSH!!!!

async def run_datamosh(full_args: list[str], cwd: Path, timeout: int = JOB_TIMEOUT_S, status_msg=None, mode: str = "", job_dir: Path = None, cpucores: int = 0,) -> tuple[int, str]:

    proc = await asyncio.create_subprocess_exec(*full_args, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,)    # run the mosh py as a subprocess and capture output
    log_chunks = []

    affinity_error = apply_cpu_limit(proc.pid, cpucores)

    if affinity_error:
        log_chunks.append(f"{affinity_error}\n")

    async def read_output():   # collects script output lines
        async for line in proc.stdout:
            log_chunks.append(line.decode(errors="replace"))




    async def heartbeat():   # refreshes status msg on a timer
        if status_msg is None:
            return
        
        cpu_note = f"CPU limit: {cpucores} core(s)" if cpucores > 0 else "CPU limit: none"

        while True:
            await asyncio.sleep(MOSH_HEARTBEAT_INTERVAL_S)
            try:
                # notify that we are working
                await status_msg.edit(
                    content=(f"running `{mode}` mosh... this can take a bit.\n" f"{workfolder_note(job_dir)}"
                        f"{cpu_note}\n"
                        f"{system_stats_line()}"))
                
            except discord.HTTPException:
                pass

    hb_task = asyncio.create_task(heartbeat())


    # run the mosh script and wait for finish

    try:
        await asyncio.wait_for(asyncio.gather(read_output(), proc.wait()), timeout=timeout)

    except asyncio.TimeoutError:    # if timeout
        proc.kill()
        await proc.wait()
        log_chunks.append("\nTIMED OUT and was killed.\n")
        return -1, "".join(log_chunks)
    
    finally:
        hb_task.cancel()

        try:
            await hb_task
        except asyncio.CancelledError:
            pass

    return proc.returncode, "".join(log_chunks)


def cleanup_job_dir(job_dir: Path):   # deletes the job folder
    shutil.rmtree(job_dir, ignore_errors=True)

# ///////////////////////////////////////////////////////////////////////////////////////////

@bot.check
async def global_gate(ctx: commands.Context) -> bool:   # blocked users and channel whitelist
    if ctx.author.id in BLOCKED_USERS:
        return False

    if ALLOWED_CHANNELS:
        channel_ids = {ctx.channel.id, getattr(ctx.channel, "parent_id", None)}
        if not channel_ids & ALLOWED_CHANNELS:
            return False

    return True


@bot.event
async def on_command_error(ctx, error):   # handles command errors

    if isinstance(error, (commands.CommandNotFound, commands.CheckFailure)):
        return
    
    traceback.print_exception(type(error), error, error.__traceback__)
    await ctx.reply(f"error: `{error}`")


def main():   # start
    if not TOKEN:
        print("No discord token was set", file=sys.stderr)
        sys.exit(1)

    startup_checks()
    bot.run(TOKEN)


if __name__ == "__main__":
    main()