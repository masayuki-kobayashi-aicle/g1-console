const $=id=>document.getElementById(id);
const FRESH_S=2.5, STALE_S=8, GIVEUP_S=15, POLL_MS=1000;
const ST_LABEL={ok:'Connected',down:'Not connected',unknown:'Unverified',stale:'Stale',checking:'Checking',stopped:'Stopped',paused:'Paused'};
let S=null, recvAt=0, fails=0, busy=false, pending=null, buttons=[], transitions={}, fallbackTo=[1], speedFsm=[], logs=[], featuresLoaded=false;
const RECONNECT_ON=`Even if the server stops, this page retries every ${POLL_MS/1000} s and updates automatically once it is back.`;
const RECONNECT_OFF='Paused: the server does not check the G1. The last values received are shown as they are.';
let lastKey='',lastDiag='';

const ageNow=()=>S&&S.age_s!=null?S.age_s+(performance.now()-recvAt)/1000:null;
const clock=t=>new Date(t*1000).toLocaleTimeString('en-GB',{hour12:false});
const ago=s=>s<60?`${s.toFixed(0)} s ago`:`${Math.floor(s/60)} min ${Math.floor(s%60)} s ago`;
const U=(st,detail)=>({st,detail});

/* Three-stage connection state. If upstream is down, downstream is "unverified" (never report something as connected when it cannot be seen). */
function nodes(){
  const server=U(fails>=2?'stopped':(S?'ok':'checking'),'');
  if(server.st==='stopped'){const d='Unverified because the server is stopped';return{server,jetson:U('unknown',d),g1:U('unknown',d)}}
  if(!S||S.sampled_at==null)return{server,jetson:U('checking','First check in progress'),g1:U('checking','First check in progress')};
  if(S.paused){const d='Auto-check paused (last check: '+(S.sampled_at?clock(S.sampled_at):'none')+')';return{server,jetson:U('paused',d),g1:U('paused',d)}}
  const age=ageNow();
  if(age>STALE_S){const d=`${age.toFixed(0)} s since the last successful check`;return{server,jetson:U('stale',d),g1:U('stale',d)}}
  return{server,jetson:U(S.jetson.state,S.jetson.detail),g1:U(S.g1.state,S.g1.detail)};
}

function diagnose(n){
  const code=t=>{const c=document.createElement('code');c.textContent=t;return c};
  const out=[];
  if(n.server.st==='stopped')out.push('The console server is not running (or is not responding). In a terminal on the operator PC, start ',code('python3 server.py'),'. This page reconnects automatically.');
  else if(n.jetson.st==='paused')out.push('Auto-check and reconnect are paused. Resume, or press "Check once now", to check.');
  else if(n.server.st==='checking')out.push('Contacting the server…');
  else if(n.jetson.st==='checking')out.push('The server is up. The first check on the G1 side is in progress (it takes a few seconds).');
  else if(n.jetson.st==='stale')out.push('The server is responding, but checks on the G1 side have stalled. The communication helper may be stuck (',n.jetson.detail,').');
  else if(n.jetson.st==='down')out.push('The communication helper for the G1 (on the Jetson) is not responding: '+n.jetson.detail+'. Check the network cable (eth0) and the DDS settings.');
  else if(n.g1.st==='down')out.push('The Jetson is reachable, but the G1 motion service is not responding. Check that the G1 is powered on and has finished booting. ('+n.g1.detail+')');
  else out.push('Normal: the server, Jetson and G1 are all reachable.');
  const key=out.map(x=>typeof x==='string'?x:x.textContent).join('');
  if(key===lastDiag)return;  /* Do not touch the DOM if the text is unchanged (prevents flicker). */
  lastDiag=key;
  $('diag').className=out[0].startsWith('Normal')?'ok':'';
  $('diag').replaceChildren(...out.map(x=>typeof x==='string'?document.createTextNode(x):x));
}

function renderChain(n){
  /* The console is assumed to run on the Jetson. If the helper (inside the Jetson) is unhealthy the G1 cannot be seen either, so show that state on the G1 node. */
  const view={server:n.server,g1:n.jetson.st==='ok'?n.g1:n.jetson};
  for(const k of ['server','g1']){
    const el=$(k+'-st'),cls='node-st s-'+view[k].st,txt=ST_LABEL[view[k].st];
    if(el.className!==cls)el.className=cls;
    if(el.textContent!==txt)el.textContent=txt;
    $('n-'+k).classList.toggle('is-bad',view[k].st==='down'||view[k].st==='stopped');
    if($('n-'+k).title!==(view[k].detail||''))$('n-'+k).title=view[k].detail||'';
  }
  $('server-sub').textContent=location.host;
  const paused=!!(S&&S.paused);
  $('mon-toggle').textContent=paused?'Resume':'Pause';
  $('mon-once').hidden=!paused;
  $('reconnect-note').textContent=paused?RECONNECT_OFF:RECONNECT_ON;
}

/* Header cards. Values carry a symbol: ● normal / ▲ caution / ○ unknown. The judgement comes from the server (S.control / S.mode).
   The arm uses the mode in the state-side lowstate, not the command-side lowcmd. */
function setStat(id,cls,text,detail){
  const el=$(id);el.className='ctl '+cls;el.textContent=text;
  const d=$(id+'-d');if(d)d.textContent=detail||'';
}
/* Remote controller reception: seconds since the last rt/wirelesscontroller message. Loss and resumption are logged (to help investigate why input stops being accepted). */
const RC_LIVE_S=3;let rcWas=null;
function renderRemote(T){
  const r=T&&T.remote,age=r&&r.age_s!=null?r.age_s+(performance.now()-recvAt)/1000:null;
  if(age==null){setStat('st-rc','c-mute',T?'No data':'—',T?'Check power and the connection to the G1':'');return}
  const live=age<=RC_LIVE_S;
  setStat('st-rc',live?'c-ok':'c-warn',live?'Receiving':'Lost '+Math.round(age)+' s',live?(r.keys?'Key input':'No input'):'Check power and the connection to the G1');
  if(rcWas!==null&&rcWas!==live)addLog(live?'Remote controller: reception resumed':'Remote controller: reception lost ('+Math.round(age)+' s since the last data)',live?'ok':'bad');
  rcWas=live;
}
function renderStats(m,c){
  const none=['c-mute','—',''];
  const svc=!m?none:m.state==='ok'?['c-ok','Running','Controlling balance and walking']
    :m.state==='debug'?['c-warn','Released (stopped)','Balance, walking and the remote controller are inactive']:['c-mute','Unknown',m.detail||''];
  const dbg=!m?none:m.state==='ok'?['c-ok','No','Normal mode']
    :m.state==='debug'?['c-warn','Yes','Low-level commands can be sent directly. Mode switching from this console is disabled']:['c-mute','Unknown',''];
  setStat('st-svc',...svc);setStat('st-dbg',...dbg);
  const fsm=$('st-fsm');fsm.textContent=m&&m.state==='ok'&&m.fsm_id!=null?String(m.fsm_id):'—';
  $('st-fsm-d').textContent=m&&m.state==='ok'?m.label:'';
  const L=c&&c.legs,A=c&&c.arm;
  const legs=!L?none:L.state==='autonomous'?['c-ok','Autonomous',m&&m.label||'']
    :L.state==='not_autonomous'?['c-warn','Not autonomous',m&&m.state==='debug'?'Debug mode':(m&&m.label||'')]:['c-mute','Unknown','Mode not available'];
  setStat('st-legs',...legs);
  const nm=A?`${A.enabled_count}/${A.total}`:'';
  const arm=!A?none:A.state==='enabled'?['c-ok','Enabled '+nm,A.commanded?'Receiving commands':'No commands']
    :A.state==='disabled'?['c-warn','Disabled '+nm,'Zero Torque']:A.state==='partial'?['c-warn','Partially enabled '+nm,'']
    :['c-mute','Unknown','Joint state not received'];
  setStat('st-arm',...arm);
}

function renderMode(n){
  const live=n.jetson.st==='ok'&&n.g1.st==='ok'&&S.mode;
  const m=live?S.mode:null;
  const mode=$('mode');
  if(m&&m.state==='ok'){mode.className='m-ok';mode.textContent=m.label;$('mode-sub').textContent=`ID ${m.fsm_id} · service=${m.service}`}
  else if(m&&m.state==='debug'){mode.className='m-debug';mode.textContent='Debug mode';$('mode-sub').textContent=''}
  else if(m&&m.state==='unknown'){mode.className='m-none';mode.textContent='Unknown state';$('mode-sub').textContent=m.detail||''}
  else{
    mode.className='m-none';
    mode.textContent=n.server.st==='checking'||n.jetson.st==='checking'?'Checking…':(n.jetson.st==='paused'?'Check paused':(n.jetson.st==='down'||n.g1.st==='down'?'Not connected':'Unknown'));
    const lm=S&&S.last_mode;
    $('mode-sub').textContent=lm?`Last confirmed mode: ${lm.label}${lm.fsm_id!=null?` (ID ${lm.fsm_id})`:''} · ${clock(lm.at)} (${ago(Math.max(0,Date.now()/1000-lm.at))})`:'';
  }
  renderStats(m,live?S.control:null);
  renderRemote(live?S.telemetry:null);
  const age=ageNow(),f=$('st-last'),fd=$('st-last-d');
  $('st-lat').textContent=live&&S.latency_ms!=null?`${S.latency_ms} ms`:'—';
  if(n.jetson.st==='paused'){f.className='sv';f.textContent=S.sampled_at?clock(S.sampled_at):'—';fd.textContent=S.sampled_at?'Not updating because auto-check is paused':'Not fetched yet'}
  else if(age==null){f.className='sv';f.textContent='—';fd.textContent='Not available yet'}
  else{
    f.className='sv '+(age<=FRESH_S?'f-fresh':(age<=STALE_S?'f-slow':'f-stale'));
    f.textContent=clock(S.sampled_at);
    fd.textContent=`${age.toFixed(1)} s ago`+(n.server.st==='stopped'?' · Server stopped (last received value)':'');
  }
}

