'use strict';
const $=id=>document.getElementById(id);
let charts=[]; let historyBusy=false; let historyAgain=false;
let latestData=null; // last successful /api/latest payload, shared by every view

/* ===================== Live dashboard: gate v2 + environment ===================== */
function reading(source,key,suffix='',digits=1){return source.fresh&&source.payload_valid&&source[key+'_valid']&&Number.isFinite(source[key])?source[key].toFixed(digits)+suffix:'Unknown';}
function zone(id,value){$(id).textContent={clear:'Clear',detected:'Detected',unknown:'Unknown'}[value]||'Unknown';$(id).className='state '+(value==='clear'?'available':value==='detected'?'occupied':'unknown');}
/* G3 entrance/exit controller (sensor team's parking v1 simulation). Display only. */
const P3_PHASE=['Boot / check zones','Closed · simulation','Entrance authorization wait','Open · simulation','Closing · simulation','Hold / supervised review'];
const P3_CLASS=['unknown','available','pending','available','pending','occupied'];
function renderG3(parking3,p3){
  const cm=v=>v===null||v===undefined?'No echo':v+' cm';
  $('parking3-badge').textContent=parking3.enabled?'G3 · isolated simulation · Servo disconnected':'G3 · not enabled on this run';
  $('parking3-status').textContent=p3?(P3_PHASE[p3.phase]||'Unknown'):parking3.enabled?'Waiting for fresh entrance/exit telemetry':'Not enabled';
  $('parking3-status').className='state '+(p3?(P3_CLASS[p3.phase]||'unknown'):'unknown');
  $('parking3-detail').textContent=p3?`Direction: ${['none','entrance','exit','manual'][p3.lane]||'unknown'} · Cycle ${p3.cycle} · U1 ${cm(p3.u1_distance_cm)} · U2 ${cm(p3.u2_distance_cm)} · Minimum ${p3.minimum_open_ms/1000}s · Servo disabled`:'New G3 data stays separate from historical G2 passages';
  $('p3-direction').textContent=p3?(['None','Entrance','Exit','Manual'][p3.lane]||'Unknown'):'—';
  $('p3-cycle').textContent=p3?String(p3.cycle):'—';
  $('p3-u1').textContent=p3?cm(p3.u1_distance_cm):'—';$('p3-u2').textContent=p3?cm(p3.u2_distance_cm):'—';
  $('p3-minimum').textContent=p3?(p3.minimum_open_ms/1000)+' s':'—';
  $('p3-feedback').textContent=parking3.enabled?String(parking3.pending_feedback||0):'—';
  $('parking3-command').textContent=`Command receipt: ${parking3.command_outcome||'none'} · Feedback awaiting receipt: ${parking3.pending_feedback||0} · Session matching/release: teammate owned`;
}
function unavailable(){renderG3({},null);for(const id of ['gate-sim-state','u1-state','u2-state','u1-distance','u2-distance','servo-status','arrivals','passages','temperature','humidity','light','gas','vibration-count'])$(id).textContent='Unknown';$('gate-sim-state').className='state unknown';$('u1-state').className='state unknown';$('u2-state').className='state unknown';$('gate-event').textContent='No current gate telemetry';$('license-plate').textContent='Unavailable';$('vehicle-type').textContent='UNKNOWN';$('recognition-time').textContent='Unavailable';$('recognition-status').textContent='Unavailable';}
async function live(){try{const r=await fetch('/api/latest',{cache:'no-store'});if(!r.ok)throw Error();const d=await r.json(),g=d.sources.gate||{},e=d.sources.esp32||{},cloud=d.cloud||{};
const usable=g.fresh&&g.payload_valid;
$('gate-sim-state').textContent=usable?({boot_wait:'Checking zones',closed:'Closed · simulation',authorization_wait:'Waiting for authorization',open_wait:'Open · simulation',passing:'Vehicle passing · simulation',closing:'Closing · simulation',hold:'Hold / supervised review'}[g.gate_sim_state]||'Unknown'):'Unknown';
$('gate-sim-state').className='state '+(usable&&g.gate_sim_state!=='hold'?'available':'unknown');
zone('u1-state',usable?g.u1_state:'unknown');zone('u2-state',usable?g.u2_state:'unknown');
$('u1-distance').textContent=reading(g,'u1_distance_cm',' cm');$('u2-distance').textContent=reading(g,'u2_distance_cm',' cm');
$('servo-status').textContent=usable&&g.servo_enabled===false?'Disabled · no physical movement':'Unknown';
$('arrivals').textContent=reading(g,'arrival_count','',0);$('passages').textContent=reading(g,'completed_count','',0);
$('gate-event').textContent=usable?('Latest event · '+(g.last_event||'unknown').replaceAll('_',' ')+' · '+new Date(g.last_received_utc).toLocaleTimeString()):'Waiting for fresh gate-v2 telemetry';
$('temperature').textContent=reading(e,'temperature_c',' °C');$('humidity').textContent=reading(e,'humidity_pct',' %');$('light').textContent=reading(e,'light_raw','',0);$('gas').textContent=reading(e,'gas_raw','',0);
$('vibration-count').textContent=reading(g,'vibration_transition_count','',0);$('vibration-raw').textContent='Raw level '+(usable&&g.vibration_raw_valid?(g.vibration_raw?'High':'Low'):'unknown')+' · Polarity unverified';
const parking3=d.parking3||{},p3=parking3.fresh?parking3.telemetry:null;renderG3(parking3,p3);
if(p3){$('vibration-count').textContent=p3.vibration_transition_count;$('vibration-raw').textContent=`Raw level ${p3.vibration_raw?'High':'Low'} · Polarity unverified · G3`;}
const recognition=parking3.recognition?{status:'authorized_simulation',...parking3.recognition}:d.recognition||{},test=recognition.origin==='synthetic',hasResult=!!recognition.license_plate;
$('recognition-status').textContent=test?'Test recognition · synthetic':(recognition.status||'Not configured').replaceAll('_',' ');
$('license-plate').textContent=hasResult?recognition.license_plate:'Unavailable';$('vehicle-type').textContent=hasResult?(recognition.vehicle_type||'unknown').toUpperCase():'UNKNOWN';
$('recognition-time').textContent=recognition.occurred_at?new Date(recognition.occurred_at).toLocaleString():'Unavailable';
$('recognition-note').textContent=test?'Isolated test result · Not a real recognized vehicle':hasResult?'Original plate text retained; LCD delivery is separate':'Waiting for the agreed teammate interface';
$('uno-status').textContent='UNO gate · '+(usable?'Receiving':'Stale / Unknown');$('esp32-status').textContent='ESP32 · '+(e.fresh&&e.payload_valid?'Receiving':'Stale / Unknown');
$('storage-status').textContent='Storage · '+(d.storage_connected?'Connected':'Unavailable')+' · Backlog '+(d.storage_backlog||0)+' · Dropped '+(d.storage_dropped_points||0);
$('mqtt-status').textContent='Broker · '+(d.mqtt_connected?'Connected':'Disconnected');$('ingestion-status').textContent='Ingestion · '+(d.ingestion_connected?'Receiving':'Waiting')+' · Rejected '+(d.rejected_messages||0)+' · Queue dropped '+(d.dropped_messages||0);
const healthy=d.mqtt_connected&&d.storage_connected;$('system').textContent=healthy?'System connected':'Connection issue';$('system').className='badge '+(healthy?'healthy':'warning');$('updated').textContent='Updated '+new Date(d.received_at_utc).toLocaleTimeString();
$('cloud-status').textContent='Cloud · '+(cloud.error?'Attention required':cloud.enabled?(cloud.last_success_utc?'Last upload acknowledged':'Awaiting upload'):'Not configured for this run');
$('cloud-detail').textContent=cloud.enabled?`Durable pending ${cloud.pending||0} · Staging ${cloud.staging||0} · Uploaded ${cloud.uploaded||0} · Dropped ${cloud.dropped||0} · Failures ${cloud.failures||0} · Last success ${cloud.last_success_utc?new Date(cloud.last_success_utc).toLocaleString():'None'}${cloud.error?' · Error '+cloud.error:''}`:'Live monitoring remains local. Gate simulation uses an isolated routing transition.';
latestData=d;renderLive();
}catch{unavailable();$('system').textContent='Server unavailable';$('system').className='badge warning';$('uno-status').textContent='UNO gate · Unknown';$('esp32-status').textContent='ESP32 · Unknown';$('storage-status').textContent='Storage · Unknown';$('mqtt-status').textContent='Broker · Unknown';$('ingestion-status').textContent='Ingestion · Unknown';$('updated').textContent='Live update failed';$('cloud-status').textContent='Cloud · Backend unavailable';$('cloud-detail').textContent='No current synchronization status';
latestData=null;renderLive();}}
function dataset(label,points,color){return {label,data:points.map(p=>({x:Date.parse(p.time),y:p.value})),borderColor:color,backgroundColor:color,borderWidth:2,pointRadius:1.5,pointHoverRadius:3,spanGaps:false,tension:.12};}
function chart(id,sets){return new Chart($(id),{type:'line',data:{datasets:sets},options:{responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:'nearest',axis:'x',intersect:false},plugins:{legend:{display:sets.length>1},tooltip:{callbacks:{title:items=>items.length?new Date(items[0].parsed.x).toLocaleString():''}}},scales:{x:{type:'linear',ticks:{maxTicksLimit:5,maxRotation:0,callback:value=>new Date(value).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})},grid:{display:false}},y:{grid:{color:'#e9eef6'}}}}});}
async function history(){if(historyBusy){historyAgain=true;return;}historyBusy=true;const archive=$('history-source').value;try{if(typeof Chart==='undefined')throw Error('Local Chart.js asset unavailable');const min=$('range').value;const params=[['gate','u1_distance_cm'],['gate','u2_distance_cm'],['esp32','temperature_c'],['esp32','humidity_pct'],['esp32','light_raw'],['esp32','gas_raw'],['gate','arrival_count'],['gate','completed_count'],['gate','vibration_transition_count']];const load=async([source,field])=>{const endpoint=archive==="cloud"?"/api/cloud/history":"/api/history";const r=await fetch(`${endpoint}?source=${source}&field=${field}&minutes=${min}`,{cache:"no-store"});if(!r.ok)throw Error(archive==="cloud"?"Cloud history unavailable":"History unavailable");return(await r.json()).points;};let data;if(archive==="cloud"){data=[];for(const param of params)data.push(await load(param));}else data=await Promise.all(params.map(load));if(archive!==$('history-source').value||min!==$('range').value)return;const step=(label,points,color)=>({...dataset(label,points,color),stepped:true,tension:0});const specs=[['distance-chart',[dataset('U1 approach',data[0],'#2f7bf6'),dataset('U2 passage',data[1],'#7c5cdb')]],['environment-chart',[dataset('Temperature °C',data[2],'#f08a3c'),dataset('Humidity %',data[3],'#19a3a8')]],['light-chart',[dataset('Light ADC',data[4],'#d4a017')]],['gas-chart',[dataset('Gas ADC · uncalibrated',data[5],'#7c5cdb')]],['counts-chart',[step('Arrivals · boot counter',data[6],'#2f7bf6'),step('Completed simulated passages',data[7],'#19a3a8')]],['vibration-chart',[step('Sampled vibration transitions',data[8],'#d4a017')]]];charts.forEach(c=>c.destroy());charts=[];for(const [id,sets] of specs)charts.push(chart(id,sets));$('history-status').textContent=data.some(p=>p.some(point=>Number.isFinite(point.value)))?(archive==='cloud'?'Cloud archive · Aggregated telemetry; gaps and low coverage shown as unknown':'Actual stored readings · Gaps represent unavailable measurements'):(archive==='cloud'?'No cloud readings in this time range':'No stored readings in this time range');}catch(e){charts.forEach(c=>c.destroy());charts=[];$('history-status').textContent=e.message+' · Live cards remain independent';}finally{historyBusy=false;if(historyAgain){historyAgain=false;history();}}}

