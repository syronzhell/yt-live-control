"""YouTube Title Loop: OAuth, API and durable scheduler. Python 3.10+, stdlib only."""
from __future__ import annotations

import base64
import copy
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
API = "https://www.googleapis.com/youtube/v3/"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class AppError(Exception):
    def __init__(self, message, retryable=False, reason=""):
        super().__init__(message)
        self.retryable = retryable
        self.reason = reason


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.flush()
        os.fsync(file.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def load_json(path, default):
    if not path.exists():
        return copy.deepcopy(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise AppError(f"File data tidak bisa dibaca: {path.name}. Pulihkan backup; jangan hapus data tanpa backup.") from exc


def _dpapi(data: bytes, decrypt=False):
    """Bind saved credentials to the current Windows user, using Windows DPAPI."""
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]
    buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), buf)
    output = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise AppError("Windows gagal mengamankan token. Gunakan akun Windows yang sama saat membuka tool.")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))


class SecretStore:
    def __init__(self, path):
        self.path = path

    def save(self, data):
        raw = json.dumps(data).encode("utf-8")
        protected = os.name == "nt"
        if protected:
            raw = _dpapi(raw)
        atomic_json(self.path, {"protected": protected, "data": base64.b64encode(raw).decode()})

    def load(self):
        if not self.path.exists():
            return {}
        try:
            envelope = load_json(self.path, {})
            raw = base64.b64decode(envelope["data"])
            if envelope["protected"]:
                if os.name != "nt":
                    raise AppError("Token ini terikat ke akun Windows asal.")
                raw = _dpapi(raw, decrypt=True)
            return json.loads(raw)
        except AppError:
            raise
        except Exception as exc:
            raise AppError("Token tersimpan tidak bisa dibaca. Hubungkan YouTube lagi.") from exc