function switchBlockReason(n){
  if(n.server.st==='stopped')return 'Console server stopped';
  if(n.server.st==='checking'||n.jetson.st==='checking')return 'Checking';
  if(n.jetson.st==='paused')return 'Auto-check paused';
  if(n.jetson.st==='stale')return 'Status is not updating';
  if(n.jetson.st==='down')return 'Jetson not connected';
  if(n.g1.st==='down')return 'G1 not connected';
  if(S.mode.state==='debug')return 'Cannot switch in debug mode';
  if(S.mode.state!=='ok')return 'Current mode unavailable';
  return '';
}

function renderButtons(n){
  const why=switchBlockReason(n);
  $('why').textContent=why?'Switching disabled: '+why:'';
  const cur=!why?S.mode.fsm_id:null;
  /* Only modes reachable from the current mode can be pressed (official transition diagram). If the current value is not in the table, only Damping is allowed. */
  const ok=cur==null?[]:(transitions[cur]||fallbackTo);
  document.querySelectorAll('#btns button').forEach(b=>{
    const id=Number(b.dataset.id),isCur=id===cur,reach=ok.includes(id);
    b.classList.toggle('current',isCur);
    b.disabled=!!why||busy||!reach;
    b.title=why||isCur?'':reach?'':'Cannot switch directly from the current mode (go through Damping)';
  });
  const walking=cur!=null&&speedFsm.includes(cur);
  document.querySelectorAll('#speed-btns button').forEach(b=>{
    b.disabled=!walking||busy;
    b.title=walking?'':'Can be sent only in Regular Mode (walking)';
  });
}

/* "Sent" and "reached the target mode" are different things. Show the wait until it arrives (buttons stay pressable meanwhile, so an emergency Damping is never blocked). */
function renderPending(){
  const el=$('pending');
  if(!pending){el.hidden=true;return}
  const elapsed=(performance.now()-pending.at)/1000;
  const cur=S&&S.mode&&S.mode.state==='ok'?S.mode.fsm_id:null;
  if(cur===pending.id){addLog(`Reached "${pending.label}" (${elapsed.toFixed(1)} s)`,'ok');pending=null;el.hidden=true;return}
  if(elapsed>GIVEUP_S){addLog(`Did not reach "${pending.label}" within ${GIVEUP_S} s (current: ${S&&S.mode?S.mode.label:'unknown'})`,'bad');pending=null;el.hidden=true;return}
  el.hidden=false;
  el.textContent=`Moving to "${pending.label}"… current: ${S&&S.mode?S.mode.label:'unknown'} · ${elapsed.toFixed(0)} s elapsed`;
}

function addLog(text,cls){
  logs=[{t:new Date().toLocaleTimeString('en-GB',{hour12:false}),text,cls},...logs].slice(0,30);
  $('log').replaceChildren(...logs.map(l=>{
    const li=document.createElement('li'),t=document.createElement('span'),s=document.createElement('span');
    t.className='t';t.textContent=l.t;s.className=l.cls||'';s.textContent=l.text;li.append(t,s);return li;
  }));
}

const JOINT_NAMES=['left hip pitch','left hip roll','left hip yaw','left knee','left ankle pitch','left ankle roll',
 'right hip pitch','right hip roll','right hip yaw','right knee','right ankle pitch','right ankle roll',
 'waist yaw','waist roll','waist pitch',
 'left shoulder pitch','left shoulder roll','left shoulder yaw','left elbow','left wrist roll','left wrist pitch','left wrist yaw',
 'right shoulder pitch','right shoulder roll','right shoulder yaw','right elbow','right wrist roll','right wrist pitch','right wrist yaw'];
const RAD=180/Math.PI;
const f=(v,d=2)=>v==null||!isFinite(v)?'—':Number(v).toFixed(d);

function setKV(id,rows,live){
  const el=$(id);el.className='kv'+(live?'':' stale');el.textContent='';
  rows.forEach(([k,v])=>{const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=k;dd.textContent=live?v:'—';el.append(dt,dd)});
}

const JSON_S=v=>typeof v==='string'?v:JSON.stringify(v);
function renderSystem(T,live){
  const sy=live&&T.system,mb=live&&T.mainboard;
  const temps=sy&&sy.temps?Object.entries(sy.temps):[];
  const hot=temps.reduce((a,b)=>b[1]>a[1]?b:a,['',-1]);
  setKV('sys-kv',[
    ['Jetson load (1/5/15 min)',sy&&sy.load?`${sy.load.join(' / ')} (${sy.cpus} cores)`:'—'],
    ['Free memory',sy&&sy.mem_total_mb?`${sy.mem_avail_mb} / ${sy.mem_total_mb} MB`:'—'],
    ['Jetson max temperature',temps.length?`${f(hot[1],1)}°C (${hot[0]})`:'—'],
    ['Free disk',sy&&sy.disk_free_gb!=null?`${sy.disk_free_gb} GB`:'—'],
    ['Jetson uptime',sy&&sy.uptime_s!=null?`${(sy.uptime_s/60).toFixed(0)} min`:'—'],
    ['Main board temperature',mb?mb.temperature.filter(t=>t>0).map(t=>`${t}°C`).join(' / ')||'—':'—'],
    ['Main board value (raw)',mb?mb.value.slice(0,3).map(v=>f(v,1)).join(' / '):'—'],
    ['Main board state (raw)',mb?JSON.stringify(mb.state.slice(0,3)):'—']],!!(sy||mb));
}
function renderMisc(T,live){
  const rows=[];
  const r=live&&T.remote,e=live&&T.estop;
  rows.push(['Wireless remote controller input',r?`lx ${f(r.lx)} ly ${f(r.ly)} rx ${f(r.rx)} ry ${f(r.ry)} keys ${r.keys}`:'No data']);
  rows.push(['Emergency stop event',e?JSON_S(Object.fromEntries(Object.entries(e).filter(([k])=>k!=='age_s'))):'No data']);
  const st=live&&T.strings?T.strings:{};
  ['rt/servicestate','rt/servicestateactivate','rt/multiplestate','rt/selftest','rt/lf/battery_alarm','rt/rtc/state','rt/arm/action/state','rt/public_network_status','rt/gpt_state'].forEach(k=>{
    rows.push([k.replace('rt/',''),st[k]?JSON_S(st[k].value):'No data']);
  });
  setKV('misc-kv',rows,live);
  const tb=document.querySelector('#rates tbody');tb.textContent='';
  Object.entries(live&&T.ages?T.ages:{}).sort((a,b)=>(a[1]==null)-(b[1]==null)||(a[1]||0)-(b[1]||0)).forEach(([k,v])=>{
    const tr=document.createElement('tr');[k,v==null?'—':f(v,1)].forEach(x=>{const td=document.createElement('td');td.textContent=x;tr.append(td)});tb.append(tr);
  });
}

function renderTelemetry(n){
  const T=S&&S.telemetry,age=ageNow();
  const live=!!T&&n.jetson.st==='ok'&&n.g1.st==='ok'&&age!=null&&age<=STALE_S;
  const b=live&&T.battery,i=live&&T.imu,o=live&&T.odom,j=live&&T.joints;
  const soc=$('bat-soc'),bar=$('bat-bar');
  if(b){
    soc.textContent=`${b.soc}%`;soc.style.color='';
    bar.className=b.soc<=10?'crit':(b.soc<=20?'low':'');bar.firstElementChild.style.width=`${Math.max(0,Math.min(100,b.soc))}%`;
  }else{soc.textContent='—';soc.style.color='';bar.className='';bar.firstElementChild.style.width='0'}
  const volts=b?b.voltage.filter(v=>v>0):[],temps=b?b.temperature.filter(t=>t>0):[];
  setKV('bat-kv',[
    ['Voltage (est.)',volts.map(v=>`${f(v/1000,2)} V`).join(' / ')||'—'],
    ['Current (est.)',b?`${f(b.current/1000,2)} A (${b.current<0?'discharging':'charging'})`:'—'],
    ['Temperature',temps.length?temps.map(t=>`${t}°C`).join(' / '):'—'],
    ['Updated',b?`received ${f(b.age_s,1)} s ago`:'—']],!!b);
  const d=i?i.rpy.map(v=>v*RAD):[];
  setKV('imu-kv',[
    ['Roll / pitch / yaw',i?`${f(d[0],1)}° / ${f(d[1],1)}° / ${f(d[2],1)}°`:'—'],
    ['Angular velocity [rad/s]',i?i.gyro.map(v=>f(v)).join(' / '):'—'],
    ['Acceleration [m/s²]',i?i.accel.map(v=>f(v)).join(' / '):'—'],
    ['IMU temperature',i?`${i.temperature}°C`:'—'],
    ['Second IMU (roll / pitch / yaw)',i&&T.imu2?T.imu2.rpy.map(v=>f(v*RAD,1)+'°').join(' / '):'—']],!!i);
  setKV('odom-kv',[
    ['Position x / y / z [m]',o?o.position.map(v=>f(v)).join(' / '):'—'],
    ['Velocity x / y / z [m/s]',o?o.velocity.map(v=>f(v)).join(' / '):'—'],
    ['Yaw rate [rad/s]',o?f(o.yaw_speed):'—'],
    ['Body height [m]',o?f(o.body_height):'—'],
    ['mode / gait / error',o?`${o.mode} / ${o.gait_type} / ${o.error_code}`:'—']],!!o);
  renderSystem(T,live);renderMisc(T,live);
  const tb=document.querySelector('#joints tbody');tb.textContent='';
  if(j){
    let hot=0,hotI=0;
    j.items.forEach((m,k)=>{
      const t=Math.max(...m.temperature);if(t>hot){hot=t;hotI=k}
      const tr=document.createElement('tr');
      const c=T.lowcmd&&T.lowcmd.items[k];
      [JOINT_NAMES[k]||`#${k}`,f(m.q*RAD,1),f(m.dq),f(m.tau),String(t),c?f(c.q*RAD,1):'—',c?f(c.kp,0):'—',c?f(c.kd,1):'—',m.mode==null?'—':String(m.mode),c&&c.mode!=null?String(c.mode):'—'].forEach(x=>{const td=document.createElement('td');td.textContent=x;tr.append(td)});
      tb.append(tr);
    });
    const lost=j.items.filter(m=>m.lost!==0).length;
    $('joint-sum').textContent=`Max temperature ${hot}°C (${JOINT_NAMES[hotI]||'#'+hotI}) · ${lost} joint(s) with non-zero motorstate · mode_machine ${j.mode_machine} · commands ${T.lowcmd?'present':'none received'}`;
  }else $('joint-sum').textContent=T&&live?'Joint values not received':'— (not connected or stale data)';
}

