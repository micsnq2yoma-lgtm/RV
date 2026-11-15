'use strict';
// Workbench v2 (task 015). Live data: SSE /events from the board; video: MJPEG straight from the PC simulator.
const $=id=>document.getElementById(id);
// Pages may set window.RV_CONFIG (nav.html: navigation demo) to choose cameras, stream host and mode.
const C=window.RV_CONFIG||{};
const CAMS=C.cams||['front','top','side','wrist'],LABEL=C.labels||{front:'FRONT · 正面',top:'TOP · 俯视',side:'SIDE · 侧面',wrist:'WRIST · 腕部'};
const CN={red:'红',green:'绿',blue:'蓝',orange:'橙'},HEX={red:'#dc2626',green:'#16a34a',blue:'#2563eb',orange:'#ea8a1a'};
const PH={observe:['观察','var(--accent)'],plan:['规划','var(--plan)'],act:['执行','var(--amber)'],verify:['校验','var(--ok)'],fail:['失败','var(--warn)'],done:['完成','var(--ok)'],idle:['待命','var(--muted)']};
const KD={obs:'感知',think:'思考',plan:'计划',call:'调用',ok:'结果',err:'失败',board:'主板'};
const S={mode:C.nav?'navigate':'instruction',goal:null,scenarios:{},main:C.main||'front',nav:{map:null,zones:{},path:null,robot:null},replay:null,replayRun:null,images:null,detections:[],
  run:null,started:null,finished:null,calls:0,tokens:0,version:0,streaming:false,actStart:0,actLen:1,
  hist:[[],[],[]],health:[],lastBoardNote:0,busy:false,ready:false};
const num=(v,n=1)=>typeof v==='number'&&isFinite(v)?v.toFixed(n):'—';
const css=name=>getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const color=c=>String(c).replace('_cube','');

async function api(path,body){
  const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  let d={};try{d=await r.json();}catch{}
  if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:(d.error||r.statusText));
  return d;
}

// ---------- views ----------
const stream=(cam,big)=>`${C.mjpeg||'http://127.0.0.1:8090'}/stream/${cam}.mjpg?w=${big?640:320}&h=${big?480:240}&fps=8`;
function src(cam,big){return S.replay&&S.images?`/runs/${S.replayRun}/file/${S.images[cam]||S.images.top}`:stream(cam,big);}
function views(){
  const img=$('mainImg'),want=src(S.main,true);if(img.dataset.src!==want){img.src=want;img.dataset.src=want;}
  $('mainTag').textContent=LABEL[S.main];$('liveTag').hidden=!!S.replay;$('ovlToggle').hidden=S.main!=='top';
  const box=$('thumbs');box.replaceChildren();
  for(const cam of CAMS.filter(c=>c!==S.main)){
    const b=document.createElement('button');b.className='thumb';b.title='点一下换成主画面';
    const i=document.createElement('img');i.alt=LABEL[cam];i.src=src(cam,false);
    const t=document.createElement('span');t.className='tag';t.textContent=LABEL[cam];
    b.append(i,t);b.onclick=()=>{S.main=cam;views();};box.append(b);
  }
  overlay();
}
$('mainImg').onerror=()=>$('mainImg').classList.add('offline');$('mainImg').onload=()=>$('mainImg').classList.remove('offline');
function overlay(){
  const c=$('overlay'),g=c.getContext('2d');g.clearRect(0,0,c.width,c.height);
  if(S.main!=='top'||!$('ovl').checked||S.replay)return;
  // Canvas covers the <img>; the image uses object-fit:cover, so map 640x480 into the visible box.
  const r=c.getBoundingClientRect();c.width=r.width;c.height=r.height;const k=Math.max(r.width/640,r.height/480),ox=(r.width-640*k)/2,oy=(r.height-480*k)/2;
  g.lineWidth=2;g.font='600 12px '+css('--mono');
  for(const d of S.detections){
    const [x,y,w,h]=d.bbox,col=HEX[d.name]||'#fff';g.strokeStyle=col;g.strokeRect(ox+x*k,oy+y*k,w*k,h*k);
    const label=(CN[d.name]||d.name)+' · 板上';g.fillStyle='rgba(0,0,0,.65)';g.fillRect(ox+x*k,oy+y*k-17,g.measureText(label).width+8,16);g.fillStyle='#fff';g.fillText(label,ox+x*k+4,oy+y*k-5);
  }
}
$('ovl').onchange=overlay;addEventListener('resize',overlay);