/* ===================== Helpers ===================== */
const esc=s=>String(s??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
// The AI may answer sportcar or supercar; both use VIP bays, so the UI shows them as one class.
const typeLabel={car:'Normal car',sportcar:'Sport car',supercar:'Sport car',unknown:'Unknown'};
const typeGroup=type=>type==='car'?'car':(type==='sportcar'||type==='supercar')?'sport':null;
const kindLabel={vip:'VIP',normal:'Normal'};
const reasonLabel={entry_registered:'Entry registered',exit_registered:'Exit registered',recognition_needs_review:'Recognition needs review',no_active_session:'No active visit for this plate',already_inside:'Plate already inside',unsupported_vehicle_type:'Unsupported vehicle type',vip_full:'VIP bays full',normal_full:'Normal bays full'};
const fmtTime=iso=>iso?new Date(iso).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}):'—';
const fmtDateTime=iso=>iso?new Date(iso).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}):'—';
function fmtDur(ms){if(!Number.isFinite(ms)||ms<0)return '—';const m=Math.round(ms/60000);return m<60?m+' min':Math.floor(m/60)+' h '+(m%60)+' min';}
const isToday=iso=>!!iso&&new Date(iso).toDateString()===new Date().toDateString();
const statusTag=s=>s==='still_in'?'<span class="tag blue">Still in</span>':'<span class="tag gray">Left</span>';
const kindOf=type=>type==='car'?'normal':(type==='sportcar'||type==='supercar')?'vip':null;
const sid=x=>x.id||x.session_id;
const plateOf=x=>x.plate||x.license_plate||null;
const plateHtml=p=>p?`<span class="plate">${esc(p)}</span>`:'<span class="plate none">not read</span>';
// The parking service returns "/parking/media/<uuid>"; photos are read through this dashboard's backend.
function photoUrl(u){const m=/^\/parking\/media\/([0-9a-fA-F-]{36})$/.exec(u||'');return m?'/api/parking/media/'+m[1]:null;}
function carThumb(type){const cls=type==='supercar'?'sup':type==='sportcar'?'spo':'std';return `<span class="thumb ${cls}" aria-hidden="true"><svg viewBox="0 0 48 32"><rect x="4" y="12" width="40" height="13" rx="5"/><path d="M12 12l5-7h14l6 7z"/><circle cx="14" cy="26" r="4" class="w"/><circle cx="34" cy="26" r="4" class="w"/></svg></span>`;}
const photoThumb=(u,type,visit)=>{const src=photoUrl(u);return src?`<button type="button" class="photo" data-visit="${esc(visit)}" data-which="entry" aria-label="View entrance photo"><img src="${src}" alt="" loading="lazy"></button>`:carThumb(type);};

/* ===================== Parking data: live from the parking service, else sample ===================== */
let pStatus=null,pHistory={events:[],sessions:[]},usingSample=true,parkingError='',parkingUpdated=null,parkingLoaded=false;
async function getJson(url){const r=await fetch(url,{cache:'no-store'});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.error||('HTTP '+r.status));return d;}
async function loadParking(){
  try{
    const [st,hi]=await Promise.all([getJson('/api/parking/status'),getJson('/api/parking/history?limit=100')]);
    if(!Array.isArray(st.spaces)||!Array.isArray(hi.sessions)||!Array.isArray(hi.events))throw Error('Unexpected parking payload');
    pStatus=st;pHistory=hi;usingSample=false;parkingError='';parkingUpdated=new Date();
  }catch(e){
    const demo=window.DEMO_PARKING;pStatus=demo.status;pHistory=demo.history;usingSample=true;parkingError=e.message||'unreachable';parkingUpdated=null;
  }
  parkingLoaded=true;
  const label=usingSample?'Sample data':`Parking service · ${pStatus.storage==='supabase'?'Supabase':pStatus.storage==='local'?'SQLite':esc(pStatus.storage||'connected')}`;
  document.querySelectorAll('[data-src-chip]').forEach(c=>{c.textContent=label;c.className='src-chip '+(usingSample?'sample':'live');});
  document.querySelectorAll('[data-demo-banner]').forEach(b=>{b.hidden=!usingSample;});
  document.querySelectorAll('[data-demo-reason]').forEach(r=>{r.textContent=`The parking service is not reachable (${parkingError}).`;});
  renderAdmin();renderDevices();
}
function totalAvail(){const c=(pStatus&&pStatus.capacity)||{};return Object.values(c).reduce((n,k)=>n+(k.available||0),0);}