// ---- Voice and LED ----
let originalVolume=null,audioReady=false,volumeTried=false;
function setRes(id,text,cls){const e=$(id);e.textContent=text;e.className='res '+(cls||'')}
async function audioPost(kind,body){
  const r=await fetch('/api/audio/'+kind,{method:'POST',body:JSON.stringify(body)});
  let j={};try{j=await r.json()}catch(_){}
  return{ok:r.ok,j,status:r.status};
}
function stopCameras(){document.querySelectorAll('#cams img').forEach(i=>i.removeAttribute('src'))}  // Close the stream connections when leaving the tab
async function loadCameras(){
  try{
    const epoch=uiRouteEpoch;
    const r=await (await fetch('/api/cameras')).json();
    if(epoch!==uiRouteEpoch||tab!=='camera'||window.uiSensor&&window.uiSensor!=='camera')return;
    if(!r.enabled){$('cam-note').textContent='No camera is configured. Start server.py with --camera-url.';return}
    $('cams').replaceChildren(...Object.entries(r.cameras).map(([id,label])=>{
      const box=document.createElement('div'),cap=document.createElement('b'),img=document.createElement('img');
      cap.textContent=label;img.src='/camera/'+id;img.alt=label+' (no video)';img.style.cssText='width:100%;display:block;background:#000';
      img.onerror=()=>{box.hidden=true;  // Hide the whole frame of a camera that is not connected
        if([...$('cams').children].every(b=>b.hidden))$('cam-note').textContent='No video. Check that you pressed "Start" above and that the camera is connected.'};
      box.append(cap,img);return box}));
    $('cam-note').textContent='Relaying video from camera_stream.py on the Jetson. If nothing appears, check that it is running on the Jetson and that the camera is plugged into USB.';
  }catch(e){$('cam-note').textContent='Cannot get camera info: '+e}
}
function renderCamProc(j){
  const own=j.holders.filter(h=>h.own).length,foreign=j.foreign.length;
  $('cp-state').textContent=(j.running?'camera_stream running (pid='+j.pid+')':'camera_stream stopped')+
    (foreign?' / '+foreign+' other process(es) holding devices':' / no other process holding devices');
  for(const p of ['cp','cv']){$(p+'-start').disabled=j.running;$(p+'-stop').disabled=!j.running}
  $('cv-state').textContent=j.running?'Streaming':'Stopped';
  const rows=j.holders.map(h=>{const tr=document.createElement('tr');
    [h.device,h.pid,h.user,h.cmd+(h.own?' (own)':'')].forEach(v=>{const td=document.createElement('td');td.textContent=v;tr.append(td)});return tr});
  if(!rows.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=4;td.textContent='No process is holding a video device';tr.append(td);rows.push(tr)}
  $('cp-table').tBodies[0].replaceChildren(...rows);
}
async function camProc(action){
  const get=action==='status';
  if(!get&&!await guard('camera',{quiet:true,title:(action==='start'?'Start':'Stop')+' the camera stream',lines:['This '+(action==='start'?'starts':'stops')+' the camera stream process on the Jetson','Check the result in the status display and the video']}))return;setRes('cp-res',get?'Checking…':(action==='start'?'Starting…':'Stopping…'));
  ['cp-refresh','cp-start','cp-stop','cv-start','cv-stop'].forEach(i=>$(i).disabled=true);
  try{
    const r=await fetch('/api/camera/'+(get?'status':action),{method:get?'GET':'POST'});
    const j=await r.json();
    if(!r.ok){setRes('cp-res',j.error||('Failed '+r.status),'bad');$('cp-refresh').disabled=false;return}
    renderCamProc(j);setRes('cp-res',j.message||'');
    if(!get&&tab==='camera'&&(!window.uiSensor||window.uiSensor==='camera'))loadCameras();  // Reconnect the video after start/stop
  }catch(e){setRes('cp-res','Cannot fetch: '+e,'bad')}
  $('cp-refresh').disabled=false;
}
$('cv-start').onclick=()=>camProc('start');$('cv-stop').onclick=()=>camProc('stop');
$('cp-refresh').onclick=()=>camProc('status');$('cp-start').onclick=()=>camProc('start');$('cp-stop').onclick=()=>camProc('stop');
/* ---- lidar (point cloud): start/stop and 2D projection. Stop fetching when the tab is left ---- */
const LD_POLL_MS=120, LD_RETRY_MS=1500, LD_VIEW0={yaw:0.6,pitch:1.1,scale:70}, LD_RINGS_M=[1,2,3,5,8,12];
let ld={...LD_VIEW0,frames:[],seq:null,timer:null,running:false,times:[]};
const LD_COLORS=16;  // Split height colors into 16 steps and paint each step in one pass (stays light even with tens of thousands of stacked points)
function ldDraw(){
  const c=$('ld-canvas'),g=c.getContext('2d'),w=c.width,h=c.height,cx=w/2,cy=h/2;
  g.clearRect(0,0,w,h);
  const cy_=Math.cos(ld.yaw),sy_=Math.sin(ld.yaw),cp=Math.cos(ld.pitch),sp=Math.sin(ld.pitch);
  const proj=(x,y,z)=>{const x1=x*cy_-y*sy_,y1=x*sy_+y*cy_;return[cx+x1*ld.scale,cy-(y1*sp+z*cp)*ld.scale]};
  g.strokeStyle='rgba(180,190,200,.25)';g.fillStyle='rgba(200,210,220,.7)';g.lineWidth=1;g.font='22px sans-serif';
  for(const r of LD_RINGS_M){g.beginPath();for(let i=0;i<=64;i++){const a=i/64*2*Math.PI,[px,py]=proj(r*Math.cos(a),r*Math.sin(a),0);i?g.lineTo(px,py):g.moveTo(px,py)}g.stroke();
    const[lx,ly]=proj(r,0,0);g.fillText(r+' m',lx+4,ly-4)}
  for(const [vx,vy,col,name] of [[1,0,'#ef5350','x'],[0,1,'#66bb6a','y']]){const[a0,b0]=proj(0,0,0),[a1,b1]=proj(vx,vy,0);g.strokeStyle=col;g.fillStyle=col;g.lineWidth=2;g.beginPath();g.moveTo(a0,b0);g.lineTo(a1,b1);g.stroke();g.fillText(name,a1+4,b1)}
  const zs=[];for(const p of ld.frames)for(let i=2;i<p.length;i+=4)zs.push(p[i]);
  if(!zs.length)return;
  zs.sort((a,b)=>a-b);
  const lo=zs[Math.floor(zs.length*.05)],hi=zs[Math.floor(zs.length*.95)],span=Math.max(hi-lo,.1);
  for(let k=0;k<LD_COLORS;k++){
    g.fillStyle='hsl('+Math.round(240-k/(LD_COLORS-1)*240)+',85%,60%)';g.beginPath();
    for(const p of ld.frames)for(let i=0;i<p.length;i+=4){
      if(Math.min(LD_COLORS-1,Math.max(0,Math.floor((p[i+2]-lo)/span*LD_COLORS)))!==k)continue;
      const[px,py]=proj(p[i],p[i+1],p[i+2]);g.rect(px-1,py-1,2.5,2.5)}
    g.fill();
  }
}
function ldStats(points,ageMs){
  const now=performance.now();ld.times=ld.times.filter(t=>now-t<3000);ld.times.push(now);
  const hz=ld.times.length>1?(ld.times.length-1)/((now-ld.times[0])/1000):0;
  const total=ld.frames.reduce((n,f)=>n+f.length/4,0);
  $('ld-stats').textContent=points+' pts × '+ld.frames.length+' frames = '+total+' pts / '+hz.toFixed(1)+' fps / delay '+ageMs+' ms';
}
function ldQuery(){const[v,m]=$('ld-density').value.split(',');return '?voxel='+v+'&max='+m}
async function ldTick(){
  if(!ld.running)return;
  let wait=LD_POLL_MS;
  try{
    const r=await fetch('/lidar'+ldQuery(),{cache:'no-store'});
    if(!r.ok){let m='';try{m=(await r.json()).error}catch(_){}throw new Error(m||('HTTP '+r.status))}
    const buf=await r.arrayBuffer(),seq=r.headers.get('X-Lidar-Seq');
    if(!ld.running||tab!=='camera'||window.uiSensor!=='lidar')return;
    if(buf.byteLength%16)throw new Error('Invalid point cloud format');
    if(seq!==ld.seq){  // Do not stack the same frame twice
      ld.seq=seq;const keep=Number($('ld-stack').value);
      ld.frames=[...ld.frames,new Float32Array(buf)].slice(-keep);
      ldStats(buf.byteLength/16,r.headers.get('X-Lidar-Age-Ms')||'?');ldDraw();
    }
    setRes('ld-res','');
  }catch(e){$('ld-stats').textContent='Cannot fetch the point cloud';setRes('ld-res',String(e.message||e),'bad');wait=LD_RETRY_MS}
  if(ld.running)ld.timer=setTimeout(ldTick,wait);
}
function ldView(on){
  ld.running=on;clearTimeout(ld.timer);
  if(on)ldTick();else{ld.frames=[];ld.seq=null;ld.times=[];$('ld-stats').textContent='Stopped';ldDraw()}
}
$('ld-stack').onchange=()=>{ld.frames=ld.frames.slice(-Number($('ld-stack').value));ldDraw()};
$('ld-density').onchange=()=>{ld.frames=[];ld.seq=null;ldDraw()};  // Do not mix point clouds of different density
function renderLidarProc(j){
  $('ld-state').textContent=j.running?'lidar_stream running (pid='+j.pid+')':'lidar_stream stopped';
  $('ld-start').disabled=j.running;$('ld-stop').disabled=!j.running;
  const viewing=tab==='camera'&&window.uiSensor==='lidar';
  if(viewing&&j.running!==ld.running)ldView(j.running);
}
async function ldProc(action){
  const get=action==='status';
  if(!get&&!await guard('lidar',{quiet:true,title:(action==='start'?'Start':'Stop')+' the lidar stream',lines:['This '+(action==='start'?'starts':'stops')+' the lidar stream process on the Jetson','Check the result in the status display and the point cloud']}))return;setRes('ld-res',get?'Checking…':(action==='start'?'Starting…':'Stopping…'));
  ['ld-refresh','ld-start','ld-stop'].forEach(i=>$(i).disabled=true);
  try{
    const r=await fetch('/api/lidar/'+action,{method:get?'GET':'POST'}),j=await r.json();
    if(!r.ok){setRes('ld-res',j.error||('Failed '+r.status),'bad');ldView(false);$('ld-state').textContent='Cannot check the status';$('ld-start').disabled=false}
    else{renderLidarProc(j);setRes('ld-res',j.message||'')}
  }catch(e){setRes('ld-res','Cannot fetch: '+e,'bad')}
  $('ld-refresh').disabled=false;
}
const LS_POLL_MS=5000, LS_BADGE={1:['SAMPLING (measuring)','done'],2:['IDLE (standby, laser stopped)','unver'],9:['READY (preparing)','plan']};
let lsBusy=false;
function lsBadge(text,cls){const b=$('ls-badge');b.textContent=text;b.className='tag '+cls}
function renderLidarSensor(j){
  $('ld-sensor-row').hidden=false;
  const[text,cls]=LS_BADGE[j.mode]||['Unknown (mode='+j.mode+')','plan'];
  lsBadge(text,cls);$('ls-time').textContent='Checked '+new Date().toLocaleTimeString('en-GB',{hour12:false});
  $('ls-idle').disabled=j.mode===2;$('ls-sampling').disabled=j.mode===1;
}
function lsUnknown(){lsBadge('Cannot check the status','plan');$('ls-idle').disabled=$('ls-sampling').disabled=false}
setInterval(()=>{if(!lsBusy&&!document.hidden&&tab==='camera')lsSensor('status',true)},LS_POLL_MS);  // Re-read every 5 s only while the tab is visible
async function lsSensor(action,quiet){
  const get=action==='status',idle=action==='idle';
  if(lsBusy)return;
  if(!get&&!await guard('lidar_sensor',{quiet:true,title:(idle?'Stop (standby) the LiDAR unit':'Start (measure) the LiDAR unit'),lines:idle
    ?['The LiDAR laser stops and point clouds no longer arrive','Processes that use the point cloud (such as mapping) stop working','Power-cycling the unit returns it to measuring']
    :['The LiDAR resumes measuring and point clouds arrive']}))return;
  if(lsBusy)return;  // A periodic re-read ran while the confirmation dialog was open
  lsBusy=true;
  if(!quiet){setRes('ls-res',get?'Checking…':'Switching…');['ls-idle','ls-sampling'].forEach(i=>$(i).disabled=true)}
  try{
    const r=await fetch(get?'/api/lidar/sensor':'/api/lidar/sensor/'+action,{method:get?'GET':'POST',cache:'no-store'});
    if(r.status===404){$('ld-sensor-row').hidden=true;setRes('ls-res','');return}  // Hidden unless --local
    const j=await r.json();
    if(!r.ok){setRes('ls-res',j.error||('Failed '+r.status),'bad');lsUnknown()}
    else{renderLidarSensor(j);setRes('ls-res','')}
  }catch(e){setRes('ls-res','Cannot fetch: '+e,'bad');lsUnknown()}
  finally{lsBusy=false}
}
$('ls-idle').onclick=()=>lsSensor('idle');$('ls-sampling').onclick=()=>lsSensor('sampling');
$('ld-refresh').onclick=()=>{ldProc('status');lsSensor('status')};$('ld-start').onclick=()=>ldProc('start');$('ld-stop').onclick=()=>ldProc('stop');
$('ld-reset').onclick=()=>{Object.assign(ld,LD_VIEW0);ldDraw()};
{const c=$('ld-canvas');let drag=null;
 c.onpointerdown=e=>{drag=[e.clientX,e.clientY];c.setPointerCapture(e.pointerId);c.style.cursor='grabbing'};
 c.onpointerup=()=>{drag=null;c.style.cursor='grab'};
 c.onpointermove=e=>{if(!drag)return;ld.yaw+=(e.clientX-drag[0])*.01;ld.pitch=Math.min(Math.PI/2,Math.max(0,ld.pitch+(e.clientY-drag[1])*.01));drag=[e.clientX,e.clientY];ldDraw()};
 c.addEventListener('wheel',e=>{e.preventDefault();ld.scale=Math.min(400,Math.max(10,ld.scale*(e.deltaY<0?1.1:1/1.1)));ldDraw()},{passive:false});
 ldDraw()}