// ---------- agent panel ----------
function phase(key,title,step,call){
  const p=PH[key];const k=$('kicker');k.textContent='智能体 · '+p[0]+(step?' · 第 '+step+' 步':'');k.style.color=p[1];
  if(title!==undefined)$('nowT').textContent=title;
  $('capK').textContent=p[0]+(step?' · 第 '+step+' 步':'');$('capK').style.color=key==='fail'?'#ff8a80':'';
  if(title!==undefined)$('capT').textContent=title;if(call!==undefined)$('capC').textContent=call;
}
function addFeed(kind,text,ts){
  const feed=$('feed'),stick=feed.scrollTop+feed.clientHeight>=feed.scrollHeight-24;
  feed.querySelector('.new')?.classList.remove('new');
  const d=document.createElement('div');d.className='fl new k-'+kind;
  const tm=document.createElement('span');tm.className='tm';tm.textContent=new Date((ts||Date.now()/1000)*1000).toLocaleTimeString('zh-CN',{hour12:false});
  const kd=document.createElement('span');kd.className='kd';kd.textContent=KD[kind];
  const tx=document.createElement('span');tx.className='tx';tx.textContent=text;
  d.append(tm,kd,tx);feed.append(d);while(feed.children.length>600)feed.firstChild.remove();
  if(stick||S.replay)feed.scrollTop=feed.scrollHeight;   // pause auto-scroll while the user reads older lines
}
function towersText(scene){
  if(!scene)return '';const t=(scene.towers||[]).map(x=>x.map(c=>CN[color(c)]||c).join('·'));
  const l=(scene.loose||[]).map(c=>CN[color(c)]||c);const h=scene.holding?' · 手里：'+(CN[color(scene.holding)]||scene.holding):'';
  return (t.length?'塔 '+t.join(' / '):'没有塔')+(l.length?' · 桌面 '+l.join('、'):'')+h+((scene.occluded_or_inferred||[]).length?' · 推断：'+scene.occluded_or_inferred.map(c=>CN[color(c)]||c).join('、'):'');
}
function plan(e){
  const ol=$('plan');
  if(e.version>1){
    ol.querySelectorAll('li.s:not(.done):not(.dropped)').forEach(li=>{li.classList.remove('cur','fail');li.classList.add('dropped');li.querySelector('.st').textContent='已替换';});
  }
  const v=document.createElement('li');v.className='ver'+(e.version>1?' re':'');v.textContent=`第 ${e.version} 版计划`;
  if(e.reason){const w=document.createElement('span');w.className='why';w.textContent=' · '+e.reason;v.append(w);}
  ol.append(v);
  e.steps.forEach((s,i)=>{const li=document.createElement('li');li.className='s';li.dataset.v=e.version;li.dataset.i=i+1;
    li.innerHTML='<span class="n"></span><span class="tx"></span><span class="st"></span>';li.querySelector('.n').textContent=i+1;li.querySelector('.tx').textContent=s;ol.append(li);});
  S.version=e.version;$('sRe').textContent=Math.max(0,e.version-1);
  ol.scrollTop=v.offsetTop-ol.offsetTop;
}
function planItem(i){return $('plan').querySelector(`li.s[data-v="${S.version}"][data-i="${i}"]`);}
function markStep(i,state){
  const li=planItem(i);if(!li)return;
  $('plan').querySelectorAll(`li.s.cur[data-v="${S.version}"]`).forEach(x=>{if(x!==li){x.classList.remove('cur');x.querySelector('.st').textContent='';}});
  const box=li.closest('.plan');if(box){const r=li.getBoundingClientRect(),q=box.getBoundingClientRect();if(r.bottom>q.bottom||r.top<q.top)box.scrollTop+=r.top-q.top-q.height/2;}
  li.classList.remove('cur','fail','done');li.classList.add(state);li.querySelector('.st').textContent={cur:'进行中',done:'完成',fail:'失败'}[state];
  if(state==='done')for(const x of $('plan').querySelectorAll(`li.s[data-v="${S.version}"]`))if(+x.dataset.i<i&&!x.classList.contains('done')&&!x.classList.contains('fail')){x.classList.add('done');x.querySelector('.st').textContent='完成';}
}
function callText(tool,args){const a=Object.values(args||{}).map(v=>typeof v==='string'?v:JSON.stringify(v));return `${tool}(${a.join(', ')})`;}