/* ===================== Live-sensor driven pieces ===================== */
function renderLive(){
  renderDevices();
}
/* MQTT topics: live receive state per source, from the sensor backend's /api/latest */
const TOPIC_ROWS=[['gate','parking/gate/telemetry','Arduino UNO gate via ESP32 (UART)','U1/U2 zones, gate simulation, counters, vibration'],
  ['uno','parking/node/telemetry','Legacy UNO sensor node','Earlier single-bay format · superseded by gate v2'],
  ['esp32','parking/gateway/telemetry','ESP32 DevKit','Temperature, humidity, light, gas · 2.5 s'],
  ['camera','parking/camera/result','Camera service','Advisory camera slot result']];
function renderTopics(){
  const d=latestData;
  $('topic-body').innerHTML=TOPIC_ROWS.map(([key,topic,pub,carries])=>{
    const s=d&&d.sources?d.sources[key]:null;
    let tag='<span class="tag gray">Unknown</span>',last='—';
    if(s){
      const age=Number.isFinite(s.age_seconds)?s.age_seconds:null;
      last=s.last_received_utc?`${fmtTime(s.last_received_utc)} · ${age!=null?age.toFixed(1)+' s ago':''}`:(age!=null?age.toFixed(1)+' s ago':'No message yet');
      tag=s.fresh&&s.payload_valid?'<span class="tag green">Receiving</span>':s.received_recently&&!s.payload_valid?'<span class="tag red">Invalid payload</span>':age!=null?'<span class="tag amber">Stale</span>':'<span class="tag gray">No publisher yet</span>';
    }
    return `<tr><td><code>${topic}</code></td><td>${pub}</td><td>${carries}</td><td>${last}</td><td>${tag}</td></tr>`;}).join('');
  $('topic-note').textContent=d?`Broker ${d.mqtt_connected?'connected':'disconnected'} · Mosquitto · TCP 1883 · authenticated`:'Sensor server unavailable';
  $('topic-foot').textContent=d?`Rejected ${d.rejected_messages||0} · Discarded ${d.discarded_messages||0} · Queue dropped ${d.dropped_messages||0} · updates every 2 s`:'';
}
function renderDevices(){
  const d=latestData,s=d?d.sources:{};
  const ok=src=>src&&src.fresh&&src.payload_valid;
  const ago=src=>src&&Number.isFinite(src.age_seconds)?src.age_seconds.toFixed(1)+' s ago':'no message';
  const cloud=(d&&d.cloud)||{};
  const pk=parkingLoaded?(usingSample?'offline':'online'):'unknown';
  const items=[
    ['Arduino UNO gate','U1 approach · U2 passage · KY-002 · LCD · servo disabled',d?(ok(s.gate)?'online':'stale'):'unknown',d?'Last message '+ago(s.gate):'Sensor server unavailable'],
    ['ESP32 DevKit','Gateway · DHT22 · LDR · MQ-2 · Wi-Fi',d?(ok(s.esp32)?'online':'stale'):'unknown',d?'Last message '+ago(s.esp32):'Sensor server unavailable'],
    ['Mosquitto broker','MQTT · TCP 1883 · authenticated',d?(d.mqtt_connected?'online':'offline'):'unknown',d?(d.ingestion_connected?'Ingestion receiving':'Waiting for messages'):'Sensor server unavailable'],
    ['InfluxDB (local)','Sensor time-series · 7-day retention',d?(d.storage_connected?'online':'offline'):'unknown',d?'Backlog '+(d.storage_backlog||0)+' · Dropped '+(d.storage_dropped_points||0):'Sensor server unavailable'],
    ['InfluxDB Cloud','Optional sensor archive · 30-day retention',d?(cloud.error?'offline':cloud.enabled?'online':'idle'):'unknown',d?(cloud.enabled?'Uploaded '+(cloud.uploaded||0)+' · Pending '+(cloud.pending||0):'Not configured'):'Sensor server unavailable'],
    ['Parking service','FastAPI :8000 · Gemini + PaddleOCR',pk,usingSample?(parkingLoaded?'Unreachable · '+parkingError:'Checking…'):'Gate mode '+esc(pStatus.gate_mode||'simulation')],
    ['Parking ledger',usingSample?'Supabase or SQLite':(pStatus.storage==='supabase'?'Supabase PostgreSQL':'SQLite (local)'),pk,usingSample?'No live ledger':`${pStatus.spaces.length} bays · ${pStatus.archived_observations??'—'} observations`],
    ['Photo archive',usingSample?'Private bucket or local disk':(pStatus.storage==='supabase'?'Supabase private bucket':'Local disk'),pk,usingSample?'No live archive':`${pStatus.archived_images??'—'} images archived`],
    ['ESP32-CAM ×2','Entrance + exit · HTTP /capture',parkingLoaded&&!usingSample?'idle':'unknown','Captured by the parking service · open the camera console for previews']
  ];
  const label={online:'Online',stale:'Stale',offline:'Offline',idle:'Via parking service',unknown:'Unknown'};
  renderTopics();
  $('device-grid').innerHTML=items.map(([n,sub,st,detail])=>`<article class="card device ${st}"><div class="dev-top"><span class="dev-dot" aria-hidden="true"></span><span class="dev-state">${label[st]}</span></div><h3>${esc(n)}</h3><p>${esc(sub)}</p><div class="dev-detail">${esc(detail)}</div></article>`).join('');
}

/* ===================== Admin views ===================== */
const bayState={free:['Free','available','green'],occupied:['Occupied','occupied','red'],sensor_occupied:['Sensor: occupied','occupied','red'],sensor_stale:['Sensor stale','unknown','amber'],sensor_unknown:['Sensor unknown','unknown','amber']};
function bayHtml(b,big){
  const [label,cls,tag]=bayState[b.status]||['Unknown','unknown','gray'];
  if(!big)return `<div class="mini-bay ${cls}"><span class="bay-name">${esc(b.id)}</span><span class="bay-kind">${kindLabel[b.kind]||esc(b.kind)}</span><span class="bay-state">${label}</span>${b.plate?`<span class="bay-plate">${esc(b.plate)}</span>`:''}</div>`;
  return `<article class="bay-card ${cls}"><div class="bay-top"><span class="bay-id">${esc(b.id)}</span><span class="tag ${tag}">${label}</span></div>
    <svg viewBox="0 0 80 120" class="bay-car" aria-hidden="true"><rect x="12" y="10" width="56" height="100" rx="16"/><rect x="20" y="26" width="40" height="20" rx="5" class="g"/><rect x="20" y="70" width="40" height="16" rx="4" class="g"/></svg>
    <dl><dt>Plate</dt><dd>${b.plate?esc(b.plate):'—'}</dd><dt>Type</dt><dd>${b.vehicle_type?typeLabel[b.vehicle_type]||esc(b.vehicle_type):'—'}</dd><dt>Since</dt><dd>${b.entered_at?fmtTime(b.entered_at)+' · '+fmtDur(Date.now()-Date.parse(b.entered_at)):'—'}</dd>${b.sensor_observed_at?`<dt>Sensor</dt><dd>${b.sensor_occupied?'Occupied':'Free'} · ${fmtTime(b.sensor_observed_at)}</dd>`:''}</dl></article>`;
}
/* ---------- shared helpers for the admin pages ---------- */
const pad2=n=>String(n).padStart(2,'0');
const dayKey=v=>{const d=new Date(v);return `${d.getFullYear()}-${pad2(d.getMonth()+1)}-${pad2(d.getDate())}`;};
const dayStart=key=>{const [y,m,d]=key.split('-').map(Number);return new Date(y,m-1,d).getTime();};
const fmtDay=key=>new Date(dayStart(key)).toLocaleDateString([], {weekday:'short',month:'short',day:'numeric'});
const darkScales={x:{grid:{display:false},ticks:{color:'#64748f'}},y:{beginAtZero:true,ticks:{precision:0,color:'#64748f'},grid:{color:'#e9eef6'}}};
const darkLegend={display:true,labels:{color:'#11223f',boxWidth:12,boxHeight:12}};
function barRows(el,entries,cls){
  const max=Math.max(1,...entries.map(e=>e[1]));
  $(el).innerHTML=entries.length?entries.map(([label,n,c])=>`<div class="tbar"><span>${esc(label)}</span><div class="track"><div class="fill ${c||cls||''}" data-w="${(n/max*100).toFixed(0)}"></div></div><strong>${n}</strong></div>`).join(''):'<p class="nempty">No visits</p>';
  document.querySelectorAll(`#${el} .fill`).forEach(f=>{f.style.width=f.dataset.w+'%';});
}
const gbayHtml=b=>{const [label,cls]=bayState[b.status]||['Unknown','unknown'];return `<div class="gbay ${cls}"><strong>${esc(b.id)}</strong><span>${b.plate?esc(b.plate):label}</span></div>`;};
const typeCounts=rows=>[['Normal car','car','car'],['Sport car','sport','sportcar']].map(([label,g,c])=>[label,rows.filter(x=>typeGroup(x.vehicle_type)===g).length,c]);

