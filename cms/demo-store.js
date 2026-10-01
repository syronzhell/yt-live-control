// Local test/demo store ONLY. Production api/index.js always uses Supabase.
import {Fault} from './lib/security.js';
export class DemoStore {
  constructor(clock=()=>Date.now()){
    this.clock=clock;this.control={config:{},revision:0,snapshot:{},last_seen:null,agent_id:null};this.commands=[];this.seq=0;this.attempts=new Map();
  }
  async dashboard(){return structuredClone({...this.control,commands:[...this.commands].reverse().slice(0,30)});}
  async rpc(name,input){
    if(name==='ytloop_login_gate'){
      const now=this.clock(),old=this.attempts.get(input.p_key)||{start:now,count:0};
      if(now-old.start>=900000){old.start=now;old.count=0;}if(old.count>=8)throw new Fault('Terlalu banyak percobaan login. Tunggu 15 menit.',429);
      old.count++;this.attempts.set(input.p_key,old);return {ok:true};
    }
    if(name==='ytloop_enqueue'){
      const previous=this.commands.find(x=>x.id===input.p_request);if(previous)return {id:previous.id,status:previous.status,duplicate:true};
      const action=input.p_action,now=this.clock(),state=this.control.snapshot.state||{};
      if(['start','next','end_live','reset'].includes(action)&&(!this.control.last_seen||now-new Date(this.control.last_seen).getTime()>60000))throw new Fault('RDP belum terhubung. Tunggu heartbeat lalu coba lagi.');
      if(['configure','reset'].includes(action)&&state.running)throw new Fault('Pause Loop dan tunggu status PAUSE sebelum mengubah pengaturan.');
      if(['start','next','reset'].includes(action)&&!this.control.config.video_id)throw new Fault('Simpan antrean dulu.');
      if(action==='end_live'&&input.p_payload.confirmation!==state.video_id)throw new Fault('Live berubah. Refresh status sebelum Stop Live.');
      for(const x of this.commands){if(x.status==='pending'&&(['pause','end_live'].includes(action)&&['start','next','reset'].includes(x.action)||action==='configure'&&x.action==='configure')){x.status='cancelled';x.result={message:'Diganti/dibatalkan perintah lebih baru.'};}}
      if(this.commands.filter(x=>['pending','delivered'].includes(x.status)).length>=50)throw new Fault('Antrean perintah penuh.');
      let payload=structuredClone(input.p_payload);
      if(action==='configure'){this.control.config=payload;this.control.revision++;}
      else payload._expected_video_id=action==='end_live'?payload.confirmation:this.control.config.video_id;
      const expires=['configure','pause','refresh'].includes(action)?null:now+(action==='end_live'?120000:900000);
      const command={id:input.p_request,seq:++this.seq,action,payload,status:'pending',created_at:new Date(now).toISOString(),expires_at:expires,result:null};
      this.commands.push(command);return {id:command.id,status:command.status,duplicate:false};
    }
    if(name==='ytloop_sync'){
      if(this.control.agent_id&&this.control.agent_id!==input.p_agent)throw new Fault('RDP lain sudah dipasangkan.',409);
      this.control.agent_id=input.p_agent;this.control.last_seen=new Date(this.clock()).toISOString();this.control.snapshot=structuredClone(input.p_snapshot);
      for(const receipt of input.p_receipts||[]){const command=this.commands.find(x=>x.id===receipt.id&&x.status==='delivered'&&x.delivered_to===input.p_agent);if(command){command.status=receipt.ok?'done':'error';command.result={ok:receipt.ok,message:receipt.message};}}
      for(const command of this.commands)if(command.status==='pending'&&command.expires_at&&command.expires_at<this.clock()){command.status='expired';command.result={message:'Perintah kedaluwarsa sebelum diterima RDP.'};}
      const command=this.commands.find(x=>['pending','delivered'].includes(x.status));
      if(command){command.status='delivered';command.delivered_to=input.p_agent;return {command:{id:command.id,action:command.action,payload:structuredClone(command.payload)},server_time:this.clock()/1000};}
      return {command:null,server_time:this.clock()/1000};
    }
    throw new Fault('RPC tidak dikenal.');
  }
}