async function loadVolume(){
  setRes('vol-res','Loading…');
  try{
    const r=await fetch('/api/audio/volume',{cache:'no-store'}),j=await r.json();
    if(!r.ok||j.volume==null){setRes('vol-res',`Fetch failed: ${j.error||'code='+j.code}`,'bad');return}
    if(originalVolume==null){originalVolume=j.volume;$('vol-restore').disabled=false;$('vol-restore').textContent=`Restore previous (${originalVolume})`}
    $('vol-now').textContent=`Current ${j.volume}`;$('vol').value=j.volume;$('vol-out').value=j.volume;
    setRes('vol-res',`Fetched (${clock(Date.now()/1000)})`,'ok');
  }catch(e){setRes('vol-res',`Cannot reach the server (${e})`,'bad')}
}
async function setVolume(v){
  if(originalVolume==null){setRes('vol-res','First click "Load" to get the value before the change','warn');return}
  setRes('vol-res','Sending…');
  try{
    const {ok,j}=await audioPost('volume',{volume:v});
    if(!ok){setRes('vol-res',`Failed: ${j.error||`set_code=${j.set_code} read_code=${j.read_code}`}`,'bad');addLog(`Volume ${v} failed`,'bad');return}
    const match=j.volume_after===v;
    $('vol-now').textContent=`Current ${j.volume_after}`;
    setRes('vol-res',match?`Accepted → read back ${j.volume_after}, matches (confirmed)`:`Accepted, but the read-back is ${j.volume_after} (does not match the set value ${v})`,match?'ok':'bad');
    addLog(`Volume set to ${v} (read-back ${j.volume_after}${match?', match':', mismatch'})`,match?'':'bad');
  }catch(e){setRes('vol-res',`Cannot reach the server (${e})`,'bad')}
}
async function setLed(r,g,b){
  if(!await guard('audio',{title:'Change the head LED color',ok:'Send',lines:[`Sends color (${r}, ${g}, ${b}). It cannot be read back, so check by eye that the color changed`]}))return;
  setRes('led-res','Sending…');
  try{
    const {ok,j}=await audioPost('led',{r,g,b});
    setRes('led-res',ok?`Sent (accepted, code=${j.code}). Check by eye that the color changed`:`Failed: ${j.error||'code='+j.code}`,ok?'warn':'bad');
    addLog(`LED (${r},${g},${b}) ${ok?'sent (accepted, awaiting visual check)':'failed'}`,ok?'':'bad');
  }catch(e){setRes('led-res',`Cannot reach the server (${e})`,'bad')}
}
async function speak(){
  const text=$('tts').value.trim();if(!text){setRes('tts-res','Enter text','warn');return}
  if(!await guard('audio',{title:'Speak',ok:'Speak',always:true,lines:[`Speaks "${text}" through the real robot's speaker`,'Is the area around the robot clear?']}))return;
  setRes('tts-res','Sending…');
  try{
    const {ok,j}=await audioPost('tts',{text,speaker_id:+$('tts-spk').value});
    setRes('tts-res',ok?`Sent (accepted, code=${j.code}). Check by ear that sound played`:`Failed: ${j.error||'code='+j.code}`,ok?'warn':'bad');
    addLog(`Speak "${text}" ${ok?'sent (accepted, awaiting listening check)':'failed'}`,ok?'':'bad');
  }catch(e){setRes('tts-res',`Cannot reach the server (${e})`,'bad')}
}
function hexRgb(h){return[1,3,5].map(i=>parseInt(h.slice(i,i+2),16))}
function initAudio(){
  $('vol').oninput=()=>{$('vol-out').value=$('vol').value};
  $('vol-load').onclick=loadVolume;
  $('vol-set').onclick=()=>setVolume(+$('vol').value);
  $('vol-restore').onclick=()=>setVolume(originalVolume);
  $('led-set').onclick=()=>setLed(...hexRgb($('led').value));
  $('led-off').onclick=()=>setLed(0,0,0);
  $('tts-go').onclick=speak;
}
function renderAudio(n){
  const live=n.jetson.st==='ok'&&n.g1.st==='ok'&&!busy;
  document.querySelectorAll('#tab-audio .arow button,#tab-audio .arow input,#tab-audio .arow select').forEach(e=>{if(e.id==='vol-restore'&&originalVolume==null)return;e.disabled=!live});
}