function reset(e){
  S.run=e.run;S.started=e.ts;S.finished=null;S.calls=0;S.tokens=0;S.version=0;S.streaming=false;S.actStart=0;
  $('plan').replaceChildren();$('feed').replaceChildren();$('quote').textContent='';$('quote').classList.remove('reasoning');
  for(const id of ['sStep','sCalls','sTok','sRe'])$(id).textContent='0';$('prog').style.width='0';
  phase('observe','读取场景'+(e.kind==='instruction'?'':'和目标'),0,'');
  if(e.goal)showGoal({image_url:e.goal.image_url,recognition:{towers:e.goal.towers,loose:e.goal.loose,confidence:e.goal.confidence}},true);
  if(!S.replay){if(e.text)$('instr').value=e.text;const g=e.kind!=='instruction';$('modeInstr').setAttribute('aria-selected',!g);$('modeGoal').setAttribute('aria-selected',g);}
}

// ---------- event handling (live and replay share this) ----------
function handle(e,live=true){
  switch(e.type){
  case 'sysmon':if(live)board(e);return;
  case 'task_start':reset(e);addFeed('obs',(e.kind==='baseline'?'基线脚本 · ':'')+'任务开始 · '+(e.text||'')+(e.scenario?' · '+e.scenario:'')+(e.seed!=null?' · seed '+e.seed:''),e.ts);if(live)busy(true);break;
  case 'observe':
    S.detections=e.detections||[];overlay();phase('observe','观察场景');
    if(e.map){S.nav.map=e.map;S.nav.zones=e.scene?.zones||S.nav.zones;S.nav.robot=e.scene?.robot||S.nav.robot;drawMap();}
    if(e.summary){addFeed('obs',e.summary,e.ts);break;}
    addFeed('obs',(e.scene&&e.scene.towers?towersText(e.scene):'俯视感知 '+(e.scene?.objects||[]).filter(o=>!o.occluded).length+' 个物体')+(e.seconds?` · ${num(e.seconds,2)} s`:''),e.ts);break;
  case 'think_delta':
    if(!S.streaming){S.streaming=true;$('quote').textContent='';phase('plan','思考中…');}
    $('quote').classList.toggle('reasoning',e.channel==='reasoning_content');$('quote').textContent+=e.text;$('quote').scrollTop=$('quote').scrollHeight;return;
  case 'think_end':
    S.streaming=false;S.calls++;S.tokens+=e.tokens?.total_tokens||0;$('sCalls').textContent=S.calls;$('sTok').textContent=S.tokens.toLocaleString();
    if(!live||!$('quote').textContent)$('quote').textContent=e.text||'（本次调用没有返回文字）';
    if(e.text)addFeed('think',e.text.replace(/\s+/g,' ').slice(0,180)+(e.text.length>180?'…':''),e.ts);break;
  case 'nav_plan':S.nav.path=e.path;drawMap();addFeed('plan',`板上规划路线 → ${e.target} · ${num(e.length,2)} m`+(e.avoid?.length?` · 避开 ${e.avoid.join('、')}`:''),e.ts);break;
  case 'nav_escape':addFeed('obs',`离障碍太近，先${e.direction==='back'?'后退':'前进'} 0.25 m 再转向（净空 ${num(e.clearance,2)} m）`,e.ts);break;
  case 'nav_fix':S.detections=e.detections||[];overlay();S.nav.robot=e.pose;drawMap();addFeed('obs',`途中重定位 (${num(e.pose.x,2)}, ${num(e.pose.y,2)})`,e.ts);break;
  case 'plan':plan(e);phase('plan',e.version>1?'重新规划 · 第 '+e.version+' 版':'计划已列出');addFeed('plan',`update_plan 第 ${e.version} 版：${e.steps.length} 步${e.reason?' · '+e.reason:''}`,e.ts);break;
  case 'step_start':{
    const title=planItem(e.index)?.querySelector('.tx').textContent||callText(e.tool,e.args);
    markStep(e.index,'cur');phase('act',title,e.index,callText(e.tool,e.args));$('sStep').textContent=e.index;
    S.actStart=performance.now();S.actLen=(e.expected_s||8)*1000;$('prog').style.width='0';addFeed('call',callText(e.tool,e.args),e.ts);break;}
  case 'step_result':{
    S.actStart=0;$('prog').style.width='100%';const d=e.detail||{};
    if(e.ok){if(e.index)markStep(e.index,'done');phase('verify','重新观察，确认结果');
      addFeed('ok',d.target?`到达 ${d.target} · 行驶 ${num(d.travelled_m,2)} m（规划 ${num(d.planned_m,2)} m）· ${num(d.seconds,0)} s`:d.holding?`已抓住 ${d.holding}${d.gripper_m?' · 夹爪 '+num(d.gripper_m,3)+' m':''}`:d.placed?`${d.placed} 放到 ${d.on}${d.xy?' ('+d.xy.join(', ')+')':''}${d.z?' · 高度 '+num(d.z,3)+' m':''}`:d.summary?`finish · ${d.summary}`:JSON.stringify(d),e.ts);}
    else{if(e.index)markStep(e.index,'fail');phase('fail',d.error||'动作失败');addFeed('err',(d.target?`去 ${d.target} 未完成 · 行驶 ${num(d.travelled_m,2)} m · `:'')+(d.error||JSON.stringify(d)),e.ts);}
    break;}
  case 'finish':{
    S.finished=e.ts;const t=e.success_truth;const st=e.stats||{};
    phase(t?'done':'fail',t?'任务完成 · 真值验收通过':t===false?'任务结束 · 真值验收未通过':'任务结束 · 没有真值判定',undefined,'');
    if(st.seconds!=null)$('sTime').textContent=num(st.seconds);
    addFeed(t?'ok':'err',`结束（${st.status||'?'}）· 模型自报 ${e.success_self===true?'成功':e.success_self===false?'失败':'—'} · 真值 ${t===true?'通过':t===false?'未通过':'未判定'}`,e.ts);
    if(live){busy(false);$('notice').textContent='真值验收：'+(t===true?'通过':t===false?'未通过':'未判定');}
    break;}
  case 'alert':addFeed(e.level==='error'?'err':'board',e.text,e.ts);break;
  }
}