def request_json(method, url, payload=None, headers=None, form=False):
    head = dict(headers or {})
    body = None
    if payload is not None:
        body = urlencode(payload).encode() if form else json.dumps(payload).encode()
        head["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
    try:
        with urlopen(Request(url, body, head, method=method), timeout=20) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        try:
            error = json.loads(exc.read())
        except ValueError:
            error = {}
        detail = error.get("error", {})
        if isinstance(detail, str):
            reason = detail
        else:
            errors = detail.get("errors", [])
            reason = errors[0].get("reason", "") if errors else detail.get("status", "")
        messages = {
            "invalid_grant": "Izin Google kedaluwarsa/dicabut. Klik Hubungkan YouTube lagi.",
            "invalid_client": "OAuth Client tidak valid. Import ulang JSON tipe Desktop app.",
            "quotaExceeded": "Kuota API habis. Loop dijeda; lanjutkan setelah kuota tersedia.",
            "dailyLimitExceeded": "Batas kuota harian habis. Loop dijeda.",
            "accessNotConfigured": "Aktifkan YouTube Data API v3 di project Google Cloud.",
            "insufficientPermissions": "Izin belum cukup. Hubungkan channel lagi.",
            "forbidden": "Akses ditolak. Pastikan login pemilik channel/live yang dipilih.",
            "liveStreamingNotEnabled": "Channel belum mengaktifkan live streaming.",
        }
        retryable = exc.code in (408, 429, 500, 502, 503, 504) or reason in ("rateLimitExceeded", "userRateLimitExceeded", "backendError")
        message = messages.get(reason, f"YouTube/Google menolak permintaan (HTTP {exc.code}, {reason or 'unknown'}).")
        raise AppError(message, retryable, reason) from None
    except (URLError, TimeoutError, OSError) as exc:
        raise AppError("Koneksi ke Google gagal. Periksa internet RDP.", True, "network") from exc
    except ValueError as exc:
        raise AppError("Respons Google tidak valid. Coba lagi nanti.", True, "response") from exc


def validate_title(title):
    if not isinstance(title, str):
        raise AppError("Judul harus berupa teks.")
    title = title.strip()
    if not title or len(title) > 100 or "<" in title or ">" in title or any(ord(c) < 32 for c in title):
        raise AppError("Judul wajib 1–100 karakter, satu baris, tanpa karakter < atau >.")
    return title


def title_payload(video, title):
    old = video.get("snippet", {})
    if not old.get("categoryId"):
        raise AppError("Kategori video tidak tersedia; update dibatalkan untuk menjaga metadata.")
    fields = ("categoryId", "description", "tags", "defaultLanguage", "defaultAudioLanguage")
    snippet = {key: copy.deepcopy(old[key]) for key in fields if key in old}
    snippet["title"] = validate_title(title)
    return {"id": video["id"], "snippet": snippet}


class YouTube:
    def __init__(self, folder):
        self.store = SecretStore(folder / "credentials.json")
        self.secrets = self.store.load()
        self.lock = threading.RLock()
        self.auth_pending = None
        self.auth_message = ""

    def status(self):
        with self.lock:
            return {"has_client": bool(self.secrets.get("client")),
                    "connected": bool(self.secrets.get("refresh_token")),
                    "auth_pending": bool(self.auth_pending), "auth_message": self.auth_message,
                    "channel": self.secrets.get("channel", {})}

    def import_client(self, raw):
        installed = raw.get("installed", {}) if isinstance(raw, dict) else {}
        if not installed.get("client_id", "").endswith(".apps.googleusercontent.com") or not installed.get("client_secret"):
            raise AppError("Pilih file OAuth JSON dengan tipe Desktop app, bukan API key/Web application.")
        with self.lock:
            if self.auth_pending:
                raise AppError("Tunggu proses login selesai sebelum mengganti OAuth Client.")
            self.secrets = {"client": {"client_id": installed["client_id"], "client_secret": installed["client_secret"]}}
            self.store.save(self.secrets)
            self.auth_message = "OAuth Client tersimpan. Klik Hubungkan YouTube."

    def disconnect(self):
        with self.lock:
            if self.auth_pending:
                raise AppError("Tunggu proses login selesai sebelum disconnect.")
            refresh = self.secrets.get("refresh_token")
            if refresh:
                request_json("POST", "https://oauth2.googleapis.com/revoke", {"token": refresh}, form=True)
            self.secrets = {"client": self.secrets.get("client", {})}
            self.store.save(self.secrets)
            self.auth_message = "Izin YouTube dicabut; token lokal dihapus."

    def begin_auth(self):
        with self.lock:
            if self.auth_pending:
                raise AppError("Login sedang berjalan. Selesaikan di browser atau tunggu 5 menit.")
            client = self.secrets.get("client")
            if not client:
                raise AppError("Import file OAuth Client JSON dulu.")
            state = secrets.token_urlsafe(32)
            verifier = secrets.token_urlsafe(64)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            result = {}
            done = threading.Event()
            class Callback(BaseHTTPRequestHandler):
                def log_message(self, *_):
                    pass
                def do_GET(self):
                    parts = urlparse(self.path)
                    args = parse_qs(parts.query)
                    if parts.path != "/" or not secrets.compare_digest(args.get("state", [""])[0], state):
                        self.send_error(400, "Invalid OAuth state")
                        return
                    result.update({k: v[0] for k, v in args.items()})
                    data = b"<html><meta charset='utf-8'><body style='font:18px sans-serif;padding:40px'>Login diterima. Kembali ke dashboard YouTube Title Loop.</body></html>"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    done.set()
            server = HTTPServer(("127.0.0.1", 0), Callback)
            server.timeout = 0.5
            redirect = f"http://127.0.0.1:{server.server_port}/"
            self.auth_pending = state
            self.auth_message = "Selesaikan login Google di browser RDP (batas waktu 5 menit)."
            url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
                "client_id": client["client_id"], "redirect_uri": redirect,
                "response_type": "code", "scope": SCOPE, "state": state,
                "code_challenge": challenge, "code_challenge_method": "S256",
                "access_type": "offline", "prompt": "consent"})
            def wait_auth():
                try:
                    deadline = time.monotonic() + 300
                    while not done.is_set() and time.monotonic() < deadline:
                        server.handle_request()
                    if not done.is_set():
                        raise AppError("Login melewati batas waktu. Klik Hubungkan YouTube lagi.")
                    if "error" in result or not result.get("code"):
                        raise AppError("Login dibatalkan atau izin tidak diberikan.")
                    tokens = request_json("POST", TOKEN_URL, {
                        **client, "code": result["code"], "code_verifier": verifier,
                        "redirect_uri": redirect, "grant_type": "authorization_code"}, form=True)
                    if not tokens.get("refresh_token"):
                        raise AppError("Google tidak memberi refresh token. Hubungkan ulang dan beri izin offline.")
                    with self.lock:
                        self.secrets = {"client": client, **tokens, "expires_at": time.time() + tokens.get("expires_in", 3600)}
                        self.store.save(self.secrets)
                        channels = self.call("GET", "channels", {"part": "snippet", "mine": "true"}).get("items", [])
                        if channels:
                            self.secrets["channel"] = {"id": channels[0]["id"], "title": channels[0]["snippet"]["title"]}
                            self.store.save(self.secrets)
                        self.auth_message = "YouTube terhubung. Refresh daftar live."
                except AppError as exc:
                    with self.lock:
                        self.auth_message = str(exc)
                except Exception:
                    with self.lock:
                        self.auth_message = "Login gagal. Import OAuth JSON dan coba lagi."
                finally:
                    server.server_close()
                    with self.lock:
                        self.auth_pending = None
            threading.Thread(target=wait_auth, daemon=True).start()
            return url

    def access_token(self, force=False):
        with self.lock:
            if not self.secrets.get("refresh_token"):
                raise AppError("Hubungkan YouTube dulu.")
            if force or self.secrets.get("expires_at", 0) <= time.time() + 60:
                response = request_json("POST", TOKEN_URL, {
                    **self.secrets["client"], "refresh_token": self.secrets["refresh_token"],
                    "grant_type": "refresh_token"}, form=True)
                self.secrets.update(response)
                self.secrets["expires_at"] = time.time() + response.get("expires_in", 3600)
                self.store.save(self.secrets)
            return self.secrets["access_token"]

    def call(self, method, resource, params, body=None):
        for attempt in range(2):
            token = self.access_token(force=attempt == 1)
            try:
                return request_json(method, API + resource + "?" + urlencode(params), body,
                                    {"Authorization": "Bearer " + token})
            except AppError as exc:
                if attempt == 0 and exc.reason in ("authError", "UNAUTHENTICATED", "invalidCredentials"):
                    continue
                raise

    def lives(self):
        result = []
        page = None
        while True:
            params = {"part": "snippet,status", "broadcastStatus": "active", "broadcastType": "all", "maxResults": 50}
            if page:
                params["pageToken"] = page
            response = self.call("GET", "liveBroadcasts", params)
            result.extend({"id": x["id"], "title": x["snippet"]["title"],
                           "status": x["status"]["lifeCycleStatus"]} for x in response.get("items", []))
            page = response.get("nextPageToken")
            if not page:
                return result

    def assert_live(self, video_id):
        response = self.call("GET", "liveBroadcasts", {"part": "status", "id": video_id})
        items = response.get("items", [])
        if not items or items[0]["status"]["lifeCycleStatus"] != "live":
            raise AppError("Live yang dipilih sudah berhenti atau belum LIVE. Loop dijeda.", reason="notLive")

    def set_title(self, video_id, title):
        self.assert_live(video_id)
        response = self.call("GET", "videos", {"part": "snippet", "id": video_id})
        items = response.get("items", [])
        if not items:
            raise AppError("Video live tidak ditemukan.")
        # Idempotent retry: if the prior PUT succeeded but its response was lost, no second PUT.
        if items[0]["snippet"]["title"] != title:
            self.call("PUT", "videos", {"part": "snippet"}, title_payload(items[0], title))

    def end_live(self, video_id):
        response = self.call("GET", "liveBroadcasts", {"part": "status", "id": video_id})
        items = response.get("items", [])
        if items and items[0]["status"]["lifeCycleStatus"] == "complete":
            return  # Idempotent recovery if the earlier End Live response was lost.
        if not items or items[0]["status"]["lifeCycleStatus"] != "live":
            raise AppError("Live belum aktif atau tidak ditemukan.")
        self.call("POST", "liveBroadcasts/transition", {"part": "status", "id": video_id, "broadcastStatus": "complete"})


