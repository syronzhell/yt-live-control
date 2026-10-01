import {Fault} from './security.js';
export class Database {
  constructor(settings){this.url=settings.SUPABASE_URL.replace(/\/$/,'')+'/rest/v1/';this.key=settings.SUPABASE_SECRET_KEY||settings.SUPABASE_SERVICE_ROLE_KEY;}
  async request(path,method='GET',body){
    let response;
    const headers={'apikey':this.key,'Content-Type':'application/json'};
    // New Supabase sb_secret_ keys are NOT JWTs; send only as apikey. Legacy service_role JWTs also use Bearer.
    if(!this.key.startsWith('sb_secret_'))headers.Authorization='Bearer '+this.key;
    try{response=await fetch(this.url+path,{method,headers,body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(10000)});}catch{throw new Fault('Database tidak terjangkau. Perintah belum dikonfirmasi tersimpan; coba dengan ID permintaan yang sama.',503);}
    if(!response.ok){
      let detail={};try{detail=await response.json();}catch{}
      const messages={AGENT_CONFLICT:'RDP lain sudah dipasangkan. Pause mesin lama sebelum mengganti pairing.',QUEUE_FULL:'Antrean perintah penuh. Tunggu RDP terhubung atau kirim Pause.',AGENT_OFFLINE:'RDP belum terhubung. Tunggu heartbeat lalu coba lagi.',PAUSE_FIRST:'Pause Loop dan tunggu status PAUSE sebelum mengubah pengaturan.',NO_CONFIG:'Simpan antrean dulu.',STOP_MISMATCH:'Live berubah. Refresh status sebelum Stop Live.',LOGIN_LIMIT:'Terlalu banyak percobaan login. Tunggu 15 menit.'};
      if(messages[detail.message])throw new Fault(messages[detail.message],detail.message==='AGENT_CONFLICT'?409:detail.message==='LOGIN_LIMIT'?429:400);
      throw new Fault('Database belum siap / menolak permintaan. Jalankan supabase.sql dan periksa service role key.',503);
    }
    const text=await response.text();return text?JSON.parse(text):null;
  }
  rpc(name,body){return this.request('rpc/'+name,'POST',body);}
  async dashboard(){
    const [controls,commands]=await Promise.all([
      this.request('ytloop_control?id=eq.1&select=config,revision,snapshot,last_seen,agent_id'),
      this.request('ytloop_commands?select=id,seq,action,status,created_at,result&order=seq.desc&limit=30')]);
    if(!controls?.length)throw new Fault('Jalankan supabase.sql terlebih dahulu.',503);
    return {...controls[0],commands};
  }
}