// ---------- board map (navigation demo) ----------
const ZC={red:'#dc2626',green:'#16a34a',blue:'#2563eb',yellow:'#e0b000'};
function drawMap(){
  const c=$('navMap');if(!c||!S.nav.map)return;const m=S.nav.map,X0=-2.1,Y0=-1.6,CELL=.05;
  const r=c.getBoundingClientRect(),dpr=devicePixelRatio||1;c.width=r.width*dpr;c.height=r.height*dpr;const g=c.getContext('2d');g.scale(dpr,dpr);
  const k=Math.min(r.width/m.w,r.height/m.h),ox=(r.width-m.w*k)/2,oy=(r.height-m.h*k)/2;
  const P=(x,y)=>[ox+(x-X0)/CELL*k,oy+(m.h-(y-Y0)/CELL)*k];
  g.fillStyle=css('--surface');g.fillRect(ox,oy,m.w*k,m.h*k);
  for(const [z,v] of Object.entries(S.nav.zones||{})){const [a,b]=P(v.center[0]-v.half[0],v.center[1]+v.half[1]);g.fillStyle=ZC[z]||'#999';g.globalAlpha=.55;g.fillRect(a,b,2*v.half[0]/CELL*k,2*v.half[1]/CELL*k);g.globalAlpha=1;}
  const bits=atob(m.bits);g.fillStyle=css('--ink-2');
  for(let j=0;j<m.h;j++)for(let i=0;i<m.w;i++){const n=j*m.w+i;if(bits.charCodeAt(n>>3)&(128>>(n&7)))g.fillRect(ox+i*k,oy+(m.h-1-j)*k,k+.4,k+.4);}
  if(S.nav.path){g.strokeStyle=css('--plan');g.lineWidth=2;g.setLineDash([5,3]);g.beginPath();S.nav.path.forEach((p,i)=>{const [a,b]=P(p[0],p[1]);i?g.lineTo(a,b):g.moveTo(a,b);});g.stroke();g.setLineDash([]);}
  const rb=S.nav.robot;if(rb){const [a,b]=P(rb.x,rb.y);g.fillStyle=css('--accent');g.beginPath();g.arc(a,b,4,0,7);g.fill();g.strokeStyle=css('--accent');g.lineWidth=2;g.beginPath();g.moveTo(a,b);g.lineTo(a+10*Math.cos(rb.yaw),b-10*Math.sin(rb.yaw));g.stroke();}
}
addEventListener('resize',drawMap);

