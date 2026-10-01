import {Fault} from './security.js';
export const ACTIONS=new Set(['configure','start','pause','next','reset','end_live','refresh']);
export function videoId(id){if(typeof id!=='string'||!/^[a-zA-Z0-9_-]{11}$/.test(id))throw new Fault('Pilih live aktif dari RDP.');return id;}
export function validConfig(raw){
  if(!raw||!Array.isArray(raw.titles)||raw.titles.length<1||raw.titles.length>500)throw new Fault('Isi 1–500 judul.');
  const titles=raw.titles.map(title=>{
    if(typeof title!=='string')throw new Fault('Judul harus berupa teks.');
    title=title.trim();if(!title||[...title].length>100||/[<>\x00-\x1f]/.test(title))throw new Fault('Judul wajib 1–100 karakter, satu baris, tanpa < atau >.');
    return title;
  });
  const minutes=Number(raw.interval_minutes);
  if(!Number.isFinite(minutes)||minutes<10||minutes>43200)throw new Fault('Interval 10 menit sampai 30 hari.');
  return {video_id:videoId(raw.video_id),video_title:String(raw.video_title||'').slice(0,100),titles,interval_minutes:minutes};
}
export function uuid(value){if(typeof value!=='string'||!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value))throw new Fault('ID permintaan tidak valid.');return value;}
export function safeSnapshot(raw){
  if(!raw||typeof raw!=='object')throw new Fault('Status RDP tidak valid.');
  // Only keep explicit public fields. Never forward OAuth/bridge credentials to the DB/UI.
  const input=raw.state||{},state={};
  for(const key of ['video_id','video_title','interval_minutes','running','current_index','next_due','pending_index','failures','last_error','last_changed','cycles'])state[key]=input[key]??null;
  state.titles=Array.isArray(input.titles)?input.titles.slice(0,500).map(x=>String(x).slice(0,100)):[];
  state.logs=Array.isArray(input.logs)?input.logs.slice(-100).map(x=>({time:Number(x.time)||0,message:String(x.message||'').slice(0,500)})):[];
  const youtube=raw.youtube||{};
  return {state,youtube:{connected:!!youtube.connected,channel:{title:String(youtube.channel?.title||'').slice(0,120),id:String(youtube.channel?.id||'').slice(0,80)}},
    lives:Array.isArray(raw.lives)?raw.lives.slice(0,50).map(x=>({id:String(x.id).slice(0,11),title:String(x.title||'').slice(0,100),status:String(x.status||'').slice(0,30)})):[],
    lives_updated:Number(raw.lives_updated)||null,lives_error:String(raw.lives_error||'').slice(0,500),version:'2.0.0'};
}
export function safeReceipts(raw){
  if(!Array.isArray(raw))return [];
  return raw.slice(-100).map(x=>({id:uuid(x.id),ok:x.ok===true,message:String(x.message||'').slice(0,500)}));
}
