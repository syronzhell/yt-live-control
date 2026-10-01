import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core import AppError, Engine, SecretStore, YouTube, title_payload, validate_title


class Clock:
    value = 1000
    def __call__(self): return self.value


class FakeYouTube:
    def __init__(self): self.calls=[]; self.error=None; self.active=True
    def assert_live(self, video_id):
        if not self.active: raise AppError("Live selesai", reason="notLive")
    def set_title(self, video_id, title):
        self.assert_live(video_id)
        if self.error: raise self.error
        self.calls.append(title)
    def end_live(self, video_id): self.assert_live(video_id); self.active=False


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.folder=Path(self.temp.name)
        self.clock=Clock(); self.api=FakeYouTube(); self.engine=Engine(self.folder,self.api,self.clock)
        self.config={"video_id":"abcdefghijk","video_title":"Old","titles":["A","B","C"],"interval_minutes":10}
        self.engine.configure(self.config)
    def tearDown(self): self.temp.cleanup()
    def advance(self,seconds=600): self.clock.value+=seconds; self.engine.tick()
    def test_queue_wrap_and_no_early_update(self):
        self.engine.start(); self.advance(599); self.assertEqual(self.api.calls,["A"])
        self.advance(1); self.advance(); self.advance()
        self.assertEqual(self.api.calls,["A","B","C","A"]); self.assertEqual(self.engine.data["cycles"],1)
    def test_pause_resume_does_not_skip_title(self):
        self.engine.start(); self.engine.pause(); self.advance(1000); self.assertEqual(self.api.calls,["A"])
        self.engine.start(); self.assertEqual(self.api.calls,["A"]); self.advance(); self.assertEqual(self.api.calls,["A","B"])
    def test_retry_keeps_target_then_success(self):
        self.engine.start(); self.api.error=AppError("Network",True); self.advance()
        self.assertEqual(self.engine.data["current_index"],0); self.assertEqual(self.engine.data["pending_index"],1)
        self.assertEqual(self.engine.data["next_due"],self.clock.value+30)
        self.api.error=None; self.advance(30)
        self.assertEqual(self.api.calls,["A","B"]); self.assertIsNone(self.engine.data["pending_index"])
    def test_retry_limit_pauses_without_skipping(self):
        self.api.error=AppError("Network",True); self.engine.start()
        for delay in [30,60,120]: self.advance(delay)
        self.assertFalse(self.engine.data["running"]); self.assertEqual(self.engine.data["current_index"],-1)
        self.api.error=None; self.engine.start(); self.assertEqual(self.api.calls,["A"])
    def test_quota_error_pauses_immediately(self):
        self.api.error=AppError("Quota",False,"quotaExceeded"); self.engine.start()
        self.assertFalse(self.engine.data["running"]); self.assertEqual(self.engine.data["pending_index"],0)
    def test_restart_catches_up_once(self):
        self.engine.start(); self.clock.value+=7200
        restored=Engine(self.folder,self.api,self.clock); restored.tick(); restored.tick()
        self.assertEqual(self.api.calls,["A","B"])
    def test_restart_pending_intent_recovers_same_title(self):
        self.engine.start(); self.api.error=AppError("Timeout",True); self.advance()
        self.api.error=None; self.clock.value+=31; restored=Engine(self.folder,self.api,self.clock);restored.tick()
        self.assertEqual(self.api.calls,["A","B"])
    def test_manual_next_while_paused_stays_paused(self):
        self.engine.next_now(); self.assertFalse(self.engine.data["running"])
        self.assertEqual(self.api.calls,["A"]); self.assertIsNone(self.engine.data["next_due"])
    def test_edit_running_blocked(self):
        self.engine.start()
        with self.assertRaises(AppError): self.engine.configure(self.config)
    def test_stop_pauses_loop_and_ends_live(self):
        self.engine.start(); self.engine.end_live(); self.assertFalse(self.api.active);self.assertFalse(self.engine.data["running"])
    def test_live_ends_health_check_pauses_loop(self):
        self.engine.start();self.api.active=False;self.advance(301);self.assertFalse(self.engine.data["running"])
    def test_reset_starts_first(self):
        self.engine.start();self.advance();self.engine.pause();self.engine.reset();self.engine.start()
        self.assertEqual(self.api.calls,["A","B","A"])
    def test_invalid_intervals_rejected(self):
        for value in [float('nan'),float('inf'),0,9,43201,'invalid']:
            with self.subTest(value=value),self.assertRaises(AppError): self.engine.configure({**self.config,"interval_minutes":value})
    def test_corrupt_state_does_not_silently_reset(self):
        (self.folder/'state.json').write_text('invalid')
        with self.assertRaises(AppError):Engine(self.folder,self.api,self.clock)


class ApiTests(unittest.TestCase):
    def test_title_validation_unicode(self):
        self.assertEqual(validate_title('  音楽 🎵  '),'音楽 🎵')
        for value in ['', 'a'*101, '<bad>', 'line\nline', 99]:
            with self.subTest(value=value),self.assertRaises(AppError):validate_title(value)
    def test_metadata_preserved_and_readonly_omitted(self):
        snippet={"title":"Old","description":"Keep\nhttps://example.com","tags":["a","b"],"categoryId":"10",
                 "defaultLanguage":"id","defaultAudioLanguage":"en","channelId":"c","thumbnails":{"x":"y"}}
        old=copy.deepcopy(snippet);result=title_payload({"id":"v","snippet":snippet},'New')
        self.assertEqual(snippet,old);self.assertEqual(result['snippet']['title'],'New')
        for key in ['description','tags','categoryId','defaultLanguage','defaultAudioLanguage']:self.assertEqual(result['snippet'][key],old[key])
        self.assertNotIn('status',result);self.assertNotIn('thumbnails',result['snippet']);self.assertNotIn('channelId',result['snippet'])
    def test_missing_category_aborts(self):
        with self.assertRaises(AppError):title_payload({'id':'v','snippet':{'title':'old'}},'New')
    def test_retry_already_applied_title_skips_put(self):
        with tempfile.TemporaryDirectory() as folder:
            api=YouTube(Path(folder)); calls=[]
            def call(method,resource,params,body=None):
                calls.append((method,resource))
                if resource=='liveBroadcasts':return {'items':[{'status':{'lifeCycleStatus':'live'}}]}
                return {'items':[{'id':'v','snippet':{'title':'Same','categoryId':'10'}}]}
            api.call=call;api.set_title('v','Same');self.assertNotIn(('PUT','videos'),calls)
    def test_active_list_uses_one_filter_and_pagination(self):
        with tempfile.TemporaryDirectory() as folder:
            api=YouTube(Path(folder));calls=[]
            def call(method,resource,params):
                calls.append(params)
                return {'items':[{'id':str(len(calls)),'snippet':{'title':'X'},'status':{'lifeCycleStatus':'live'}}],**({'nextPageToken':'p2'} if len(calls)==1 else {})}
            api.call=call;self.assertEqual(len(api.lives()),2)
            self.assertNotIn('mine',calls[0]);self.assertEqual(calls[1]['pageToken'],'p2')
    def test_import_only_desktop_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            api=YouTube(Path(folder))
            with self.assertRaises(AppError):api.import_client({'web':{'client_id':'abc'}})
    def test_secret_store_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            store=SecretStore(Path(folder)/'credentials.json');store.save({'refresh_token':'test-token'});self.assertEqual(store.load()['refresh_token'],'test-token')


if __name__=='__main__': unittest.main()