// ---------- board ----------
function spark(id,h,col,max,thr){
  const c=$(id),r=c.getBoundingClientRect(),dpr=devicePixelRatio||1;if(!r.width)return;c.width=r.width*dpr;c.height=r.height*dpr;const g=c.getContext('2d');g.scale(dpr,dpr);
  const w=r.width,ht=r.height,y=v=>ht-Math.min(v,max)/max*(ht-4)-2;
  if(thr!==undefined){g.strokeStyle=css('--warn');g.setLineDash([4,3]);g.beginPath();g.moveTo(0,y(thr));g.lineTo(w,y(thr));g.stroke();g.setLineDash([]);}
  if(h.length<2)return;const x=j=>j/(60-1)*w+(60-h.length)/(60-1)*w;
  g.strokeStyle=col;g.lineWidth=1.6;g.beginPath();h.forEach((v,j)=>j?g.lineTo(x(j),y(v)):g.moveTo(x(j),y(v)));g.stroke();
  g.lineTo(w,ht);g.lineTo(x(0),ht);g.closePath();g.globalAlpha=.12;g.fillStyle=col;g.fill();g.globalAlpha=1;
  if(thr!==undefined)h.forEach((v,j)=>{if(v>=thr*.8){g.fillStyle=v>=thr?css('--warn'):css('--amber');g.beginPath();g.arc(x(j),y(v),2.5,0,7);g.fill();}});
}
function board(e){
  const cp=e.cpus||{},rt=e.rt||{},m=e.memory||{};
  const win=rt.window_processing_us_max!=null?rt.window_processing_us_max/1000:null;
  const vals=[cp.cpu0?.busy,cp.cpu1?.busy,win];
  vals.forEach((v,i)=>{if(typeof v==='number'){S.hist[i].push(v);if(S.hist[i].length>60)S.hist[i].shift();}});
  spark('c0',S.hist[0],css('--accent'),100);spark('c1',S.hist[1],css('--plan'),100);spark('c2',S.hist[2],css('--amber'),Math.max(1.5,...S.hist[2]),1);
  $('v0').textContent=num(vals[0],0)+'%';$('v1').textContent=num(vals[1],0)+'%';$('v2').textContent=win==null?'—':num(win,2);
  const rtMax=rt.processing_us_max/1000;$('rtMean').textContent=num(rt.processing_us_mean/1000,2);$('rtMax').textContent=num(rtMax,2);
  $('rtGap').textContent=num(rt.interval_ms_max,1);$('rtLoss').textContent=rt.lost??'—';
  $('rtMaxBox').className=rtMax>=1?'hot':'ok';$('rtLossBox').className=rt.lost?'hot':'ok';$('rtMeanBox').className='ok';$('rtGapBox').className=rt.interval_ms_max>50?'hot':'ok';
  // Health chip: green only if every second in the last 10 s had window max < 1 ms and no new loss.
  S.health.push({ts:e.utc||e.ts,max:win,lost:rt.lost});S.health=S.health.filter(x=>(e.utc||e.ts)-x.ts<10.5);
  const first=S.health[0],newLoss=first&&rt.lost!=null&&first.lost!=null?rt.lost-first.lost:0,peak=Math.max(...S.health.map(x=>x.max??0));
  const state=win==null?['idle','等待实时环']:newLoss>0||peak>=1.5?['bad',`实时环异常 · ${num(peak,2)} ms`]:peak>=1?['amber',`实时环超 1 ms · ${num(peak,2)}`]:['ok','实时环正常'];
  $('rtChip').className='chip '+state[0];$('rtChip').lastChild.textContent=state[1];
  const used=m.total_mb-m.available_mb;$('mem').textContent=`${num(used,0)} / ${num(m.total_mb,0)} MB`;$('memBar').style.width=(used/m.total_mb*100||0)+'%';
  const n=e.eth0_bytes_per_s||{};$('net').textContent=`收 ${num((n.rx||0)/1024,0)} KB/s · 发 ${num((n.tx||0)/1024,0)} KB/s`;
  const q=e.irq_per_s||{};$('irq').textContent=[['eth0','eth0'],['emmc','eMMC'],['tf','TF'],['serial','串口']].filter(([k])=>k in q).map(([k,l])=>`${l} ${num(q[k],0)}/s`).join(' · ')||'—';
  $('temp').textContent=e.temperatures_c?.length?e.temperatures_c.map(v=>num(v)+' °C').join(' / '):'不可读';
  $('kernel').textContent=(e.kernel||'—')+(e.loadavg?' · load '+e.loadavg.join(' '):'');$('boardHead').textContent='芯来 UX900 ×2 · '+(e.kernel||'');
  const names={rt_ctl:'rt_ctl',agent:'智能体',dashboard:'面板',sysmon:'监控'};
  $('procs').textContent=Object.entries(e.processes||{}).map(([k,v])=>`${names[k]||k} ${num(v.percent,0)}% · CPU${v.cpu} · ${v.policy===1?'FIFO'+(v.priority<0?-v.priority-1:v.priority):'普通'}`).join('\n')||'—';
  // Insert a board line into the activity feed only at notable moments.
  const now=Date.now();if(S.run&&!S.finished&&now-S.lastBoardNote>15000&&(vals[0]>=95||win>=1)){S.lastBoardNote=now;addFeed('board',`CPU0 ${num(vals[0],0)}% · 实时环本秒峰值 ${num(win,2)} ms`,e.utc);}
}

