import asyncio
import os
import shlex
import sys
import tempfile
import time
import traceback
from pathlib import Path

import discord
import psutil
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
COMMAND_PREFIX = os.getenv("MOSH_PREFIX", "!")
MAX_INPUT_MB = float(os.getenv("MOSH_MAX_INPUT_MB", "100"))
MAX_DURATION_S = float(os.getenv("MOSH_MAX_DURATION_S", "120"))
WORK_ROOT = Path(os.getenv("MOSH_WORKDIR", str(Path(tempfile.gettempdir()) / "moshbot_jobs")))
SCRIPT_PATH = Path(__file__).resolve().parent / "datamosh.py"
DEFAULT_RUNMEME_MUSIC = str(Path(__file__).resolve().parent / "stupidshit.mp3")
DISCORD_UPLOAD_LIMIT_MB = float(os.getenv("MOSH_UPLOAD_LIMIT_MB", "24"))

MOSH_CPU_CORES = int(os.getenv("MOSH_CPU_CORES", "0"))
MOSH_HEARTBEAT_INTERVAL_S = float(os.getenv("MOSH_HEARTBEAT_INTERVAL_S", "10"))

WORK_ROOT.mkdir(parents=True, exist_ok=True)

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}

MODE_OPTIONS = {"real": {"start": ("--start", int, 0), "end": ("--end", int, "10**9 (whole video)"), "all": ("--all", "flag", False), "keepevery": ("--keep-every", int, 1), "gop": ("--gop", int, 30), "qscale": ("--qscale", int, 3), "keeptemp": ("--keep-temp", "flag", False), "noaudio": ("--no-audio", "flag", False),}, "sim": {"start": ("--start", int, 0), "end": ("--end", int, "10**9 (whole video)"), "strength": ("--strength", float, 0.85), "threshold": ("--threshold", int, 18), "qscale": ("--qscale", int, 18), "noaudio": ("--no-audio", "flag", False),}, "stutter": {"chance": ("--chance", float, 0.5), "dups": ("--dups", int, 5), "gop": ("--gop", int, 30), "qscale": ("--qscale", int, 3), "keeptemp": ("--keep-temp", "flag", False), "noaudio": ("--no-audio", "flag", False), "nospeedfix": ("--no-speed-fix", "flag", False), "audiostutter": ("--audio-stutter", "flag", False),}, "ricecake": {"chance": ("--chance", float, 1.0), "dups": ("--dups", int, 5), "gop": ("--gop", int, 30), "qscale": ("--qscale", int, 3), "keeptemp": ("--keep-temp", "flag", False), "noaudio": ("--no-audio", "flag", False), "nospeedfix": ("--no-speed-fix", "flag", False),}, "ytp": {"iterations": ("--iterations", int, 6), "chopmin": ("--chop-min", float, "auto"), "chopmax": ("--chop-max", float, "auto"), "freezechance": ("--freeze-chance", float, 0.0), "freezedur": ("--freeze-dur", float, 0.4), "qscale": ("--qscale", int, 18), "keeptemp": ("--keep-temp", "flag", False), "noaudio": ("--no-audio", "flag", False),}, "ytpstutter": {"iterations": ("--iterations", int, 6), "chopmin": ("--chop-min", float, "auto"), "chopmax": ("--chop-max", float, "auto"), "freezechance": ("--freeze-chance", float, 0.0), "freezedur": ("--freeze-dur", float, 0.4), "chance": ("--chance", float, 0.5), "dups": ("--dups", int, 4), "gop": ("--gop", int, 30), "qscale": ("--qscale", int, 3), "keeptemp": ("--keep-temp", "flag", False), "noaudio": ("--no-audio", "flag", False),}, "scatter": {"chopmin": ("--chop-min", float, 0.3), "chopmax": ("--chop-max", float, 2.0), "resample": ("--resample", "flag", False), "count": ("--count", int, 30), "qscale": ("--qscale", int, 18), "keeptemp": ("--keep-temp", "flag", False), "noaudio": ("--no-audio", "flag", False),}, "runmeme": {"music": ("--music", str, DEFAULT_RUNMEME_MUSIC), "chopdur": ("--chop-dur", float, 0.5), "loopreps": ("--loop-reps", int, 4), "jump": ("--jump", float, 2.0), "beats": ("--beats", int, 3), "qscale": ("--qscale", int, 18), "keeptemp": ("--keep-temp", "flag", False),}, "rotting": {"introdur":     ("--intro-dur",      float, 3.0), "stutterchance":("--stutter-chance", float, 0.6), "stutterdups":  ("--stutter-dups",   int,   6), "gop":          ("--gop",            int,   30), "moshqscale":   ("--mosh-qscale",    int,   3), "qscale":       ("--qscale",         int,   18), "distortgain":  ("--distort-gain",   float, 8.0), "noaudio":      ("--no-audio",       "flag", False), "keeptemp":     ("--keep-temp",      "flag", False),},}

