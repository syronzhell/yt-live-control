import {createHmac,createHash,timingSafeEqual,randomUUID} from 'node:crypto';

export class Fault extends Error {
  constructor(message,status=400){super(message);this.status=status;}
}
export function equal(a,b){const x=Buffer.from(String(a||'')),y=Buffer.from(String(b||''));return x.length===y.length&&timingSafeEqual(x,y);}
export function config(env=process.env){
  env={...env,SUPABASE_SECRET_KEY:env.SUPABASE_SECRET_KEY||env.SUPABASE_SERVICE_ROLE_KEY};
  const names=['SUPABASE_URL','SUPABASE_SECRET_KEY','CMS_PASSWORD','SESSION_SECRET','AGENT_KEY','CMS_PUBLIC_URL'];
  if(names.some(k=>!env[k]))throw new Fault('Setup Vercel belum lengkap. Isi 6 environment variables sesuai panduan.',503);
  if(names.some(k=>/^(YOUR_|GENERATE_|CHOOSE_)/.test(env[k])))throw new Fault('Ganti nilai contoh environment variables dengan konfigurasi sendiri.',503);
  if(env.CMS_PASSWORD.length<12||env.SESSION_SECRET.length<32||env.AGENT_KEY.length<32||env.AGENT_KEY===env.SESSION_SECRET)throw new Fault('Password/secret terlalu pendek atau sama. Periksa environment variables.',503);
  let origin;
  try{origin=new URL(env.CMS_PUBLIC_URL).origin;const db=new URL(env.SUPABASE_URL);if(db.protocol!=='https:')throw Error();}catch{throw new Fault('URL konfigurasi tidak valid.',503);}
  if(!origin.startsWith('https://')&&!(env.NODE_ENV!=='production'&&/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(origin)))throw new Fault('CMS_PUBLIC_URL harus HTTPS.',503);
  return {...env,origin};
}
const hmac=(secret,value)=>createHmac('sha256',secret).update(value).digest('base64url');
function sessionKey(settings){return hmac(settings.SESSION_SECRET,settings.CMS_PASSWORD);}
export function newSession(settings,now=Date.now()){
  const payload=Buffer.from(JSON.stringify({id:randomUUID(),exp:Math.floor(now/1000)+43200})).toString('base64url');
  return payload+'.'+hmac(sessionKey(settings),payload);
}
export function verifySession(value,settings,now=Date.now()){
  if(typeof value!=='string'||value.length>1000)return null;
  const [payload,signature,extra]=value.split('.');
  if(extra||!payload||!equal(signature,hmac(sessionKey(settings),payload)))return null;
  try{const session=JSON.parse(Buffer.from(payload,'base64url').toString());return typeof session.id==='string'&&session.exp>Math.floor(now/1000)&&session.exp<=Math.floor(now/1000)+43200?session:null;}catch{return null;}
}
export function csrfToken(session,settings){return hmac(settings.SESSION_SECRET,'csrf:'+session.id);}
export function cookieValue(req){
  const parts=(req.headers.cookie||'').split(';').map(x=>x.trim());
  return parts.find(x=>x.startsWith('ytloop_session='))?.slice('ytloop_session='.length)||'';
}
export function cookie(token,settings,clear=false){
  return `ytloop_session=${token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${clear?0:43200}${settings.origin.startsWith('https:')?'; Secure':''}`;
}
export function originCheck(req,settings){if(req.headers.origin!==settings.origin)throw new Fault('Origin ditolak. Buka domain CMS_PUBLIC_URL yang dikonfigurasi.',403);}
export function requireSession(req,settings){const session=verifySession(cookieValue(req),settings);if(!session)throw new Fault('Login diperlukan.',401);return session;}
export function requireCsrf(req,session,settings){originCheck(req,settings);if(!equal(req.headers['x-csrf-token'],csrfToken(session,settings)))throw new Fault('Sesi tidak valid. Refresh dashboard dan login ulang.',403);}
export function loginHash(req,settings){
  const ip=String(req.headers['x-forwarded-for']||req.socket?.remoteAddress||'unknown').split(',')[0].trim();
  return createHash('sha256').update(settings.SESSION_SECRET+':'+ip).digest('hex');
}