// ---------- task bar ----------
function mode(m){
  if(C.nav){S.mode='navigate';for(const id of ['modeInstr','modeGoal','preset','randomGoal'])$(id).hidden=true;$('upload').parentElement.hidden=true;$('goalPicker').hidden=false;$('goalImg').hidden=true;$('goalEmpty').hidden=true;$('goalBox').classList.remove('empty');return;}
  S.mode=m;$('modeInstr').setAttribute('aria-selected',m==='instruction');$('modeGoal').setAttribute('aria-selected',m==='goal_stack');
  $('goalPicker').hidden=m!=='goal_stack';$('instr').readOnly=m==='goal_stack';
  if(m==='goal_stack'){$('instr').value='按照目标图片的顺序把积木叠起来';if(!S.goal)$('preset').dispatchEvent(new Event('change'));else showGoal(S.goal);}
  else{$('instr').value='把红色方块放进左边的托盘';$('goalImg').hidden=true;$('goalEmpty').hidden=false;$('goalBox').classList.add('empty');$('parsed').replaceChildren();}
}
$('modeInstr').onclick=()=>mode('instruction');$('modeGoal').onclick=()=>mode('goal_stack');
function chip(c){const s=document.createElement('span');s.className='cube';const i=document.createElement('i');i.style.background=HEX[c]||'#999';s.append(i,CN[c]||c);return s;}
function showGoal(item,fromEvent){
  if(!fromEvent)S.goal=item;const r=item.recognition||{};
  $('goalImg').src=item.image_url;$('goalImg').hidden=false;$('goalEmpty').hidden=true;$('goalBox').classList.remove('empty');
  const p=$('parsed');p.replaceChildren('板上识别目标：');
  (r.towers||[]).forEach((t,k)=>{if(k)p.append(' / ');t.forEach((c,j)=>{if(j){const a=document.createElement('span');a.className='arrow';a.textContent='→';p.append(a);}p.append(chip(c));});});
  if(r.towers?.length){const a=document.createElement('span');a.className='arrow';a.textContent='（自下而上）';p.append(a);}
  if(r.loose?.length){r.loose.forEach(c=>p.append(chip(c)));p.append(' 留在桌面');}
  if(!fromEvent&&(r.confidence??0)<.8){const w=document.createElement('span');w.className='warn';w.textContent=` · 识别不确定（置信度 ${num(r.confidence,2)}），请确认`;p.append(w);
    const b=document.createElement('button');b.className='btn ghost confirm';b.textContent='确认识别结果';b.onclick=()=>{S.goal.confirmed=true;w.textContent=' · 已人工确认';b.remove();};p.append(b);}
}
async function recognize(body){try{$('notice').textContent='板上识别目标图片…';showGoal(await api('/goals/recognize',body));$('notice').textContent='';}catch(err){$('notice').textContent='识别失败：'+err.message;}}
$('preset').onchange=()=>{if($('preset').value)recognize({preset:$('preset').value});};
$('randomGoal').onclick=()=>{$('scenario').value='';recognize({random_seed:Math.floor(Math.random()*1e6)});};
$('upload').onchange=()=>{const f=$('upload').files[0];if(!f)return;const rd=new FileReader();rd.onload=()=>{$('scenario').value='';recognize({image_b64:String(rd.result).split(',')[1]});};rd.readAsDataURL(f);$('upload').value='';};
$('scenario').onchange=()=>{const s=S.scenarios[$('scenario').value];if(!s)return;if(C.nav){$('instr').value=s.task;return;}$('preset').value=s.goal;recognize({preset:s.goal});};
async function loadGoals(){
  try{const g=await api('/goals');S.scenarios=g.scenarios;
    for(const [k,v]of Object.entries(g.scenarios))$('scenario').add(new Option(`${k} · ${v.title}`,k));
    for(const p of g.presets)$('preset').add(new Option('目标 · '+p.name.replace(/-/g,' '),p.id));
  }catch(err){$('notice').textContent='目标库不可用：'+err.message;}
}
function busy(b){S.busy=b;$('start').disabled=b||!S.ready;$('stop').disabled=!b;$('start').textContent=S.ready?(b?'运行中…':'开始任务'):'等待智能体';}
$('start').onclick=async()=>{
  if(S.replay)leaveReplay();
  const body={task:$('instr').value.trim(),seed:$('seed').value===''?null:Number($('seed').value),kind:S.mode};
  if(C.nav&&$('scenario').value)body.scenario=$('scenario').value;
  if(S.mode==='goal_stack'){if(!S.goal){$('notice').textContent='先选择或上传目标图片';return;}body.goal_id=S.goal.id;body.confirmed=!!S.goal.confirmed;if($('scenario').value)body.scenario=$('scenario').value;}
  try{busy(true);await api('/task',body);$('notice').textContent='任务已提交';}catch(err){busy(false);$('notice').textContent=err.message;}
};
$('stop').onclick=async()=>{try{await api('/stop',{});$('notice').textContent='正在停止：取消当前动作后回到初始位置';}catch(err){$('notice').textContent=err.message;}};
$('theme').onclick=()=>{const r=document.documentElement;const dark=r.dataset.theme?r.dataset.theme==='dark':matchMedia('(prefers-color-scheme: dark)').matches;r.dataset.theme=dark?'light':'dark';board.last&&board(board.last);};