MODE_DESCRIPTIONS = {"real": "I-frame removal", "sim": "OpenCV framebleed simulation", "stutter": "randomly duplicates pframes for stutter effect.", "ricecake": "naive raw bytesplit P-frame duplication", "ytp": "random forward/reverse stutter loop splices", "ytpstutter": "splices with P-frame stutter on loop segments", "scatter": "chop video into random segments and shuffle them", "runmeme": "that one running meme", "rotting": "rot with stutter + decayed/stretched glitchy audio",}

PARAM_HELP = {
    "real": {
        "start": "frame number to start removing keyframes from",
        "end": "frame number to stop removing keyframes at",
        "all": "flag that nukes every keyframe in the whole vid instead of framerange",
        "keepevery": "only kills every nth keyframe in the range instead of all of them",
        "gop": "group of pictures size for the avi transcode",
        "qscale": "Output quality higher value = lower quality",
        "keeptemp": "flag, dont delete the messy temp files it makes while moshing",
        "noaudio": "flag, strips the audio out of the output",
    },
    "sim": {
        "start": "frame to start framebleed on",
        "end": "frame to stop framebleed on",
        "strength": "how strong the bleed is (closer to 1 = frames stick around longer and blend more)",
        "threshold": "how much motion is needed before pixels refresh",
        "qscale": "Output quality higher value = lower quality",
        "noaudio": "flag, strips the audio out of the output",
    },
    "stutter": {
        "chance": "chance that any given pframe gets duplicated",
        "dups": "how many copies to make when a pframe gets picked for dupe",
        "gop": "group of pictures size for the avi transcode",
        "qscale": "Output quality higher value = lower quality",
        "keeptemp": "flag, dont delete the messy temp files",
        "noaudio": "flag, strips the audio out of the output",
        "nospeedfix": "flag, normally the vid gets sped back up since duping frames slows it down, this skips that and leaves it slow",
        "audiostutter": "flag, also stutters the audio to roughly match the video instead of leaving it clean",
    },
    "ricecake": {
        "chance": "chance that any given pframe gets duplicated",
        "dups": "how many copies to make when a p-frame gets picked for dupe",
        "gop": "group of pictures size for the avi transcode",
        "qscale": "Output quality higher value = lower quality",
        "keeptemp": "flag, dont delete the messy temp files",
        "noaudio": "flag, strips the audio out of the output",
        "nospeedfix": "flag, leaves the vid slowed down from the dupes instead of speeding it back up",
    },
    "ytp": {
        "iterations": "roughly how many stutter loops get connected in",
        "chopmin": "shortest a chopped segment can be in seconds",
        "chopmax": "longest a chopped segment can be in seconds",
        "freezechance": "chance a chop freezes on the last frame for a sec",
        "freezedur": "how long the freeze frame holds in seconds when it happens",
        "qscale": "Output quality higher value = lower quality",
        "keeptemp": "flag, dont delete the messy temp files",
        "noaudio": "flag, strips the audio out of the output",
    },
    "ytpstutter": {
        "iterations": "roughly how many stutter loops get connected in",
        "chopmin": "shortest a chopped segment can be in seconds",
        "chopmax": "longest a chopped segment can be in seconds",
        "freezechance": "chance a chop freezes on the last frame for a sec",
        "freezedur": "how long the freeze frame holds in seconds when it happens",
        "chance": "chance a stutter loop also gets its pframes duped on top",
        "dups": "how many copies to make for those duped pframes",
        "gop": "group of pictures size for the stutter segments",
        "qscale": "quality for the stutter segments, also doubles as the final output quality",
        "keeptemp": "flag, dont delete the messy temp files",
        "noaudio": "flag, strips the audio out of the output",
    },
    "scatter": {
        "chopmin": "shortest a random chopped segment can be in seconds",
        "chopmax": "longest a random chopped segment can be in seconds",
        "resample": "flag, instead of shuffling every segment once it randomly picks segments with repeats allowed some parts repeat some get skipped",
        "count": "how many segments to grab when resample is on",
        "qscale": "Output quality higher value = lower quality",
        "keeptemp": "flag, dont delete the messy temp files",
        "noaudio": "flag, strips the audio out of the output",
    },
    "runmeme": {
        "music": "!! Indev !! path to the music file to mix in",
        "chopdur": "how long each fwd and reverse chop is in seconds",
        "loopreps": "how many fwd+rev pairs happen per beat, more = longer beats",
        "jump": "how far it jumps ahead in the source between beats, in seconds",
        "beats": "how many beat loops to make total",
        "qscale": "Output quality higher value = lower quality",
        "keeptemp": "flag, dont delete the messy temp files",
    },
    "rotting": {
        "introdur": "seconds of normal clean video before everything starts rotting",
        "stutterchance": "chance a p-frame gets duplicated once the rot kicks in",
        "stutterdups": "how many copies to make for those duped pframes",
        "gop": "group of pictures size for the avi transcode used during the rot part",
        "moshqscale": "quality of that internal avi transcode",
        "qscale": "quality for the stutter segments, also doubles as the final output quality",
        "distortgain": "how much the audio gets overdriven",
        "noaudio": "flag, strips the audio out of the output",
        "keeptemp": "flag, dont delete the messy temp files",
    },
}

