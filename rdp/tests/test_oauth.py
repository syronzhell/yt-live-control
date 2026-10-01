import base64
import hashlib
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs,urlparse,urlencode
from urllib.request import urlopen
from urllib.error import HTTPError
from core import YouTube


class OAuthTests(unittest.TestCase):
    def test_pkce_state_loopback_and_offline_token(self):
        with tempfile.TemporaryDirectory() as folder:
            api=YouTube(Path(folder))
            api.import_client({'installed':{'client_id':'test.apps.googleusercontent.com','client_secret':'test'}})
            captured=[]
            def transport(method,url,payload=None,headers=None,form=False):
                captured.append((method,url,payload))
                if 'oauth2.googleapis.com/token' in url:
                    return {'access_token':'fake-access','refresh_token':'fake-refresh','expires_in':3600}
                return {'items':[{'id':'channel123','snippet':{'title':'Test channel'}}]}
            with patch('core.request_json',side_effect=transport):
                login=api.begin_auth();args=parse_qs(urlparse(login).query)
                self.assertEqual(args['code_challenge_method'],['S256'])
                self.assertEqual(args['access_type'],['offline'])
                redirect=args['redirect_uri'][0];self.assertEqual(urlparse(redirect).hostname,'127.0.0.1')
                with self.assertRaises(HTTPError) as exc:urlopen(redirect+'?state=wrong&code=attack')
                self.assertEqual(exc.exception.code,400)
                with urlopen(redirect+'?'+urlencode({'state':args['state'][0],'code':'valid-code'})) as response:
                    self.assertEqual(response.status,200)
                deadline=time.monotonic()+3
                while api.status()['auth_pending'] and time.monotonic()<deadline:time.sleep(.01)
                self.assertFalse(api.status()['auth_pending']);self.assertTrue(api.status()['connected'])
                self.assertEqual(api.status()['channel']['title'],'Test channel')
                exchange=captured[0][2]
                verifier=exchange['code_verifier']
                challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
                self.assertEqual(challenge,args['code_challenge'][0])
                self.assertEqual(exchange['code'],'valid-code')
                self.assertEqual(YouTube(Path(folder)).status()['connected'],True)
    def test_cancel_does_not_create_token(self):
        with tempfile.TemporaryDirectory() as folder:
            api=YouTube(Path(folder));api.import_client({'installed':{'client_id':'test.apps.googleusercontent.com','client_secret':'test'}})
            login=api.begin_auth();args=parse_qs(urlparse(login).query)
            with urlopen(args['redirect_uri'][0]+'?'+urlencode({'state':args['state'][0],'error':'access_denied'})) as response:self.assertEqual(response.status,200)
            deadline=time.monotonic()+3
            while api.status()['auth_pending'] and time.monotonic()<deadline:time.sleep(.01)
            self.assertFalse(api.status()['connected']);self.assertIn('dibatalkan',api.status()['auth_message'])


if __name__=='__main__':unittest.main()
