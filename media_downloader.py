import ctypes
import io
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from ctypes import wintypes
from fractions import Fraction
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlsplit
from urllib.request import urlopen
from uuid import uuid4

from PIL import Image, ImageOps, ImageTk


NAME = "Media Downloader Malaysia"
ORIGINAL_FPS = "Original"
BG, PANEL, BORDER = "#101012", "#19191c", "#38383e"
WHITE, GRAY, RED = "#f7f7f8", "#bcbcc4", "#db1930"
CHOICES = {
    "resolution": ("480p", "720p", "1080p", "4K", "8K"),
    "fps": (ORIGINAL_FPS, "24 fps", "30 fps", "60 fps", "120 fps"),
    "ratio": ("FULL", "1:1", "3:4", "9:16", "16:9", "4:3"),
    "format": ("MP4", "MKV", "WEBM"),
    "language": ("Tiada", "English", "Melayu", "Chinese"),
    "color": ("Tiada", "Putih", "Kuning", "Merah"),
}
LABELS = {
    "resolution": "Resolusi", "fps": "Kadar bingkai", "ratio": "Bingkai video",
    "format": "Format", "language": "Sari kata", "color": "Warna teks",
}
RESOLUTION = dict(zip(CHOICES["resolution"], (480, 720, 1080, 2160, 4320)))
COLORS = {"Putih": ("#ffffff", "FFFFFF"), "Kuning": ("#ffe145", "45E1FF"),
          "Merah": ("#ff303c", "3C30FF")}
LANGUAGES = {"English": {"en", "eng"}, "Melayu": {"ms", "msa", "may"},
             "Chinese": {"zh", "zho", "chi", "cmn", "yue"}}
SETTINGS = {
    "folder": str(Path.home() / "Downloads" / NAME), "parallel": 2,
    "resolution": "1080p", "fps": "30 fps", "ratio": "FULL", "format": "MP4",
    "language": "Tiada", "color": "Tiada",
}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
KERNEL = ctypes.WinDLL("kernel32", use_last_error=True)
KERNEL.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
KERNEL.CreateJobObjectW.restype = wintypes.HANDLE
KERNEL.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
KERNEL.AssignProcessToJobObject.restype = wintypes.BOOL
KERNEL.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
KERNEL.TerminateJobObject.restype = wintypes.BOOL
KERNEL.CloseHandle.argtypes = (wintypes.HANDLE,)
KERNEL.CloseHandle.restype = wintypes.BOOL


def tool(name):
    override = os.environ.get("MDM_" + name.replace("-", "_").upper())
    bundled = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "tools" / (name + ".exe")
    found = override or (str(bundled) if bundled.is_file() else shutil.which(name))
    if not found:
        raise RuntimeError(f"Komponen {name} tidak dijumpai.")
    return found


def http_link(value):
    try:
        parts = urlsplit(value)
        return (parts.scheme in ("http", "https") and bool(parts.hostname)
                and not parts.username and not parts.password
                and not any(char.isspace() or ord(char) < 32 for char in value))
    except ValueError:
        return False


def engine():
    args = [tool("yt-dlp"), "--ignore-config", "--no-playlist", "--no-colors",
            "--socket-timeout", "15", "--retries", "2", "--ffmpeg-location", tool("ffmpeg")]
    try:
        node = tool("node")
    except RuntimeError:
        pass
    else:
        args.extend(("--js-runtimes", f"node:{node}"))
    return args


def capture(args, timeout):
    result = subprocess.run(args, capture_output=True, encoding="utf-8",
                            errors="replace", creationflags=NO_WINDOW, timeout=timeout)
    if result.returncode:
        lines = result.stderr.strip().splitlines()
        raise RuntimeError(lines[-1] if lines else "Proses gagal.")
    return result.stdout


def direct_video(url):
    return Path(urlsplit(url).path).suffix.lower() in (".mp4", ".webm", ".mkv", ".mov", ".m4v")


def inspect_media(url):
    info = json.loads(capture(engine() + ["--dump-single-json", "--", url], 120))
    formats = [item for item in info.get("formats", []) if item.get("vcodec") != "none"
               and not item.get("has_drm") and item.get("format_id")]
    if not formats or info.get("is_live") or info.get("_type") in ("playlist", "multi_video"):
        raise ValueError("Pautan ini tidak menyediakan satu video yang boleh dimuat turun.")
    if not any(item.get("width") and item.get("height") and item.get("fps") for item in formats):
        if direct_video(url):
            data = json.loads(capture([
                tool("ffprobe"), "-v", "error", "-rw_timeout", "15000000",
                "-protocol_whitelist", "http,https,tcp,tls,crypto", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,avg_frame_rate", "-of", "json", url,
            ], 30))
            streams = data.get("streams") or []
            if streams:
                video = streams[0]
                rate = video.get("avg_frame_rate")
                formats[-1].update(width=video.get("width"), height=video.get("height"),
                                   fps=float(Fraction(rate)) if rate not in (None, "0/0") else None)
    info["formats"] = formats
    return info


def preview_media(info, url):
    thumbnail = info.get("thumbnail")
    if thumbnail and http_link(thumbnail):
        with urlopen(thumbnail, timeout=8) as response:
            content = response.read(8_000_001)
    elif direct_video(url):
        result = subprocess.run([
            tool("ffmpeg"), "-nostdin", "-v", "error", "-rw_timeout", "10000000",
            "-protocol_whitelist", "http,https,tcp,tls,crypto", "-i", url, "-frames:v", "1",
            "-vf", "scale=720:-2", "-c:v", "png", "-f", "image2pipe", "-",
        ], capture_output=True, creationflags=NO_WINDOW, timeout=14)
        content = result.stdout if result.returncode == 0 else b""
    else:
        return None
    if content and len(content) <= 8_000_000:
        with Image.open(io.BytesIO(content)) as image:
            image.thumbnail((1200, 900))
            return image.convert("RGB")
    return None