def extract_cpucores_override(tokens: list[str]) -> tuple[list[str], int | None, str | None]:
    remaining = []
    override = None
    error = None
    for tok in tokens:
        if tok.lower().startswith("cpucores="):
            _, _, val = tok.partition("=")
            try:
                override = int(val)
                if override < 0:
                    error = "`cpucores` must be 0 (no limit) or a positive number."
            except ValueError:
                error = f"`cpucores` expects a whole number, got `{val}`."
        else:
            remaining.append(tok)
    return remaining, override, error

def parse_kv_args(tokens: list[str], schema: dict) -> tuple[list[str], list[str]]:
    cli_args = []
    errors = []
    for tok in tokens:
        if "=" in tok:
            key, _, val = tok.partition("=")
        else:
            key, val = tok, None
        key = key.strip().lower()
        if key not in schema:
            errors.append(f"Unknown option `{key}` for this mode.")
            continue
        flag, typ, _default = schema[key]
        if typ == "flag":
            cli_args.append(flag)
            continue
        if val is None:
            errors.append(f"Option `{key}` needs a value, e.g. `{key}=10`.")
            continue
        try:
            typ(val)
        except ValueError:
            errors.append(f"Option `{key}` expects a {typ.__name__}, got `{val}`.")
            continue
        cli_args += [flag, val]
    return cli_args, errors

def build_help_embed(mode: str | None = None) -> discord.Embed:
    if mode is None:
        embed = discord.Embed(title="help", description=(f"attach a video and run `{COMMAND_PREFIX}mosh <mode> [options]`.\n\n" + "\n".join(f"**{m}** — {desc}" for m, desc in MODE_DESCRIPTIONS.items()) + f"\n\nRun `{COMMAND_PREFIX}mosh help <mode>` for that mode's options."), color=discord.Color.purple(),)
        return embed

    if mode not in MODE_OPTIONS:
        return discord.Embed(title="unknown mode", description=f"valid modes: {', '.join(MODE_OPTIONS)}", color=discord.Color.red(),)

    lines = []
    for key, (flag, typ, default) in MODE_OPTIONS[mode].items():
        typename = "flag" if typ == "flag" else typ.__name__
        explainer = PARAM_HELP.get(mode, {}).get(key)
        line = f"`{key}` ({typename}, default `{default}`)"
        if explainer:
            line += f"\n  {explainer}"
        lines.append(line)
    embed = discord.Embed(title=f"Options for `{mode}`", description=MODE_DESCRIPTIONS[mode] + "\n\n" + "\n".join(lines), color=discord.Color.purple(),)
    embed.set_footer(text=f"example: {COMMAND_PREFIX}mosh {mode} " + " ".join(f"{k}={v}" for k, (f, t, v) in list(MODE_OPTIONS[mode].items())[:2] if t != "flag"))
    return embed

def system_stats_line() -> str:
    cpu = psutil.cpu_percent(interval=None)
    ram = psutil.virtual_memory().percent
    return f"CPU: {cpu:.0f}% | RAM: {ram:.0f}%"

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents, help_command=None)