// ---------- replay (design §4.6) ----------
$('replayBtn').onclick=async()=>{
  const list=$('runsList');if(!list.hidden){list.hidden=true;return;}
  try{const rows=(await api('/runs')).filter(r=>r.status&&r.status!=='running');list.replaceChildren();
    if(!rows.length)list.textContent='还没有完成的任务';
    for(const r of rows.slice(0,60)){const b=document.createElement('button');const ok=r.evaluation?.success;
      b.innerHTML='<span class="tm"></span><span class="nm"></span><span class="res"></span>';
      b.querySelector('.tm').textContent=r.run.slice(9,15).replace(/(..)(..)(..)/,'$1:$2:$3');
      b.querySelector('.nm').textContent=(r.kind==='baseline'?'[基线] ':'')+(r.scenario?r.scenario+' · ':'')+(r.task||'')+(r.seed!=null?' · seed '+r.seed:'');
      const res=b.querySelector('.res');res.textContent=ok===true?'通过':ok===false?'未通过':r.status;res.className='res '+(ok===true?'ok':ok===false?'bad':'');
      b.onclick=()=>{list.hidden=true;enterReplay(r.run);};list.append(b);}
    list.hidden=false;
  }catch(err){$('notice').textContent=err.message;}
};
async function enterReplay(run){
  try{const d=await api('/runs/'+run);S.replay=d;S.replayRun=run;
    $('liveBtn').hidden=false;$('online').className='chip replay';$('online').lastChild.textContent='回放中 · '+run.slice(9,15).replace(/(..)(..)(..)/,'$1:$2:$3');
    $('start').disabled=true;$('stop').disabled=true;
    const req=d.request||{};if(req.goal_image){$('goalImg').src=`/runs/${run}/file/goal.jpg`;$('goalImg').hidden=false;$('goalEmpty').hidden=true;$('goalBox').classList.remove('empty');}
    if(req.task)$('instr').value=req.task;
    const nav=$('chapters');nav.replaceChildren();const l=document.createElement('span');l.className='lbl';l.textContent='回放 · 步骤';nav.append(l);
    d.steps.forEach((s,i)=>{const b=document.createElement('button');b.textContent=i+1;b.title=(s.tool||'')+' '+JSON.stringify(s.arguments||{});
      b.className=s.result?.ok===false?'bad':s.result?.ok?'ok':'';b.onclick=()=>seek(i);nav.append(b);});
    nav.hidden=false;seek(Math.max(0,d.steps.length-1));
  }catch(err){$('notice').textContent='回放失败：'+err.message;}
}
function seek(i){
  const d=S.replay,row=d.steps[i];if(!row)return;
  $('chapters').querySelectorAll('button').forEach((b,k)=>b.classList.toggle('on',k===i));
  // Re-run the saved event log up to the end of step i; the four saved images of that step become the views.
  const results=d.events.filter(e=>e.type==='step_result');const cutoff=i+1<d.steps.length?(results[i]?.ts??Infinity):Infinity;
  $('plan').replaceChildren();$('feed').replaceChildren();$('quote').textContent='';
  for(const e of d.events)if(e.ts<=cutoff+.001)handle(e,false);
  const fin=d.status||{};if(fin.seconds!=null&&i===d.steps.length-1)$('sTime').textContent=num(fin.seconds);
  S.images=row.images&&Object.keys(row.images).length?row.images:null;views();
}
function leaveReplay(){S.replay=null;S.images=null;$('liveBtn').hidden=true;$('chapters').hidden=true;$('online').className='chip ok';$('online').lastChild.textContent='主板在线 192.168.50.2';busy(S.busy);views();}
$('liveBtn').onclick=leaveReplay;