def options_for(info, resolution=None, fps=None):
    min_size = RESOLUTION.get(resolution, 0)
    min_fps = int(fps.split()[0]) if fps and fps != ORIGINAL_FPS else 0
    candidates = []
    for item in info["formats"]:
        width, height, rate = (item.get(key) or 0 for key in ("width", "height", "fps"))
        short_edge = min(width, height)
        if short_edge >= min_size and rate + 0.5 >= min_fps:
            candidates.append(item)
    return candidates


def subtitle_track(info, language):
    if language == "Tiada":
        return None
    for key in ("subtitles", "automatic_captions"):
        tracks = info.get(key) or {}
        for code in tracks:
            if code.lower().replace("_", "-").split("-")[0] in LANGUAGES[language]:
                return key, code
    return None


def read_json(path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    pending.replace(path)


def probe_file(path):
    data = json.loads(capture([
        tool("ffprobe"), "-v", "error", "-protocol_whitelist", "file,pipe",
        "-show_streams", "-show_format", "-of", "json", str(path),
    ], 30))
    video = next((item for item in data.get("streams", []) if item["codec_type"] == "video"), None)
    if not video:
        raise ValueError("Tiada trek video dalam fail.")
    return data, video


def render_args(source, options, folder, subtitle=None):
    data, video = probe_file(source)
    width, height = video["width"], video["height"]
    if any(int(item.get("rotation", 0)) % 180 for item in video.get("side_data_list", [])):
        width, height = height, width
    sar = video.get("sample_aspect_ratio", "1:1")
    filters = []
    if sar not in ("1:1", "N/A", "0:1"):
        width = round(width * Fraction(sar.replace(":", "/")))
        filters.append(f"scale={width}:{height}")
    if options["ratio"] != "FULL":
        horizontal, vertical = map(int, options["ratio"].split(":"))
        scale = min(width / horizontal, height / vertical)
        even_scale = int(scale) // 2 * 2
        width, height = horizontal * even_scale, vertical * even_scale
        filters.append(f"crop={width}:{height}")
    target = RESOLUTION[options["resolution"]]
    size = target / min(width, height)
    final_width, final_height = (max(2, round(side * size / 2) * 2) for side in (width, height))
    filters.extend((f"scale={final_width}:{final_height}:flags=lanczos", "setsar=1"))
    timing = []
    if options["fps"] == ORIGINAL_FPS:
        timing = ["-fps_mode:v", "passthrough", "-enc_time_base:v", "filter"]
    else:
        rate = int(options["fps"].split()[0])
        filters.append(f"fps={rate}")
    if subtitle:
        style = COLORS[options["color"]][1]
        filters.append("subtitles=captions.srt:charenc=UTF-8:force_style="
                       f"'FontName=Segoe UI,PrimaryColour=&H00{style},OutlineColour=&H00000000,Outline=2'")
    fmt = options["format"]
    if fmt == "WEBM":
        codecs = ["-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0", "-deadline", "good",
                  "-cpu-used", "4", "-row-mt", "1", "-c:a", "libopus"]
    else:
        codecs = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac"]
    if max(final_width, final_height) > 4096 and fmt != "WEBM":
        codecs[:3] = ["-c:v", "libx265", "-preset"]
        codecs[3] = "fast"
        if fmt == "MP4":
            codecs.extend(("-tag:v", "hvc1"))
    if fmt == "MP4":
        codecs.extend(("-movflags", "+faststart"))
    output = folder / f"output.{fmt.lower()}"
    args = [tool("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-protocol_whitelist", "file,pipe", "-i", str(source), "-map", "0:v:0",
            "-map", "0:a:0?", "-vf", ",".join(filters), "-pix_fmt", "yuv420p",
            *timing, *codecs, "-progress", "pipe:1", str(output)]
    return args, output, float(data.get("format", {}).get("duration") or 0)


def filename(title):
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", title).strip(" .")[:115].rstrip(" .")
    if not safe or re.fullmatch(r"(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])", safe.split(".")[0], re.I):
        safe = "Video " + safe
    return safe.strip()


def finish_file(source, folder, name):
    for index in range(1, 10000):
        suffix = "" if index == 1 else f" ({index})"
        target = folder / (name + suffix + source.suffix)
        try:
            source.rename(target)
            return target
        except FileExistsError:
            continue
    raise RuntimeError("Terlalu banyak fail dengan nama yang sama.")


class Job:
    def __init__(self, url, info, options, folder):
        self.url, self.info, self.options = url, info, options
        self.title = info.get("title") or "Video"
        self.folder = Path(folder).resolve()
        self.scratch = self.folder / (".mdm-" + uuid4().hex)
        self.state, self.progress = "Menunggu", 0
        self.stop = threading.Event()
        self.process_lock = threading.Lock()
        self.process = None
        self.process_group = None
        self.intent = None

    def interrupt(self, intent):
        self.intent = intent
        self.stop.set()
        with self.process_lock:
            if self.process and self.process.poll() is None:
                if self.process_group and KERNEL.TerminateJobObject(self.process_group, 1):
                    return
                self.process.kill()

    def run_process(self, args, read):
        with self.process_lock:
            if self.stop.is_set():
                raise InterruptedError()
            self.process = subprocess.Popen(
                args, cwd=self.scratch, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW,
            )
            group = KERNEL.CreateJobObjectW(None, None)
            if group and KERNEL.AssignProcessToJobObject(group, int(self.process._handle)):
                self.process_group = group
            elif group:
                KERNEL.CloseHandle(group)
        recent = []
        try:
            with self.process.stdout:
                for line in self.process.stdout:
                    line = line.strip()
                    if line:
                        recent = (recent + [line])[-6:]
                        read(line)
            code = self.process.wait()
        finally:
            with self.process_lock:
                if self.process_group:
                    KERNEL.CloseHandle(self.process_group)
                    self.process_group = None
                self.process = None
        if self.stop.is_set():
            raise InterruptedError()
        if code:
            errors = [line for line in recent if not line.startswith(("MDM_", "out_time"))]
            raise RuntimeError(errors[-1] if errors else "Proses gagal.")

    def execute(self, update):
        self.scratch.mkdir(parents=True, exist_ok=True)
        options = self.options
        choices = options_for(self.info, options["resolution"], options["fps"])
        if not choices:
            raise ValueError("Resolusi dan kadar bingkai ini tidak tersedia untuk video tersebut.")
        fps_preference = -1 if options["fps"] == ORIGINAL_FPS else 1
        selected = min(choices, key=lambda item: (
            min(item["width"], item["height"]), fps_preference * (item.get("fps") or 0),
            -(item.get("tbr") or 0),
        ))
        format_id = selected["format_id"]
        if not re.fullmatch(r"[A-Za-z0-9_.:-]+", format_id):
            raise ValueError("Format video sumber tidak disokong.")
        if selected.get("acodec") in (None, "none"):
            format_id = f"{format_id}+bestaudio/{format_id}"
        track = subtitle_track(self.info, options["language"])
        if options["language"] != "Tiada" and not track:
            raise ValueError("Sari kata bahasa ini tidak tersedia pada sumber.")
        args = engine() + [
            "--newline", "--progress", "--encoding", "utf-8",
            "--progress-template", "download:MDM_PROGRESS|%(progress._percent_str)s",
            "--print", "after_move:MDM_FILE|%(filepath)s", "--merge-output-format", "mkv",
            "--no-embed-subs", "-f", format_id, "-o", str(self.scratch / "source.%(ext)s"),
        ]
        if track:
            key, code = track
            language_pattern = re.escape(code)
            args.extend(("--write-auto-subs" if key == "automatic_captions" else "--write-subs",
                         "--sub-langs", language_pattern, "--sub-format", "srt/vtt/best",
                         "--convert-subs", "srt", "-o", "subtitle:captions.%(ext)s"))
        paths = []

        def downloaded(line):
            if line.startswith("MDM_PROGRESS|"):
                percent = re.search(r"([\d.]+)%", line)
                if percent:
                    update("Memuat turun", min(69, int(float(percent[1]) * 0.69)))
            if line.startswith("MDM_FILE|"):
                paths.append(Path(line.split("|", 1)[1]))

        self.run_process(args + ["--", self.url], downloaded)
        if not paths or paths[-1].parent.resolve() != self.scratch or not paths[-1].is_file():
            raise RuntimeError("Fail video tidak ditemui selepas muat turun.")
        caption = next(self.scratch.glob("captions.*.srt"), None) if track else None
        if track and caption is None:
            raise RuntimeError("Sari kata dipilih tetapi tidak dapat dimuat turun.")
        if caption and caption.name != "captions.srt":
            caption.replace(self.scratch / "captions.srt")
        update("Memproses video", 70)
        cmd, output, duration = render_args(paths[-1], options, self.scratch, caption is not None)

        def converted(line):
            if duration and line.startswith("out_time_us=") and line[12:].isdigit():
                fraction = int(line[12:]) / 1_000_000 / duration
                update("Memproses video", min(99, 70 + int(29 * fraction)))

        self.run_process(cmd, converted)
        if self.stop.is_set():
            raise InterruptedError()
        return finish_file(output, self.folder, filename(self.title))


def frame(parent, bg=BG, border=False):
    return tk.Frame(parent, bg=bg, highlightthickness=int(border), highlightbackground=BORDER)


def label(parent, text, size=11, bold=False, fg=WHITE, **kw):
    return tk.Label(parent, text=text, font=("Segoe UI", size, "bold" if bold else "normal"),
                    bg=parent["bg"], fg=fg, anchor="w", **kw)


def button(parent, text, command, active=False, **kw):
    return tk.Button(
        parent, text=text, command=command, bg=RED if active else PANEL, fg=WHITE,
        activebackground="#a91122" if active else "#303037", activeforeground=WHITE,
        disabledforeground="#84848e", borderwidth=0, relief="flat",
        highlightthickness=1, highlightbackground=RED if active else BORDER,
        highlightcolor="#ff8290", font=("Segoe UI", 10, "bold"), cursor="hand2",
        padx=10, pady=5, **kw,
    )


class App:
    def __init__(self, root, data_folder):
        self.root, self.data_folder = root, data_folder
        self.settings_path = data_folder / "settings.json"
        self.history_path = data_folder / "history.json"
        saved = read_json(self.settings_path, {})
        self.settings = SETTINGS | (saved if isinstance(saved, dict) else {})
        for key, values in CHOICES.items():
            if self.settings[key] not in values:
                self.settings[key] = SETTINGS[key]
        if self.settings["parallel"] not in (1, 2, 3, 4):
            self.settings["parallel"] = SETTINGS["parallel"]
        self.history = read_json(self.history_path, [])
        if not isinstance(self.history, list):
            self.history = []
        self.settings["folder"] = str(self.settings["folder"] or SETTINGS["folder"])
        self.options = {key: self.settings[key] for key in CHOICES}
        if "Tiada" in (self.options["language"], self.options["color"]):
            self.options.update(language="Tiada", color="Tiada")
        self.events = queue.Queue()
        self.info = self.image = None
        self.checked_url = None
        self.checking = False
        self.retry = None
        self.closing = False
        self.jobs = []
        self.tab = "Muat Turun"
        self.completed = 0

        root.title(NAME)
        root.configure(bg=BG)
        root.geometry("1180x760")
        root.minsize(1030, 690)
        icon = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "icon.ico"
        if icon.is_file():
            root.iconbitmap(str(icon))
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.link = tk.StringVar()
        self.status = tk.StringVar(value="Tampal pautan video untuk mula.")
        self.filter_text = tk.StringVar()
        self.filter_status = tk.StringVar(value="Semua status")
        self.link.trace_add("write", self.link_changed)
        self.filter_text.trace_add("write", self.filter_changed)
        self.filter_status.trace_add("write", self.filter_changed)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("MDM.Horizontal.TProgressbar", background=RED, troughcolor=BORDER,
                        bordercolor=PANEL, lightcolor=RED, darkcolor=RED)
        style.configure("MDM.TCombobox", fieldbackground=PANEL, background=PANEL,
                        foreground=WHITE, arrowcolor=WHITE, bordercolor=BORDER, padding=6)
        style.map("MDM.TCombobox", fieldbackground=[("readonly", PANEL)],
                  foreground=[("readonly", WHITE)], selectbackground=[("readonly", PANEL)],
                  selectforeground=[("readonly", WHITE)])
        root.option_add("*TCombobox*Listbox.background", PANEL)
        root.option_add("*TCombobox*Listbox.foreground", WHITE)
        root.option_add("*TCombobox*Listbox.selectBackground", RED)
        style.configure("MDM.Treeview", background=PANEL, fieldbackground=PANEL,
                        foreground=WHITE, bordercolor=BORDER, rowheight=38, font=("Segoe UI", 10))
        style.configure("MDM.Treeview.Heading", background="#252529", foreground=WHITE,
                        font=("Segoe UI", 10, "bold"))
        style.map("MDM.Treeview", background=[("selected", "#5f1823")])
        self.events_id = root.after(80, self.poll)
        self.show("Muat Turun")

    def show(self, tab):
        self.tab = tab
        for child in self.root.winfo_children():
            child.destroy()
        top = frame(self.root, PANEL)
        top.pack(fill="x")
        label(top, "↓", 23, True, "#fa3448").pack(side="left", padx=(22, 8))
        label(top, NAME, 15, True).pack(side="left", padx=(0, 24), pady=10)
        for page in ("Muat Turun", "Sejarah", "Tetapan"):
            button(top, page, lambda page=page: self.show(page), page == tab).pack(side="left", padx=4)
        self.content = frame(self.root)
        self.content.pack(fill="both", expand=True, padx=20, pady=13)
        if tab == "Muat Turun":
            self.download_page()
        elif tab == "Sejarah":
            self.history_page()
        else:
            self.settings_page()

    def entry(self, parent, variable):
        return tk.Entry(parent, textvariable=variable, font=("Segoe UI", 11), fg=WHITE, bg=PANEL,
                        insertbackground=WHITE, selectbackground=RED, relief="flat",
                        highlightthickness=1, highlightbackground=BORDER, highlightcolor=RED)

    def combo(self, parent, variable, values):
        return ttk.Combobox(parent, textvariable=variable, values=values, state="readonly",
                            style="MDM.TCombobox", font=("Segoe UI", 10))

    def download_page(self):
        label(self.content, "Muat turun media", 28, True).pack(pady=(0, 8))
        linkrow = frame(self.content)
        linkrow.pack(fill="x", pady=(0, 4))
        url = self.entry(linkrow, self.link)
        url.pack(side="left", fill="x", expand=True, ipady=9)
        url.bind("<Return>", lambda event: self.check_link())
        button(linkrow, "Tampal", self.paste_link).pack(side="left", padx=(8, 0))
        self.check_button = button(linkrow, "Semak pautan", self.check_link)
        self.check_button.pack(side="left", padx=(8, 0))
        if self.checking:
            self.check_button.configure(state="disabled")
        label(self.content, "", 10, fg=GRAY, textvariable=self.status).pack(fill="x", pady=(0, 8))

        cards = frame(self.content)
        cards.pack(fill="both", expand=True)
        cards.columnconfigure(0, weight=1, uniform="card")
        cards.columnconfigure(1, weight=1, uniform="card")
        cards.rowconfigure(0, weight=1)
        left = frame(cards, PANEL, True)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        right = frame(cards, PANEL, True)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.controls = frame(left, PANEL)
        self.controls.pack(fill="both", expand=True, padx=14, pady=(12, 6))
        self.download_button = button(left, "↓   Muat turun", self.add_current, True)
        self.download_button.pack(fill="x", padx=14, pady=(4, 12), ipady=5)

        self.canvas = tk.Canvas(right, bg="#060607", highlightthickness=0, height=210)
        self.canvas.pack(fill="both", expand=True, padx=11, pady=(11, 5))
        self.canvas.bind("<Configure>", lambda event: self.draw_preview())
        self.preview_title = label(right, "", 14, True)
        self.preview_title.pack(fill="x", padx=11, pady=(2, 3))
        self.source_button = button(right, "Buka video asal", self.open_source)
        self.source_button.pack(anchor="w", padx=11, pady=(0, 9))

        bottom = frame(self.content, PANEL, True)
        bottom.pack(fill="x", pady=(11, 0))
        label(bottom, "Barisan muat turun", 14, True).pack(anchor="w", padx=13, pady=(8, 5))
        queue_canvas = tk.Canvas(bottom, bg=PANEL, highlightthickness=0, height=101)
        scrollbar = ttk.Scrollbar(bottom, command=queue_canvas.yview)
        scrollbar.pack(side="right", fill="y", pady=(0, 6))
        queue_canvas.pack(fill="x", expand=True, padx=12, pady=(0, 6))
        queue_canvas.configure(yscrollcommand=scrollbar.set)
        self.job_list = frame(queue_canvas, PANEL)
        window = queue_canvas.create_window((0, 0), window=self.job_list, anchor="nw")
        self.job_list.bind("<Configure>", lambda event: queue_canvas.configure(scrollregion=queue_canvas.bbox("all")))
        queue_canvas.bind("<Configure>", lambda event: queue_canvas.itemconfigure(window, width=event.width))
        self.refresh_controls()
        self.refresh_preview()
        self.refresh_jobs()

    def refresh_controls(self):
        if self.tab != "Muat Turun":
            return
        for child in self.controls.winfo_children():
            child.destroy()
        for row, (key, values) in enumerate(CHOICES.items()):
            label(self.controls, LABELS[key], 11, True).grid(row=row, column=0, sticky="w", padx=(0, 8))
            group = frame(self.controls, PANEL)
            group.grid(row=row, column=1, sticky="ew", pady=3)
            if key == "format":
                self.format_var = tk.StringVar(value=self.options[key])
                combo = self.combo(group, self.format_var, values)
                combo.pack(fill="x")
                combo.bind("<<ComboboxSelected>>", lambda event: self.pick("format", self.format_var.get()))
                continue
            for value in values:
                display = "● " + value if value in COLORS else value
                item = button(group, display, lambda key=key, value=value: self.pick(key, value),
                              self.options[key] == value)
                item.configure(padx=5)
                if value in COLORS and self.options[key] != value:
                    item.configure(fg=COLORS[value][0])
                if not self.available(key, value):
                    item.configure(state="disabled", cursor="arrow")
                item.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.controls.columnconfigure(1, weight=1)
        can_download = not self.checking and self.info and options_for(
            self.info, self.options["resolution"], self.options["fps"])
        self.download_button.configure(state="normal" if can_download else "disabled")

    def available(self, key, value):
        if key == "color":
            return value == "Tiada" or self.options["language"] != "Tiada"
        if not self.info:
            return True
        if key == "resolution":
            return bool(options_for(self.info, value))
        if key == "fps":
            return bool(options_for(self.info, self.options["resolution"], value))
        if key == "language":
            return value == "Tiada" or subtitle_track(self.info, value) is not None
        return True

    def pick(self, key, value):
        self.options[key] = value
        if key == "language":
            self.options["color"] = "Tiada" if value == "Tiada" else (
                self.options["color"] if self.options["color"] != "Tiada" else "Putih"
            )
        if key == "color" and value == "Tiada":
            self.options["language"] = "Tiada"
        self.fit_options()
        self.refresh_controls()
        self.draw_preview()

    def fit_options(self):
        if not self.info:
            return
        for key in ("resolution", "fps"):
            available = [value for value in CHOICES[key] if self.available(key, value)]
            if available and self.options[key] not in available:
                self.options[key] = available[-1]
        if not self.available("language", self.options["language"]):
            self.options.update(language="Tiada", color="Tiada")

    def link_changed(self, *args):
        if self.retry and self.retry["url"] != self.link.get().strip():
            self.retry = None
        if self.checked_url != self.link.get().strip() and self.info is not None:
            self.checked_url = self.info = self.image = None
            self.status.set("Tampal pautan video untuk mula.")
            self.refresh_controls()
            self.refresh_preview()

    def paste_link(self):
        try:
            self.link.set(self.root.clipboard_get().strip())
        except tk.TclError:
            self.status.set("Tiada pautan teks dalam papan klip.")

    def check_link(self):
        if self.checking:
            return
        url = self.link.get().strip()
        if not http_link(url):
            self.status.set("Masukkan pautan video http:// atau https:// yang sah.")
            return
        self.checking = True
        self.check_button.configure(state="disabled")
        self.download_button.configure(state="disabled")
        self.status.set("Sedang menyemak pautan…")

        def inspect():
            try:
                info = inspect_media(url)
                self.events.put(("inspected", url, info, None))
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                self.events.put(("inspected", url, None, str(error)))
                return
            try:
                image = preview_media(info, url)
                if image:
                    self.events.put(("thumbnail", url, image))
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, Image.DecompressionBombError):
                pass

        threading.Thread(target=inspect, daemon=True).start()

    def refresh_preview(self):
        if self.tab != "Muat Turun":
            return
        self.preview_title.configure(text=(self.info.get("title") or "Video") if self.info else "Pratonton video")
        self.source_button.configure(state="normal" if self.checked_url else "disabled")
        self.draw_preview()

    def draw_preview(self):
        if self.tab != "Muat Turun":
            return
        canvas = self.canvas
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width < 3 or height < 3:
            return
        ratio = self.options["ratio"]
        if ratio == "FULL":
            formats = options_for(self.info, self.options["resolution"], self.options["fps"]) if self.info else []
            first = formats[-1] if formats else {}
            aspect = (first.get("width") or (self.image.width if self.image else 16)) / (
                first.get("height") or (self.image.height if self.image else 9)
            )
        else:
            first, second = map(int, ratio.split(":"))
            aspect = first / second
        target_width = max(2, min(width, int(height * aspect)))
        target_height = max(2, min(height, int(width / aspect)))
        if self.image:
            fitted = ImageOps.fit(self.image, (target_width, target_height), Image.Resampling.LANCZOS)
            self.preview_image = ImageTk.PhotoImage(fitted)
            canvas.create_image(width / 2, height / 2, image=self.preview_image)
        else:
            canvas.create_rectangle((width-target_width)/2, (height-target_height)/2,
                                    (width+target_width)/2, (height+target_height)/2,
                                    fill=PANEL, outline=BORDER)
            canvas.create_text(width / 2, height / 2, text=(
                "Tiada imej pratonton" if self.info else "Tampal pautan dan semak video"
            ), fill=GRAY, font=("Segoe UI", 11))
        if self.info and self.options["language"] != "Tiada":
            sample = {"Melayu": "Contoh sari kata", "English": "Subtitle preview", "Chinese": "字幕预览"}
            y = (height + target_height) / 2 - 22
            text = canvas.create_text(width / 2, y, text=sample[self.options["language"]],
                                      fill=COLORS[self.options["color"]][0], font=("Segoe UI", 11, "bold"))
            x1, y1, x2, y2 = canvas.bbox(text)
            background = canvas.create_rectangle(x1 - 6, y1 - 2, x2 + 6, y2 + 2, fill="black", outline="")
            canvas.tag_lower(background, text)

    def open_source(self):
        if self.checked_url:
            webbrowser.open(self.checked_url)

    def add_current(self):
        if not self.info or self.checking or self.checked_url != self.link.get().strip():
            return
        self.add_job(self.checked_url, self.info, self.options.copy())

    def add_job(self, url, info, options, folder=None):
        job = Job(url, info, options, folder or self.settings["folder"])
        self.jobs.append(job)
        self.schedule()
        self.refresh_jobs()

    def schedule(self):
        if self.closing:
            return
        running = sum(job.state in ("Memuat turun", "Memproses video", "Menjeda", "Membatalkan")
                      for job in self.jobs)
        for job in self.jobs:
            if running >= self.settings["parallel"]:
                break
            if job.state != "Menunggu":
                continue
            job.stop.clear()
            job.intent = None
            job.state = "Memuat turun"
            running += 1
            threading.Thread(target=self.run_job, args=(job,), daemon=True).start()

    def run_job(self, job):
        path, error = None, None
        try:
            path = job.execute(lambda state, percent: self.events.put(("progress", job, state, percent)))
            state = "Selesai"
        except InterruptedError:
            state = job.intent or "Dibatalkan"
        except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as failure:
            state = job.intent or "Gagal"
            error = str(failure)
        if state != "Dijeda":
            shutil.rmtree(job.scratch, ignore_errors=True)
        self.events.put(("finished", job, state, path, error))

    def change_job(self, job, action):
        if action == "Sambung":
            job.state = "Menunggu"
        elif job.state in ("Menunggu", "Dijeda"):
            job.state = "Dibatalkan" if action == "Batal" else "Dijeda"
            if action == "Batal":
                shutil.rmtree(job.scratch, ignore_errors=True)
                self.record(job, job.state, None, None)
                self.jobs.remove(job)
        elif job.state in ("Memuat turun", "Memproses video"):
            job.state = "Menjeda" if action == "Jeda" else "Membatalkan"
            job.interrupt("Dijeda" if action == "Jeda" else "Dibatalkan")
        self.schedule()
        self.refresh_jobs()

    def refresh_jobs(self):
        if self.tab != "Muat Turun":
            return
        for child in self.job_list.winfo_children():
            child.destroy()
        jobs = [job for job in self.jobs if job.state not in ("Selesai", "Gagal", "Dibatalkan")]
        if not jobs:
            label(self.job_list, "Tiada muat turun dalam barisan.", 10, fg=GRAY).pack(anchor="w", pady=8)
        for job in jobs:
            row = frame(self.job_list, PANEL)
            row.pack(fill="x", pady=2)
            label(row, job.title[:42], 10, True, width=35).pack(side="left")
            label(row, f"{job.state}  ·  {job.progress}%", 10, fg=GRAY, width=23).pack(side="left")
            ttk.Progressbar(row, value=job.progress, style="MDM.Horizontal.TProgressbar").pack(
                side="left", expand=True, fill="x", padx=8)
            if job.state not in ("Menjeda", "Membatalkan"):
                action = "Sambung" if job.state == "Dijeda" else "Jeda"
                button(row, action, lambda job=job, action=action: self.change_job(job, action)).pack(side="left", padx=2)
                button(row, "Batal", lambda job=job: self.change_job(job, "Batal")).pack(side="left", padx=2)

    def record(self, job, state, path, error):
        self.completed += 1
        self.history.insert(0, {
            "title": job.title, "platform": job.info.get("extractor_key", ""),
            "date": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "status": state, "path": str(path) if path else "", "error": error or "",
            "url": job.url, "options": job.options, "folder": str(job.folder),
        })
        try:
            write_json(self.history_path, self.history)
        except OSError as failure:
            self.status.set(f"Sejarah tidak dapat disimpan. {failure}")
        if self.tab == "Sejarah":
            self.update_history()

    def poll(self):
        refresh = False
        for _ in range(150):
            try:
                kind, *event = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "inspected":
                url, info, error = event
                self.checking = False
                if self.tab == "Muat Turun":
                    self.check_button.configure(state="normal")
                if url != self.link.get().strip():
                    self.status.set("Tampal pautan video untuk mula.")
                    continue
                self.info = info
                self.checked_url = url if info else None
                self.image = None
                self.fit_options()
                if info and not options_for(info, self.options["resolution"], self.options["fps"]):
                    self.status.set("Video ini tiada gabungan resolusi dan kadar bingkai yang disokong.")
                elif info:
                    self.status.set(f"Pautan disemak  ·  {info.get('extractor_key', 'Video')}")
                else:
                    self.status.set("Semakan gagal. " + (error or "Sumber tidak tersedia.")[:145])
                self.refresh_controls()
                self.refresh_preview()
                if self.retry and url == self.retry["url"]:
                    retry, self.retry = self.retry, None
                    settings = retry["options"]
                    if info and options_for(info, settings["resolution"], settings["fps"]):
                        if settings["language"] == "Tiada" or subtitle_track(info, settings["language"]):
                            self.add_job(url, info, settings.copy(), retry["folder"])
                        else:
                            self.status.set("Sari kata pilihan terdahulu tidak tersedia.")
                    elif info:
                        self.status.set("Kualiti pilihan terdahulu tidak tersedia.")
            elif kind == "thumbnail":
                url, image = event
                if url == self.checked_url:
                    self.image = image
                    self.draw_preview()
            elif kind == "progress":
                job, state, percent = event
                if job.intent is None:
                    job.state = state
                    job.progress = max(job.progress, percent)
                    refresh = True
            elif kind == "finished":
                job, state, path, error = event
                job.state = state
                if state != "Dijeda":
                    self.record(job, state, path, error)
                    self.jobs.remove(job)
                    self.status.set(
                        f"Muat turun selesai. {path.name}" if path else
                        ("Muat turun gagal. " + (error or "")[:125]) if state == "Gagal" else "Muat turun dibatalkan."
                    )
                self.schedule()
                refresh = True
        if refresh:
            self.refresh_jobs()
        self.events_id = self.root.after(80, self.poll)

    def history_page(self):
        label(self.content, "Sejarah muat turun", 28, True).pack(anchor="w", pady=(0, 13))
        filters = frame(self.content)
        filters.pack(fill="x", pady=(0, 10))
        label(filters, "Cari tajuk atau platform").pack(side="left", padx=(0, 8))
        self.entry(filters, self.filter_text).pack(side="left", ipady=6, fill="x", expand=True)
        self.combo(filters, self.filter_status, ("Semua status", "Selesai", "Gagal", "Dibatalkan")).pack(
            side="left", padx=(9, 0))
        table = frame(self.content, PANEL, True)
        table.pack(fill="both", expand=True)
        columns = ("title", "platform", "details", "date", "status")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", style="MDM.Treeview", selectmode="browse")
        scrollbar = ttk.Scrollbar(table, command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        for key, heading, width in zip(columns, ("Fail", "Platform", "Butiran", "Tarikh", "Status"),
                                       (300, 105, 220, 145, 105)):
            self.tree.heading(key, text=heading, anchor="w")
            self.tree.column(key, width=width, minwidth=65, anchor="w", stretch=key in ("title", "details"))
        self.tree.bind("<<TreeviewSelect>>", self.history_selected)
        self.tree.bind("<Double-1>", lambda event: self.history_action("Buka fail"))
        actions = frame(self.content)
        actions.pack(fill="x", pady=9)
        self.history_actions = {}
        for text in ("Buka fail", "Buka folder", "Cuba semula"):
            item = button(actions, text, lambda text=text: self.history_action(text))
            item.pack(side="left", padx=(0, 6))
            self.history_actions[text] = item
        self.history_detail = label(actions, "", 10, fg=GRAY)
        self.history_detail.pack(side="left", fill="x", expand=True, padx=6)
        self.update_history()

    def filter_changed(self, *args):
        if self.tab == "Sejarah":
            self.update_history()

    def update_history(self):
        self.tree.delete(*self.tree.get_children())
        query, status = self.filter_text.get().casefold(), self.filter_status.get()
        for index, row in enumerate(self.history):
            if status != "Semua status" and status != row["status"]:
                continue
            if query not in f"{row['title']} {row['platform']}".casefold():
                continue
            options = row["options"]
            self.tree.insert("", "end", iid=str(index), values=(
                Path(row["path"]).name if row["path"] else row["title"], row["platform"],
                " · ".join(options[key] for key in ("resolution", "fps", "ratio")),
                row["date"], row["status"],
            ))
        self.history_selected()

    def selected_history(self):
        selection = self.tree.selection()
        return self.history[int(selection[0])] if selection else None

    def history_selected(self, event=None):
        row = self.selected_history()
        for action, widget in self.history_actions.items():
            enabled = row and row["status"] == ("Gagal" if action == "Cuba semula" else "Selesai")
            widget.configure(state="normal" if enabled else "disabled")
        self.history_detail.configure(text=(row["error"][:105] if row else ""))

    def history_action(self, action):
        row = self.selected_history()
        if not row:
            return
        if action == "Cuba semula" and row["status"] == "Gagal":
            if self.checking:
                return
            self.show("Muat Turun")
            self.link.set(row["url"])
            self.options.update(row["options"])
            self.refresh_controls()
            self.retry = row
            self.check_link()
        elif row["path"]:
            path = Path(row["path"])
            try:
                os.startfile(str(path if action == "Buka fail" else path.parent))
            except OSError as error:
                self.history_detail.configure(text=f"Fail atau folder tidak dapat dibuka. {error}"[:110])

    def settings_page(self):
        label(self.content, "Tetapan", 28, True).pack(anchor="w", pady=(0, 13))
        cards = frame(self.content)
        cards.pack(fill="x")
        cards.columnconfigure(0, weight=1, uniform="settings")
        cards.columnconfigure(1, weight=1, uniform="settings")
        left, right = frame(cards, PANEL, True), frame(cards, PANEL, True)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.setting_vars = {key: tk.StringVar(value=str(value)) for key, value in self.settings.items()}
        label(left, "Muat turun", 19, True).pack(anchor="w", padx=15, pady=14)
        label(left, "Folder simpanan", bold=True).pack(anchor="w", padx=15)
        folder = frame(left, PANEL)
        folder.pack(fill="x", padx=15, pady=(5, 15))
        self.entry(folder, self.setting_vars["folder"]).pack(side="left", fill="x", expand=True, ipady=7)
        button(folder, "Tukar folder", self.choose_folder, True).pack(side="left", padx=(6, 0))
        for key, caption, values in (
            ("format", "Format lalai", CHOICES["format"]),
            ("parallel", "Muat turun serentak", ("1", "2", "3", "4")),
        ):
            label(left, caption, bold=True).pack(anchor="w", padx=15)
            self.combo(left, self.setting_vars[key], values).pack(fill="x", padx=15, pady=(5, 15))
        label(right, "Pilihan lalai", 19, True).pack(anchor="w", padx=15, pady=14)
        for key in ("resolution", "fps", "ratio", "language", "color"):
            row = frame(right, PANEL)
            row.pack(fill="x", padx=15, pady=(0, 13))
            caption = {"language": "Bahasa sari kata", "color": "Warna sari kata"}.get(key, LABELS[key])
            label(row, caption, bold=True, width=18).pack(side="left")
            combo = self.combo(row, self.setting_vars[key], CHOICES[key])
            combo.pack(side="left", fill="x", expand=True)
            if key in ("language", "color"):
                combo.bind("<<ComboboxSelected>>", lambda event, key=key: self.pick_setting(key))
        foot = frame(self.content)
        foot.pack(fill="x", pady=12)
        self.settings_status = label(foot, "", fg=GRAY)
        self.settings_status.pack(side="left")
        button(foot, "Simpan tetapan", self.save_settings, True).pack(side="right", ipady=4)

    def pick_setting(self, key):
        language, color = self.setting_vars["language"], self.setting_vars["color"]
        if key == "language":
            color.set("Tiada" if language.get() == "Tiada" else
                      "Putih" if color.get() == "Tiada" else color.get())
        elif color.get() == "Tiada":
            language.set("Tiada")
        elif language.get() == "Tiada":
            color.set("Tiada")

    def choose_folder(self):
        current = self.setting_vars["folder"].get()
        folder = filedialog.askdirectory(initialdir=current if Path(current).is_dir() else None, parent=self.root)
        if folder:
            self.setting_vars["folder"].set(folder)

    def save_settings(self):
        values = {key: variable.get() for key, variable in self.setting_vars.items()}
        folder = values["folder"].strip()
        if not folder or not Path(folder).is_absolute():
            self.settings_status.configure(text="Pilih lokasi folder simpanan yang sah.")
            return
        values["folder"] = str(Path(folder))
        values["parallel"] = int(values["parallel"])
        try:
            write_json(self.settings_path, values)
        except OSError as error:
            self.settings_status.configure(text=f"Tetapan tidak dapat disimpan. {error}"[:110])
            return
        self.settings = values
        self.options.update({key: values[key] for key in CHOICES})
        self.fit_options()
        self.schedule()
        self.settings_status.configure(text="Tetapan disimpan.")

    def close(self):
        if self.jobs:
            confirmed = messagebox.askyesno(NAME, "Batalkan barisan muat turun dan tutup aplikasi?", parent=self.root)
            if not confirmed:
                return
            self.closing = True
            for job in list(self.jobs):
                self.change_job(job, "Batal")
            self.root.after(150, self.close_when_idle)
            return
        self.root.destroy()

    def close_when_idle(self):
        if any(job.state in ("Menjeda", "Membatalkan") for job in self.jobs):
            self.root.after(150, self.close_when_idle)
        else:
            self.root.destroy()


def main():
    if len(sys.argv) in (3, 4) and sys.argv[1] == "--smoke-test":
        root = tk.Tk()
        data = Path(sys.argv[2])
        app = App(root, data)
        for tab in ("Sejarah", "Tetapan", "Muat Turun"):
            app.show(tab)
            root.update()
        fps_row = app.controls.grid_slaves(row=1, column=1)[0]
        assert any(item.cget("text") == ORIGINAL_FPS for item in fps_row.winfo_children())
        checks = {name: capture([tool(name), flag], 20).splitlines()[0] for name, flag in (
            ("yt-dlp", "--version"), ("ffmpeg", "-version"), ("ffprobe", "-version"), ("node", "--version"),
        )}
        if len(sys.argv) == 4:
            url = sys.argv[3]
            job = Job(url, inspect_media(url), SETTINGS | {"resolution": "480p", "fps": ORIGINAL_FPS}, data)
            try:
                path = job.execute(lambda *_: None)
                _, video = probe_file(path)
                checks["video"] = [path.name, video["width"], video["height"], video["avg_frame_rate"]]
            finally:
                shutil.rmtree(job.scratch, ignore_errors=True)
        write_json(data / "smoke.json", checks)
        root.destroy()
        return
    root = tk.Tk()
    data_folder = Path(os.environ.get("LOCALAPPDATA", Path.home())) / NAME
    App(root, data_folder)
    root.mainloop()


if __name__ == "__main__":
    main()