/* ---------- Today ---------- */
let trendChart=null,histChart=null,recPage=0,decFilter='denied',hScope='all',hDay=dayKey(Date.now());
function renderAdmin(){
  if(!pStatus)return;
  const cap=pStatus.capacity||{},spaces=pStatus.spaces,events=pHistory.events;
  const inside=spaces.filter(b=>b.session_id);
  $('today-date').textContent=new Date().toLocaleDateString('en-US', {weekday:'long',day:'numeric',month:'long',year:'numeric'})+' · Live updates every few seconds';
  $('live-cars').textContent=inside.length;
  $('live-cars-sub').textContent=`${inside.length} of ${spaces.length} spaces occupied`;
  $('live-cars-kinds').textContent=['vip','normal'].map(k=>`${kindLabel[k]}: ${cap[k]?cap[k].occupied:0}`).join(' · ');
  $('live-avail').textContent=totalAvail();
  $('live-avail-sub').textContent=['vip','normal'].map(k=>`${kindLabel[k]}: ${cap[k]?cap[k].available:0}`).join(' · ')+(Object.values(cap).some(k=>k.unavailable)?' · some blocked by sensor':'');
  const todayEv=events.filter(e=>isToday(e.created_at));
  $('kpi-entries').textContent=todayEv.filter(e=>e.approved&&e.reason==='entry_registered').length;
  $('kpi-entries-sub').textContent=`${inside.length} vehicle${inside.length===1?'':'s'} currently parked`;
  const denied=todayEv.filter(e=>!e.approved).length;$('kpi-denied').textContent=denied;$('review-count').textContent=denied;
  $('kpi-denied-sub').textContent=denied?`${denied} denied entr${denied===1?'y':'ies'} today`:'No denied entries today';
  $('ov-updated').textContent=parkingUpdated?parkingUpdated.toLocaleTimeString():'sample';
  $('live-bays').innerHTML=spaces.map(b=>gbayHtml(b).replace('class="gbay ',`class="gbay ${b.kind} `)).join('');
  $('lot-vip').innerHTML=spaces.filter(b=>b.kind==='vip').map(b=>bayHtml(b,true)).join('');
  $('lot-normal').innerHTML=spaces.filter(b=>b.kind==='normal').map(b=>bayHtml(b,true)).join('');
  barRows('live-types',typeCounts(visitRows().filter(x=>isToday(x.entered_at))));
  const photos={};pHistory.sessions.forEach(x=>{photos[String(sid(x))]=x.entrance_photo_url;});
  $('today-parked').innerHTML=inside.map(b=>`<tr><td>${photoThumb(photos[String(b.session_id)],b.vehicle_type,String(b.session_id))}</td><td>${plateHtml(b.plate)}<div class="sub">${typeLabel[b.vehicle_type]||''}</div></td><td><strong>${esc(b.id)}</strong></td><td>${fmtTime(b.entered_at)}<div class="sub">${fmtDur(Date.now()-Date.parse(b.entered_at))}</div></td></tr>`).join('')||'<tr><td colspan="4" class="empty">The car park is empty</td></tr>';
  $('activity-body').innerHTML=todayEv.slice(0,7).map(e=>`<tr><td>${fmtTime(e.created_at)}</td><td>${e.camera==='exit'?'Exit':'Entrance'}</td><td>${plateHtml(e.plate)}</td><td>${decisionTag(e)}</td></tr>`).join('')||'<tr><td colspan="4" class="empty">No gate decisions yet today</td></tr>';
  renderTrend();renderHistory();renderDecisions();renderGateLot();
}
const decisionTag=e=>`<span class="tag ${e.approved?'green':'amber'}">${esc(reasonLabel[e.reason]||e.reason)}</span>`;
function hourly(events,key,reason){const bins=new Array(24).fill(0);events.forEach(e=>{if(e.approved&&e.reason===reason&&dayKey(e.created_at)===key)bins[new Date(e.created_at).getHours()]++;});return bins;}
function renderTrend(){
  if(typeof Chart==='undefined'||!$('trend-chart').offsetParent)return;
  const key=dayKey(Date.now()),ins=hourly(pHistory.events,key,'entry_registered'),outs=hourly(pHistory.events,key,'exit_registered');
  const hour=new Date().getHours(),from=Math.max(0,hour-11),labels=[];for(let h=from;h<=hour;h++)labels.push(pad2(h)+':00');
  $('trend-note').textContent=usingSample?'Sample data':'Approved at the gate';
  if(trendChart)trendChart.destroy();
  trendChart=new Chart($('trend-chart'),{type:'bar',data:{labels,datasets:[{label:'Came in',data:ins.slice(from,hour+1),backgroundColor:'#2f7bf6',borderRadius:6,maxBarThickness:22},{label:'Drove out',data:outs.slice(from,hour+1),backgroundColor:'#19a3a8',borderRadius:6,maxBarThickness:22}]},options:{responsive:true,maintainAspectRatio:false,animation:false,plugins:{legend:darkLegend},scales:darkScales}});
}

