'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="app-token"]').content;
let state = null, busy = false, dirty = false, hydrated = false, shutdown = false, refreshing = false, clockOffset = 0;
let toastTimer, confirmAction;
function toast(message, error=false) { $('toast').textContent=message; $('toast').className='toast'+(error?' error':''); clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('toast').classList.add('hidden'),7000); }
async function api(action,payload={}) {
  const response=await fetch('/api/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-App-Token':token},body:JSON.stringify(payload)});
  const result=await response.json(); if(!response.ok) throw new Error(result.error||'Permintaan gagal.'); return result;
}
function buttons() {
  const running=state?.state.running||false;
  document.body.classList.toggle('busy',busy);
  for (const id of ['startBtn','pauseBtn','nextBtn','resetBtn','saveBtn','refreshBtn','connectBtn','endBtn','importClient','autoOn','autoOff','disconnectBtn','shutdownBtn','importTitles','exportTitles']) $(id).disabled=busy;
  $('startBtn').disabled=busy||running||dirty||!state?.youtube.connected;
  $('pauseBtn').disabled=busy||!running;
  $('nextBtn').disabled=busy||dirty||!state?.state.titles.length;
  $('resetBtn').disabled=busy||running;
  $('saveBtn').disabled=busy||running;
  $('endBtn').disabled=busy||!state?.state.video_id;
  $('connectBtn').disabled=busy||running||state?.youtube.auth_pending||state?.demo;
  for (const id of ['titles','interval','liveSelect']) $(id).disabled=busy||running;
  $('importTitles').disabled=busy||running;
  $('importClient').disabled=busy||running||state?.demo;
  $('disconnectBtn').disabled=busy||running||state?.demo;
  $('dirtyNotice').classList.toggle('hidden',!dirty);
  if(state?.bridge?.enabled){for(const id of ['startBtn','pauseBtn','nextBtn','resetBtn','saveBtn','endBtn','titles','interval','liveSelect','importTitles'])$(id).disabled=true;}
  $('pairBtn').disabled=busy; $('unpairBtn').disabled=busy||!state?.bridge?.enabled;
}
async function run(fn, success='') {
  if(busy)return; busy=true;buttons();
  try {await fn();if(success)toast(success);} catch(error){toast(error.message,true);} finally {busy=false;await refresh();buttons();}
}
function ensureOption(id,title) {
  if(!id)return; let option=[...$('liveSelect').options].find(x=>x.value===id);
  if(!option){option=document.createElement('option');option.value=id;$('liveSelect').append(option);}
  option.textContent=title+' · '+id;option.dataset.title=title;
}
function render() {
  const s=state.state,y=state.youtube;
  if(!hydrated){$('titles').value=s.titles.join('\n');$('interval').value=s.interval_minutes;ensureOption(s.video_id,s.video_title);$('liveSelect').value=s.video_id;hydrated=true;estimate();}
  $('loopBadge').textContent=s.running?'LOOP AKTIF':'PAUSE';$('loopBadge').classList.toggle('running',s.running);
  $('currentTitle').textContent=s.video_title||'Pilih live dan simpan antrean';
  $('watchLink').classList.toggle('hidden',!s.video_id);$('watchLink').href='https://www.youtube.com/watch?v='+encodeURIComponent(s.video_id);
  $('queueCount').textContent=s.titles.length+' judul';
  $('position').textContent=s.current_index>=0?(s.current_index+1)+' / '+s.titles.length:'Belum mulai';
  $('cycles').textContent=s.cycles;
  const target=s.pending_index??((s.current_index+1)%s.titles.length);
  $('nextTitle').textContent=s.titles.length?'Berikut: '+s.titles[target]:'Antrean belum tersimpan';
  $('lastError').textContent=s.last_error;$('lastError').classList.toggle('hidden',!s.last_error);
  $('channelName').textContent=y.channel?.title||'Belum terhubung';$('authState').textContent=y.connected?'YouTube terhubung':'Import OAuth JSON melalui Pengaturan.';
  $('authMessage').textContent=y.auth_message||'';$('connectBtn').textContent=y.auth_pending?'Menunggu login…':y.connected?'Hubungkan ulang':'Hubungkan YouTube';
  $('clientStatus').textContent=y.has_client?'OAuth Client sudah tersimpan.':'Belum ada OAuth Client.';
  $('demoBanner').classList.toggle('hidden',!state.demo);
  $('bridgeBanner').classList.toggle('hidden',!state.bridge?.enabled);
  $('bridgeInfo').textContent=state.bridge?.error|| (state.bridge?.last_sync?'Sync terakhir: '+new Date(state.bridge.last_sync*1000).toLocaleTimeString('id-ID'):'Menunggu sync pertama.');
  $('bridgeLink').href=state.bridge?.url||'#';
  if(!$('cmsUrl').matches(':focus')&&!$('cmsUrl').value)$('cmsUrl').value=state.bridge?.url||'';
  $('logs').replaceChildren();
  if(!s.logs.length){const empty=document.createElement('div');empty.className='log-empty';empty.textContent='Aktivitas loop akan muncul di sini.';$('logs').append(empty);}
  for(const log of [...s.logs].reverse()){const line=document.createElement('div');line.className='log-line';const time=document.createElement('span');time.className='log-time';time.textContent=new Date(log.time*1000).toLocaleTimeString('id-ID',{hour:'2-digit',minute:'2-digit',second:'2-digit'});time.title=new Date(log.time*1000).toLocaleString('id-ID');const message=document.createElement('span');message.textContent=log.message;line.append(time,message);$('logs').append(line);}
  buttons();countdown();
}
async function refresh(){if(shutdown||refreshing)return;refreshing=true;try{const response=await fetch('/api/status');if(!response.ok)throw Error();state=await response.json();clockOffset=state.server_time*1000-Date.now();$('offline').classList.add('hidden');render();}catch(_){$('offline').classList.remove('hidden');}finally{refreshing=false;}}
function countdown(){if(!state)return;const s=state.state;if(!s.running||!s.next_due){$('countdown').textContent='—';return;}const seconds=Math.max(0,Math.ceil(s.next_due-(Date.now()+clockOffset)/1000));const h=Math.floor(seconds/3600),m=Math.floor(seconds%3600/60),z=seconds%60;$('countdown').textContent=seconds===0?'Memproses…':[h,m,z].map(v=>String(v).padStart(2,'0')).join(':');}
function estimate(){const n=Number($('interval').value);$('quotaEstimate').textContent=Number.isFinite(n)&&n>=10?`${n} menit = ${Number((n/60).toFixed(2))} jam · Perkiraan ${Math.ceil(1440/n)*53+288} unit API/hari saat terus berjalan.`:'Minimum interval 10 menit.';}
function markDirty(){dirty=true;buttons();estimate();}
function confirm(title,text,action){confirmAction=action;$('confirmTitle').textContent=title;$('confirmText').textContent=text;$('confirmDialog').showModal();}
$('cancelConfirm').onclick=()=>$('confirmDialog').close();
$('acceptConfirm').onclick=()=>{$('confirmDialog').close();if(confirmAction)confirmAction();};
$('settingsBtn').onclick=()=>$('settingsDialog').showModal();$('closeSettings').onclick=()=>$('settingsDialog').close();
for(const id of ['titles','interval','liveSelect'])$(id).addEventListener('input',markDirty);
$('saveBtn').onclick=()=>run(async()=>{const option=$('liveSelect').selectedOptions[0];await api('configure',{video_id:$('liveSelect').value,video_title:option?.dataset.title||'',titles:$('titles').value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean),interval_minutes:Number($('interval').value)});dirty=false;},'Antrean tersimpan.');
$('refreshBtn').onclick=()=>run(async()=>{const result=await api('lives');const selected=$('liveSelect').value;$('liveSelect').replaceChildren(new Option('Pilih live aktif…',''));for(const live of result.lives)ensureOption(live.id,live.title);ensureOption(state.state.video_id,state.state.video_title);$('liveSelect').value=selected;$('emptyLive').classList.toggle('hidden',!!result.lives.length);},'Daftar live diperbarui.');
$('startBtn').onclick=()=>run(()=>api('start'),'Loop dimulai.');$('pauseBtn').onclick=()=>run(()=>api('pause'),'Loop dijeda. Live tetap berjalan.');$('nextBtn').onclick=()=>run(()=>api('next'),'Permintaan ganti judul diproses. Cek aktivitas.');
$('resetBtn').onclick=()=>confirm('Reset posisi antrean?','Start Loop berikutnya akan memakai judul pertama. Judul live sekarang tetap.',()=>run(()=>api('reset'),'Posisi antrean direset.'));
$('endBtn').onclick=()=>confirm('Akhiri live YouTube?','Live yang dipilih akan selesai dan tidak bisa dilanjutkan sebagai sesi yang sama. Loop juga berhenti. Aplikasi pengirim video tetap berjalan.',()=>run(()=>api('end-live',{confirmation:state.state.video_id}),'Permintaan Stop Live dikirim.'));
$('connectBtn').onclick=()=>run(async()=>{const result=await api('connect');$('authLink').href=result.url;$('authLink').classList.remove('hidden');toast('Klik “Buka halaman login Google” di kartu channel.');});
$('importClient').onclick=()=>$('clientFile').click();$('clientFile').onchange=event=>run(async()=>{const file=event.target.files[0];if(!file)return;if(file.size>1048576)throw Error('File terlalu besar. Maksimum 1 MB.');let credentials;try{credentials=JSON.parse(await file.text());}catch(_){throw Error('File JSON tidak valid.');}await api('import-client',{credentials});$('clientFile').value='';},'OAuth Client tersimpan. Tutup Pengaturan lalu Hubungkan YouTube.');
$('disconnectBtn').onclick=()=>confirm('Cabut izin YouTube?','Token Google dicabut dan dihapus dari tool. Antrean tetap tersimpan.',()=>run(()=>api('disconnect'),'YouTube diputuskan.'));
$('autoOn').onclick=()=>run(async()=>{const result=await api('autostart',{enabled:true});toast(result.message);});$('autoOff').onclick=()=>run(async()=>{const result=await api('autostart',{enabled:false});toast(result.message);});
$('pairBtn').onclick=()=>run(async()=>{await api('bridge-connect',{url:$('cmsUrl').value,key:$('agentKey').value});$('agentKey').value='';},'Pairing tersimpan. Tunggu heartbeat di CMS.');
$('unpairBtn').onclick=()=>confirm('Putus CMS dan pause loop?','Loop lokal dijeda. CMS tidak bisa mengirim perintah ke RDP ini sampai pairing diaktifkan lagi.',()=>run(()=>api('bridge-disconnect'),'CMS diputus, loop dijeda.'));
$('shutdownBtn').onclick=()=>confirm('Tutup program?','Pergantian judul berhenti. Live YouTube tetap berjalan. Jalankan START.bat / RUN_BACKGROUND.vbs untuk membuka lagi.',()=>run(async()=>{await api('shutdown');shutdown=true;$('settingsDialog').close();$('footerStatus').textContent='Program ditutup. Buka launcher untuk menjalankan lagi.';toast('Program ditutup. Live tetap berjalan.');}));
$('importTitles').onclick=()=>$('titlesFile').click();$('titlesFile').onchange=async event=>{const file=event.target.files[0];if(!file)return;if(file.size>200000){toast('File judul terlalu besar.',true);return;}$('titles').value=await file.text();$('titlesFile').value='';markDirty();toast('Judul diimport. Klik Simpan antrean.');};
$('exportTitles').onclick=()=>{const url=URL.createObjectURL(new Blob([$ ('titles').value],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='antrean-judul.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
refresh();setInterval(()=>{if(!busy)refresh();},4000);setInterval(countdown,1000);
