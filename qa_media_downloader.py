import functools
import http.server
import json
import subprocess
import sys
import threading
import time
import tkinter as tk
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from media_downloader import App, Job, ORIGINAL_FPS, SETTINGS, capture, http_link, options_for, probe_file, render_args, subtitle_track, tool


def wait(root, ready, seconds=80):
    expire = time.monotonic() + seconds
    while not ready():
        root.update()
        if time.monotonic() > expire:
            raise AssertionError("Application did not reach its expected state")
        time.sleep(0.04)
    root.update()


class QuietServer(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def test_app(folder):
    fixture = folder / "fixture.mp4"
    capture([tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i",
             "color=black:s=1280x720:r=30000/1001:d=1", "-f", "lavfi", "-i",
             "sine=frequency=510:duration=1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-movflags", "+faststart", str(fixture)], 30)
    handler = functools.partial(QuietServer, directory=folder)
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_port}/fixture.mp4"
        root = tk.Tk()
        errors = []
        root.report_callback_exception = lambda *args: errors.append(args)
        try:
            app = App(root, folder / "data")
            root.update()
            app.link.set("file:///C:/fixture.mp4")
            app.check_button.invoke()
            assert "sah" in app.status.get()
            app.show("Tetapan")
            app.setting_vars["folder"].set(str(folder / "Downloads"))
            app.setting_vars["ratio"].set("9:16")
            app.setting_vars["resolution"].set("480p")
            app.setting_vars["fps"].set(ORIGINAL_FPS)
            app.setting_vars["parallel"].set("1")
            app.setting_vars["language"].set("Chinese")
            app.pick_setting("language")
            assert app.setting_vars["color"].get() == "Putih"
            app.setting_vars["color"].set("Tiada")
            app.pick_setting("color")
            assert app.setting_vars["language"].get() == "Tiada"
            app.save_settings()
            assert json.loads(app.settings_path.read_text(encoding="utf-8"))["fps"] == ORIGINAL_FPS
            app.show("Muat Turun")
            app.link.set(url)
            app.check_button.invoke()
            wait(root, lambda: not app.checking)
            assert app.info is not None, app.status.get()
            assert app.available("resolution", "720p") and not app.available("resolution", "4K")
            assert app.available("fps", ORIGINAL_FPS)
            assert app.available("fps", "30 fps") and not app.available("fps", "60 fps")
            assert app.options["fps"] == ORIGINAL_FPS
            assert app.options["ratio"] == "9:16" and app.options["language"] == "Tiada"
            app.download_button.invoke()
            wait(root, lambda: app.completed == 1)
            row = app.history[0]
            assert row["status"] == "Selesai", row
            streams, video = probe_file(Path(row["path"]))
            assert (video["width"], video["height"]) == (480, 854), video
            assert Fraction(video["avg_frame_rate"]) == Fraction(30000, 1001)
            assert row["options"]["fps"] == ORIGINAL_FPS
            assert {stream["codec_type"] for stream in streams["streams"]} == {"audio", "video"}
            app.show("Sejarah")
            assert len(app.tree.get_children()) == 1
            app.filter_text.set("no match")
            assert not app.tree.get_children()
            app.filter_text.set("fixture")
            assert len(app.tree.get_children()) == 1
            app.tree.selection_set("0")
            app.history_selected()
            assert app.history_actions["Buka fail"]["state"] == "normal"
            app.show("Muat Turun")
            app.add_job(url, app.info, app.options.copy(), fixture)
            wait(root, lambda: app.completed == 2)
            assert app.history[0]["status"] == "Gagal"
            app.history[0]["folder"] = str(folder / "Downloads")
            app.show("Sejarah")
            app.tree.selection_set("0")
            app.history_action("Cuba semula")
            wait(root, lambda: app.completed == 3)
            assert app.history[0]["status"] == "Selesai", app.history[0]
            assert app.history[0]["path"] != row["path"] and Path(row["path"]).is_file()
            assert not errors, errors
            print("PASS: Tk tabs, invalid link, settings, HTTP inspection, download, history, retry, no overwrite.")
        finally:
            root.destroy()
            server.shutdown()
    return fixture


