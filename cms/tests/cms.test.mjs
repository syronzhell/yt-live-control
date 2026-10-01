import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {once} from 'node:events';
import {randomUUID} from 'node:crypto';
import {createHandler} from '../api/index.js';
import {DemoStore} from '../demo-store.js';
import {config,newSession,verifySession,csrfToken} from '../lib/security.js';
import {validConfig,safeSnapshot} from '../lib/validation.js';
import {Database} from '../lib/database.js';

const settings={NODE_ENV:'development',SUPABASE_URL:'https://demo.supabase.co',SUPABASE_SERVICE_ROLE_KEY:'test-db-key',CMS_PASSWORD:'private-test-password',SESSION_SECRET:'test-session-012345678901234567890',AGENT_KEY:'test-agent-key-012345678901234567890',CMS_PUBLIC_URL:'http://127.0.0.1:3000'};
const sample={video_id:'abcdefghijk',video_title:'Old',titles:['A','B','C'],interval_minutes:180};
test('session signature, expiry and password rotation',()=>{
  const token=newSession(settings,1000000);assert.ok(verifySession(token,settings,1000001));
  assert.equal(verifySession(token+'bad',settings,1000001),null);assert.equal(verifySession(token,settings,1000000+43200001),null);
  assert.equal(verifySession(token,{...settings,CMS_PASSWORD:'rotated-password'},1000001),null);
});
test('configuration rejects unsafe secrets/URLs',()=>{
  assert.throws(()=>config({...settings,AGENT_KEY:'short'}));assert.throws(()=>config({...settings,CMS_PUBLIC_URL:'http://example.com'}));assert.throws(()=>config({...settings,AGENT_KEY:settings.SESSION_SECRET}));
});
test('config validation supports Unicode and rejects invalid titles/intervals',()=>{
  assert.equal(validConfig({...sample,titles:['音楽 🎵']}).titles[0],'音楽 🎵');
  for(const titles of [[],['<script>'],['x'.repeat(101)],['line\nline']])assert.throws(()=>validConfig({...sample,titles}));
  for(const interval_minutes of [0,9,Infinity,NaN])assert.throws(()=>validConfig({...sample,interval_minutes}));
});
test('snapshot whitelist strips all credentials',()=>{
  const result=safeSnapshot({state:{access_token:'secret',titles:['A'],logs:[]},youtube:{refresh_token:'secret',channel:{title:'X'},connected:true},key:'secret'});
  assert.equal(JSON.stringify(result).includes('secret'),false);assert.equal(result.youtube.channel.title,'X');
});
test('new Supabase secret key is sent only as apikey',async t=>{
  let sent;t.mock.method(globalThis,'fetch',async(url,options)=>{sent=options.headers;return new Response('{}',{status:200});});
  const db=new Database({...settings,SUPABASE_SECRET_KEY:'sb_secret_test-only'});await db.rpc('test',{});
  assert.equal(sent.apikey,'sb_secret_test-only');assert.equal(sent.Authorization,undefined);
});
test('legacy Supabase JWT uses Bearer and apikey',async t=>{
  let sent;t.mock.method(globalThis,'fetch',async(url,options)=>{sent=options.headers;return new Response('{}',{status:200});});
  const db=new Database({...settings,SUPABASE_SECRET_KEY:'legacy-test-jwt'});await db.rpc('test',{});
  assert.equal(sent.Authorization,'Bearer legacy-test-jwt');assert.equal(sent.apikey,'legacy-test-jwt');
});
test('queue idempotency, ordered delivery, ack, pause cancellation and agent binding',async()=>{
  const store=new DemoStore();const agent=randomUUID(),request=randomUUID();
  await store.rpc('ytloop_sync',{p_agent:agent,p_snapshot:{state:{running:false}},p_receipts:[]});
  await store.rpc('ytloop_enqueue',{p_action:'configure',p_payload:sample,p_request:request});
  const duplicate=await store.rpc('ytloop_enqueue',{p_action:'configure',p_payload:sample,p_request:request});assert.equal(duplicate.duplicate,true);assert.equal(store.commands.length,1);
  const first=await store.rpc('ytloop_sync',{p_agent:agent,p_snapshot:{state:{running:false}},p_receipts:[]});assert.equal(first.command.id,request);
  const repeated=await store.rpc('ytloop_sync',{p_agent:agent,p_snapshot:{state:{running:false}},p_receipts:[]});assert.equal(repeated.command.id,request);
  const done=await store.rpc('ytloop_sync',{p_agent:agent,p_snapshot:{state:{running:false}},p_receipts:[{id:request,ok:true,message:'Done'}]});assert.equal(done.command,null);assert.equal(store.commands[0].status,'done');
  await store.rpc('ytloop_enqueue',{p_action:'start',p_payload:{},p_request:randomUUID()});await store.rpc('ytloop_enqueue',{p_action:'pause',p_payload:{},p_request:randomUUID()});assert.equal(store.commands[1].status,'cancelled');
  await assert.rejects(store.rpc('ytloop_sync',{p_agent:randomUUID(),p_snapshot:{},p_receipts:[]}));
});
test('offline commands and stale stop do not run blindly',async()=>{
  let time=1000000;const store=new DemoStore(()=>time);await assert.rejects(store.rpc('ytloop_enqueue',{p_action:'start',p_payload:{},p_request:randomUUID()}));
  const agent=randomUUID();await store.rpc('ytloop_sync',{p_agent:agent,p_snapshot:{state:{running:false,video_id:'abcdefghijk'}},p_receipts:[]});
  await store.rpc('ytloop_enqueue',{p_action:'configure',p_payload:sample,p_request:randomUUID()});
  const configCmd=(await store.rpc('ytloop_sync',{p_agent:agent,p_snapshot:{state:{running:false}},p_receipts:[]})).command;
  await store.rpc('ytloop_sync',{p_agent:agent,p_snapshot:{state:{running:false,video_id:'abcdefghijk'}},p_receipts:[{id:configCmd.id,ok:true,message:'ok'}]});
  await assert.rejects(store.rpc('ytloop_enqueue',{p_action:'end_live',p_payload:{confirmation:'wrongwrong1'},p_request:randomUUID()}));
  await store.rpc('ytloop_enqueue',{p_action:'end_live',p_payload:{confirmation:'abcdefghijk'},p_request:randomUUID()});time+=120001;
  const result=await store.rpc('ytloop_sync',{p_agent:agent,p_snapshot:{},p_receipts:[]});assert.equal(result.command,null);assert.equal(store.commands.at(-1).status,'expired');
});
test('HTTP auth, CSRF, agent auth, login throttle and command flow',async()=>{
  const env={...settings},store=new DemoStore(),handler=createHandler({env,dbFactory:()=>store});
  const server=createServer(handler);server.listen(0,'127.0.0.1');await once(server,'listening');
  const url=`http://127.0.0.1:${server.address().port}`;env.CMS_PUBLIC_URL=url;let sessionCookie='',csrf='';
  async function request(route,payload,headers={}){const response=await fetch(url+'/api/'+route,{method:payload===undefined?'GET':'POST',headers:{'Content-Type':'application/json',Origin:url,...(sessionCookie?{Cookie:sessionCookie}:{}),...(csrf?{'X-CSRF-Token':csrf}:{}),...headers},body:payload===undefined?undefined:JSON.stringify(payload)});return {response,json:await response.json()};}
  try{
    assert.equal((await request('status')).response.status,401);
    assert.equal((await request('login',{password:env.CMS_PASSWORD},{Origin:'https://evil.example'})).response.status,403);
    assert.equal((await request('login',{password:'wrong'})).response.status,401);
    const login=await request('login',{password:env.CMS_PASSWORD});assert.equal(login.response.status,200);sessionCookie=login.response.headers.get('set-cookie').split(';')[0];assert.match(login.response.headers.get('set-cookie'),/HttpOnly; SameSite=Strict/);
    const status=await request('status');csrf=status.json.csrf;assert.ok(csrf);
    assert.equal((await request('command',{action:'pause',request_id:randomUUID()},{'X-CSRF-Token':'wrong'})).response.status,403);
    const agent=randomUUID(),syncBody={agent_id:agent,snapshot:{state:{running:false},youtube:{connected:true}},receipts:[]};
    assert.equal((await request('agent/sync',syncBody,{Authorization:'Bearer wrong'})).response.status,401);
    assert.equal((await request('agent/sync',syncBody,{Authorization:'Bearer '+env.AGENT_KEY})).response.status,200);
    const id=randomUUID();const configure=await request('command',{action:'configure',request_id:id,payload:sample});assert.equal(configure.response.status,200);
    const duplicate=await request('command',{action:'configure',request_id:id,payload:sample});assert.equal(duplicate.json.duplicate,true);
    const command=(await request('agent/sync',syncBody,{Authorization:'Bearer '+env.AGENT_KEY})).json.command;assert.equal(command.id,id);
    syncBody.receipts=[{id,ok:true,message:'Configured'}];const ack=await request('agent/sync',syncBody,{Authorization:'Bearer '+env.AGENT_KEY});assert.equal(ack.json.command,null);
    const dashboard=await request('status');assert.equal(dashboard.json.commands[0].status,'done');assert.equal(dashboard.json.config.titles[1],'B');
    await request('logout',{});sessionCookie='';assert.equal((await request('status')).response.status,401);
    for(let i=0;i<6;i++)await request('login',{password:'wrong'});
    assert.equal((await request('login',{password:'wrong'})).response.status,429);
  }finally{server.close();server.closeAllConnections();await once(server,'close');}
});