@bot.event
async def on_ready():
    psutil.cpu_percent(interval=None)
    print(f"logged in as {bot.user} (id={bot.user.id})")
    print(f"prefix: {COMMAND_PREFIX}   Script: {SCRIPT_PATH}")
    if not SCRIPT_PATH.exists():
        print(f"datamosh.py not found at {SCRIPT_PATH}")

def pick_video_attachment(attachments) -> "discord.Attachment | None":
    return next((a for a in attachments if Path(a.filename).suffix.lower() in VIDEO_EXTS), None,)

async def find_video_attachment(ctx: commands.Context, history_search_limit: int = 25) -> tuple["discord.Attachment | None", str | None, bool]:
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
    try:
        async for msg in ctx.channel.history(limit=history_search_limit, before=ctx.message):
            found = pick_video_attachment(msg.attachments)
            if found is not None:
                return found, f"the most recent video in this channel (from {msg.author.display_name})", False
    except discord.HTTPException:
        pass

    return None, None, False

@bot.command(name="mosh")
async def mosh(ctx: commands.Context, mode: str = None, *, raw_opts: str = ""):
    if mode is None or mode.lower() == "help":
        sub = raw_opts.strip().split()[0] if raw_opts.strip() else None
        await ctx.reply(embed=build_help_embed(sub))
        return

    mode = mode.lower()
    if mode not in MODE_OPTIONS:
        await ctx.reply(f"unknown mode `{mode}`. valid modes: {', '.join(MODE_OPTIONS)}.\n" f"run `{COMMAND_PREFIX}mosh help` for details.")
        return

    attachment, attachment_source, wrong_format = await find_video_attachment(ctx)
    if attachment is None:
        if wrong_format:
            await ctx.reply(f"invalid video format: {', '.join(sorted(VIDEO_EXTS))}")
        else:
            await ctx.reply("couldnt find a video. attach one to your message or reply to a message " "that has one or make sure one was posted recently in this channel.")
        return

    size_mb = attachment.size / (1024 * 1024)
    if size_mb > MAX_INPUT_MB:
        await ctx.reply(f"that file is too large! ({size_mb:.1f}MB). i can only process {MAX_INPUT_MB:.0f}MB limit")
        return

    tokens = shlex.split(raw_opts) if raw_opts else []
    tokens, cpucores_override, cpucores_error = extract_cpucores_override(tokens)
    if cpucores_error:
        await ctx.reply(f"couldn't parse options:\n- {cpucores_error}")
        return
    cpucores = cpucores_override if cpucores_override is not None else MOSH_CPU_CORES

    cli_args, errors = parse_kv_args(tokens, MODE_OPTIONS[mode])
    if errors:
        await ctx.reply("couldn't parse options:\n" + "\n".join(f"- {e}" for e in errors))
        return

    if not SCRIPT_PATH.exists():
        await ctx.reply(f"datamosh.py not found at `{SCRIPT_PATH}`.")
        return

    job_dir = Path(tempfile.mkdtemp(prefix=f"mosh_{mode}_", dir=WORK_ROOT))
    in_path = job_dir / f"input{Path(attachment.filename).suffix.lower()}"
    out_path = job_dir / "output.mp4"

    source_note = f"using video from {attachment_source}\n" if attachment_source else ""
    job_started_at = time.monotonic()

    status_msg = await ctx.reply(f"{source_note}" f"downloading `{attachment.filename}`...\n" f"workfolder: `{job_dir}`\n" f"{system_stats_line()}")

    try:
        await attachment.save(in_path)

        duration = await probe_duration(in_path)
        if duration is not None and duration > MAX_DURATION_S:
            await status_msg.edit(content=(f"that clip is {duration:.1f}s long, over the {MAX_DURATION_S:.0f}s limit\n" f"workfolder: `{job_dir}`\n" f"{system_stats_line()}"))
            return

        full_args = [sys.executable, str(SCRIPT_PATH), mode, str(in_path), str(out_path)] + cli_args
        cpu_note = f"CPU limit: {cpucores} core(s)" if cpucores > 0 else "CPU limit: none"
        await status_msg.edit(content=(f"running `{mode}` mosh... this can take a bit.\n" f"workfolder: `{job_dir}`\n" f"{cpu_note}\n" f"{system_stats_line()}"))

        rc, log_tail = await run_datamosh(full_args, job_dir, status_msg=status_msg, mode=mode, job_dir=job_dir, cpucores=cpucores)

        if rc != 0 or not out_path.exists():
            tail = log_tail[-1500:] if log_tail else "(no output captured)"
            await status_msg.edit(content=(f"mosh failed! (exit code {rc}).\n" f"workfolder: `{job_dir}`\n" f"{system_stats_line()}\n" f"```\n{tail}\n```"))
            return

        out_mb = out_path.stat().st_size / (1024 * 1024)
        if out_mb > DISCORD_UPLOAD_LIMIT_MB:
            await status_msg.edit(content=(f"done, but the result is {out_mb:.1f}MB which is over this server's " f"{DISCORD_UPLOAD_LIMIT_MB:.0f}mb upload limit. It's saved on the host machine at:\n" f"workfolder: `{job_dir}`\n" f"{system_stats_line()}"))
            return

        await status_msg.edit(content=(f"done! `{mode}` mosh of `{attachment.filename}`:\n" f"workfolder: `{job_dir}`\n" f"{system_stats_line()}"))

        elapsed_s = time.monotonic() - job_started_at
        out_filename = f"mosh_{mode}_{attachment.filename}.mp4"
        try:
            await ctx.reply(content=f"Done! `{out_filename}`, job took {elapsed_s:.1f}s", file=discord.File(str(out_path), filename=out_filename),)
        except discord.HTTPException as upload_err:
            await safe_status_update(status_msg, f"done moshing, but Discord rejected the upload ({upload_err.status} " f"{upload_err.text}). File is {out_mb:.1f}MB and saved on the host machine at:\n" f"workfolder: `{job_dir}`\n" f"{system_stats_line()}",)

    except Exception as e:
        traceback.print_exc()
        await safe_status_update(status_msg, f"Unexpected error: `{e}`\n" f"workfolder: `{job_dir}`\n" f"{system_stats_line()}",)
    finally:
        cleanup_job_dir(job_dir)

