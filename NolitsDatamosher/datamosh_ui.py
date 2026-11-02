import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

# datamosh standalone ui


# ///////////////////////////////////////////////////////////////////////////////////////////


SCRIPT_DIR = Path(__file__).resolve().parent
DATAMOSH_SCRIPT = SCRIPT_DIR / "datamosh.py"

COLOR_OK = "#3adb3a"
COLOR_ERR = "#f84848"
COLOR_INFO = "#e7b431"

# ///////////////////////////////////////////////////////////////////////////////////////////
class DATAMOSH_UI(tk.Tk):
    def __init__(self):
        super().__init__()


        self.title("Datamosh")
        self.geometry("1340x666")
        self.minsize(560, 580)

        self.script_path = tk.StringVar(value=str(DATAMOSH_SCRIPT))
        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()

        self.mode = tk.StringVar(value="real")

        self.start = tk.IntVar(value=0)
        self.end = tk.IntVar(value=1_000_000_000)
        self.drop_all = tk.BooleanVar(value=False)
        self.keep_every = tk.IntVar(value=1)
        self.gop = tk.IntVar(value=30)
        self.qscale = tk.IntVar(value=3)
        self.keep_temp = tk.BooleanVar(value=False)
        self.add_audio = tk.BooleanVar(value=True)


        self.sim_start = tk.IntVar(value=0)
        self.sim_end = tk.IntVar(value=1_000_000_000)
        self.strength = tk.DoubleVar(value=0.85)
        self.threshold = tk.IntVar(value=18)
        self.sim_add_audio = tk.BooleanVar(value=True)


        self.stutter_chance = tk.DoubleVar(value=0.5)
        self.stutter_dups = tk.IntVar(value=5)
        self.stutter_gop = tk.IntVar(value=30)
        self.stutter_qscale = tk.IntVar(value=3)
        self.stutter_keep_temp = tk.BooleanVar(value=False)
        self.stutter_add_audio = tk.BooleanVar(value=True)
        self.stutter_speed_fix = tk.BooleanVar(value=True)
        self.stutter_audio_stutter = tk.BooleanVar(value=False)


        self.ricecake_chance = tk.DoubleVar(value=1.0)
        self.ricecake_dups = tk.IntVar(value=5)
        self.ricecake_gop = tk.IntVar(value=30)
        self.ricecake_qscale = tk.IntVar(value=3)
        self.ricecake_keep_temp = tk.BooleanVar(value=False)
        self.ricecake_add_audio = tk.BooleanVar(value=True)
        self.ricecake_speed_fix = tk.BooleanVar(value=True)

        self.ytp_iterations = tk.IntVar(value=6)
        self.ytp_chop_min = tk.StringVar(value="")
        self.ytp_chop_max = tk.StringVar(value="")
        self.ytp_freeze_chance = tk.DoubleVar(value=0.0)
        self.ytp_freeze_dur = tk.DoubleVar(value=0.4)
        self.ytp_keep_temp = tk.BooleanVar(value=False)
        self.ytp_add_audio = tk.BooleanVar(value=True)

        self.scatter_chop_min = tk.DoubleVar(value=0.3)
        self.scatter_chop_max = tk.DoubleVar(value=2.0)
        self.scatter_resample = tk.BooleanVar(value=False)
        self.scatter_count = tk.IntVar(value=30)
        self.scatter_keep_temp = tk.BooleanVar(value=False)
        self.scatter_add_audio = tk.BooleanVar(value=True)

        self.runmeme_music = tk.StringVar(value=str(SCRIPT_DIR / "stupidshit.mp3"))
        self.runmeme_chop_dur = tk.DoubleVar(value=0.5)
        self.runmeme_loop_reps = tk.IntVar(value=4)
        self.runmeme_jump = tk.DoubleVar(value=2.0)
        self.runmeme_beats = tk.IntVar(value=3)
        self.runmeme_keep_temp = tk.BooleanVar(value=False)

        self.rotting_intro_dur      = tk.DoubleVar(value=3.0)
        self.rotting_stutter_chance = tk.DoubleVar(value=0.6)
        self.rotting_stutter_dups   = tk.IntVar(value=6)
        self.rotting_gop            = tk.IntVar(value=30)
        self.rotting_mosh_qscale    = tk.IntVar(value=3)
        self.rotting_qscale         = tk.IntVar(value=18)
        self.rotting_distort_gain   = tk.DoubleVar(value=8.0)
        self.rotting_add_audio      = tk.BooleanVar(value=True)
        self.rotting_keep_temp      = tk.BooleanVar(value=False)

        self.lipsync_gif = tk.StringVar(value=str(SCRIPT_DIR / "assets" / "lips.gif"))
        self.lipsync_intro_dur = tk.DoubleVar(value=2.5)
        self.lipsync_probe_frames = tk.IntVar(value=60)
        self.lipsync_scale = tk.DoubleVar(value=1.0)
        self.lipsync_y_offset = tk.DoubleVar(value=0.0)
        self.lipsync_detect_every = tk.IntVar(value=3)
        self.lipsync_add_audio = tk.BooleanVar(value=True)

        self.proc = None
        self._build_ui()

