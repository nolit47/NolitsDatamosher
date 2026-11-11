Advanced standalone toolset for datamoshing including a toolset for discord bot hosting.


## Repository directory

| File | |
| --- | --- |
| bottest.py | the discord bot |
| datamosh.py | modes loader |
| glitchcut.py | standalone script for the `glitchcut` mode. |
| datamosh_ui.py | desktop UI for `datamosh.py`. |
| modes/ | contains .py files with various datamosh modes |
| .env | bot configuration file |

## Requirements

- [python 3.10 or above](https://www.python.org/downloads/release/python-3100/)
- [`ffmpeg` and `ffprobe`.](https://ffmpeg.org/download.html#build-windows) Make sure they are installed into PATH
- py packages: `discord.py`, `psutil`, `python-dotenv`, `yt-dlp`. Please note: The bot always autoinstalls the missing packages when you launch it.

## Bot Setup

1. [Create a bot](https://discord.com/developers/applications) and get its token.
2. Open .env file and then set:
    ```
   DISCORD_TOKEN=
   ```
   to your bot token
3. Invite the bot to your server with permission to read messages, send messages and attach files
5. Run it:
   ```
   python bottest.py
   ```

## Bot Usage

The prefix is `!` by default (Controlled by `MOSH_PREFIX` in `.env`).

```
!mosh <mode> [options]
!mosh help
!mosh help <mode>
```


The video job priority is being selected in this order:

1. a link typed in the command. for example: `!mosh sim https://x.com/user/status/123`
2. a video attached to your message
3. the message you replied to (its attachment, or a link in its text)
4. the most recent video posted in the channel (searches the last 25 messages by default)

Supported links: YouTube (`youtube.com`, `youtu.be`) and Twitter (`twitter.com`, `x.com`) also supporting embed-fix domains such as `fxtwitter`, `vxtwitter` and `fixupx`

**Options** are `name=value`.
Flags are just the name:

```
!mosh stutter chance=0.7 dups=8 noaudio
```

Add `cpucores=VALUE` to any command to pin that job to the first X CPU cores.

### Datamosh Modes

| Mode | Description |
| --- | --- |
| `real` | I-frame removal |
| `sim` | OpenCV framebleed simulation |
| `stutter` | Randomly duplicate P-frames |
| `ricecake` | Naive raw byte-split P-frame duplication |
| `ytp` | Random forward and reverse stutter loops |
| `ytpstutter` | Splices with P-frame stutter on looped segments |
| `scatter` | Chop the video into random segments and shuffle them |
| `runmeme` | That one running meme |
| `rotting` | Rot with stutter and stretched glitchy audio |
| `glitchcut` | Clean intro then the video breaks apart with stutters and fuzzed audio then cuts to green |
| `lipsync` | Overlays a mouth gif |

`!mosh help <mode>` for the options and defaults of a specific mode

### glitchcut

`glitchcut` prints the seed it used and the bot includes it in the reply so you can repeat a mosh:

```
!mosh glitchcut seed=676767 count=3
```

| option | default |  |
| --- | --- | --- |
| `start` | random | seconds of clean video before the datamosh |
| `stutter` | random 1-4 | length of each stutter in seconds |
| `count` | 1 | number of stutters (max 20). only the last one ends in green |
| `seed` | random | reuse a seed to get the same glitch |
| `qscale` | 20 | output quality 0-51. higher is smaller and worse |

## Configuration

Everything is set in `.env`. All values present in the config are optional except the bot token.

| variable | default value | description |
| --- | --- | --- |
| `DISCORD_TOKEN` | none | bot token |
| `MOSH_PREFIX` | `!` | bot command prefix |
| `MOSH_ALLOWED_CHANNELS` | all | channel ids where the bot is allowed to talk. ChannelID only. |
| `MOSH_BLOCKED_USERS` | none | user IDs the bot ignores |
| `MOSH_USER_COOLDOWN_S` | `0` | seconds between jobs per user. 0 is off |
| `MOSH_MAX_CONCURRENT_JOBS` | `2` | max jobs allowed running at once. the rest wait in a queue |
| `MOSH_HISTORY_SEARCH_LIMIT` | `25` | recent messages searched for a video. 0 is off |
| `MOSH_MAX_INPUT_MB` | `100` | biggest accepted input |
| `MOSH_MAX_DURATION_S` | `120` | longest accepted input |
| `MOSH_UPLOAD_LIMIT_MB` | `24` | results bigger than this arent uploaded |
| `MOSH_JOB_TIMEOUT_S` | `600` | mosh script running longer than this is killed |
| `MOSH_VIDEO_EXTS` | `.mp4,.mov,.avi,.mkv,.webm,.m4v` | accepted input formats |
| `MOSH_CPU_CORES` | `0` | pin mosh scripts to the first X cores. 0 = no limit |
| `MOSH_HEARTBEAT_INTERVAL_S` | `10` | how often the status message refreshes |
| `MOSH_LINKS_ENABLED` | `1` | 1 to accept both attachments and links. 0 to accept attachments only |
| `MOSH_DOWNLOAD_TIMEOUT_S` | `180` | link download timeout |
| `MOSH_MAX_DOWNLOAD_HEIGHT` | `720` | biggest video height to download |
| `MOSH_YTDLP_COOKIES` | none | path to `cookies.txt`. useful when yt blocks your host ip |
| `MOSH_YTDLP_EXTRA_ARGS` | none | raw extra yt-dlp arguments. example: `--proxy socks5://127.0.0.1:1111` |
| `MOSH_UPDATE_YTDLP` | `0` | 1 to update yt-dlp on every start |
| `MOSH_WORKDIR` | system temp `/moshbot_jobs` | where job folders are created. default is %temp% |
| `MOSH_KEEP_JOBS` | `never` | `never`, `failed` or `always`: what happens to a job folder when the job ends |
| `MOSH_SHOW_WORKDIR` | `1` | show the job folder path in status messages |
| `MOSH_SHOW_STATS` | `1` | show CPU and RAM in status messages |


## How the Bot works

1. Firstly it finds the video using video job priority mentioned before and checks the size and downloads it.
2. Then it checks the duration against `MOSH_MAX_DURATION_S` using `ffprobe`.
3. It runs `datamosh.py` as a subprocess in a temp job folder
4. After doing the job, it uploads the result, then deletes the job folder, depending on `MOSH_KEEP_JOBS` flag in the config

For links, `yt-dlp` skips videos over the duration limit before downloading anything.

## Terminal usage

How to use datamosher without hosting the bot and using your terminal:
```
python datamosh.py <mode> <input> <output> [options]
python datamosh.py stutter in.mp4 out.mp4 --chance 0.7 --dups 8

python glitchcut.py in.mp4 out.mp4 --count 3 --seed 123456
```

!! Note the options are `--flags` here, and `name=value` in the bot.

## UI Usage

```
python datamosh_ui.py
```

tkinter ui for `datamosh.py`. It needs the `modes/` folder and `datamosh.py` next to it to properly work.


## Troubleshooting

- **The bot is online but ignores commands.** Turn on the Message Content Intent in the devportal and check `MOSH_ALLOWED_CHANNELS` and `MOSH_BLOCKED_USERS` flags, also make sure the prefix matches.
- **A link fails to download.** Run `pip install -U yt-dlp` or set `MOSH_UPDATE_YTDLP=1`. Youtube tends to breaks yt-dlp sometimes. If Youtube blocks your server IP, set `MOSH_YTDLP_COOKIES`
- **"result is over the upload limit".** Raise `qscale` in the mode options, shorten the clip, or set `MOSH_UPLOAD_LIMIT_MB` to match your server's real limit.
- **A job is killed.** It hit `MOSH_JOB_TIMEOUT_S`. You should use a shorter clip or raise the timeout.
- **"ffmpeg not found".** Install ffmpeg and make sure it's on the PATH of the account running the bot.
- **Installing packages fails on startup.** Create a virtualenv and run the bot from it.