async def safe_status_update(status_msg, content: str):
    try:
        await status_msg.edit(content=content)
    except discord.HTTPException:
        try:
            print(f"[moshbot] couldn't update status message, content was:\n{content}")
        except Exception:
            pass

async def probe_duration(path: Path) -> float | None:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)]

    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()
        return float(stdout.decode().strip())
    except Exception:
        return None

def apply_cpu_limit(pid: int, cpucores: int) -> str | None:
    if cpucores <= 0:
        return None
    try:
        proc = psutil.Process(pid)
        total_cores = psutil.cpu_count() or 1
        n = min(cpucores, total_cores)
        proc.cpu_affinity(list(range(n)))
        return None
    except (psutil.NoSuchProcess, psutil.AccessDenied, NotImplementedError) as e:
        return f"couldn't apply CPU limit ({e})"

async def run_datamosh(full_args: list[str], cwd: Path, timeout: int = 600, status_msg=None, mode: str = "", job_dir: Path = None, cpucores: int = 0,) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(*full_args, cwd=str(cwd), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,)

    affinity_error = apply_cpu_limit(proc.pid, cpucores)
    log_chunks = []
    if affinity_error:
        log_chunks.append(f"[moshbot] {affinity_error}\n")

    async def read_output():
        async for line in proc.stdout:
            log_chunks.append(line.decode(errors="replace"))

    async def heartbeat():
        if status_msg is None:
            return
        cpu_note = f"CPU limit: {cpucores} core(s)" if cpucores > 0 else "CPU limit: none"
        while True:
            await asyncio.sleep(MOSH_HEARTBEAT_INTERVAL_S)
            try:
                await status_msg.edit(content=(f"running `{mode}` mosh... this can take a bit.\n" f"workfolder: `{job_dir}`\n" f"{cpu_note}\n" f"{system_stats_line()}"))
            except discord.HTTPException:
                pass

    hb_task = asyncio.create_task(heartbeat())
    try:
        await asyncio.wait_for(asyncio.gather(read_output(), proc.wait()), timeout=timeout)
    except asyncio.TimeoutError:
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

def cleanup_job_dir(job_dir: Path):
    import shutil
    try:
        shutil.rmtree(job_dir, ignore_errors=True)
    except Exception:
        pass

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    traceback.print_exception(type(error), error, error.__traceback__)
    await ctx.reply(f"error: `{error}`")

def main():
    if not TOKEN:
        print("No discord token was set", file=sys.stderr)
        sys.exit(1)
    bot.run(TOKEN)

if __name__ == "__main__":
    main()