// ---------- live connection ----------
function connect(){
  const es=new EventSource('/events');
  es.onopen=()=>{if(!S.replay){$('online').className='chip ok';$('online').lastChild.textContent='主板在线 192.168.50.2';}};
  es.onmessage=m=>{const e=JSON.parse(m.data);if(e.type==='sysmon'){board.last=e;board(e);return;}if(!S.replay)handle(e,true);};
  es.onerror=()=>{if(!S.replay){$('online').className='chip bad';$('online').lastChild.textContent='主板连接中断';}};
}
async function poll(){
  try{const st=await api('/state');S.ready=!!st.worker_ready;if(!S.replay)busy(!!st.busy);
    if(!st.connected)$('notice').textContent='仿真端未连接';}catch{}
  setTimeout(poll,3000);
}
setInterval(()=>{
  if(S.actStart){$('prog').style.width=Math.min(95,(performance.now()-S.actStart)/S.actLen*100)+'%';}
  if(S.started&&!S.finished&&!S.replay)$('sTime').textContent=num(Date.now()/1000-S.started);
},200);
document.addEventListener('click',e=>{if(!$('runsList').hidden&&!e.target.closest('#runsList,#replayBtn'))$('runsList').hidden=true;});
mode('instruction');views();loadGoals();connect();poll();