def test_encoding(folder, fixture):
    captions = folder / "captions.srt"
    captions.write_text("1\n00:00:00,000 --> 00:00:00,950\n中文和 Bahasa Melayu\n", encoding="utf-8")
    tracks = {"subtitles": {"en-US": []}, "automatic_captions": {"ms": [], "zh-Hant": []}}
    assert subtitle_track(tracks, "English") == ("subtitles", "en-US")
    assert subtitle_track(tracks, "Melayu") == ("automatic_captions", "ms")
    assert subtitle_track(tracks, "Chinese") == ("automatic_captions", "zh-Hant")
    assert subtitle_track(tracks, "Tiada") is None
    assert not options_for({"formats": [{"width": 1920, "height": 1080, "fps": 30}]}, "1080p", "60 fps")
    for ratio, format_, expected in (
        ("FULL", "MP4", (854, 480)), ("1:1", "MKV", (480, 480)),
        ("3:4", "WEBM", (480, 640)), ("9:16", "MP4", (480, 854)),
        ("16:9", "MP4", (854, 480)), ("4:3", "MP4", (640, 480)),
    ):
        settings = SETTINGS | {"resolution": "480p", "fps": "24 fps", "ratio": ratio,
                               "format": format_, "language": "Chinese", "color": "Merah"}
        args, output, _ = render_args(fixture, settings, folder, subtitle=True)
        result = subprocess.run(args, cwd=folder, capture_output=True, timeout=30)
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        metadata, video = probe_file(output)
        assert (video["width"], video["height"]) == expected and Fraction(video["avg_frame_rate"]) == 24
        assert not any(item["codec_type"] == "subtitle" for item in metadata["streams"])
        still = folder / "still.png"
        capture([tool("ffmpeg"), "-v", "error", "-y", "-i", str(output),
                 "-frames:v", "1", str(still)], 15)
        with Image.open(still) as image:
            red = sum(r > 120 and r > 2 * g and r > 2 * b for r, g, b in image.convert("RGB").getdata())
            assert red > 12, (ratio, red)
    print("PASS: all six frame ratios, MP4/MKV/WEBM, 24 fps, audio, Chinese subtitle rendering and red text.")


def test_interrupt(folder):
    job = Job("http://127.0.0.1", {"title": "Stop test"}, SETTINGS, folder)
    job.scratch.mkdir()
    started, stopped = threading.Event(), threading.Event()
    ffmpeg = [tool("ffmpeg"), "-v", "error", "-re", "-f", "lavfi", "-i",
              "color=s=320x180:r=30:d=20", "-f", "null", "-"]
    script = f"import subprocess; p = subprocess.Popen({ffmpeg!r}); print(p.pid, flush=True); p.wait()"

    def process():
        try:
            job.run_process([sys.executable, "-c", script], lambda line: started.set() if line.isdigit() else None)
        except InterruptedError:
            stopped.set()

    worker = threading.Thread(target=process, daemon=True)
    worker.start()
    assert started.wait(5), "Child process did not start"
    assert job.process_group, "Could not attach child tree to the Windows job"
    job.interrupt("Dijeda")
    worker.join(5)
    assert stopped.is_set() and not worker.is_alive(), "Pausing did not stop the process tree"
    print("PASS: pausing stops an active Windows process and its child.")


def test_original_timing(folder):
    source = folder / "variable.mp4"
    capture([tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=854x480:r=30:d=1",
             "-vf", "select='not(mod(n,2))+not(mod(n,5))'", "-fps_mode", "vfr",
             "-c:v", "libx264", str(source)], 15)

    def timestamps(path):
        data = json.loads(capture([tool("ffprobe"), "-v", "error", "-select_streams", "v:0",
                                   "-show_frames", "-show_entries", "frame=best_effort_timestamp_time",
                                   "-of", "json", str(path)], 15))
        return [float(frame["best_effort_timestamp_time"]) for frame in data["frames"]]

    original = timestamps(source)
    assert len({round(b - a, 3) for a, b in zip(original, original[1:])}) > 1
    for fmt in ("MP4", "MKV", "WEBM"):
        settings = SETTINGS | {"resolution": "480p", "fps": ORIGINAL_FPS, "format": fmt}
        args, output, _ = render_args(source, settings, folder)
        result = subprocess.run(args, cwd=folder, capture_output=True, timeout=30)
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        actual = timestamps(output)
        assert len(actual) == len(original) and all(abs(a - b) <= 0.001 for a, b in zip(original, actual))
    print("PASS: Original preserves variable frame timing in MP4, MKV and WEBM.")


if __name__ == "__main__":
    assert http_link("https://example.com/video") and not http_link("https://user@example.com/video")
    with TemporaryDirectory(prefix="mdm-qa-", dir=Path(__file__).parent) as temp:
        folder = Path(temp).resolve()
        fixture = test_app(folder)
        test_encoding(folder, fixture)
        test_original_timing(folder)
        test_interrupt(folder)
