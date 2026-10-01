"""Loopback-only web dashboard. Launch with START.bat on Windows/RDP."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from core import AppError, Engine, YouTube
from bridge import Bridge

ROOT = Path(__file__).resolve().parent


def data_folder(demo=False):
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    return base / ("YouTubeTitleLoopDemo" if demo else "YouTubeTitleLoop")


class DemoYouTube:
    def __init__(self):
        self.title = "Relaxing Music — Morning"
        self.active = True
    def status(self):
        return {"has_client": True, "connected": True, "auth_pending": False,
                "auth_message": "Mode demo. Tidak terhubung ke Google dan tidak mengubah live asli.",
                "channel": {"id": "demo", "title": "Audio Nova · Demo"}}
    def lives(self):
        return [{"id": "DEMOlive001", "title": self.title, "status": "live"}] if self.active else []
    def assert_live(self, video_id):
        if not self.active or video_id != "DEMOlive001":
            raise AppError("Demo live sudah berhenti.")
    def set_title(self, video_id, title):
        self.assert_live(video_id)
        self.title = title
    def end_live(self, video_id):
        self.assert_live(video_id)
        self.active = False


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False
    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(port=8765, demo=False, folder=None):
    # Bind BEFORE loading the scheduler, so two instances cannot run the same loop.
    server = LocalServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.folder = folder or data_folder(demo)
    server.folder.mkdir(parents=True, exist_ok=True)
    try:
        server.youtube = DemoYouTube() if demo else YouTube(server.folder)
        server.engine = Engine(server.folder, server.youtube)
    except Exception:
        server.server_close()
        raise
    server.demo = demo
    server.app_token = secrets.token_urlsafe(40)
    server.origin = f"http://127.0.0.1:{server.server_port}"
    server.stop_event = threading.Event()
    server.bridge = Bridge(server.folder, server.engine, server.youtube, server.stop_event, allow_local=demo)
    server.bridge.start()
    def scheduler():
        while not server.stop_event.wait(1):
            try:
                server.engine.tick()
            except Exception:
                # Unexpected errors fail closed. No secrets or raw API payloads in log.
                with server.engine.lock:
                    server.engine.data.update(running=False, next_due=None, last_error="Kesalahan internal. Periksa ruang disk / izin folder data.")
                    server.engine.log("Loop dijeda karena kesalahan internal / penyimpanan.")
                    try:
                        server.engine.save()
                    except OSError:
                        pass
    server.scheduler_thread = threading.Thread(target=scheduler, daemon=True)
    server.scheduler_thread.start()
    return server


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *_):
        pass
    def valid_host(self):
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"
    def send(self, value, status=200, mime="application/json; charset=utf-8"):
        data = json.dumps(value, ensure_ascii=False).encode() if not isinstance(value, bytes) else value
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        if not self.valid_host():
            self.send({"error": "Host ditolak."}, 403)
            return
        path = urlparse(self.path).path
        if path == "/api/status":
            self.send({"state": self.server.engine.snapshot(), "youtube": self.server.youtube.status(),
                       "bridge": self.server.bridge.status(), "demo": self.server.demo, "version": "2.0.0", "server_time": time.time()})
            return
        files = {"/": ("index.html", "text/html; charset=utf-8"),
                 "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                 "/style.css": ("style.css", "text/css; charset=utf-8")}
        if path not in files:
            self.send({"error": "Halaman tidak ditemukan."}, 404)
            return
        name, mime = files[path]
        raw = (ROOT / "web" / name).read_bytes()
        if name == "index.html":
            raw = raw.replace(b"__APP_TOKEN__", self.server.app_token.encode())
        self.send(raw, mime=mime)
    def do_POST(self):
        token = self.headers.get("X-App-Token", "")
        if not self.valid_host() or self.headers.get("Origin") not in (None, self.server.origin) or not secrets.compare_digest(token, self.server.app_token):
            self.send({"error": "Permintaan ditolak. Refresh dashboard."}, 403)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 <= size <= 1048576:
                raise AppError("File/permintaan terlalu besar. Maksimum 1 MB.")
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise AppError("Format permintaan harus JSON.")
            payload = json.loads(self.rfile.read(size) or b"{}")
            if not isinstance(payload, dict):
                raise AppError("Format permintaan tidak valid.")
            path = urlparse(self.path).path
            engine = self.server.engine
            youtube = self.server.youtube
            if self.server.bridge.enabled() and path in ("/api/configure", "/api/start", "/api/pause", "/api/next", "/api/reset", "/api/end-live"):
                raise AppError("Mode CMS aktif. Gunakan tombol di Vercel agar antrean tetap sinkron. Darurat: Pengaturan → Putus CMS akan menjeda loop lokal.")
            if path == "/api/bridge-connect":
                self.server.bridge.configure(payload.get("url", ""), payload.get("key", ""))
                self.send({"ok": True})
                return
            if path == "/api/bridge-disconnect":
                self.server.bridge.disconnect()
                self.send({"ok": True})
                return
            if path == "/api/configure":
                engine.configure(payload)
            elif path == "/api/start":
                engine.start()
            elif path == "/api/pause":
                engine.pause()
            elif path == "/api/next":
                engine.next_now()
            elif path == "/api/reset":
                engine.reset()
            elif path == "/api/end-live":
                if payload.get("confirmation") != engine.snapshot()["video_id"]:
                    raise AppError("Konfirmasi Stop Live tidak valid.")
                engine.end_live()
            elif path == "/api/lives":
                self.send({"lives": youtube.lives()})
                return
            elif path in ("/api/import-client", "/api/connect", "/api/disconnect"):
                if self.server.demo:
                    raise AppError("Mode demo tidak memakai akun Google.")
                with engine.lock:
                    if engine.data["running"]:
                        raise AppError("Pause Loop sebelum mengganti koneksi YouTube.")
                    if path == "/api/import-client":
                        youtube.import_client(payload.get("credentials"))
                    elif path == "/api/connect":
                        url = youtube.begin_auth()
                        self.send({"ok": True, "url": url})
                        return
                    else:
                        youtube.disconnect()
            elif path == "/api/autostart":
                if os.name != "nt" or self.server.demo:
                    raise AppError("Autostart tersedia saat tool dijalankan di Windows.")
                startup = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"
                startup.mkdir(parents=True, exist_ok=True)
                shortcut = startup / "YouTubeTitleLoop.vbs"
                if payload.get("enabled"):
                    pythonw = Path(sys.executable).with_name("pythonw.exe")
                    if not pythonw.exists():
                        raise AppError("pythonw.exe tidak ditemukan. Install Python resmi untuk Windows.")
                    command = f'"{pythonw}" "{ROOT / "server.py"}" --no-browser'
                    shortcut.write_text('Set shell = CreateObject("WScript.Shell")\n' +
                        'shell.Run "' + command.replace('"', '""') + '", 0, False\n', encoding="utf-16")
                else:
                    shortcut.unlink(missing_ok=True)
                self.send({"ok": True, "message": "Autostart saat login Windows aktif." if payload.get("enabled") else "Autostart dinonaktifkan."})
                return
            elif path == "/api/shutdown":
                self.server.stop_event.set()
                self.server.bridge.wake.set()
                engine.pause()
                self.send({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            else:
                self.send({"error": "Endpoint tidak ditemukan."}, 404)
                return
            self.send({"ok": True})
        except (AppError, ValueError) as exc:
            self.send({"error": str(exc)}, 400)
        except Exception:
            self.send({"error": "Terjadi kesalahan internal. Cek izin folder data dan ruang disk."}, 500)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    try:
        server = make_server(args.port, args.demo)
    except OSError:
        if not args.no_browser:
            webbrowser.open(f"http://127.0.0.1:{args.port}")
        print("Port sudah digunakan. Dashboard dibuka; jangan jalankan dua salinan tool.")
        return
    except AppError as exc:
        print(str(exc))
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, str(exc), "YouTube Title Loop", 0x10)
        return
    if not args.no_browser:
        webbrowser.open(server.origin)
    print(f"YouTube Title Loop: {server.origin} (Ctrl+C untuk menutup program)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        # Keep the saved running flag, allowing recovery after an accidental process stop.
        pass
    finally:
        server.stop_event.set()
        server.server_close()


if __name__ == "__main__":
    main()
