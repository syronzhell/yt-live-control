"""Outbound-only bridge between Windows/RDP and the Vercel CMS."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import secrets
import threading
import time
import uuid
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

from core import AppError, SecretStore


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None


def cloud_request(url, key, payload):
    request = Request(url + '/api/agent/sync', json.dumps(payload).encode(),
                      {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, method='POST')
    try:
        with build_opener(NoRedirect).open(request, timeout=20) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        if exc.code == 401:
            raise AppError('Agent key ditolak CMS. Loop dijeda; periksa key.', reason='bridgeAuth') from None
        if exc.code == 409:
            raise AppError('RDP lain sudah terpasang ke CMS. Loop dijeda; gunakan satu instalasi.', reason='bridgeConflict') from None
        if exc.code in (301, 302, 307, 308):
            raise AppError('CMS melakukan redirect. Masukkan URL production HTTPS yang final.', reason='bridgeRedirect') from None
        raise AppError(f'CMS menolak sync (HTTP {exc.code}). Cek deploy / database / protection Vercel.', True) from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise AppError('CMS tidak terjangkau. Loop lokal tetap memakai pengaturan terakhir.', True) from None


class Bridge:
    def __init__(self, folder, engine, youtube, stop_event, allow_local=False):
        self.engine, self.youtube, self.stop_event = engine, youtube, stop_event
        self.store = SecretStore(folder / 'bridge_credentials.json')
        self.settings = self.store.load()
        self.lock = threading.RLock()
        self.allow_local = allow_local
        self.last_sync = None
        self.error = ''
        self.lives = []
        self.lives_updated = None
        self.lives_error = ''
        self.inventory_due = 0
        self.wake = threading.Event()
        self.thread = None

    def enabled(self):
        with self.lock:
            return bool(self.settings.get('enabled') and self.settings.get('url') and self.settings.get('key'))

    def status(self):
        with self.lock:
            return {'enabled': self.enabled(), 'url': self.settings.get('url', ''),
                    'last_sync': self.last_sync, 'error': self.error,
                    'agent_id': self.settings.get('agent_id', '')}

    def configure(self, url, key):
        if not isinstance(url, str) or not isinstance(key, str):
            raise AppError('URL CMS dan Agent key harus berupa teks.')
        parsed = urlparse(url.strip())
        local = self.allow_local and parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost')
        if (parsed.scheme != 'https' and not local) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
            raise AppError('Gunakan origin HTTPS CMS final, contoh https://nama.vercel.app, tanpa path/query.')
        if len(key) < 32 or len(key) > 512 or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise AppError('Agent key wajib 32–512 karakter ASCII tanpa spasi.')
        with self.engine.lock:
            self.engine.pause()
            with self.lock:
                if self.settings.get('url') and self.settings['url'] != url.strip().rstrip('/') and self.engine.data.get('remote_journal'):
                    raise AppError('Ada perintah CMS yang belum selesai. Selesaikan pairing lama dulu.')
                self.settings = {'enabled': True, 'url': url.strip().rstrip('/'), 'key': key,
                                 'agent_id': self.settings.get('agent_id') or str(uuid.uuid4())}
                self.store.save(self.settings)
                self.error = ''; self.last_sync = None; self.inventory_due = 0
            self.engine.log('Mode CMS aktif. Antrean dan tombol loop dikontrol dari Vercel.')
            self.engine.save()
        self.wake.set()

    def disconnect(self):
        with self.engine.lock:
            self.engine.pause()
            journal = self.engine.data.get('remote_journal')
            if journal:
                receipts = self.engine.data.setdefault('remote_receipts', [])
                self.engine.data['remote_receipts'] = (receipts + [{'id': journal['id'], 'ok': False,
                    'message': 'Perintah dihentikan melalui Putus CMS di RDP.'}])[-100:]
                self.engine.data['remote_journal'] = None
            with self.lock:
                self.settings['enabled'] = False
                self.store.save(self.settings)
                self.error = ''; self.last_sync = None
            self.engine.log('CMS dilepas dari RDP. Loop dijeda; kontrol lokal tersedia lagi.')
            self.engine.save()
        self.wake.set()

    def update_lives(self):
        try:
            if not self.youtube.status().get('connected'):
                raise AppError('Hubungkan YouTube melalui dashboard lokal RDP dulu.')
            lives = self.youtube.lives()
            with self.lock:
                self.lives = lives
                self.lives_updated = time.time()
                self.lives_error = ''
        except AppError as exc:
            with self.lock:
                self.lives_error = str(exc)
            raise
        finally:
            self.inventory_due = time.time() + 300

    def execute(self, command):
        """Journal the command and its receipt in the SAME atomic state file as the loop."""
        command_id = str(command['id'])
        uuid.UUID(command_id)
        with self.engine.lock:
            if self.stop_event.is_set():
                raise AppError('Program sedang ditutup. Perintah CMS belum diproses.')
            data = self.engine.data
            receipts = data.setdefault('remote_receipts', [])
            prior = next((r for r in receipts if r['id'] == command_id), None)
            if prior:
                return copy.deepcopy(prior)
            journal = data.get('remote_journal')
            if journal and journal['id'] != command_id:
                raise AppError('Ada perintah lokal yang belum selesai. Recovery dilakukan sebelum menerima perintah lain.')
            if not journal:
                journal = copy.deepcopy(command)
                if command['action'] == 'next':
                    journal['before_mutation'] = data['mutation_seq']
                    if not data['titles']:
                        journal['target'] = None
                    else:
                        journal['target'] = data['pending_index'] if data['pending_index'] is not None else (data['current_index'] + 1) % len(data['titles'])
                data['remote_journal'] = journal
                self.engine.save()
            action, payload = journal['action'], journal.get('payload', {})
            result = {'id': command_id, 'ok': True, 'message': 'Perintah selesai diproses RDP.'}
            try:
                expected = payload.get('_expected_video_id')
                if expected and action in ('start', 'next', 'reset', 'end_live') and expected != data['video_id']:
                    raise AppError('Live/antrean di RDP berbeda. Simpan pengaturan CMS dulu dan ulangi perintah.')
                if action == 'configure':
                    self.engine.configure(payload)
                elif action == 'start':
                    self.engine.start()
                    if data['last_error']:
                        result['message'] = data['last_error'] + (' Retry lokal berjalan.' if data['running'] else ' Loop dijeda.')
                        result['ok'] = bool(data['running'])
                elif action == 'pause':
                    self.engine.pause()
                elif action == 'next':
                    target = journal.get('target')
                    if target is None or not data['titles'] or not data['video_id']:
                        raise AppError('Simpan antrean dan pilih live dulu.')
                    # If a crash happened AFTER the title commit, do not advance again.
                    if data['mutation_seq'] == journal['before_mutation']:
                        data['pending_index'] = target
                        self.engine._advance()
                    if data['last_error']:
                        result.update(ok=False, message=data['last_error'])
                elif action == 'reset':
                    self.engine.reset()
                elif action == 'end_live':
                    self.engine.end_live()
                elif action == 'refresh':
                    self.update_lives()
                else:
                    raise AppError('Perintah CMS tidak dikenal.')
            except AppError as exc:
                result.update(ok=False, message=str(exc))
            data['remote_receipts'] = (receipts + [result])[-100:]
            data['remote_journal'] = None
            self.engine.log('CMS · ' + action + ': ' + result['message'])
            self.engine.save()
            return result

    def payload(self):
        state = self.engine.snapshot()
        youtube = self.youtube.status()
        with self.lock:
            return {'agent_id': self.settings['agent_id'], 'receipts': state.get('remote_receipts', []),
                    'snapshot': {'state': {key: value for key, value in state.items() if not key.startswith('remote_')},
                                 'youtube': {'connected': youtube.get('connected', False), 'channel': youtube.get('channel', {})},
                                 'lives': copy.deepcopy(self.lives), 'lives_updated': self.lives_updated,
                                 'lives_error': self.lives_error}}

    def sync_once(self):
        with self.lock:
            settings = copy.deepcopy(self.settings)
        if not settings.get('enabled'):
            return False
        # Recover an interrupted command locally first; scheduler defers while the journal exists.
        with self.engine.lock:
            with self.lock:
                if settings != self.settings or self.stop_event.is_set():
                    return False
            journal = self.engine.data.get('remote_journal')
            if journal:
                self.execute(journal)
        response = cloud_request(settings['url'], settings['key'], self.payload())
        with self.engine.lock:
            with self.lock:
                if settings != self.settings or self.stop_event.is_set():
                    return False  # Ignore a response from a pairing that was disconnected/replaced.
                self.last_sync = time.time(); self.error = ''
            command = response.get('command')
            if command:
                self.execute(command)
                return True  # Immediate follow-up sends receipt and receives next queued command.
        return False

    def run(self):
        delay = 15
        while not self.stop_event.is_set():
            if self.enabled():
                try:
                    if time.time() >= self.inventory_due:
                        try:
                            self.update_lives()
                        except AppError:
                            pass
                    again = self.sync_once()
                    delay = 1 if again else 15
                except AppError as exc:
                    with self.lock:
                        self.error = str(exc)
                    if exc.reason in ('bridgeAuth', 'bridgeConflict'):
                        with self.engine.lock:
                            if self.engine.data['running']:
                                self.engine.pause()
                    delay = 30
                except Exception:
                    with self.lock:
                        self.error = 'Bridge gagal memproses sync. Cek ruang disk, pairing, dan setup CMS.'
                    with self.engine.lock:
                        self.engine.data.update(running=False, next_due=None)
                        try:
                            self.engine.save()
                        except OSError:
                            pass
                    delay = 30
            self.wake.wait(delay)
            self.wake.clear()

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