/* ---------- History ---------- */
let recStatus='';
function visitRows(){
  // Every active visit comes from the bay status (always complete); history adds photos and past visits.
  const rows=new Map();
  pHistory.sessions.forEach(x=>rows.set(String(sid(x)),x));
  pStatus.spaces.filter(b=>b.session_id).forEach(b=>{const k=String(b.session_id);const old=rows.get(k)||{};
    rows.set(k,{...old,id:b.session_id,plate:b.plate||plateOf(old),vehicle_type:b.vehicle_type||old.vehicle_type,space_id:b.id,status:'still_in',entered_at:b.entered_at||old.entered_at,exited_at:null});});
  return [...rows.values()].sort((a,b)=>(a.status==='still_in'?0:1)-(b.status==='still_in'?0:1)||Date.parse(b.entered_at)-Date.parse(a.entered_at));
}
function scopeRows(){
  const all=visitRows();if(hScope==='all')return all;
  const s=dayStart(hDay),e=s+86400000;
  return all.filter(x=>Date.parse(x.entered_at)<e&&(!x.exited_at||Date.parse(x.exited_at)>=s));
}
const scopeEvents=()=>hScope==='all'?pHistory.events:pHistory.events.filter(e=>dayKey(e.created_at)===hDay);
function recFiltered(){
  const q=$('rec-q').value.replace(/\s/g,'').toLowerCase(),t=$('rec-type').value;
  return scopeRows().filter(x=>(!q||(plateOf(x)||'').replace(/\s/g,'').toLowerCase().includes(q))&&(!recStatus||x.status===recStatus)&&(!t||typeGroup(x.vehicle_type)===t));
}
function renderHistory(){
  if(!pStatus)return;
  const rows=scopeRows(),ev=scopeEvents(),done=rows.filter(x=>x.exited_at);
  const capped=pHistory.sessions.length>=100;
  const oldest=visitRows().reduce((m,x)=>Math.min(m,Date.parse(x.entered_at)||Infinity),Infinity);
  $('hist-note').textContent=hScope==='all'?(Number.isFinite(oldest)?`${capped?'Latest 100 visits':'All recorded visits'} · since ${fmtDay(dayKey(oldest))}`:'No visits recorded yet'):fmtDay(hDay)+(hDay===dayKey(Date.now())?' (today)':'');
  $('day-pick').hidden=hScope!=='day';$('day-input').max=dayKey(Date.now());$('day-input').value=hDay;$('day-next').disabled=hDay>=dayKey(Date.now());
  $('h-visits').textContent=rows.length;
  $('h-visits-sub').textContent=`${rows.filter(x=>x.status==='still_in').length} still parked · ${done.length} completed`;
  if(hScope==='all'){
    const per={};rows.forEach(x=>{const k=dayKey(x.entered_at);per[k]=(per[k]||0)+1;});
    const best=Object.entries(per).sort((a,b)=>b[1]-a[1])[0];
    $('h-peak-label').textContent='Busiest day';$('h-peak').textContent=best?fmtDay(best[0]):'—';$('h-peak-sub').textContent=best?`${best[1]} visits`:'No visits';
  }else{
    const ins=hourly(pHistory.events,hDay,'entry_registered');const m=Math.max(...ins);const h=ins.indexOf(m);
    $('h-peak-label').textContent='Busiest hour';$('h-peak').textContent=m?`${pad2(h)}:00–${pad2(h+1)}:00`:'—';$('h-peak-sub').textContent=m?`${m} cars came in`:'No cars came in';
  }
  $('h-avg').textContent=done.length?fmtDur(done.reduce((n,x)=>n+Date.parse(x.exited_at)-Date.parse(x.entered_at),0)/done.length):'—';
  $('h-avg-sub').textContent=done.length?`From ${done.length} completed visit${done.length>1?'s':''}`:'No completed visits';
  const checks=ev.filter(e=>e.camera==='entrance'),ok=checks.filter(e=>e.approved);
  $('h-rate').textContent=checks.length?Math.round(ok.length/checks.length*100)+'%':'—';
  $('h-rate-sub').textContent=checks.length?`${ok.length} of ${checks.length} entrance checks`:'No entrance checks';
  barRows('h-types',typeCounts(rows));
  const bays={};rows.forEach(x=>{if(x.space_id)bays[x.space_id]=(bays[x.space_id]||0)+1;});
  barRows('h-bays',Object.entries(bays).sort((a,b)=>b[1]-a[1]).slice(0,5).map(([k,n])=>[k,n,k.startsWith('VIP')?'sportcar':'car']));
  renderHistChart();renderRecords();
}
function renderHistChart(){
  if(typeof Chart==='undefined'||!$('hist-chart').offsetParent)return;
  let labels,sets;
  if(hScope==='all'){
    const today=dayStart(dayKey(Date.now())),keys=[];for(let i=13;i>=0;i--)keys.push(dayKey(today-i*86400000+43200000));
    const ins=keys.map(k=>pHistory.events.filter(e=>e.approved&&e.reason==='entry_registered'&&dayKey(e.created_at)===k).length);
    const den=keys.map(k=>pHistory.events.filter(e=>!e.approved&&e.camera==='entrance'&&dayKey(e.created_at)===k).length);
    labels=keys.map(k=>new Date(dayStart(k)).toLocaleDateString([], {month:'short',day:'numeric'}));
    sets=[{label:'Came in',data:ins,backgroundColor:'#2f7bf6',borderRadius:5,maxBarThickness:26},{label:'Turned away',data:den,backgroundColor:'#ffb648',borderRadius:5,maxBarThickness:26}];
    $('h-chart-title').textContent='Cars per day · last 14 days';
  }else{
    labels=[...Array(24).keys()].map(h=>pad2(h));
    sets=[{label:'Came in',data:hourly(pHistory.events,hDay,'entry_registered'),backgroundColor:'#2f7bf6',borderRadius:5,maxBarThickness:18},{label:'Drove out',data:hourly(pHistory.events,hDay,'exit_registered'),backgroundColor:'#19a3a8',borderRadius:5,maxBarThickness:18}];
    $('h-chart-title').textContent='Cars by hour · '+fmtDay(hDay);
  }
  $('h-chart-note').textContent=usingSample?'Sample data':'';
  if(histChart)histChart.destroy();
  histChart=new Chart($('hist-chart'),{type:'bar',data:{labels,datasets:sets},options:{responsive:true,maintainAspectRatio:false,animation:false,plugins:{legend:darkLegend},scales:darkScales}});
}
function renderRecords(){
  const all=scopeRows(),inside=all.filter(x=>x.status==='still_in');
  $('cnt-all').textContent=all.length;$('cnt-in').textContent=inside.length;$('cnt-left').textContent=all.length-inside.length;
  $('log-title').textContent=hScope==='all'?'Visit log':'Visit log · '+fmtDay(hDay);
  const rows=recFiltered(),per=10,pages=Math.max(1,Math.ceil(rows.length/per));recPage=Math.max(0,Math.min(recPage,pages-1));
  const slice=rows.slice(recPage*per,recPage*per+per);
  const link=(x,which,u,l)=>photoUrl(u)?`<button type="button" class="link-btn" data-visit="${esc(String(sid(x)))}" data-which="${which}">${l}</button>`:'';
  $('rec-body').innerHTML=slice.map(x=>{const k=kindOf(x.vehicle_type);return `<tr class="${x.status==='still_in'?'row-in':''}"><td>${photoThumb(x.entrance_photo_url,x.vehicle_type,String(sid(x)))}</td><td>${plateHtml(plateOf(x))}</td><td>${typeLabel[x.vehicle_type]||'—'}</td><td><strong>${esc(x.space_id||'—')}</strong><div class="sub">${k?kindLabel[k]:''}</div></td><td>${fmtDateTime(x.entered_at)}</td><td>${fmtDateTime(x.exited_at)}</td><td>${fmtDur((x.exited_at?Date.parse(x.exited_at):Date.now())-Date.parse(x.entered_at))}</td><td>${x.status==='still_in'?'<span class="tag blue">Parked</span>':'<span class="tag gray">Left</span>'}</td><td class="links">${[link(x,'entry',x.entrance_photo_url,'Entry'),link(x,'exit',x.exit_photo_url,'Exit')].filter(Boolean).join(' · ')||'—'}</td></tr>`;}).join('')||`<tr><td colspan="9" class="empty">${hScope==='day'?'No visits on this day':'No matching visits'}</td></tr>`;
  $('rec-info').textContent=rows.length?`Showing ${recPage*per+1}–${recPage*per+slice.length} of ${rows.length}`:'0 visits';
  $('rec-prev').disabled=recPage===0;$('rec-next').disabled=recPage>=pages-1;
}
function renderDecisions(){
  const rows=pHistory.events.filter(e=>decFilter===''||(decFilter==='approved')===!!e.approved);
  $('review-grid').innerHTML=rows.slice(0,30).map(e=>{const src=photoUrl(e.photo_url);return `<article class="card review ${e.approved?'ok':'denied'}">
    <div class="shot">${src?`<button type="button" class="shot-btn" data-event="${esc(e.id)}" aria-label="View ${e.camera} photo"><img src="${src}" alt="" loading="lazy"></button>`:'<svg viewBox="0 0 160 90" aria-hidden="true"><rect width="160" height="90" class="sky"/><rect x="30" y="38" width="100" height="34" rx="10" class="body"/><path d="M50 38l12-16h36l14 16z" class="body"/><rect x="62" y="56" width="36" height="12" rx="2" class="plate-box"/></svg>'}<span class="cam-tag">${e.camera==='exit'?'Exit':'Entrance'} camera</span></div>
    <div class="review-body"><div class="review-top">${decisionTag(e)}<span class="sub">${fmtDateTime(e.created_at)}</span></div>
    <dl><dt>Plate</dt><dd>${plateHtml(e.plate)}</dd><dt>Vehicle type</dt><dd>${typeLabel[e.vehicle_type]||'—'}</dd><dt>Space</dt><dd>${esc(e.space_id||'—')}</dd><dt>Gate</dt><dd>${e.approved?'OPEN · simulated':'Kept closed'}</dd></dl></div></article>`;}).join('')||`<article class="card empty">No ${decFilter||''} decisions in the latest 100 events</article>`;
}