function render(){
  const n=nodes();
  renderChain(n);diagnose(n);
  renderMode(n);
  renderButtons(n);
  renderPending();
  /* Redraw heavy tables only when the fetched value, state or tab changes (rebuilding every 250 ms caused flicker) */
  const key=[recvAt,tab,busy,n.server.st,n.jetson.st,n.g1.st].join('|');
  if(key!==lastKey){lastKey=key;renderTelemetry(n);renderAudio(n)}
  if(window.renderMobile)window.renderMobile(n);
  if(S)$('cadence').textContent=`The server checks the G1 about every ${S.poll_interval_s} s, and this screen asks the server every ${POLL_MS/1000} s. The display can lag by a few seconds.`;
}

async function setMode(b){
  const epoch=uiRouteEpoch;
  const cur=S&&S.mode&&S.mode.state==='ok'?S.mode.fsm_id:null;
  const warn=b.danger&&(cur===500||cur===501)?'\n\nDoing this while walking may make the robot fall.':'';
  if(!await guard('mode',{title:`Switch to "${b.label}"`,ok:'Switch',always:true,quiet:true,danger:b.danger,
    lines:['Check that the surroundings are safe',...(warn?['Doing this while walking may make the robot fall']:[]),'Keep the physical remote controller at hand']}))return;
  if(epoch!==uiRouteEpoch||tab!=='ops')return;
  busy=true;render();
  try{
    const r=await fetch('/api/mode',{method:'POST',body:JSON.stringify({id:b.id})});
    const j=await r.json();
    const resp=JSON.stringify(j);  /* Keep the G1's response as is in the log (to tell accepted from refused) */
    if(r.ok){pending={id:b.id,label:b.label,at:performance.now()};addLog(`Sent "${b.label}" (current: ${cur==null?'unknown':cur}) · response ${resp} · waiting to arrive`,'')}
    else addLog(`"${b.label}" failed (HTTP ${r.status}): ${j.error||'no reason given'} · response ${resp}`,'bad');
  }catch(e){addLog(`"${b.label}" failed: cannot reach the server (${e})`,'bad')}
  busy=false;render();
}

async function setSpeed(b){
  const epoch=uiRouteEpoch;
  if(!await guard('speed',{title:`Switch to "${b.label}"`,ok:'Switch',always:true,
    lines:['Check that the surroundings are safe','The walking speed changes. What low and high speed mean is unverified','Keep the physical remote controller at hand']}))return;
  if(epoch!==uiRouteEpoch||tab!=='ops')return;
  busy=true;render();
  try{
    const r=await fetch('/api/speed',{method:'POST',body:JSON.stringify({value:b.value})});
    const j=await r.json(),resp=JSON.stringify(j);
    if(r.ok)addLog(`Sent "${b.label}" · response ${resp}`,'');
    else addLog(`"${b.label}" failed (HTTP ${r.status}): ${j.error||'no reason given'} · response ${resp}`,'bad');
  }catch(e){addLog(`"${b.label}" failed: cannot reach the server (${e})`,'bad')}
  busy=false;render();
}

async function loadButtons(){
  const j=await (await fetch('/api/buttons',{cache:'no-store'})).json();
  const list=j.buttons;buttons=list;transitions=j.transitions||{};fallbackTo=j.fallback||[1];speedFsm=j.speed_fsm_ids||[];
  $('speed-btns').replaceChildren(...(j.speed||[]).map(b=>{
    const el=document.createElement('button');el.textContent=b.label;el.disabled=true;el.onclick=()=>setSpeed(b);return el;
  }));
  $('btns').replaceChildren(...list.map(b=>{
    const el=document.createElement('button');
    el.textContent=b.label;el.dataset.id=b.id;el.disabled=true;
    if(b.danger)el.classList.add('danger');
    el.onclick=()=>setMode(b);return el;
  }));
}

async function loadScenarios(){
  const r=await fetch('/api/scenarios',{cache:'no-store'});
  if(!r.ok)return;
  const {scenarios,current}=await r.json();
  const sel=$('scenario');
  sel.replaceChildren(...Object.entries(scenarios).map(([k,v])=>{const o=document.createElement('option');o.value=k;o.textContent=v;return o}));
  sel.value=current;
  sel.onchange=async()=>{await fetch('/api/scenario',{method:'POST',body:JSON.stringify({scenario:sel.value})});await poll(true)};
  $('mockbar').hidden=false;
}

/* Caution dialog for unverified operations. For operations not tested on a real robot, a caution is shown on press and confirmation is requested.
   Text is drawn with textContent only (strings from the server, such as task cautions, are never interpreted as HTML). */
let featureList=[];
async function featureInfo(id){
  if(!featureList.length){try{featureList=(await (await fetch('/api/features',{cache:'no-store'})).json()).features}catch(e){}}
  return featureList.find(f=>f.id===id)||null;
}
function askCaution(o){
  return new Promise(resolve=>{
    const d=$('caution'),lines=o.lines||[];
    if(d.open){resolve(false);return}
    if(typeof d.showModal!=='function'){resolve(confirm([o.title,o.unverified?'(unverified on a real robot)':'',...lines].filter(Boolean).join('\n')));return}
    $('ca-title').textContent=o.title;
    $('ca-unver').hidden=!o.unverified;$('ca-note').textContent=o.note||'';$('ca-note').hidden=!o.note;
    $('ca-lines').replaceChildren(...lines.map(t=>{const li=document.createElement('li');li.textContent=t;return li}));
    $('ca-check').hidden=!o.needCheck;$('ca-checkbox').checked=false;
    const ok=$('ca-ok');ok.textContent=o.ok||'Run';ok.className=o.danger?'danger':'';ok.disabled=!!o.needCheck;
    $('ca-checkbox').onchange=e=>{ok.disabled=!e.target.checked};
    d.onclose=()=>resolve(d.returnValue==='ok');
    d.returnValue='';d.showModal();
  });
}
/* Show a caution if the feature id (FEATURES) is unverified on a real robot. If verified, show it only with always (the safety check question). */
async function guard(fid,o){
  const epoch=uiRouteEpoch;
  const f=await featureInfo(fid),unverified=!f||!f.verified;
  if(epoch!==uiRouteEpoch||document.hidden)return false;
  if(!unverified&&!o.always)return true;
  /* quiet: the operation is verified on a real robot. Do not show the "Unverified" label; show only the safety check question */
  const accepted=await askCaution({...o,unverified:unverified&&!o.quiet,note:o.quiet?'':f&&f.note||''});
  return accepted&&epoch===uiRouteEpoch&&!document.hidden;
}

/* Status badges. Not implemented = feature does not exist yet; Unverified = implemented but not tried on the G1 */
const tag=(text,cls)=>{const s=document.createElement('span');s.className='tag '+cls;s.textContent=text;return s};
const statusTags=f=>!f?[]:!f.implemented?[tag('Not implemented','plan')]:[tag('Implemented','done'),...(f.verified?[]:[tag('Unverified','unver')])];
const headTags=f=>!f?[]:!f.implemented?[tag('Not implemented','plan')]:(f.verified?[]:[tag('Unverified','unver')]);

function renderPlanned(el,list){
  el.replaceChildren(...list.map(p=>{
    const b=document.createElement('button');
    b.disabled=true;b.title=p.note||'';b.textContent=p.label;
    const s=document.createElement('small');s.append(tag('Not implemented','plan'));b.append(s);return b;
  }));
}

async function loadFeatures(){
  const j=await (await fetch('/api/features',{cache:'no-store'})).json();
  document.querySelectorAll('.tags').forEach(el=>el.replaceChildren(...headTags(j.features.find(f=>f.id===el.dataset.feature))));
  renderPlanned($('planned-modes'),j.planned_modes);
  renderActions(j.actions);
  $('features').replaceChildren(...j.features.map(f=>{
    const li=document.createElement('li'),b=document.createElement('b');
    b.textContent=f.label;li.append(b,...statusTags(f));
    if(f.note){const n=document.createElement('span');n.className='note';n.textContent=f.note;li.append(n)}
    return li;
  }));
  featuresLoaded=true;
}

