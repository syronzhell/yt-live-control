import {config,Fault,equal,newSession,cookie,originCheck,requireSession,requireCsrf,csrfToken,loginHash} from '../lib/security.js';
import {validConfig,uuid,safeSnapshot,safeReceipts,ACTIONS,videoId} from '../lib/validation.js';
import {Database} from '../lib/database.js';

async function body(req){
  if(!String(req.headers['content-type']||'').startsWith('application/json'))throw new Fault('Format permintaan harus JSON.');
  if(Number(req.headers['content-length']||0)>180000)throw new Fault('Permintaan terlalu besar.',413);
  let result;
  try{
    if(req.body!==undefined)result=typeof req.body==='string'?JSON.parse(req.body):req.body;
    else {const parts=[];let length=0;for await(const chunk of req){length+=chunk.length;if(length>180000)throw new Fault('Permintaan terlalu besar.',413);parts.push(chunk);}result=JSON.parse(Buffer.concat(parts).toString()||'{}');}
  }catch(error){if(error instanceof Fault)throw error;throw new Fault('JSON tidak valid.');}
  if(!result||typeof result!=='object'||Array.isArray(result))throw new Fault('JSON tidak valid.');return result;
}
export function createHandler({env=process.env,dbFactory=settings=>new Database(settings)}={}){
  return async function handler(req,res){
    res.setHeader('Content-Type','application/json; charset=utf-8');res.setHeader('Cache-Control','no-store');res.setHeader('X-Content-Type-Options','nosniff');
    const send=(data,status=200)=>{res.statusCode=status;res.end(JSON.stringify(data));};
    try{
      const settings=config(env),db=dbFactory(settings);
      const parsed=new URL(req.url,'http://local');
      const route=String(req.query?.path||parsed.searchParams.get('path')||parsed.pathname.replace(/^\/api\//,'')).replace(/^\/+|\/+$/g,'');
      if(route==='agent/sync'){
        if(req.method!=='POST')throw new Fault('Method ditolak.',405);
        if(!equal(req.headers.authorization,'Bearer '+settings.AGENT_KEY))throw new Fault('Agent key tidak valid.',401);
        const input=await body(req),id=uuid(input.agent_id);
        const result=await db.rpc('ytloop_sync',{p_agent:id,p_snapshot:safeSnapshot(input.snapshot),p_receipts:safeReceipts(input.receipts)});
        send(result);return;
      }
      if(route==='login'){
        if(req.method!=='POST')throw new Fault('Method ditolak.',405);
        originCheck(req,settings);const input=await body(req);
        await db.rpc('ytloop_login_gate',{p_key:loginHash(req,settings)});
        if(!equal(input.password,settings.CMS_PASSWORD))throw new Fault('Password salah.',401);
        const token=newSession(settings);res.setHeader('Set-Cookie',cookie(token,settings));send({ok:true});return;
      }
      const session=requireSession(req,settings);
      if(route==='status'){
        if(req.method!=='GET')throw new Fault('Method ditolak.',405);
        send({...(await db.dashboard()),csrf:csrfToken(session,settings),server_time:Date.now()/1000,version:'2.0.0'});return;
      }
      if(req.method!=='POST')throw new Fault('Method ditolak.',405);
      requireCsrf(req,session,settings);const input=await body(req);
      if(route==='logout'){res.setHeader('Set-Cookie',cookie('',settings,true));send({ok:true});return;}
      if(route!=='command')throw new Fault('Halaman tidak ditemukan.',404);
      if(!ACTIONS.has(input.action))throw new Fault('Perintah tidak valid.');
      const requestId=uuid(input.request_id);
      let payload={};
      if(input.action==='configure')payload=validConfig(input.payload);
      if(input.action==='end_live')payload={confirmation:videoId(input.payload?.confirmation)};
      const result=await db.rpc('ytloop_enqueue',{p_action:input.action,p_payload:payload,p_request:requestId});
      send({ok:true,...result});
    }catch(error){send({error:error instanceof Fault?error.message:'Kesalahan internal. Periksa setup Vercel/Supabase.',uncertain:error?.status===503},error instanceof Fault?error.status:500);}
  };
}
export default createHandler();