DEFAULT = {"version": 1, "video_id": "", "video_title": "", "titles": [], "interval_minutes": 180,
           "running": False, "current_index": -1, "next_due": None, "pending_index": None,
           "failures": 0, "last_error": "", "last_changed": None, "cycles": 0, "mutation_seq": 0, "logs": []}


class Engine:
    def __init__(self, folder, youtube, clock=time.time):
        self.path = folder / "state.json"
        self.youtube = youtube
        self.clock = clock
        self.lock = threading.RLock()
        self.data = {**copy.deepcopy(DEFAULT), **load_json(self.path, {})}
        self.health_due = self.clock() + 300
        if self.data["running"]:
            self.log("Aplikasi dibuka kembali. Loop dilanjutkan; jadwal terlewat hanya diproses satu kali.")

    def save(self):
        atomic_json(self.path, self.data)

    def log(self, message):
        self.data["logs"].append({"time": self.clock(), "message": message})
        self.data["logs"] = self.data["logs"][-150:]

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.data)

    def configure(self, payload):
        with self.lock:
            if self.data["running"]:
                raise AppError("Pause Loop sebelum mengedit antrean atau memilih live.")
            titles = payload.get("titles", [])
            if not isinstance(titles, list) or not 1 <= len(titles) <= 500:
                raise AppError("Isi 1–500 judul, satu judul per baris.")
            titles = [validate_title(x) for x in titles]
            try:
                minutes = float(payload.get("interval_minutes", 180))
            except (TypeError, ValueError):
                raise AppError("Interval harus berupa angka.")
            if not math.isfinite(minutes) or not 10 <= minutes <= 43200:
                raise AppError("Interval 10 menit sampai 30 hari. Gunakan jam × 60 untuk menit.")
            video_id = payload.get("video_id", "")
            if not isinstance(video_id, str) or len(video_id) != 11 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in video_id):
                raise AppError("Pilih live aktif dari daftar.")
            changed = video_id != self.data["video_id"] or titles != self.data["titles"]
            self.data.update(video_id=video_id, video_title=str(payload.get("video_title", ""))[:100],
                             titles=titles, interval_minutes=minutes, pending_index=None,
                             failures=0, last_error="")
            if changed:
                self.data.update(current_index=-1, cycles=0, last_changed=None)
            self.data["next_due"] = None
            self.log("Antrean dan pengaturan tersimpan.")
            self.save()

    def start(self):
        with self.lock:
            if self.data["running"]:
                return
            if not self.data["titles"] or not self.data["video_id"]:
                raise AppError("Pilih live, isi judul, lalu Simpan Antrean dulu.")
            self.youtube.assert_live(self.data["video_id"])
            self.data.update(running=True, failures=0, last_error="")
            # Fresh queue applies row 1 now. Resume keeps current title for a full interval.
            self.data["next_due"] = self.clock() if self.data["current_index"] < 0 or self.data["pending_index"] is not None else self.clock() + self.data["interval_minutes"] * 60
            self.health_due = self.clock() + 300
            self.log("Loop berjalan. Antrean berulang sampai Pause Loop / Stop Live.")
            self.save()
            if self.data["next_due"] <= self.clock():
                self._advance()

    def pause(self):
        with self.lock:
            self.data.update(running=False, next_due=None)
            self.log("Loop dijeda. Video live tetap berjalan.")
            self.save()

    def next_now(self):
        with self.lock:
            if not self.data["titles"] or not self.data["video_id"]:
                raise AppError("Simpan antrean dulu.")
            self._advance()

    def reset(self):
        with self.lock:
            if self.data["running"]:
                raise AppError("Pause Loop sebelum reset antrean.")
            self.data.update(current_index=-1, pending_index=None, failures=0, last_error="", cycles=0, next_due=None)
            self.log("Posisi antrean direset. Start Loop berikutnya memakai judul pertama.")
            self.save()

    def end_live(self):
        with self.lock:
            if not self.data["video_id"]:
                raise AppError("Pilih live dulu.")
            self.data.update(running=False, next_due=None)
            self.log("Loop dihentikan. Meminta YouTube mengakhiri live…")
            self.save()
            self.youtube.end_live(self.data["video_id"])
            self.log("Permintaan Stop Live diterima YouTube. Encoder tetap berjalan; hentikan juga jika diperlukan.")
            self.save()

    def _failed(self, exc):
        self.data["failures"] += 1
        self.data["last_error"] = str(exc)
        if exc.retryable and self.data["running"] and self.data["failures"] <= 3:
            delay = 30 * 2 ** (self.data["failures"] - 1)
            self.data["next_due"] = self.clock() + delay
            self.log(f"{exc} Retry {self.data['failures']}/3 dalam {delay} detik. Posisi antrean tetap.")
        else:
            self.data.update(running=False, next_due=None)
            self.log(f"Loop dijeda: {exc} Perbaiki penyebab lalu Start Loop lagi.")
        self.save()

    def _advance(self):
        target = self.data["pending_index"]
        if target is None:
            target = (self.data["current_index"] + 1) % len(self.data["titles"])
            self.data["pending_index"] = target
            # Persist intent before sending API mutation, so a crash cannot skip a title.
            self.save()
        try:
            self.youtube.set_title(self.data["video_id"], self.data["titles"][target])
        except AppError as exc:
            self._failed(exc)
            return
        if target == 0 and self.data["current_index"] >= 0:
            self.data["cycles"] += 1
        self.data.update(current_index=target, pending_index=None, failures=0, last_error="",
                         last_changed=self.clock(), video_title=self.data["titles"][target])
        self.data["mutation_seq"] += 1
        self.data["next_due"] = self.clock() + self.data["interval_minutes"] * 60 if self.data["running"] else None
        self.log(f"Judul {target + 1}/{len(self.data['titles'])} aktif: {self.data['titles'][target]}")
        self.save()

    def tick(self):
        with self.lock:
            if self.data.get("remote_journal"):
                return  # Bridge recovers this durable command before normal scheduling resumes.
            if not self.data["running"]:
                return
            if self.data["next_due"] is not None and self.clock() >= self.data["next_due"]:
                self._advance()
                self.health_due = self.clock() + 300
            elif self.clock() >= self.health_due:
                self.health_due = self.clock() + 300
                try:
                    self.youtube.assert_live(self.data["video_id"])
                except AppError as exc:
                    if exc.retryable:
                        self.log("Pemeriksaan live gagal sementara. Jadwal berikutnya tetap disimpan.")
                        self.save()
                    else:
                        self._failed(exc)