async function poll(once){
  try{
    const ctl=new AbortController(),t=setTimeout(()=>ctl.abort(),3000);
    const r=await fetch('/api/status',{signal:ctl.signal,cache:'no-store'});
    clearTimeout(t);
    if(!r.ok)throw new Error('HTTP '+r.status);
    const next=await r.json();
    if(!next.server||!next.jetson||!next.g1)throw new Error('Invalid format of the status response');
    S=next;recvAt=performance.now();fails=0;
    if(!buttons.length)await loadButtons();
    if(!featuresLoaded)await loadFeatures();
    if(!audioReady){audioReady=true;initAudio()}
    if(!volumeTried&&S.jetson.state==='ok'&&S.g1.state==='ok'){volumeTried=true;loadVolume()}
    if(S.server.mock&&$('mockbar').hidden)await loadScenarios();
  }catch(e){fails++}
  render();
  if(!once)setTimeout(poll,POLL_MS);
}

/* ---- DDS list tab ---- */
const DDS_LABEL={displayed:['Displayed','done'],todo:['Not subscribed (not implemented)','unver'],excluded:['Excluded','plan']};
let dds=null,ddsFilter='all',tab='home';
let uiRouteEpoch=0;
function td(tr,x,cls){const c=document.createElement('td');c.textContent=x;if(cls)c.className=cls;tr.append(c);return c}

/* ---- Move and actions (substitute for the physical remote controller). Only ctl is sent, at 10 Hz. If it stops for 0.5 s, the hub stops the robot and releases the operator lock. ---- */
const MO_MS=100;
let moEpoch=0,moClaimBusy=false;
let moSession=null,moSeq=0,moTimer=null,moBusy=0,moLim={vx:[-0.2,0.3],vy:[-0.2,0.2],wz:[-0.4,0.4]},moKeys=new Set();
function makePad(el,twoAxes){
  const knob=el.firstElementChild,v={x:0,y:0};let id=null;
  const draw=()=>{const r=el.clientWidth/2,h=el.clientHeight/2;knob.style.transform='translate('+(v.x*(r-29))+'px,'+(v.y*(h-29))+'px)'};
  const at=e=>{
    const b=el.getBoundingClientRect(),r=b.width/2,h=b.height/2;
    let x=(e.clientX-b.left-r)/(r-29),y=twoAxes?(e.clientY-b.top-h)/(h-29):0;
    const m=Math.hypot(x,y);if(m>1){x/=m;y/=m}
    v.x=Math.abs(x)<0.08?0:x;v.y=Math.abs(y)<0.08?0:y;draw();
  };
  const end=e=>{if(id===null||(e&&e.pointerId!==id))return;id=null;v.x=v.y=0;el.classList.remove('on');draw()};
  el.addEventListener('pointerdown',e=>{if(!moSession||tab!=='motion'||document.hidden||id!==null)return;id=e.pointerId;el.setPointerCapture(id);el.classList.add('on');at(e)});
  el.addEventListener('pointermove',e=>{if(e.pointerId===id)at(e)});
  ['pointerup','pointercancel','lostpointercapture'].forEach(n=>el.addEventListener(n,end));
  return {v,reset:()=>{id=null;v.x=v.y=0;el.classList.remove('on');draw()}};
}
const padMove=makePad($('pad-move'),true),padTurn=makePad($('pad-turn'),false);
const KEY_AXES={ArrowUp:['f',1],ArrowDown:['f',-1],ArrowLeft:['s',1],ArrowRight:['s',-1],q:['t',1],e:['t',-1]};
const scale=(a,[lo,hi])=>a>=0?a*hi:a*-lo;
function moTarget(){
  let f=-padMove.v.y,s=-padMove.v.x,t=-padTurn.v.x;
  moKeys.forEach(k=>{const [ax,sg]=KEY_AXES[k];if(ax==='f')f=sg;if(ax==='s')s=sg;if(ax==='t')t=sg});
  const mobile=window.mobileDriveTarget?window.mobileDriveTarget():{f:0,s:0,t:0,ratio:1};
  f=Math.max(-1,Math.min(1,f+mobile.f));s=Math.max(-1,Math.min(1,s+mobile.s));t=Math.max(-1,Math.min(1,t+mobile.t));
  return {vx:scale(f,moLim.vx)*mobile.ratio,vy:scale(s,moLim.vy)*mobile.ratio,wz:scale(t,moLim.wz)*mobile.ratio};
}
function moShow(j,note){
  const el=$('mo-state');let txt,cls='';
  if(!j){txt=note;cls='s-bad'}
  else if(moSession){txt=j.blocked?'Operating (cannot move: '+j.blocked+')':'Operating';cls=j.blocked?'s-warn':'s-on'}
  else{
    const ev=j.last_event,why={lost:'Stopped because the connection was lost',estop:'Emergency stop was triggered',disabled:'Manual control was disabled',sender_error:'Stopped because sending failed',takeover:'Someone else took the operator lock'}[ev&&ev.kind];
    txt=(why?why+'. ':'')+(j.operator?'Someone else is operating':'Not operating');
    cls=why?'s-warn':'';
  }
  if(note&&j)txt+=' '+note;
  el.textContent=txt;el.className=cls;
  if(j){moLim=j.limits||moLim;$('mo-lim').textContent='Forward/back '+moLim.vx.join(' to ')+' m/s · left/right '+moLim.vy.join(' to ')+' m/s · turn '+moLim.wz.join(' to ')+' rad/s'}
  if(j?.blocked){padMove.reset();padTurn.reset();moKeys.clear();window.resetMobileDrive?.()}
  const on=!!moSession;
  $('mo-claim').disabled=on||moClaimBusy;$('mo-release').disabled=!on;$('mo-estop-float').hidden=!on;
  $('ac-claim').disabled=on||moClaimBusy;$('ac-release').disabled=!on;$('ac-state').textContent=txt;$('ac-state').className=cls;
  if(window.mobileMotionState)window.mobileMotionState(on&&!j?.blocked,txt);
  document.querySelectorAll('#mo-actions button').forEach(b=>b.disabled=!on||!!(j&&j.blocked));
}
async function moPost(kind,body){
  const r=await fetch('/api/motion/'+kind,{method:'POST',body:JSON.stringify(body||{})});
  return {ok:r.ok,status:r.status,j:await r.json().catch(()=>({error:'Cannot read the response'}))};
}
function moLost(j,msg){
  moSession=null;clearInterval(moTimer);moTimer=null;padMove.reset();padTurn.reset();moKeys.clear();window.resetMobileDrive?.();
  moShow(null,msg||(j&&j.error)||'You do not hold the operator lock');
}
async function moStatus(){
  if(!['motion','action'].includes(tab)||moSession)return;
  try{const r=await fetch('/api/motion/status',{cache:'no-store'});moShow(await r.json())}
  catch(e){moShow(null,'Cannot reach the hub')}
}
async function moTick(){
  if(!moSession||moBusy>=2)return;
  const t=moTarget(),sid=moSession;moBusy++;
  $('mo-vel').textContent='vx '+t.vx.toFixed(2)+' / vy '+t.vy.toFixed(2)+' / wz '+t.wz.toFixed(2);
  try{
    const r=await moPost('ctl',{session:sid,seq:++moSeq,...t});
    if(sid!==moSession)return;
    if(r.ok)moShow(r.j);else moLost(r.j);
  }catch(e){if(sid===moSession){moRelease();moShow(null,'Cannot reach the hub. Operation ended (the hub stops the robot after 0.5 s)')}}
  finally{moBusy--}
}
async function moClaim(){
  if(moClaimBusy||moSession||!['motion','action'].includes(tab)||document.hidden)return;
  const epoch=moEpoch;moClaimBusy=true;moShow(null,'Confirming before starting operation…');
  try{
    if(!await guard('move',{title:'Start move and action control',ok:'Start operating',danger:true,always:true,quiet:true,
      lines:['Keep the physical remote controller at hand. The stop on this screen does not meet safety standards','Check that no people or objects are within 2 m','The speed limits are unverified on a real robot']}))return;
    if(epoch!==moEpoch||!['motion','action'].includes(tab)||document.hidden)return;
    moShow(null,'Acquiring the operator lock… (the first time takes a few seconds)');
    const r=await moPost('claim',{});
    if(epoch!==moEpoch||document.hidden||!['motion','action'].includes(tab)){
      if(r.ok&&r.j.session)moSendRelease(r.j.session);
      return;
    }
    if(!r.ok){moShow(null,r.j.error||'Cannot start operating');return}
    moSession=r.j.session;moSeq=0;moShow(r.j);
    moTimer=setInterval(moTick,MO_MS);
    addLog('Move/actions: operation started','ok');
  }catch(e){if(epoch===moEpoch)moShow(null,'Cannot reach the hub')}
  finally{if(epoch===moEpoch){moClaimBusy=false;$('mo-claim').disabled=!!moSession;$('ac-claim').disabled=!!moSession}}
}
function moSendRelease(sid){
  if(!(navigator.sendBeacon&&navigator.sendBeacon('/api/motion/release',JSON.stringify({session:sid}))))
    fetch('/api/motion/release',{method:'POST',body:JSON.stringify({session:sid}),keepalive:true}).catch(()=>{});
}
function moRelease(){
  moEpoch++;moClaimBusy=false;
  const sid=moSession;moLost(null,'Operation ended');
  if(sid)moSendRelease(sid);
}