/* ===================== Gate operation (camera + recognition via the parking service) ===================== */
const decisionMessages={entry_registered:'Entry registered',exit_registered:'Exit registered · space released',normal_full:'No normal bay is free · normal cars cannot use VIP bays',vip_full:'No VIP bay is free · sport cars cannot use normal bays',already_inside:'This plate is already registered inside',no_active_session:'No active visit matches this exit plate',recognition_needs_review:'Plate or vehicle recognition needs review',unsupported_vehicle_type:'Vehicle type is not supported'};
const G={dir:'entrance',captured:'entrance',blob:null,url:null,box:null,drag:null,obs:null,fresh:false,registered:false,busy:false,paused:false,gateTimer:null};
const cams={entrance:{timer:null,loading:false,url:null,streaming:false,fallback:false},exit:{timer:null,loading:false,url:null,streaming:false,fallback:false}};
const gateActive=()=>!document.querySelector('[data-view="gate"]').hidden&&!document.hidden;
const secs=v=>v==null||!Number.isFinite(Number(v))?'—':(Number(v)/1000).toFixed(2)+' s';
function gStatus(text,state){const el=$('g-status');el.textContent=text;el.dataset.state=state||'';}
function gError(text){$('g-error').textContent=text||'';$('g-error').hidden=!text;}
function gSteps(n){document.querySelectorAll('#g-steps li').forEach(li=>{const s=+li.dataset.step;li.className=s<n?'done':s===n?'on':'';});}
const SIM_COMMIT=document.body.dataset.simulatorCommit!=='no';
if(!SIM_COMMIT){$('g-commit').textContent='Simulator commit off';$('g-sim-note').textContent='Simulator commit is turned off (PARKING_SIMULATOR_COMMIT=no). Entry and exit are recorded by the passage-aware gate workflow.';}
function gControls(){
  $('g-capture').disabled=G.busy;$('g-file').disabled=G.busy;$('g-reset').disabled=G.busy;
  document.querySelectorAll('#dir-seg button').forEach(b=>{b.disabled=G.busy;});
  $('g-read').disabled=G.busy||!G.blob||G.registered;$('g-read').textContent=G.box?'Read selected plate':'Analyze photo';
  $('g-commit').disabled=!SIM_COMMIT||G.busy||!G.fresh||!G.obs||G.registered||usingSample;
  document.querySelectorAll('.cam-card').forEach(c=>c.classList.toggle('selected',c.dataset.camera===G.dir));
}
/* --- live previews: one fresh still per camera about once a second, paused while capturing --- */
function pollCam(role){
  const c=cams[role];clearTimeout(c.timer);
  if(!gateActive())return;
  if(c.loading||(G.paused&&G.captured===role)){c.timer=setTimeout(()=>pollCam(role),1000);return;}
  c.loading=true;
  fetch(`/api/camera/frame?camera=${role}`,{cache:'no-store'}).then(async r=>{
    if(!r.ok){const d=await r.json().catch(()=>({}));throw Error(d.error||'Camera unavailable');}
    const blob=await r.blob();if(c.url)URL.revokeObjectURL(c.url);c.url=URL.createObjectURL(blob);
    const img=$(`cam-${role}-img`);img.src=c.url;await img.decode();img.hidden=false;$(`cam-${role}-msg`).hidden=true;
    $(`cam-${role}-tag`).textContent='Live · 1 fps';$(`cam-${role}-tag`).className='tag green';
    c.timer=setTimeout(()=>pollCam(role),1000);
  }).catch(e=>{
    $(`cam-${role}-img`).hidden=true;const m=$(`cam-${role}-msg`);m.hidden=false;m.textContent=(e.message||'Camera unavailable')+' · retrying…';
    $(`cam-${role}-tag`).textContent='Offline';$(`cam-${role}-tag`).className='tag amber';
    c.timer=setTimeout(()=>pollCam(role),8000);
  }).finally(()=>{c.loading=false;});
}
/* Live video: MJPEG from the parking service (~4 fps), relayed by this dashboard's backend.
   If a camera is already streaming to another page (409), fall back to one still per second. */
function camOk(role,label){$(`cam-${role}-img`).hidden=false;$(`cam-${role}-msg`).hidden=true;$(`cam-${role}-tag`).textContent=label;$(`cam-${role}-tag`).className='tag green';}
function camDown(role,text){const img=$(`cam-${role}-img`);img.hidden=true;const m=$(`cam-${role}-msg`);m.hidden=false;m.textContent=text;$(`cam-${role}-tag`).textContent='Offline';$(`cam-${role}-tag`).className='tag amber';}
function startStream(role){
  const c=cams[role];if(!gateActive()||(G.paused&&G.captured===role)||c.streaming)return;
  clearTimeout(c.timer);c.timer=null;c.streaming=true;c.fallback=false;
  const img=$(`cam-${role}-img`);
  img.onload=()=>{if(c.streaming)camOk(role,'Live video');};
  img.onerror=async()=>{
    if(!c.streaming)return;c.streaming=false;img.removeAttribute('src');
    const busy=await fetch(`/api/camera/stream?camera=${role}&probe=1`,{cache:'no-store'}).then(r=>r.json()).then(d=>d.busy).catch(()=>false);
    if(busy){
      // Another page (or a just-closed connection) holds the stream: show stills, then try live video again.
      c.fallback=true;pollCam(role);clearTimeout(c.retry);
      c.retry=setTimeout(()=>{if(!c.fallback)return;c.fallback=false;clearTimeout(c.timer);c.timer=null;startStream(role);},6000);return;}
    camDown(role,'Camera unavailable · reconnecting…');c.timer=setTimeout(()=>startStream(role),3000);
  };
  img.src=`/api/camera/stream?camera=${role}&t=${Date.now()}`;
}
function stopStream(role){const c=cams[role];c.streaming=false;const img=$(`cam-${role}-img`);img.onload=img.onerror=null;img.removeAttribute('src');}
function startCams(){for(const r of Object.keys(cams)){if(cams[r].fallback){if(!cams[r].timer&&!cams[r].loading)pollCam(r);}else startStream(r);}}
function stopCams(){for(const r of Object.keys(cams)){clearTimeout(cams[r].timer);clearTimeout(cams[r].retry);cams[r].timer=null;cams[r].fallback=false;stopStream(r);}}
function pauseCam(role,text){G.paused=true;G.captured=role;clearTimeout(cams[role].timer);cams[role].timer=null;stopStream(role);$(`cam-${role}-img`).hidden=true;$(`cam-${role}-msg`).hidden=false;$(`cam-${role}-msg`).textContent='Paused while this camera takes a photo';$(`cam-${role}-tag`).textContent=text;$(`cam-${role}-tag`).className='tag blue';}
/* --- capture / upload --- */
function clearResult(){
  G.obs=null;G.fresh=false;G.registered=false;
  for(const id of ['g-vehicle','g-kind','g-t-cam','g-t-gemini','g-t-enh','g-t-ocr'])$(id).textContent='—';
  $('g-plate').textContent='—';$('g-plate').className='plate big none';$('g-ocr-conf').textContent='OCR confidence —';$('g-vehicle-conf').textContent='—';$('g-model').textContent='Model —';
  $('g-crop').hidden=true;$('g-crop').removeAttribute('src');gError('');$('g-decision').hidden=true;
}
function resetCapture(){
  G.blob=null;G.box=null;G.drag=null;if(G.url)URL.revokeObjectURL(G.url);G.url=null;G.paused=false;
  $('g-stage').hidden=true;$('g-box').hidden=true;$('g-still').removeAttribute('src');
  $('g-finder-msg').hidden=false;$('g-finder-msg').textContent='Choose a direction, then capture a fresh photo or upload a test photo.';
  $('g-reset').hidden=true;$('g-hint').textContent='Live previews refresh about once a second while this page is open.';
  clearResult();gSteps(1);gStatus('Ready.');gControls();startCams();
}
async function showStill(blob){
  G.blob=blob;if(G.url)URL.revokeObjectURL(G.url);G.url=URL.createObjectURL(blob);
  $('g-still').src=G.url;await $('g-still').decode();
  $('g-finder-msg').hidden=true;$('g-stage').hidden=false;$('g-reset').hidden=false;
  $('g-hint').textContent='Drag a tight box around the registration characters to correct the plate crop.';
}
$('g-capture').addEventListener('click',async()=>{
  if(G.busy)return;G.busy=true;G.box=null;$('g-box').hidden=true;clearResult();pauseCam(G.dir,'Capturing');gControls();
  gStatus('Taking a fresh photo…','pending');$('g-finder-msg').hidden=false;$('g-finder-msg').textContent='Taking a fresh photo…';$('g-stage').hidden=true;
  try{
    const r=await fetch(`/api/camera/frame?camera=${G.dir}`,{cache:'no-store'});
    if(!r.ok){const d=await r.json().catch(()=>({}));throw Error(d.error||'Could not take a photo');}
    $('g-t-cam').textContent=secs(r.headers.get('X-Camera-Ms'));
    await showStill(await r.blob());$(`cam-${G.dir}-tag`).textContent='Paused';
    await analyze();
  }catch(e){gStatus('Capture failed.','error');gError(e.message);if(!G.blob)resetCapture();}
  finally{G.busy=false;gControls();}
});
$('g-file').addEventListener('change',async ev=>{
  const f=ev.target.files[0];ev.target.value='';if(!f||G.busy)return;
  if(f.size>15*1024*1024){gError('Choose an image smaller than 15 MiB.');return;}
  G.box=null;$('g-box').hidden=true;clearResult();pauseCam(G.dir,'Test photo');
  try{await showStill(f);gSteps(2);gStatus(G.dir==='entrance'?'Test photo loaded. Analyze it (Gemini finds the plate) or draw a box first.':'Test photo loaded. Draw a box around the plate, then read it.');}
  catch{gError('Could not open this image. Try JPEG or PNG.');resetCapture();}
  gControls();
});
$('g-reset').addEventListener('click',resetCapture);
$('dir-seg').addEventListener('click',ev=>{const b=ev.target.closest('button');if(!b||G.busy)return;G.dir=b.dataset.dir;$('dir-seg').querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));resetCapture();});
/* --- plate box drawing (coordinates in original-image pixels) --- */
const stage=$('g-stage'),still=$('g-still'),boxEl=$('g-box');
function pt(ev){const r=still.getBoundingClientRect(),c=v=>Math.max(0,Math.min(1,v));return [c((ev.clientX-r.left)/r.width),c((ev.clientY-r.top)/r.height)];}
function paint(x,y,r,b){boxEl.style.left=x*100+'%';boxEl.style.top=y*100+'%';boxEl.style.width=(r-x)*100+'%';boxEl.style.height=(b-y)*100+'%';boxEl.hidden=false;}
function paintPx(bx){const w=still.naturalWidth,h=still.naturalHeight;if(!w||!h)return;paint(bx[0]/w,bx[1]/h,bx[2]/w,bx[3]/h);}
function dragBox(ev){const e=pt(ev),s=G.drag.start,x=Math.min(s[0],e[0]),y=Math.min(s[1],e[1]),r=Math.max(s[0],e[0]),b=Math.max(s[1],e[1]);paint(x,y,r,b);
  return [Math.floor(x*still.naturalWidth),Math.floor(y*still.naturalHeight),Math.ceil(r*still.naturalWidth),Math.ceil(b*still.naturalHeight)];}
