"""End-to-end HTTP test: real CMS handlers + real RDP bridge; demo DB/YouTube only."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
import uuid

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'rdp'))
from core import Engine
from server import DemoYouTube
from bridge import Bridge


def main():
    node=os.environ.get('CODEX_PRIMARY_RUNTIME_NODE') or shutil.which('node')
    if not node:raise RuntimeError('Node.js 22 diperlukan untuk tes developer.')
    with socket.socket() as socket_probe:
        socket_probe.bind(('127.0.0.1',0));port=socket_probe.getsockname()[1]
    url=f'http://127.0.0.1:{port}'
    process=subprocess.Popen([node,'dev.mjs','--demo'],cwd=ROOT/'cms',env={**os.environ,'PORT':str(port)},stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    cookie='';csrf=''
    def request(route,payload=None):
        headers={'Content-Type':'application/json','Origin':url}
        if cookie:headers['Cookie']=cookie
        if csrf:headers['X-CSRF-Token']=csrf
        raw=None if payload is None else json.dumps(payload).encode()
        with urlopen(Request(url+'/api/'+route,raw,headers,method='GET' if payload is None else 'POST'),timeout=5) as response:
            return json.loads(response.read()),response.headers
    try:
        deadline=time.monotonic()+8
        while True:
            try:request('status')
            except HTTPError as exc:
                if exc.code==401:break
                raise
            except URLError:
                if time.monotonic()>deadline:raise
                time.sleep(.05)
        _,headers=request('login',{'password':'demo-title-loop'});cookie=headers['Set-Cookie'].split(';')[0]
        csrf=request('status')[0]['csrf']
        with tempfile.TemporaryDirectory() as folder:
            youtube=DemoYouTube();engine=Engine(Path(folder),youtube);stop=threading.Event();bridge=Bridge(Path(folder),engine,youtube,stop,allow_local=True)
            bridge.configure(url,'demo-agent-key-012345678901234567890');bridge.update_lives();bridge.sync_once()
            dashboard=request('status')[0];assert dashboard['agent_id']==bridge.settings['agent_id'];assert dashboard['snapshot']['lives'][0]['id']=='DEMOlive001'
            def send(action,payload=None,command_id=None):
                command_id=command_id or str(uuid.uuid4())
                return request('command',{'action':action,'payload':payload or {},'request_id':command_id})[0]
            def deliver():
                bridge.sync_once();bridge.sync_once()
            saved=send('configure',{'video_id':'DEMOlive001','video_title':'Demo','titles':['A','B','C'],'interval_minutes':10});deliver()
            assert request('status')[0]['commands'][0]['status']=='done'
            send('start');deliver();assert youtube.title=='A';assert engine.data['running']
            identifier=str(uuid.uuid4());send('next',command_id=identifier);duplicate=send('next',command_id=identifier);assert duplicate['duplicate'];deliver();assert youtube.title=='B'
            send('next');deliver();assert youtube.title=='C'
            send('next');deliver();assert youtube.title=='A';assert engine.data['cycles']==1
            send('pause');deliver();assert not engine.data['running']
            start=send('start');pause=send('pause');deliver();assert not engine.data['running']
            tasks=request('status')[0]['commands'];assert next(x for x in tasks if x['id']==start['id'])['status']=='cancelled'
            # Restart/replay an already processed request cannot consume another title.
            restored=Engine(Path(folder),youtube);recovered=Bridge(Path(folder),restored,youtube,stop,allow_local=True)
            before=restored.data['mutation_seq'];recovered.execute({'id':identifier,'action':'next','payload':{'_expected_video_id':'DEMOlive001'}})
            assert restored.data['mutation_seq']==before
            send('end_live',{'confirmation':'DEMOlive001'});bridge.sync_once();bridge.sync_once();assert not youtube.active
            final=request('status')[0];assert not final['snapshot']['state']['running'];assert final['commands'][0]['status']=='done'
            assert 'refresh_token' not in json.dumps(final);assert 'agent_key' not in json.dumps(final)
        print('Integration PASS: CMS login → agent pairing/heartbeat → config → loop start → next/wrap → idempotent retry → pause/cancel → restart/replay → stop/ack.')
    finally:
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':main()