async function moEstop(){
  moEpoch++;moClaimBusy=false;window.resetMobileDrive?.();
  moSession=null;clearInterval(moTimer);moTimer=null;padMove.reset();padTurn.reset();moKeys.clear();
  let note='Emergency stop sent';
  try{const r=await moPost('estop');moShow(r.j);addLog('Move/actions: emergency stop','bad');return}
  catch(e){note='Could not send the emergency stop. Stop the robot with the physical remote controller'}
  moShow(null,note);
}
async function moAction(a,b){
  if(!moSession)return;
  const session=moSession,epoch=uiRouteEpoch;
  if(!await guard('action',{title:`Run "${a.label}"`,lines:['The SetTaskId number and its effect have not been checked on a real robot','Check that no people or objects are around']}))return;
  if(epoch!==uiRouteEpoch||session!==moSession||tab!=='action')return;
  b.disabled=true;
  try{
    const r=await moPost('action',{session:moSession,name:a.id});
    addLog('Action: '+a.label+(r.ok?' (command accepted; completion unverified)':' (failed: '+(r.j.error||r.status)+')'),r.ok?'ok':'bad');
    if(r.status===409&&/operator lock/i.test(r.j.error||''))moLost(r.j);else if(r.ok)moShow(r.j);
  }catch(e){addLog('Action: '+a.label+' (cannot reach the hub)','bad')}
  finally{if(moSession)b.disabled=false}
}
function renderActions(list){
  $('mo-actions').replaceChildren(...list.map(a=>{
    const b=document.createElement('button');b.type='button';b.disabled=true;b.textContent=a.label;b.onclick=()=>moAction(a,b);return b;
  }));
}
$('mo-claim').onclick=moClaim;
$('mo-release').onclick=moRelease;
$('ac-claim').onclick=moClaim;
$('ac-release').onclick=moRelease;
['mo-estop','mo-estop-float'].forEach(id=>$(id).addEventListener('pointerdown',e=>{e.preventDefault();moEstop()}));
window.addEventListener('keydown',e=>{
  if(!moSession||tab!=='motion'||e.repeat&&moKeys.has(e.key)||/INPUT|TEXTAREA|SELECT/.test((e.target||{}).tagName||''))return;
  const k=e.key.length===1?e.key.toLowerCase():e.key;
  if(KEY_AXES[k]){moKeys.add(k);e.preventDefault()}
});
window.addEventListener('keyup',e=>{moKeys.delete(e.key.length===1?e.key.toLowerCase():e.key)});
window.addEventListener('blur',()=>{moKeys.clear();padMove.reset();padTurn.reset();window.resetMobileDrive?.()});
document.addEventListener('visibilitychange',()=>{if(document.hidden)moRelease()});
window.addEventListener('pagehide',moRelease);
setInterval(moStatus,1000);

/* ---- Tasks tab (runs predefined commands; argv exists only in the server's tasks/*.json) ---- */
let tkSel=null,tkSince=0;
const tkEls={},TK_RESULT={ok:'Succeeded',failed:'Failed',stopped:'Stopped',timeout:'Timed out'};
async function tkApi(path,body){
  const r=await fetch(path,body?{method:'POST',body:JSON.stringify(body)}:{cache:'no-store'});
  let j={};try{j=await r.json()}catch(e){}
  if(!r.ok)throw new Error(j.error||('Failed '+r.status));
  return j;
}
function tkCard(t){
  const mk=(tag,txt,cls)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(txt!=null)e.textContent=txt;return e};
  const card=mk('div',null,'tk'),st=mk('span',null,'tk-st'),row=mk('div',null,'mo-row');
  const go=mk('button','Run'),stop=mk('button','Stop','danger'),lg=mk('button','View log');
  go.onclick=()=>tkAct('start',t.name);stop.onclick=()=>tkAct('stop',t.name);lg.onclick=()=>tkSelect(t.name);
  row.append(go,stop,lg);
  const head=mk('b',t.title);if(!t.verified)head.append(tag('Unverified','unver'));
  card.append(head,st,mk('span',t.description,'note'),mk('code',t.argv.join(' ')),row);
  $('tk-list').append(card);
  return tkEls[t.name]={card,st,go,stop,def:t};
}
function renderTasks(list){
  window.mobileTasks?.(list);
  list.forEach(t=>{
    const e=tkEls[t.name]||tkCard(t),run=t.state!=='idle';
    e.go.disabled=run;e.stop.disabled=t.state!=='running';
    e.st.textContent=run?(t.state==='stopping'?'Stopping…':'Running'):(t.result?`${TK_RESULT[t.result]||t.result} (exit code ${t.exit_code})`:'Not run');
    e.card.dataset.sel=String(t.name===tkSel);
  });
}
async function tkRefresh(){
  try{renderTasks((await tkApi('/api/tasks')).tasks);$('tk-msg').textContent=''}
  catch(e){$('tk-msg').textContent='Cannot fetch: '+e.message;window.mobileTasks?.(null)}
  if(tab==='tasks'&&tkSel)tkLogs();
}
async function tkAct(kind,name){
  const epoch=uiRouteEpoch;
  const t=(tkEls[name]||{}).def;
  if(t&&(!t.verified||t.caution.length)){
    const run=kind==='start';
    if(!await askCaution({title:`${run?'Run':'Stop'} "${t.title}"`,ok:run?'Run':'Stop',danger:true,unverified:!t.verified,
      needCheck:t.caution.length>0,lines:[...t.caution,'Command: '+t.argv.join(' ')]}))return;
  }
  if(epoch!==uiRouteEpoch||tab!=='tasks'||document.hidden)return;
  try{await tkApi('/api/tasks/'+kind,{name});if(kind==='start')tkSelect(name)}
  catch(e){$('tk-msg').textContent=e.message}
  tkRefresh();
}
function tkSelect(name){
  tkSel=name;tkSince=0;$('tk-log').textContent='';$('tk-log-card').hidden=false;
  $('tk-log-h').textContent='Log: '+name;tkLogs();
}
async function tkLogs(){
  const name=tkSel;if(!name)return;
  try{
    const j=await tkApi('/api/tasks/logs?name='+encodeURIComponent(name)+'&since='+tkSince);
    if(name!==tkSel)return;
    const pre=$('tk-log');
    if(j.next<tkSince){tkSince=0;pre.textContent='';return}  /* The log was recreated by a re-run */
    if(!j.lines.length)return;
    const atEnd=pre.scrollTop+pre.clientHeight>=pre.scrollHeight-8;
    pre.textContent=(j.truncated&&!pre.textContent?'… (older lines omitted)\n':'')+(pre.textContent+j.lines.map(l=>l.text+'\n').join('')).slice(-200000);
    tkSince=j.next;
    if(atEnd)pre.scrollTop=pre.scrollHeight;
  }catch(e){}
}
setInterval(tkRefresh,1000);

/* ---- Topic messaging (inside the DDS tab). Values from DDS are drawn with textContent only ---- */
let tpT=null,tpInfo=null;
function tpMsg(cls,text){const e=$('tp-msg');e.className='res '+cls;e.textContent=text}
async function tpLoad(){
  try{tpInfo=await tkApi('/api/topics')}catch(e){tpInfo=null;$('tp-card').hidden=/404|not found/i.test(e.message);tpMsg('warn','Topic messaging is unavailable: '+e.message);return}
  $('tp-card').hidden=false;tpMsg('','');
  const sel=$('tp-type');if(!sel.children.length)tpInfo.supported_types.forEach(t=>{const o=document.createElement('option');o.value=o.textContent=t;sel.append(o)});
  const box=$('tp-pub');box.textContent='';
  if(!tpInfo.publish.length){const p=document.createElement('p');p.className='note';p.textContent='The publish allowlist is empty (nothing can be sent)';box.append(p)}
  tpInfo.publish.forEach(r=>{
    const row=document.createElement('div'),nm=document.createElement('b'),inp=document.createElement('input'),btn=document.createElement('button');
    row.className='arow';nm.textContent=r.topic;inp.type='text';inp.maxLength=r.max_bytes;inp.placeholder=`Text (up to ${r.max_bytes} bytes, ${r.min_interval_s} s interval)`;
    btn.type='button';btn.textContent='Send';
    btn.onclick=async()=>{
      if(!await guard('topics',{title:'Publish to the topic',ok:'Send',lines:[`Sends "${inp.value}" (${new TextEncoder().encode(inp.value).length} bytes) to ${r.topic}`]}))return;
      try{const j=await tkApi('/api/topics/publish',{topic:r.topic,data:inp.value});tpMsg('ok',`Sent: ${j.published} (${j.bytes} bytes)`)}
      catch(e){tpMsg('bad',e.message)}
    };
    row.append(nm,inp,btn);box.append(row);
  });
}
async function tpTick(){
  if(tab!=='dds'||!tpInfo||!tpInfo.subscribed.length&&!$('tp-table').querySelector('tbody').children.length)return;
  let items;try{items=(await tkApi('/api/topics/received')).items}catch(e){tpMsg('bad',e.message);return}
  const tb=$('tp-table').querySelector('tbody');tb.textContent='';
  items.forEach(it=>{
    const tr=document.createElement('tr');
    td(tr,it.topic);td(tr,it.age_s==null?'No data':`${f(it.age_s,1)} s ago (${it.count} msgs)`,it.age_s==null?'live-none':'live-ok');
    const m=td(tr,'');const pre=document.createElement('code');pre.textContent=it.message==null?'—':JSON.stringify(it.message).slice(0,300);m.append(pre);
    const c=td(tr,'');const b=document.createElement('button');b.type='button';b.textContent='Unsubscribe';b.className='sm';
    b.onclick=async()=>{try{await tkApi('/api/topics/unsubscribe',{topic:it.topic});await tpLoad();tpTick()}catch(e){tpMsg('bad',e.message)}};
    c.append(b);tb.append(tr);
  });
}
$('tp-sub').onclick=async()=>{
  try{const j=await tkApi('/api/topics/subscribe',{topic:$('tp-topic').value.trim(),type:$('tp-type').value});tpMsg('ok','Subscribed: '+j.topic);await tpLoad();tpTick()}
  catch(e){tpMsg('bad',e.message)}
};
function tpStart(){tpLoad().then(tpTick);if(!tpT)tpT=setInterval(tpTick,2000)}
function tpStop(){clearInterval(tpT);tpT=null}