stage.addEventListener('pointerdown',ev=>{if(!ev.isPrimary||ev.button!==0||G.busy||G.registered)return;G.fresh=false;G.drag={id:ev.pointerId,start:pt(ev)};stage.setPointerCapture(ev.pointerId);G.box=null;dragBox(ev);gControls();});
stage.addEventListener('pointermove',ev=>{if(G.drag&&G.drag.id===ev.pointerId)dragBox(ev);});
stage.addEventListener('pointerup',ev=>{if(!G.drag||G.drag.id!==ev.pointerId)return;const bx=dragBox(ev);G.drag=null;
  if(bx[2]-bx[0]<5||bx[3]-bx[1]<5){boxEl.hidden=true;gStatus('Draw a larger box around the license plate.','review');}
  else{G.box=bx;gStatus('Plate selected. Click Read selected plate.','');}gControls();});
stage.addEventListener('pointercancel',()=>{G.drag=null;boxEl.hidden=true;gControls();});
/* --- analyze + commit --- */
async function analyze(){
  const form=new FormData();form.append('image',G.blob,'capture.jpg');form.append('camera',G.dir);
  if(G.box)form.append('plate_bbox',G.box.join(','));
  if(G.obs)form.append('previous_observation_id',G.obs.observation_id);
  gStatus(G.dir==='entrance'?'Classifying the vehicle and reading the plate…':'Reading the exit plate…','pending');gSteps(2);
  const r=await fetch('/api/parking/analyze',{method:'POST',body:form});const d=await r.json().catch(()=>({}));
  if(!r.ok)throw Error(d.error||'Analysis failed');
  G.obs=d;G.fresh=true;G.registered=false;
  if(Array.isArray(d.plate_bbox)&&d.plate_bbox.length===4){G.box=d.plate_bbox;paintPx(G.box);}
  const plate=d.license_plate;$('g-plate').textContent=plate||'Unreadable';$('g-plate').className='plate big'+(plate?'':' none');
  $('g-ocr-conf').textContent='OCR confidence '+(d.ocr_confidence!=null?Number(d.ocr_confidence).toFixed(2):'—')+(d.ocr_engine?' · '+d.ocr_engine:'');
  if(G.dir==='exit'){$('g-vehicle').textContent='From entry record';$('g-vehicle-conf').textContent='Exit reads the plate only';$('g-kind').textContent='Bay of the matching visit';}
  else{$('g-vehicle').textContent=typeLabel[d.vehicle_type]||'Unknown';$('g-vehicle-conf').textContent='Confidence '+(d.vehicle_confidence!=null?Number(d.vehicle_confidence).toFixed(2):'—');
    const k=kindOf(d.vehicle_type);$('g-kind').textContent=k?kindLabel[k]+' bay':'No matching bay type';}
  $('g-model').textContent='Model '+(d.model||'—');
  const pm=d.processing_ms||{};$('g-t-gemini').textContent=G.dir==='exit'?'skipped':secs(pm.vehicle);$('g-t-enh').textContent=secs(d.preprocess_ms);$('g-t-ocr').textContent=secs(d.ocr_ms);
  if(typeof d.enhanced_plate==='string'&&d.enhanced_plate.startsWith('data:image/jpeg;base64,')){$('g-crop').src=d.enhanced_plate;$('g-crop').hidden=false;}
  gError((d.errors||[]).join(' · '));
  gStatus(d.eligible?'Analysis saved. Review the plate, then check the gate.':'Analysis saved, but recognition needs review. Redraw the plate box and read again, or check the gate to record a denial.',d.eligible?'success':'review');
  gSteps(3);
}
$('g-read').addEventListener('click',async()=>{if(G.busy||!G.blob)return;G.busy=true;gControls();try{await analyze();}catch(e){gStatus('Could not analyze this photo.','error');gError(e.message);}finally{G.busy=false;gControls();}});
function setGate(){} // the gate simulator panel was removed; the decision box shows the outcome
$('g-commit').addEventListener('click',async()=>{
  if(G.busy||!G.fresh||!G.obs||G.registered)return;G.busy=true;gControls();gStatus('Checking matching bays and recording the decision…','pending');
  try{
    const r=await fetch('/api/parking/commit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({observation_id:G.obs.observation_id,request_id:G.obs.observation_id})});
    const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.error||'Parking decision failed');
    const dec=d.decision||{};G.registered=true;
    const box=$('g-decision');box.hidden=false;box.className='decision '+(dec.approved?'ok':'denied');
    $('g-decision-title').textContent=(dec.approved?'Allowed · ':'Denied · ')+(decisionMessages[dec.reason]||dec.reason||'');
    $('g-decision-detail').textContent=[dec.plate&&('Plate '+dec.plate),dec.space_id&&('Bay '+dec.space_id),dec.replayed&&'recovered earlier decision'].filter(Boolean).join(' · ');
    setGate(!!dec.approved&&!dec.replayed,dec.camera||G.dir,!!dec.replayed);
    gStatus(dec.approved?'Decision recorded. Capture the next vehicle when ready.':'Decision recorded · gate kept closed.',dec.approved?'success':'review');
    await loadParking();
  }catch(e){gStatus(e.message,'error');setGate(false);}
  finally{G.busy=false;gControls();}
});
function renderGateLot(){
  if(!pStatus)return;
  document.querySelector('[data-gate-offline]').hidden=!usingSample;
  gControls();
}
document.addEventListener('visibilitychange',()=>{if(gateActive())startCams();else stopCams();});


