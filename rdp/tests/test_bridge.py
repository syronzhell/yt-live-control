import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid
from core import AppError,Engine,YouTube
from bridge import Bridge
from test_core import FakeYouTube,Clock


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name);self.api=FakeYouTube();self.clock=Clock()
        self.api.status=lambda:{'connected':True,'channel':{'title':'Test'},'refresh_token':'private'}
        self.api.lives=lambda:[{'id':'abcdefghijk','title':'Old','status':'live'}]
        self.engine=Engine(self.folder,self.api,self.clock);self.stop=threading.Event();self.bridge=Bridge(self.folder,self.engine,self.api,self.stop)
        self.config={'video_id':'abcdefghijk','video_title':'Old','titles':['A','B','C'],'interval_minutes':10}
        self.engine.configure(self.config)
    def tearDown(self):self.stop.set();self.temp.cleanup()
    def command(self,action,payload=None):return {'id':str(uuid.uuid4()),'action':action,'payload':payload or {'_expected_video_id':'abcdefghijk'}}
    def test_pairing_pauses_and_secret_not_in_status_or_payload(self):
        self.engine.start();self.bridge.configure('https://test.vercel.app','x'*40)
        self.assertFalse(self.engine.data['running']);self.assertTrue(self.bridge.status()['enabled'])
        self.assertNotIn('x'*40,json.dumps(self.bridge.status()));self.assertNotIn('private',json.dumps(self.bridge.payload()))
    def test_pairing_rejects_http_and_redirect_paths(self):
        for url in ['http://example.com','https://test.vercel.app/path','https://u:p@test.vercel.app','https://test.vercel.app?key=x']:
            with self.subTest(url=url),self.assertRaises(AppError):self.bridge.configure(url,'x'*40)
    def test_repeated_next_command_advances_once(self):
        self.engine.start();command=self.command('next');first=self.bridge.execute(command);second=self.bridge.execute(command)
        self.assertEqual(first,second);self.assertEqual(self.api.calls,['A','B']);self.assertEqual(self.engine.data['current_index'],1)
    def test_single_item_next_still_commits_once(self):
        self.engine.configure({**self.config,'titles':['A']});self.engine.start();command=self.command('next')
        self.bridge.execute(command);self.bridge.execute(command);self.assertEqual(self.engine.data['mutation_seq'],2);self.assertEqual(self.api.calls,['A','A'])
    def test_command_receipt_survives_restart(self):
        self.engine.start();command=self.command('next');self.bridge.execute(command)
        restored=Engine(self.folder,self.api,self.clock);bridge=Bridge(self.folder,restored,self.api,self.stop);bridge.execute(command)
        self.assertEqual(self.api.calls,['A','B'])
    def test_crash_after_title_commit_before_receipt_does_not_advance_again(self):
        self.engine.start();command=self.command('next');original=self.engine.save
        def crash_after_commit():
            original()
            if self.engine.data['current_index']==1 and self.engine.data.get('remote_journal'):
                raise OSError('simulated crash')
        self.engine.save=crash_after_commit
        with self.assertRaises(OSError):self.bridge.execute(command)
        restored=Engine(self.folder,self.api,self.clock);bridge=Bridge(self.folder,restored,self.api,self.stop);bridge.execute(command)
        self.assertEqual(self.api.calls,['A','B']);self.assertIsNone(restored.data['remote_journal']);self.assertTrue(restored.data['remote_receipts'][-1]['ok'])
    def test_scheduler_waits_for_journal_recovery(self):
        self.engine.start();self.engine.data['remote_journal']=self.command('pause');self.clock.value+=600;self.engine.tick()
        self.assertEqual(self.api.calls,['A'])
    def test_mismatched_live_cannot_be_changed(self):
        self.engine.start();result=self.bridge.execute(self.command('next',{'_expected_video_id':'otherlive12'}))
        self.assertFalse(result['ok']);self.assertEqual(self.api.calls,['A'])
    def test_sync_replayed_command_uses_stored_receipt(self):
        self.bridge.configure('https://test.vercel.app','x'*40);self.engine.start();command=self.command('next');seen=[]
        def cloud(url,key,payload):seen.append(copy.deepcopy(payload));return {'command':command}
        with patch('bridge.cloud_request',side_effect=cloud):self.bridge.sync_once();self.bridge.sync_once()
        self.assertEqual(self.api.calls,['A','B']);self.assertEqual(seen[-1]['receipts'][-1]['id'],command['id'])
    def test_rejected_pairing_pauses_loop(self):
        self.bridge.configure('https://test.vercel.app','x'*40);self.engine.start()
        def reject(*_):self.stop.set();raise AppError('Bad key',reason='bridgeAuth')
        with patch('bridge.cloud_request',side_effect=reject):
            self.bridge.wake.set();self.bridge.run()
        self.assertFalse(self.engine.data['running'])
    def test_disconnect_is_local_emergency_pause(self):
        self.bridge.configure('https://test.vercel.app','x'*40);self.engine.start();self.bridge.disconnect()
        self.assertFalse(self.engine.data['running']);self.assertFalse(self.bridge.enabled())
    def test_shutdown_cannot_receive_a_late_start(self):
        self.stop.set()
        with self.assertRaises(AppError):self.bridge.execute(self.command('start'))
        self.assertFalse(self.engine.data['running']);self.assertEqual(self.api.calls,[])
    def test_emergency_unpair_clears_journal_and_keeps_failed_receipt(self):
        command=self.command('next');self.engine.data['remote_journal']=command;self.engine.save()
        self.bridge.disconnect()
        self.assertIsNone(self.engine.data['remote_journal']);self.assertFalse(self.engine.data['remote_receipts'][-1]['ok'])
        self.assertEqual(self.engine.data['remote_receipts'][-1]['id'],command['id'])
    def test_completed_youtube_stop_is_idempotent(self):
        api=YouTube(self.folder);calls=[]
        def call(method,resource,params,body=None):calls.append(method);return {'items':[{'status':{'lifeCycleStatus':'complete'}}]}
        api.call=call;api.end_live('abcdefghijk');self.assertEqual(calls,['GET'])


if __name__=='__main__':unittest.main()