# ///////////////////////////////////////////////////////////////////////////////////////////
    # BUILD

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        top = ttk.Frame(self)
        top.pack(fill="x", **pad)

        ttk.Label(top, text="datamosh.py:").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.script_path).grid(row=0, column=1, sticky="ew")

        ttk.Button(top, text="Browse", command=self._pick_script).grid(row=0, column=2)

        ttk.Label(top, text="Input video:").grid(row=1, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.input_path).grid(row=1, column=1, sticky="ew")
        ttk.Button(top, text="Browse", command=self._pick_input).grid(row=1, column=2)

        ttk.Label(top, text="Output:").grid(row=2, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.output_path).grid(row=2, column=1, sticky="ew")
        ttk.Button(top, text="Browse", command=self._pick_output).grid(row=2, column=2)

        top.columnconfigure(1, weight=1)

        mode_frame = ttk.LabelFrame(self, text="Mode")
        mode_frame.pack(fill="x", **pad)

        ttk.Radiobutton(mode_frame, text="I-frame removal", variable=self.mode, value="real", command=self._refresh_mode).pack(side="left", padx=8)
        ttk.Radiobutton(mode_frame, text="OpenCV bleed simulation", variable=self.mode, value="sim", command=self._refresh_mode).pack(side="left", padx=8)
        ttk.Radiobutton(mode_frame, text="Stutter / P-frame duplication", variable=self.mode, value="stutter", command=self._refresh_mode).pack(side="left", padx=8)
        ttk.Radiobutton(mode_frame, text="Ricecake / Raw P-frame duplication", variable=self.mode, value="ricecake", command=self._refresh_mode).pack(side="left", padx=8)
        ttk.Radiobutton(mode_frame, text="YTP / forward and reverse stutter loops", variable=self.mode, value="ytp", command=self._refresh_mode).pack(side="left", padx=8)
        ttk.Radiobutton(mode_frame, text="Scatter chop", variable=self.mode, value="scatter", command=self._refresh_mode).pack(side="left", padx=8)
        ttk.Radiobutton(mode_frame, text="run meme", variable=self.mode, value="runmeme", command=self._refresh_mode).pack(side="left", padx=8)
        ttk.Radiobutton(mode_frame, text="Rotting", variable=self.mode, value="rotting", command=self._refresh_mode).pack(side="left", padx=8)
        ttk.Radiobutton(mode_frame, text="obsolete lips GIF", variable=self.mode, value="lipsync", command=self._refresh_mode).pack(side="left", padx=8)

        self.options_container = ttk.Frame(self)
        self.options_container.pack(fill="x", padx=8, pady=0)

        self.real_frame = ttk.LabelFrame(self.options_container, text="I-frame removal mode options")
        self._build_real_options(self.real_frame)

        self.sim_frame = ttk.LabelFrame(self.options_container, text="OpenCV bleed simulation mode options")
        self._build_sim_options(self.sim_frame)

        self.stutter_frame = ttk.LabelFrame(self.options_container, text="P-frame duplication mode options")
        self._build_stutter_options(self.stutter_frame)

        self.ricecake_frame = ttk.LabelFrame(self.options_container, text="Ricecake mode options")
        self._build_ricecake_options(self.ricecake_frame)

        self.ytp_frame = ttk.LabelFrame(self.options_container, text="YTP mode options")
        self._build_ytp_options(self.ytp_frame)

        self.scatter_frame = ttk.LabelFrame(self.options_container, text="Scatter chop mode options")
        self._build_scatter_options(self.scatter_frame)

        self.runmeme_frame = ttk.LabelFrame(self.options_container, text="Run meme mode options")
        self._build_runmeme_options(self.runmeme_frame)

        self.rotting_frame = ttk.LabelFrame(self.options_container, text="Rotting mode options")
        self._build_rotting_options(self.rotting_frame)

        self.lipsync_frame = ttk.LabelFrame(self.options_container, text="Lipsync GIF mode options")
        self._build_lipsync_options(self.lipsync_frame)

        self._refresh_mode()

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", **pad)

        self.run_btn = ttk.Button(btn_frame, text="Render!", command=self._run)
        self.run_btn.pack(side="left")

        self.cancel_btn = ttk.Button(btn_frame, text="Cancel Render", command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=8)

        self.clear_btn = ttk.Button(btn_frame, text="Clear console log", command=self._clear_log)
        self.clear_btn.pack(side="left", padx=8)

        self.copy_btn = ttk.Button(btn_frame, text="Copy console log", command=self._copy_log)
        self.copy_btn.pack(side="left", padx=8)

        log_frame = ttk.LabelFrame(self, text="Log")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(log_frame, height=14, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, side="left")
        scrollbar = ttk.Scrollbar(log_frame, command=self.log.yview)
        scrollbar.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=scrollbar.set)

        self.log.tag_configure("ok", foreground=COLOR_OK)
        self.log.tag_configure("err", foreground=COLOR_ERR)
        self.log.tag_configure("info", foreground=COLOR_INFO)

        self._build_log_context_menu()

        self.log.bind("<Button-3>", self._show_log_context_menu)
        self.log.bind("<Button-2>", self._show_log_context_menu)
        self.log.bind("<Control-Button-1>", self._show_log_context_menu)
        self.log.bind("<Control-a>", self._select_all_log)
        self.log.bind("<Control-A>", self._select_all_log)
        self.log.bind("<Command-a>", self._select_all_log)
        self.log.bind("<Command-A>", self._select_all_log)


    # ///////////////////////////////////////////////////////////////////////////////////////////
    #                                       OPTIONS
    # ///////////////////////////////////////////////////////////////////////////////////////////

    # real mosh
    def _build_real_options(self, frame):
        pad = {"padx": 6, "pady": 3}
        ttk.Label(frame, text="Start frame:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.start, width=10).grid(row=0, column=1, **pad)

        ttk.Label(frame, text="End frame:").grid(row=0, column=2, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.end, width=12).grid(row=0, column=3, **pad)

        ttk.Checkbutton(frame, text="drop ALL keyframes (WILL override start and end !!!)", variable=self.drop_all).grid(row=1, column=0, columnspan=4, sticky="w", **pad)

        ttk.Label(frame, text="keep every x Frame:").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.keep_every, width=10).grid(row=2, column=1, **pad)

        ttk.Label(frame, text="Group of Pictures:").grid(row=2, column=2, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.gop, width=12).grid(row=2, column=3, **pad)

        ttk.Label(frame, text="output quality (1 = best 31 = worst):").grid(row=3, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.qscale, width=10).grid(row=3, column=1, **pad)

        ttk.Checkbutton(frame, text="dont delete raw .AVI output file", variable=self.keep_temp).grid(row=3, column=2, columnspan=2, sticky="w", **pad)

        ttk.Checkbutton(frame, text="Keep audio", variable=self.add_audio).grid(row=4, column=0, columnspan=4, sticky="w", **pad)

    # simulated mosh

    def _build_sim_options(self, frame):
        pad = {"padx": 6, "pady": 3}
        ttk.Label(frame, text="Start frame:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.sim_start, width=10).grid(row=0, column=1, **pad)

        ttk.Label(frame, text="End frame:").grid(row=0, column=2, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.sim_end, width=12).grid(row=0, column=3, **pad)
        
        ttk.Label(frame, text="strength:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Scale(frame, from_=0.0, to=1.0, variable=self.strength, orient="horizontal", length=180).grid(row=1, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(frame, textvariable=self.strength).grid(row=1, column=3, sticky="w", **pad)

        ttk.Label(frame, text="threshold:").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.threshold, width=10).grid(row=2, column=1, **pad)

        ttk.Checkbutton(frame, text="Keep audio", variable=self.sim_add_audio).grid(row=3, column=0, columnspan=4, sticky="w", **pad)


    # stutter mosh
    def _build_stutter_options(self, frame):
        pad = {"padx": 6, "pady": 3}
        ttk.Label(frame, text="Stutter Chance:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Scale(frame, from_=0.0, to=1.0, variable=self.stutter_chance, orient="horizontal", length=160).grid(row=0, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(frame, textvariable=self.stutter_chance).grid(row=0, column=3, sticky="w", **pad)

        ttk.Label(frame, text="Dupes per frame:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.stutter_dups, width=10).grid(row=1, column=1, **pad)

        ttk.Label(frame, text="Group of Pictures:").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.stutter_gop, width=10).grid(row=2, column=1, **pad)

        ttk.Label(frame, text="Output Quality (1 = best 31 = worst):").grid(row=2, column=2, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.stutter_qscale, width=10).grid(row=2, column=3, **pad)

        ttk.Checkbutton(frame, text="Dont delete raw .AVI output file", variable=self.stutter_keep_temp).grid(row=3, column=0, columnspan=2, sticky="w", **pad)
        ttk.Checkbutton(frame, text="Sync video with datamosh", variable=self.stutter_speed_fix).grid(row=3, column=2, columnspan=2, sticky="w", **pad)
        ttk.Checkbutton(frame, text="Keep audio", variable=self.stutter_add_audio).grid(row=4, column=0, columnspan=2, sticky="w", **pad)
        ttk.Checkbutton(frame, text="Stutter audio (Experimental)", variable=self.stutter_audio_stutter).grid(row=4, column=2, columnspan=2, sticky="w", **pad)

    # ricecake mosh
    def _build_ricecake_options(self, frame):
        pad = {"padx": 6, "pady": 3}
        ttk.Label(frame, text="Ricecake Chance:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Scale(frame, from_=0.0, to=1.0, variable=self.ricecake_chance, orient="horizontal", length=160).grid(row=0, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(frame, textvariable=self.ricecake_chance).grid(row=0, column=3, sticky="w", **pad)

        ttk.Label(frame, text="Dupes per frame:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.ricecake_dups, width=10).grid(row=1, column=1, **pad)

        ttk.Label(frame, text="Group of Pictures:").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.ricecake_gop, width=10).grid(row=2, column=1, **pad)

        ttk.Label(frame, text="Output Quality (1 = best 31 = worst):").grid(row=2, column=2, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.ricecake_qscale, width=10).grid(row=2, column=3, **pad)

        ttk.Checkbutton(frame, text="Dont delete raw .AVI output file", variable=self.ricecake_keep_temp).grid(row=3, column=0, columnspan=2, sticky="w", **pad)
        ttk.Checkbutton(frame, text="Sync video with datamosh", variable=self.ricecake_speed_fix).grid(row=3, column=2, columnspan=2, sticky="w", **pad)
        ttk.Checkbutton(frame, text="Keep audio", variable=self.ricecake_add_audio).grid(row=4, column=0, columnspan=2, sticky="w", **pad)

    # ytp mosh
    def _build_ytp_options(self, frame):
        pad = {"padx": 6, "pady": 3}
        ttk.Label(frame, text="Stutter-loop count:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.ytp_iterations, width=10).grid(row=0, column=1, **pad)

        ttk.Label(frame, text="Chop min (s):").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.ytp_chop_min, width=10).grid(row=1, column=1, **pad)

        ttk.Label(frame, text="Chop max (s):").grid(row=1, column=2, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.ytp_chop_max, width=10).grid(row=1, column=3, **pad)

        ttk.Label(frame, text="blank = random", foreground="#888").grid(row=2, column=0, columnspan=4, sticky="w", **pad)
        
        ttk.Label(frame, text="Freeze chance:").grid(row=3, column=0, sticky="w", **pad)
        ttk.Scale(frame, from_=0.0, to=1.0, variable=self.ytp_freeze_chance, orient="horizontal", length=160).grid(row=3, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(frame, textvariable=self.ytp_freeze_chance).grid(row=3, column=3, sticky="w", **pad)

        ttk.Label(frame, text="Freeze duration (s):").grid(row=4, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.ytp_freeze_dur, width=10).grid(row=4, column=1, **pad)

        ttk.Checkbutton(frame, text="Dont delete temp clip folder", variable=self.ytp_keep_temp).grid(row=5, column=0, columnspan=2, sticky="w", **pad)
        ttk.Checkbutton(frame, text="Keep audio", variable=self.ytp_add_audio).grid(row=6, column=0, columnspan=2, sticky="w", **pad)

    # scatter mosh
    def _build_scatter_options(self, frame):
        pad = {"padx": 6, "pady": 3}

        ttk.Label(frame, text="Chop min (s):").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.scatter_chop_min, width=10).grid(row=0, column=1, **pad)

        ttk.Label(frame, text="Chop max (s):").grid(row=0, column=2, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.scatter_chop_max, width=10).grid(row=0, column=3, **pad)

        ttk.Checkbutton(frame, text="Resample (pick random with replacement)", variable=self.scatter_resample, command=self._refresh_scatter_resample).grid(row=1, column=0, columnspan=3, sticky="w", **pad)
        self.scatter_count_label = ttk.Label(frame, text="Segment count:")
        self.scatter_count_label.grid(row=2, column=0, sticky="w", **pad)
        self.scatter_count_entry = ttk.Entry(frame, textvariable=self.scatter_count, width=10)
        self.scatter_count_entry.grid(row=2, column=1, **pad)

        ttk.Label(frame, text="(only used when resampling)", foreground="#888").grid(row=2, column=2, columnspan=2, sticky="w", **pad)
        ttk.Checkbutton(frame, text="Dont delete temp clip folder", variable=self.scatter_keep_temp).grid(row=3, column=0, columnspan=2, sticky="w", **pad)
        ttk.Checkbutton(frame, text="Keep audio", variable=self.scatter_add_audio).grid(row=4, column=0, columnspan=2, sticky="w", **pad)
        
        self._refresh_scatter_resample()    # update vis of count entrybased on resample checkbox

    # runmeme mosh
    def _build_runmeme_options(self, frame):
        pad = {"padx": 6, "pady": 3}

        ttk.Label(frame, text="Music file:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.runmeme_music, width=40).grid(row=0, column=1, columnspan=3, sticky="ew", **pad)

        ttk.Button(frame, text="Browse", command=self._pick_runmeme_music).grid(row=0, column=4, **pad)

        ttk.Label(frame, text="Chop dur (s):").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.runmeme_chop_dur, width=8).grid(row=1, column=1, **pad)

        ttk.Label(frame, text="Fwd+rev reps:").grid(row=1, column=2, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.runmeme_loop_reps, width=8).grid(row=1, column=3, **pad)
        
        ttk.Label(frame, text="Source jump (s):").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.runmeme_jump, width=8).grid(row=2, column=1, **pad)

        ttk.Label(frame, text="Beats:").grid(row=2, column=2, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.runmeme_beats, width=8).grid(row=2, column=3, **pad)

        ttk.Checkbutton(frame, text="Dont delete temp clip folder", variable=self.runmeme_keep_temp).grid(row=4, column=0, columnspan=2, sticky="w", **pad)

        frame.columnconfigure(1, weight=1)

    # rotting mosh
    def _build_rotting_options(self, frame):
        pad = {"padx": 6, "pady": 3}

        ttk.Label(frame, text="Clean intro (s):").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.rotting_intro_dur, width=8).grid(row=0, column=1, **pad)

        ttk.Label(frame, text="seconds before rot begins", foreground="#888").grid(row=0, column=2, columnspan=2, sticky="w", **pad)

        ttk.Label(frame, text="Stutter chance:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Scale(frame, from_=0.0, to=1.0, variable=self.rotting_stutter_chance, orient="horizontal", length=140).grid(row=1, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(frame, textvariable=self.rotting_stutter_chance).grid(row=1, column=3, sticky="w", **pad)

        ttk.Label(frame, text="Stutter dupes:").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.rotting_stutter_dups, width=8).grid(row=2, column=1, **pad)
        
        ttk.Label(frame, text="Group of Pictures:").grid(row=2, column=2, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.rotting_gop, width=8).grid(row=2, column=3, **pad)

        ttk.Label(frame, text="AVI qscale (1 = best):").grid(row=3, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.rotting_mosh_qscale, width=8).grid(row=3, column=1, **pad)
        
        ttk.Label(frame, text="Output CRF (0 = best):").grid(row=3, column=2, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.rotting_qscale, width=8).grid(row=3, column=3, **pad)

        ttk.Label(frame, text="Distort gain:").grid(row=4, column=0, sticky="w", **pad)
        ttk.Scale(frame, from_=1.0, to=20.0, variable=self.rotting_distort_gain, orient="horizontal", length=140).grid(row=4, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(frame, textvariable=self.rotting_distort_gain).grid(row=4, column=3, sticky="w", **pad)

        ttk.Checkbutton(frame, text="Keep audio", variable=self.rotting_add_audio).grid(row=5, column=0, columnspan=2, sticky="w", **pad)
        ttk.Checkbutton(frame, text="Dont delete temp folder", variable=self.rotting_keep_temp).grid(row=5, column=2, columnspan=2, sticky="w", **pad)
        frame.columnconfigure(1, weight=1)

    # lips mosh
    def _build_lipsync_options(self, frame):
        pad = {"padx": 6, "pady": 3}

        ttk.Label(frame, text="gif path:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.lipsync_gif, width=40).grid(row=0, column=1, columnspan=3, sticky="ew", **pad)

        ttk.Button(frame, text="Browse", command=self._pick_lipsync_gif).grid(row=0, column=4, **pad)

        ttk.Label(frame, text="intro:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.lipsync_intro_dur, width=8).grid(row=1, column=1, **pad)

        ttk.Label(frame, text="probe frames:").grid(row=1, column=2, sticky="w", **pad)
        ttk.Entry(frame, textvariable=self.lipsync_probe_frames, width=8).grid(row=1, column=3, **pad)

        ttk.Label(frame, text="frames scanned to verify face", foreground="#888").grid(row=2, column=0, columnspan=5, sticky="w", **pad)

        ttk.Label(frame, text="scale multiplier:").grid(row=3, column=0, sticky="w", **pad)
        ttk.Scale(frame, from_=0.1, to=5.0, variable=self.lipsync_scale, orient="horizontal", length=140).grid(row=3, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(frame, textvariable=self.lipsync_scale).grid(row=3, column=3, sticky="w", **pad)

        ttk.Label(frame, text="y offset (fraction):").grid(row=4, column=0, sticky="w", **pad)
        ttk.Scale(frame, from_=-1.0, to=1.0, variable=self.lipsync_y_offset, orient="horizontal", length=140).grid(row=4, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(frame, textvariable=self.lipsync_y_offset).grid(row=4, column=3, sticky="w", **pad)

        ttk.Label(frame, text="detect every x frames:").grid(row=5, column=0, sticky="w", **pad)

        ttk.Entry(frame, textvariable=self.lipsync_detect_every, width=8).grid(row=5, column=1, **pad)
        ttk.Label(frame, text="( 1 = every frame )", foreground="#888").grid(row=5, column=2, columnspan=2, sticky="w", **pad)

        ttk.Checkbutton(frame, text="Keep audio", variable=self.lipsync_add_audio).grid(row=6, column=0, columnspan=2, sticky="w", **pad)

        ttk.Label(frame, text="!! requirement: pip install face_recognition Pillow", foreground="#666").grid(row=7, column=0, columnspan=5, sticky="w", **pad)

        frame.columnconfigure(1, weight=1)

# ///////////////////////////////////////////////////////////////////////////////////////////
    # DEFs

    def _pick_lipsync_gif(self):
        f = filedialog.askopenfilename(title="select gif", filetypes=[("gif files", "*.gif"), ("All files", "*.*")])
        
        if f:
            self.lipsync_gif.set(f)

    def _pick_runmeme_music(self):
        f = filedialog.askopenfilename(title="select music file", filetypes=[("Audio", "*.mp3 *.wav *.aac *.ogg *.flac"), ("All files", "*.*")])

        if f:
            self.runmeme_music.set(f)

    def _refresh_scatter_resample(self):    # enable or disable the count entrybased on the resample checkbox
        state = "normal" if self.scatter_resample.get() else "disabled"
        self.scatter_count_label.configure(foreground="" if self.scatter_resample.get() else "#888")
        self.scatter_count_entry.configure(state=state)

    def _refresh_mode(self):    # show options for the selected mode and hide others
        for f in (self.real_frame, self.sim_frame, self.stutter_frame, self.ricecake_frame, self.ytp_frame, self.scatter_frame, self.runmeme_frame, self.rotting_frame, self.lipsync_frame):
            f.pack_forget()

        active = {"real": self.real_frame, "sim": self.sim_frame, "stutter": self.stutter_frame, "ricecake": self.ricecake_frame, "ytp": self.ytp_frame, "scatter": self.scatter_frame, "runmeme": self.runmeme_frame, "rotting": self.rotting_frame, "lipsync": self.lipsync_frame}[self.mode.get()]
        active.pack(fill="x", pady=4)


    def _pick_script(self): # selection datamosh.py
        f = filedialog.askopenfilename(title="select datamosh.py", filetypes=[("Python", "*.py")])
        if f: self.script_path.set(f)

    def _pick_input(self):
        f = filedialog.askopenfilename(title="select input video")

        if f:
            self.input_path.set(f)

            if not self.output_path.get():
                p = Path(f)
                self.output_path.set(str(p.with_name(p.stem + "_mosh.mp4")))

    def _pick_output(self):
        f = filedialog.asksaveasfilename(title="Save output as", defaultextension=".mp4", filetypes=[("MP4 video", "*.mp4"), ("AVI video", "*.avi")],)
        if f: self.output_path.set(f)

    def _log_line(self, text, tag="info"):      # console log for lines with colors
        if text.startswith("@@OK@@ "):
            tag = "ok"
            text = text[len("@@OK@@ "):]

        elif text.startswith("@@ERR@@ "):
            tag = "err"
            text = text[len("@@ERR@@ "):]

        elif text.startswith("@@INFO@@ "):
            tag = "info"
            text = text[len("@@INFO@@ "):]

        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")



    def _clear_log(self):   # clean log
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")



    def _build_log_context_menu(self):  # build right click menu for log text
        self.log_menu = tk.Menu(self, tearoff=0)
        self.log_menu.add_command(label="Copy", command=self._copy_log_selection)
        self.log_menu.add_command(label="Copy All", command=self._copy_log)
        self.log_menu.add_separator()
        self.log_menu.add_command(label="Select All", command=lambda: self._select_all_log(None))

    def _show_log_context_menu(self, event):
        self.log.focus_set()

        try:
            self.log_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.log_menu.grab_release()

        return "break"

    def _select_all_log(self, event=None):  # select all text in log text
        self.log.configure(state="normal")
        self.log.tag_remove("sel", "1.0", "end")
        self.log.tag_add("sel", "1.0", "end")
        self.log.configure(state="disabled")

        return "break"

    def _copy_log_selection(self):  # copy selected text in log text to clipboard
        try:
            text = self.log.get("sel.first", "sel.last")
        except tk.TclError:
            text = self.log.get("1.0", "end-1c")

        self._set_clipboard(text)

    def _copy_log(self):
        text = self.log.get("1.0", "end-1c")
        self._set_clipboard(text)

    def _set_clipboard(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()

    def _build_args(self):  # build cmd arguments for datamosh.py based on user i/o
        script = self.script_path.get().strip()
        inp = self.input_path.get().strip()
        out = self.output_path.get().strip()

        if not script or not Path(script).exists():
            raise ValueError("datamosh.py path is invalid.")
        if not inp:
            raise ValueError("input video is required.")
        if not out:
            raise ValueError("output path is required.")

        args = [sys.executable, script, self.mode.get(), inp, out]  # base args


        # mode specific ffmpeg arguments


        if self.mode.get() == "real":
            args += ["--start", str(self.start.get()), "--end", str(self.end.get())]

            if self.drop_all.get():
                args += ["--all"]


            args += ["--keep-every", str(self.keep_every.get()), "--gop", str(self.gop.get()), "--qscale", str(self.qscale.get()),]

            if self.keep_temp.get():
                args += ["--keep-temp"]

            if not self.add_audio.get():
                args += ["--no-audio"]


        elif self.mode.get() == "sim":
            args += ["--start", str(self.sim_start.get()), "--end", str(self.sim_end.get()), "--strength", str(round(self.strength.get(), 3)), "--threshold", str(self.threshold.get()),]
            
            if not self.sim_add_audio.get():
                args += ["--no-audio"]


        elif self.mode.get() == "stutter":
            args += ["--chance", str(round(self.stutter_chance.get(), 3)), "--dups", str(self.stutter_dups.get()), "--gop", str(self.stutter_gop.get()), "--qscale", str(self.stutter_qscale.get()),]
            
            if self.stutter_keep_temp.get():
                args += ["--keep-temp"]
            if not self.stutter_add_audio.get():
                args += ["--no-audio"]
            if not self.stutter_speed_fix.get():
                args += ["--no-speed-fix"]
            if self.stutter_audio_stutter.get():
                args += ["--audio-stutter"]

        
        elif self.mode.get() == "ricecake":
            args += ["--chance", str(round(self.ricecake_chance.get(), 3)), "--dups", str(self.ricecake_dups.get()), "--gop", str(self.ricecake_gop.get()), "--qscale", str(self.ricecake_qscale.get()),]
            
            if self.ricecake_keep_temp.get():
                args += ["--keep-temp"]
            if not self.ricecake_add_audio.get():
                args += ["--no-audio"]
            if not self.ricecake_speed_fix.get():
                args += ["--no-speed-fix"]



        elif self.mode.get() in ("ytp", "ytpstutter"):
            args += ["--iterations", str(self.ytp_iterations.get())]

            chop_min_str = self.ytp_chop_min.get().strip()
            chop_max_str = self.ytp_chop_max.get().strip()

            # fucked chop durations will fuck the video up, warn the user if theyre incorrect
            if chop_min_str and chop_max_str:
                try:
                    cmin = float(chop_min_str)
                    cmax = float(chop_max_str)

                    if cmin <= 0 or cmax <= 0:
                        raise ValueError("!! chop durations must be a positive value")
                    if cmin > cmax:
                        raise ValueError("!! chop min must be less or equal the chop max value")
                    
                    args += ["--chop-min", str(cmin), "--chop-max", str(cmax)]  # arguments for chop min and max

            # error if only one of the chop durations is set
                except ValueError as e:
                    raise ValueError(f"Chop duration error: {e}")
                
            elif chop_min_str or chop_max_str:
                raise ValueError("!! set both Chop min and Chop max values. Leave blank for random")


            # other ytp arguments
            if self.ytp_keep_temp.get():
                args += ["--keep-temp"]

            args += ["--freeze-chance", str(round(self.ytp_freeze_chance.get(), 3))]
            args += ["--freeze-dur", str(round(self.ytp_freeze_dur.get(), 3))]

            if not self.ytp_add_audio.get():
                args += ["--no-audio"]  # if ytp mode is selected and the user didnt set keep audio add --no-audio


        elif self.mode.get() == "scatter":
            args += ["--chop-min", str(round(self.scatter_chop_min.get(), 3))]
            args += ["--chop-max", str(round(self.scatter_chop_max.get(), 3))]

            if self.scatter_resample.get():
                args += ["--resample", "--count", str(self.scatter_count.get())]

            if self.scatter_keep_temp.get():
                args += ["--keep-temp"]

            if not self.scatter_add_audio.get():
                args += ["--no-audio"]


        elif self.mode.get() == "runmeme":
            music = self.runmeme_music.get().strip()

            if not music:
                raise ValueError("!! music file path is required for runmeme mode")
            
            args += ["--music", music]
            args += ["--chop-dur", str(round(self.runmeme_chop_dur.get(), 3))]
            args += ["--loop-reps", str(self.runmeme_loop_reps.get())]
            args += ["--jump", str(round(self.runmeme_jump.get(), 3))]
            args += ["--beats", str(self.runmeme_beats.get())]

            if self.runmeme_keep_temp.get():
                args += ["--keep-temp"]


        elif self.mode.get() == "lipsync":
            gif = self.lipsync_gif.get().strip()

            if not gif:
                raise ValueError("!! GIF path is required for Lipsync mode.")
            
            args += ["--gif", gif]
            args += ["--intro-dur", str(round(self.lipsync_intro_dur.get(), 3))]
            args += ["--probe-frames", str(self.lipsync_probe_frames.get())]
            args += ["--scale", str(round(self.lipsync_scale.get(), 3))]
            args += ["--y-offset", str(round(self.lipsync_y_offset.get(), 3))]
            args += ["--detect-every", str(self.lipsync_detect_every.get())]

            if not self.lipsync_add_audio.get():
                args += ["--no-audio"]


        elif self.mode.get() == "rotting":
            args += ["--intro-dur", str(round(self.rotting_intro_dur.get(), 3))]
            args += ["--stutter-chance", str(round(self.rotting_stutter_chance.get(), 3))]
            args += ["--stutter-dups", str(self.rotting_stutter_dups.get())]
            args += ["--gop", str(self.rotting_gop.get())]
            args += ["--mosh-qscale", str(self.rotting_mosh_qscale.get())]
            args += ["--qscale", str(self.rotting_qscale.get())]
            args += ["--distort-gain", str(round(self.rotting_distort_gain.get(), 2))]

            if not self.rotting_add_audio.get():
                args += ["--no-audio"]

            if self.rotting_keep_temp.get():
                args += ["--keep-temp"]

        return args

# ///////////////////////////////////////////////////////////////////////////////////////////
#                                    RUN
# ///////////////////////////////////////////////////////////////////////////////////////////

    def _run(self):
        try: args = self._build_args()

        except ValueError as e:
            messagebox.showerror("Invalid input", str(e))
            return

        self._log_line("$ " + " ".join(args), "info")
        self.run_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")

        def worker():   # runs datamosh py as separate thread to avoid gui crashing
            try:
                self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, cwd=str(Path(self.script_path.get()).resolve().parent),)     # subprocess and capture stdout and stderr
                for line in self.proc.stdout: self.after(0, self._log_line, line.rstrip())

                
                code = self.proc.wait() # wait for Finland
                self.after(0, self._on_done, code)

            except Exception as e:
                self.after(0, self._log_line, f"ERROR: {e}", "err")
                self.after(0, self._on_done, -1)

        threading.Thread(target=worker, daemon=True).start()


    # func on done
    def _on_done(self, code):
        self._log_line(f"FINISHED! /// exit code {code}", "ok" if code == 0 else "err")
        self.run_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.proc = None

    # oncancel
    def _cancel(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self._log_line("RENDER CANCELLED BY USER !!!", "err")

if __name__ == "__main__":
    if not DATAMOSH_SCRIPT.exists():
        print(f"{DATAMOSH_SCRIPT} not found. double check your cfg and check references to datamosh.py settings, it could be empty.", file=sys.stderr,)
        sys.exit(1)
        
    app = DATAMOSH_UI()
    app.mainloop()