/* ===================== Photo viewer (popup instead of a new tab) ===================== */
let lbItems=[],lbIndex=0,lbReturn=null;
function showLb(i){
  lbIndex=i;const it=lbItems[i];
  $('lb-tabs').innerHTML=lbItems.length>1?lbItems.map((x,k)=>`<button type="button" class="${k===i?'on':''}" data-lb="${k}">${esc(x.label)}</button>`).join(''):'';
  $('lb-tabs').hidden=lbItems.length<2;
  const img=$('lb-img');
  if(it.src){img.src=it.src;img.alt=it.label+' photo';img.hidden=false;$('lb-empty').hidden=true;$('lb-full').href=it.src;$('lb-full').hidden=false;}
  else{img.hidden=true;img.removeAttribute('src');$('lb-empty').hidden=false;$('lb-full').hidden=true;}
  $('lb-meta').textContent=it.meta||'';
}
function openLb(title,sub,items,start){
  lbItems=items;lbReturn=document.activeElement;$('lb-title').textContent=title;$('lb-sub').textContent=sub||'';
  $('lightbox').hidden=false;document.body.classList.add('lb-open');showLb(start||0);$('lb-close').focus();
}
function closeLb(){$('lightbox').hidden=true;document.body.classList.remove('lb-open');$('lb-img').removeAttribute('src');if(lbReturn&&lbReturn.focus)lbReturn.focus();}
document.addEventListener('click',ev=>{
  const v=ev.target.closest('[data-visit]');
  if(v&&v.dataset.which){
    const x=visitRows().find(r=>String(sid(r))===v.dataset.visit);if(!x)return;
    const items=[{label:'Entry',src:photoUrl(x.entrance_photo_url),meta:'Entrance camera · '+fmtDateTime(x.entered_at)}];
    if(x.exited_at||x.exit_photo_url)items.push({label:'Exit',src:photoUrl(x.exit_photo_url),meta:'Exit camera · '+fmtDateTime(x.exited_at)});
    openLb(plateOf(x)||'Unknown plate',`${typeLabel[x.vehicle_type]||'Vehicle'} · ${x.space_id||'—'} · ${x.status==='still_in'?'Parked':'Left'}`,items,v.dataset.which==='exit'?1:0);return;
  }
  const e=ev.target.closest('[data-event]');
  if(e){const d=pHistory.events.find(r=>String(r.id)===e.dataset.event);if(!d)return;
    openLb(d.plate||'Plate not read',`${d.camera==='exit'?'Exit':'Entrance'} camera · ${reasonLabel[d.reason]||d.reason}`,[{label:d.camera==='exit'?'Exit':'Entry',src:photoUrl(d.photo_url),meta:fmtDateTime(d.created_at)}],0);}
});
$('lb-tabs').addEventListener('click',ev=>{const b=ev.target.closest('[data-lb]');if(b)showLb(+b.dataset.lb);});
$('lb-close').addEventListener('click',closeLb);
$('lightbox').addEventListener('click',ev=>{if(ev.target===$('lightbox'))closeLb();});
document.addEventListener('keydown',ev=>{if($('lightbox').hidden)return;if(ev.key==='Escape')closeLb();else if(ev.key==='ArrowRight'&&lbIndex<lbItems.length-1)showLb(lbIndex+1);else if(ev.key==='ArrowLeft'&&lbIndex>0)showLb(lbIndex-1);});

/* ===================== Router ===================== */
const titles={dashboard:'Live dashboard',gate:'Gate operation',admin:'Today','admin/vehicles':'History','admin/review':'Gate decisions','admin/slots':'Parking spaces','admin/devices':'Devices & services'};
function route(){
  let r=location.hash.replace(/^#\/?/,'');if(r==='admin/records'){location.replace('#/admin/vehicles');return;}if(!(r in titles))r='';
  document.body.classList.toggle('is-cover',r==='');
  document.querySelectorAll('.view').forEach(v=>{v.hidden=v.dataset.view!==(r||'cover');});
  document.querySelectorAll('#side-nav a[data-route]').forEach(a=>a.classList.toggle('active',a.dataset.route===r));
  $('crumb').textContent=titles[r]||'';document.title=(titles[r]?titles[r]+' · ':'')+'Intelligence Parking Lot';
  document.body.classList.remove('menu-open');$('menu-toggle').setAttribute('aria-expanded','false');
  if(r==='admin')renderTrend();
  if(r==='admin/vehicles'){renderHistChart();charts.forEach(c=>c.resize());}
  if(r==='gate')startCams();else stopCams();
  window.scrollTo(0,0);
}

/* ===================== Wiring ===================== */
$('range').addEventListener('change',history);$('history-source').addEventListener('change',()=>{const isCloud=$('history-source').value==='cloud';$('cloud-range').disabled=!isCloud;$('cloud-range').hidden=!isCloud;if(!isCloud&&$('range').value==='43200')$('range').value='10080';history();});$('history-refresh').addEventListener('click',history);
$('menu-toggle').addEventListener('click',()=>{const open=document.body.classList.toggle('menu-open');$('menu-toggle').setAttribute('aria-expanded',String(open));});
$('dec-seg').addEventListener('click',ev=>{const b=ev.target.closest('button');if(!b)return;decFilter=b.dataset.dec;$('dec-seg').querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));renderDecisions();});
for(const id of ['rec-q','rec-type'])$(id).addEventListener('input',()=>{recPage=0;renderRecords();});
$('hist-scope').addEventListener('click',ev=>{const b=ev.target.closest('button');if(!b)return;hScope=b.dataset.scope;$('hist-scope').querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));recPage=0;renderHistory();});
const shiftDay=n=>{const k=dayKey(dayStart(hDay)+n*86400000+43200000);if(k<=dayKey(Date.now())){hDay=k;recPage=0;renderHistory();}};
$('day-prev').addEventListener('click',()=>shiftDay(-1));$('day-next').addEventListener('click',()=>shiftDay(1));
$('day-today').addEventListener('click',()=>{hDay=dayKey(Date.now());recPage=0;renderHistory();});
$('day-input').addEventListener('change',()=>{const v=$('day-input').value;if(/^\d{4}-\d{2}-\d{2}$/.test(v)&&v<=dayKey(Date.now())){hDay=v;recPage=0;renderHistory();}else $('day-input').value=hDay;});
$('rec-seg').addEventListener('click',ev=>{const b=ev.target.closest('button');if(!b)return;recStatus=b.dataset.status;$('rec-seg').querySelectorAll('button').forEach(x=>x.classList.toggle('on',x===b));recPage=0;renderRecords();});
$('rec-prev').addEventListener('click',()=>{recPage--;renderRecords();});$('rec-next').addEventListener('click',()=>{recPage++;renderRecords();});
$('rec-export').addEventListener('click',()=>{const head=['visit_id','plate','vehicle_type','space_id','status','entered_at','exited_at'];const csv=[head.join(',')].concat(recFiltered().map(x=>[sid(x),plateOf(x),x.vehicle_type,x.space_id,x.status,x.entered_at,x.exited_at].map(v=>'"'+String(v??'').replace(/"/g,'""')+'"').join(','))).join('\n');const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['﻿'+csv],{type:'text/csv'}));a.download=usingSample?'parking-visits-SAMPLE.csv':'parking-visits.csv';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);});
window.addEventListener('hashchange',route);
route();live();history();loadParking();setInterval(live,2000);setInterval(loadParking,5000);setInterval(()=>{if($('history-source').value==='local'&&!historyBusy)history();},10000);
