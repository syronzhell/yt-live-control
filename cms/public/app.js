'use strict';
const $=id=>document.getElementById(id);
let data=null,csrf='',busy=false,dirty=false,hydrated=false,refreshing=false,offset=0,online=false,confirmAction;
let uncertain;try{uncertain=JSON.parse(localStorage.getItem('ytloop-request')||'null');}catch{uncertain=null;}
let toastTimer;
const labels={configure:'Simpan antrean',start:'Start Loop',pause:'Pause Loop',next:'Ganti judul',reset:'Reset antrean',end_live:'Stop Live',refresh:'Refresh live'};
const statuses={pending:'Menunggu RDP',delivered:'Dikirim ke RDP',done:'Selesai',error:'Gagal',cancelled:'Dibatalkan',expired:'Kedaluwarsa'};
function toast(message,error=false){$('toast').textContent=message;$('toast').className='toast'+(error?' error':'');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.add('hidden'),7000);}
function remember(value){uncertain=value;try{if(value)localStorage.setItem('ytloop-request',JSON.stringify(value));else localStorage.removeItem('ytloop-request');}catch{}buttons();}
async function api(route,body){
  let response;try{response=await fetch('/api/'+route,{method:body===undefined?'GET':'POST',credentials:'same-origin',headers:body===undefined?{}:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:body===undefined?undefined:JSON.stringify(body)});}catch{const error=Error('CMS tidak terjangkau.');error.uncertain=true;throw error;}
  let result;try{result=await response.json();}catch{const error=Error('Respons CMS tidak valid.');error.uncertain=true;throw error;}
  if(!response.ok){const error=Error(result.error||'Permintaan gagal.');error.status=response.status;error.uncertain=!!result.uncertain;if(response.status===401)showLogin();throw error;}return result;
}
function showLogin(){$('loginView').classList.remove('hidden');$('dashboard').classList.add('hidden');data=null;csrf='';hydrated=false;}
function pending(){return data?.commands?.filter(x=>x.status==='pending'||x.status==='delivered')||[];}
function buttons(){
  if(!data)return;const running=!!data.snapshot?.state?.running,inflight=pending().length>0,blocked=busy||!!uncertain;
  for(const id of ['startBtn','pauseBtn','nextBtn','resetBtn','endBtn','refreshBtn','saveBtn','importBtn','exportBtn','logoutBtn'])$(id).disabled=blocked;
  $('startBtn').disabled=blocked||!online||running||inflight||dirty||!data.config?.titles?.length||!data.snapshot?.youtube?.connected;
  $('nextBtn').disabled=blocked||!online||inflight||dirty||!data.config?.titles?.length;
  $('pauseBtn').disabled=blocked||(!running&&!inflight);
  $('resetBtn').disabled=blocked||!online||running||inflight;
  $('endBtn').disabled=blocked||!online||!data.snapshot?.state?.video_id;
  $('refreshBtn').disabled=blocked||!online||inflight;
  $('saveBtn').disabled=blocked||running||inflight;
  for(const id of ['titles','interval','liveSelect','importBtn'])$(id).disabled=blocked||running||inflight;
  $('retryBtn').disabled=busy;
  $('dirtyNotice').classList.toggle('hidden',!dirty);
  $('uncertainNotice').classList.toggle('hidden',!uncertain);
}
function hydrate(config){$('titles').value=(config.titles||[]).join('\n');$('interval').value=config.interval_minutes||180;options(config.video_id,config.video_title);$('liveSelect').value=config.video_id||'';hydrated=true;estimate();}
function options(selected,title){
  const lives=data.snapshot?.lives||[];const current=$('liveSelect').value;const target=selected??current;
  $('liveSelect').replaceChildren(new Option('Pilih live aktif…',''));
  for(const live of lives){const option=new Option(live.title+' · '+live.id,live.id);option.dataset.title=live.title;$('liveSelect').append(option);}
  if(target&&![...$('liveSelect').options].some(x=>x.value===target)){const option=new Option((title||data.config?.video_title||target)+' · '+target,target);option.dataset.title=title||data.config?.video_title||'';$('liveSelect').append(option);}
  $('liveSelect').value=target||'';
}
function lines(container,items,renderItem,empty){
  container.replaceChildren();if(!items.length){const line=document.createElement('div');line.className='log-empty';line.textContent=empty;container.append(line);return;}
  for(const item of items)container.append(renderItem(item));
}
function render(){
  $('loginView').classList.add('hidden');$('dashboard').classList.remove('hidden');
  const snapshot=data.snapshot||{},state=snapshot.state||{},yt=snapshot.youtube||{};
  const last=data.last_seen?new Date(data.last_seen).getTime():0;online=!!last&&(Date.now()+offset-last)<60000;
  $('rdpBadge').textContent=online?'RDP ONLINE':'RDP OFFLINE';$('rdpBadge').classList.toggle('running',online);
  $('agentNotice').classList.toggle('hidden',online);
  $('agentNotice').textContent=data.agent_id?'RDP offline / heartbeat terlambat. Perintah baru belum bisa dieksekusi; mesin lokal bisa tetap berjalan dengan jadwal terakhir.':'Belum ada RDP terpasang. Di aplikasi RDP: Pengaturan → Hubungkan CMS Vercel.';
  if(!hydrated)hydrate(data.config||{});else if(!dirty&&!busy)options(data.config?.video_id,data.config?.video_title);
  $('loopBadge').textContent=state.running?(online?'LOOP AKTIF':'STATUS TERAKHIR: AKTIF'):'PAUSE';$('loopBadge').classList.toggle('running',!!state.running);
  $('currentTitle').textContent=state.video_title||'Pilih live dan simpan antrean';
  $('watchLink').classList.toggle('hidden',!state.video_id);$('watchLink').href='https://www.youtube.com/watch?v='+encodeURIComponent(state.video_id||'');
  const titles=state.titles||[];const idx=Number(state.current_index??-1);const next=state.pending_index??((idx+1)%titles.length);
  $('nextTitle').textContent=titles.length?'Berikut: '+titles[next]:'Antrean belum tersimpan';
  $('queueCount').textContent=(data.config?.titles?.length||0)+' judul';
  $('position').textContent=idx>=0?(idx+1)+' / '+titles.length:'Belum mulai';$('cycles').textContent=state.cycles||0;
  $('channelName').textContent=yt.channel?.title||'Belum terhubung';$('channelStatus').textContent=yt.connected?'YouTube terhubung di RDP':'Hubungkan YouTube melalui dashboard lokal RDP.';
  $('lastSeen').textContent=last?new Date(last).toLocaleString('id-ID'):'Menunggu pairing';
  $('lastError').textContent=state.last_error||'';$('lastError').classList.toggle('hidden',!state.last_error);
  $('livesHint').textContent=snapshot.lives_error||(!snapshot.lives?.length?'Daftar live belum tersedia. Hubungkan YouTube di RDP, mulai streaming, lalu Refresh live.':snapshot.lives_updated?'Daftar diperbarui '+new Date(snapshot.lives_updated*1000).toLocaleTimeString('id-ID'):'');
  const tasks=pending();$('pendingNotice').classList.toggle('hidden',!tasks.length);$('pendingNotice').textContent=tasks.length+' perintah menunggu/diproses RDP. Status akan diperbarui setelah sync.';
  if(uncertain&&data.commands.some(x=>x.id===uncertain.request_id))remember(null);
  lines($('commands'),data.commands||[],command=>{const line=document.createElement('div');line.className='command-line';const name=document.createElement('strong');name.textContent=labels[command.action]||command.action;const status=document.createElement('span');status.className='command-status '+command.status;status.textContent=statuses[command.status]||command.status;const details=document.createElement('span');details.className='command-detail';details.textContent=new Date(command.created_at).toLocaleString('id-ID')+(command.result?.message?' · '+command.result.message:'');line.append(name,status,details);return line;},'Belum ada perintah.');
  lines($('logs'),[...(state.logs||[])].reverse(),log=>{const line=document.createElement('div');line.className='log-line';const when=document.createElement('span');when.className='log-time';when.textContent=new Date(log.time*1000).toLocaleTimeString('id-ID');when.title=new Date(log.time*1000).toLocaleString('id-ID');const message=document.createElement('span');message.textContent=log.message;line.append(when,message);return line;},'Aktivitas dari RDP akan muncul di sini.');
  buttons();countdown();
}
async function refresh(){if(refreshing)return;refreshing=true;try{const result=await api('status');data=result;csrf=result.csrf;offset=result.server_time*1000-Date.now();$('offline').classList.add('hidden');render();}catch(error){if(error.status!==401){if(data)$('offline').classList.remove('hidden');else{$('loginError').textContent=error.message;$('loginError').classList.remove('hidden');}}}finally{refreshing=false;}}
function countdown(){if(!data)return;const state=data.snapshot?.state||{};if(!online||!state.running||!state.next_due){$('countdown').textContent='—';return;}const total=Math.max(0,Math.ceil(state.next_due-(Date.now()+offset)/1000));$('countdown').textContent=total===0?'Menunggu sync…':[Math.floor(total/3600),Math.floor(total%3600/60),total%60].map(x=>String(x).padStart(2,'0')).join(':');}
function estimate(){const n=Number($('interval').value);$('intervalHint').textContent=Number.isFinite(n)&&n>=10?`${n} menit = ${Number((n/60).toFixed(2))} jam.`:'Minimum interval 10 menit.';}
function markDirty(){dirty=true;buttons();estimate();}
async function sendCommand(action,payload={},retry=null){
  if(busy)return;busy=true;
  const request=retry||{request_id:crypto.randomUUID(),action,payload};remember(request);buttons();
  try{await api('command',request);remember(null);if(action==='configure'){dirty=false;hydrated=false;}toast('Perintah tersimpan. Tunggu status Selesai dari RDP.');}
  catch(error){if(!error.uncertain)remember(null);toast(error.message,true);}
  finally{busy=false;await refresh();buttons();}
}
function confirm(title,text,action){confirmAction=action;$('confirmTitle').textContent=title;$('confirmText').textContent=text;$('confirmDialog').showModal();}
$('cancelConfirm').onclick=()=>$('confirmDialog').close();$('acceptConfirm').onclick=()=>{$('confirmDialog').close();confirmAction?.();};
$('loginForm').onsubmit=async event=>{event.preventDefault();$('loginBtn').disabled=true;$('loginError').classList.add('hidden');try{await api('login',{password:$('password').value});$('password').value='';await refresh();}catch(error){$('loginError').textContent=error.message;$('loginError').classList.remove('hidden');}finally{$('loginBtn').disabled=false;}};
$('logoutBtn').onclick=async()=>{try{await api('logout',{});showLogin();}catch(error){toast(error.message,true);}};
for(const id of ['titles','interval','liveSelect'])$(id).addEventListener('input',markDirty);
$('saveBtn').onclick=()=>sendCommand('configure',{video_id:$('liveSelect').value,video_title:$('liveSelect').selectedOptions[0]?.dataset.title||'',titles:$('titles').value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean),interval_minutes:Number($('interval').value)});
$('startBtn').onclick=()=>sendCommand('start');$('pauseBtn').onclick=()=>sendCommand('pause');$('nextBtn').onclick=()=>sendCommand('next');$('refreshBtn').onclick=()=>sendCommand('refresh');
$('resetBtn').onclick=()=>confirm('Reset antrean?','Start Loop berikutnya memakai judul pertama. Judul live saat ini tetap.',()=>sendCommand('reset'));
$('endBtn').onclick=()=>{const id=data.snapshot?.state?.video_id;confirm('Akhiri live YouTube?','Sesi ini selesai dan tidak bisa dilanjutkan sebagai live yang sama. Loop berhenti. Aplikasi pengirim video tetap berjalan.',()=>sendCommand('end_live',{confirmation:id}));};
$('retryBtn').onclick=()=>{if(uncertain)sendCommand(uncertain.action,uncertain.payload,uncertain);};
$('importBtn').onclick=()=>$('titlesFile').click();$('titlesFile').onchange=async event=>{const file=event.target.files[0];if(!file)return;if(file.size>100000){toast('File terlalu besar.',true);return;}$('titles').value=await file.text();$('titlesFile').value='';markDirty();};
$('exportBtn').onclick=()=>{const url=URL.createObjectURL(new Blob([$ ('titles').value],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='antrean-judul.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
refresh();setInterval(()=>{if(data&&!busy)refresh();},8000);setInterval(countdown,1000);