/* Main navigation (Control / Status / Tasks / Sensors / Dev). Groups without a screen are not shown.
   Tab name = #hash = API name as before. When adding a screen, put it in the array of the matching group. */
const GROUPS=[['home','Home',['home']],['ops','Control',['ops','motion','action','audio']],['state','Status',['state','joints']],['tasks','Tasks',['tasks']],['sensor','Sensors',['camera']],['dev','Dev',['dds','settings']]];
const TABS=GROUPS.flatMap(g=>g[2]);
const ROUTES={home:'home',mode:'ops',remote:'motion',actions:'action',status:'state',voice:'audio',sensors:'camera',joints:'joints',tasks:'tasks',dds:'dds',settings:'settings'};
const HASHES=Object.fromEntries(Object.entries(ROUTES).map(([k,v])=>[v,k]));
const TITLES={home:'G1 Control',ops:'Mode',motion:'Remote',action:'Actions',audio:'Voice',state:'Status',joints:'Joints',tasks:'Tasks',camera:'Sensors',dds:'DDS',settings:'Settings'};
function setTab(request,fromHistory=false){
  let t=ROUTES[request]||request;if(!TABS.includes(t))t='home';
  if(window.uiRouteReady&&t===tab)return;
  uiRouteEpoch++;
  if(t!==tab||!['motion','action'].includes(t))moRelease();
  if($('caution').open){$('caution').returnValue='cancel';$('caution').close()}
  tab=t;
  TABS.forEach(k=>{$('tab-'+k).hidden=k!==t;$('tab-b-'+k).setAttribute('aria-pressed',String(k===t));$('tab-b-'+k).hidden=false});
  $('ui-title').textContent=TITLES[t];document.title=TITLES[t]+' · G1 Control';
  $('ui-back').setAttribute('aria-label',t==='home'?'Open menu':t==='joints'?'Back to status':'Back to home');
  $('ui-back').querySelector('use').setAttribute('href',t==='home'?'#i-menu':'#i-back');
  $('ui-navigation').close();
  stopCameras();ldView(false);
  if(t==='camera')window.openSensorView?.();
  if(!fromHistory&&location.hash!=='#'+HASHES[t])history.pushState(null,'','#'+HASHES[t]);
  if(t==='dds'){if(!dds)loadDds();else renderDds()}
  t==='dds'?tpStart():tpStop();
  if(t==='settings')loadSettings();
  if(t==='motion'||t==='action')moStatus();
  if(t==='tasks')tkRefresh();
  lastKey='';window.uiRouteReady=true;
  window.scrollTo(0,0);$('tab-'+t).focus({preventScroll:true});
  render();
}

async function loadDds(){
  try{dds=await(await fetch('/api/dds',{cache:'no-store'})).json()}catch(e){$('dds-sum').textContent='Cannot fetch the list';return}
  renderDds();
}
function buildDdsFilters(){
  [['all','All'],['displayed','Displayed'],['todo','Not subscribed (not implemented)'],['excluded','Excluded']].forEach(([k,l])=>{
    const b=document.createElement('button');b.className='sm';b.textContent=l;b.dataset.k=k;
    b.onclick=()=>{ddsFilter=k;renderDds()};$('dds-filters').append(b);
  });
}
function renderDds(){
  if(!dds||tab!=='dds')return;
  const cnt={displayed:0,todo:0,excluded:0};dds.topics.forEach(t=>cnt[t.status]++);
  $('dds-sum').textContent=`${dds.topics.length} topics: displayed ${cnt.displayed} / not subscribed (not implemented) ${cnt.todo} / excluded ${cnt.excluded}`;
  if(!$('dds-filters').children.length)buildDdsFilters();
  [...$('dds-filters').children].forEach(b=>b.setAttribute('aria-pressed',b.dataset.k===ddsFilter));
  const n=S?nodes():null,T=S&&S.telemetry,live=!!T&&!!n&&n.jetson.st==='ok'&&n.g1.st==='ok';
  const tb=document.querySelector('#dds-table tbody');tb.textContent='';
  const visible=dds.topics.filter(t=>(ddsFilter==='all'||t.status===ddsFilter)&&(!window.ddsSearchMatches||window.ddsSearchMatches(t)));
  $('ui-dds-empty').hidden=visible.length>0;
  visible.forEach(t=>{
    const tr=document.createElement('tr');
    const open=document.createElement('button');open.type='button';open.className='topic-open';open.textContent=t.topic;open.onclick=()=>window.selectDdsTopic?.(t);
    td(tr,'').append(open);td(tr,t.type);
    const c=td(tr,'');const tg=document.createElement('span');tg.className='tag '+DDS_LABEL[t.status][1];tg.style.marginLeft='0';tg.textContent=DDS_LABEL[t.status][0];c.append(tg);
    let rx='—',cls='';
    if(t.status==='displayed'){
      const a=live&&T.ages?T.ages[t.topic]:undefined;
      if(a==null){rx=live?'No data':'Unverified';cls='live-none'}else{rx=`${f(a,1)} s ago`;cls=a<=5?'live-ok':'live-none'}
    }
    td(tr,rx,cls);td(tr,t.note);tb.append(tr);
  });
  const sb=document.querySelector('#svc-table tbody');sb.textContent='';
  dds.services.forEach(v=>{const tr=document.createElement('tr');td(tr,v.name);td(tr,v.status,v.status==='In use'?'live-ok':(v.status==='SDK available, not implemented'?'':'live-none'));td(tr,v.note);sb.append(tr)});
}
/* ---- Settings tab / stopping automatic checks ---- */
const form=$('set-form');
async function loadSettings(){
  try{
    const j=await(await fetch('/api/settings',{cache:'no-store'})).json();
    for(const [k,v] of Object.entries(j.settings))if(form.elements[k])form.elements[k].value=v;
    $('set-res').textContent='';
  }catch(e){$('set-res').textContent='Cannot read the settings (cannot reach the server)'}
}
form.onsubmit=async ev=>{
  ev.preventDefault();
  const body=Object.fromEntries(new FormData(form).entries()),res=$('set-res');
  res.className='res';res.textContent='Saving…';
  try{
    const r=await fetch('/api/settings',{method:'POST',body:JSON.stringify(body)}),j=await r.json();
    if(!r.ok){res.className='res bad';res.textContent=j.error||('Failed '+r.status);return}
    for(const [k,v] of Object.entries(j.settings))if(form.elements[k])form.elements[k].value=v;
    res.className='res ok';res.textContent='Saved. Reconnecting to the Jetson.';
    poll(true);
  }catch(e){res.className='res bad';res.textContent='Cannot reach the server ('+e+')'}
};
async function monitorCtl(body){
  try{await fetch('/api/monitor',{method:'POST',body:JSON.stringify(body)})}catch(e){}
  await poll(true);
}
$('mon-toggle').onclick=()=>monitorCtl({paused:!(S&&S.paused)});
$('mon-once').onclick=()=>monitorCtl({check:true});
$('hub-stop').onclick=async()=>{
  if(!await guard('hubstop',{title:'Stop the hub',ok:'Stop',danger:true,always:true,needCheck:true,
    lines:['The console itself stops, and it cannot be restarted from this screen','Restart it on the Jetson (if it is set to start automatically, it comes back when the Jetson restarts)','The camera and lidar stream processes are separate, so they are expected not to stop (unverified). Stop them first if needed']}))return;
  setRes('hub-res','Stopping…');
  try{
    const r=await fetch('/api/hub/stop',{method:'POST',body:JSON.stringify({confirm:true})}),j=await r.json();
    if(!r.ok){setRes('hub-res',j.error||('Failed '+r.status),'bad');return}
    setRes('hub-res',j.message,'ok');$('hub-stop').disabled=true;
  }catch(e){setRes('hub-res','Cannot reach the server ('+e+')','bad')}
};
TABS.forEach(k=>{$('tab-b-'+k).onclick=()=>setTab(HASHES[k])});
GROUPS.forEach(([key,label,tabs])=>{
  const group=document.createElement('section'),heading=document.createElement('h3');heading.textContent=label;group.append(heading);
  tabs.forEach(t=>{const button=$('tab-b-'+t);button.removeAttribute('role');button.removeAttribute('aria-selected');button.setAttribute('aria-label',TITLES[t]);group.append(button)});
  $('nav-main').append(group);
});
$('nav-sub').hidden=true;
window.addEventListener('popstate',()=>setTab(location.hash.slice(1),true));
window.addEventListener('hashchange',()=>setTab(location.hash.slice(1),true));
// mobile.js finishes registration before choosing the first full screen.
setInterval(render,250);setInterval(renderDds,1000);
poll();
