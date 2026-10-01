import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from server import make_server


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.server=make_server(0,True,Path(self.temp.name))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=self.server.origin
        with urlopen(self.url) as response:self.html=response.read().decode()
        self.token=re.search(r'name="app-token" content="([^"]+)"',self.html)[1]
    def tearDown(self):
        self.server.stop_event.set();self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
    def post(self,path,payload=None,token=None,origin=None):
        headers={'Content-Type':'application/json','X-App-Token':self.token if token is None else token,'Origin':origin or self.url}
        with urlopen(Request(self.url+'/api/'+path,json.dumps(payload or {}).encode(),headers,method='POST')) as response:return json.loads(response.read())
    def test_missing_token_rejected(self):
        with self.assertRaises(HTTPError) as exc:self.post('pause',token='wrong')
        self.assertEqual(exc.exception.code,403)
    def test_cross_origin_rejected(self):
        with self.assertRaises(HTTPError) as exc:self.post('pause',origin='https://evil.example')
        self.assertEqual(exc.exception.code,403)
    def test_configure_start_and_pause(self):
        self.post('configure',{'titles':['First','Second'],'interval_minutes':10,'video_id':'DEMOlive001','video_title':'Demo'})
        self.post('start');self.assertTrue(self.server.engine.snapshot()['running'])
        self.assertEqual(self.server.youtube.title,'First')
        self.post('pause');self.assertFalse(self.server.engine.snapshot()['running'])
    def test_live_end_requires_confirmation(self):
        self.post('configure',{'titles':['First'],'interval_minutes':10,'video_id':'DEMOlive001'})
        with self.assertRaises(HTTPError):self.post('end-live',{'confirmation':'wrong'})
        self.assertTrue(self.server.youtube.active)
        self.post('end-live',{'confirmation':'DEMOlive001'});self.assertFalse(self.server.youtube.active)
    def test_public_status_never_exposes_credentials(self):
        with urlopen(self.url+'/api/status') as response: data=response.read().decode()
        self.assertNotIn('access_token',data);self.assertNotIn('refresh_token',data);self.assertNotIn('client_secret',data)
    def test_host_rebinding_rejected(self):
        with self.assertRaises(HTTPError) as exc:urlopen(Request(self.url,headers={'Host':'attacker.example'}))
        self.assertEqual(exc.exception.code,403)


if __name__=='__main__':unittest.main()
