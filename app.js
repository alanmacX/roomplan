'use strict';
const $ = sel => document.querySelector(sel);
const clone = value => JSON.parse(JSON.stringify(value));
const range = (v, min, max) => Math.max(min, Math.min(max, v));
const esc = val => String(val).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
const rect = (x,y,w,h) => [[x,y],[x+w,y],[x+w,y+h],[x,y+h]];
const defs = {
  sofa:{name:'沙发',mark:'▰',w:128,h:62,color:'#d3b59b'}, table:{name:'餐桌',mark:'▱',w:100,h:62,color:'#d4bc96'},
  bed:{name:'床',mark:'▤',w:135,h:155,color:'#c6c2b0'}, lamp:{name:'调光灯',mark:'☼',w:37,h:37,color:'#efe3b2', caps:{power:[true,false],level:[1,100]}},
  ac:{name:'空调',mark:'≈',w:71,h:28,color:'#becbd2',caps:{power:[true,false],target:[16,30],mode:['制冷','制热','送风']}},
  switch:{name:'开关灯',mark:'◉',w:36,h:36,color:'#f0dfbb',caps:{power:[true,false]}},
  curtain:{name:'电动窗帘',mark:'▥',w:95,h:22,color:'#a9bcb9',caps:{position:[0,100]}},
  sensor:{name:'人体感应器',mark:'◎',w:30,h:30,color:'#b9ccad',caps:{}}
};
const roomColor=['#f4ece0','#f1ebdb','#e9e7de','#e7ede1','#e8e8e4'];
const labels={sofa:'沙发',table:'桌子',chair:'椅子',bed:'床',storage:'柜子',television:'电视',fireplace:'壁炉',stove:'灶台',refrigerator:'冰箱',sink:'水槽',toilet:'马桶',bathtub:'浴缸',dishwasher:'洗碗机',oven:'烤箱',washerDryer:'洗衣机',livingRoom:'客厅',diningRoom:'餐厅',kitchen:'厨房',bedroom:'卧室',bathroom:'卫生间'};
const cut = (a,b) => ({a,b});
const make = (id,type,x,y,angle=0,other={}) => {
  const def=defs[type]; return {id,type,x,y,angle,w:def?.w??55,h:def?.h??40, name:def?.name??'家具',
    ...(type==='lamp'?{power:false,level:60}:type==='ac'?{power:false,target:25,mode:'制冷'}:type==='switch'?{power:false}:type==='curtain'?{position:0}:{}),...other};
};
const previewBase=() => ({
  key:'apartment',title:'双职工家庭 · 两居室',outline:rect(0,0,810,485),
  rooms:[
    {id:'entry',name:'玄关',p:rect(0,0,174,189),tag:[70,62]},
    {id:'living',name:'客厅',p:rect(174,0,330,485),tag:[323,88]},
    {id:'bed',name:'主卧',p:rect(504,0,306,272),tag:[651,45],sleep:true},
    {id:'bath',name:'卫生间',p:rect(504,272,306,213),tag:[663,323]},
    {id:'room',name:'次卧',p:rect(0,189,174,296),tag:[84,241]}
  ],
  walls:[cut([0,0],[810,0]),cut([810,0],[810,485]),cut([810,485],[0,485]),cut([0,485],[0,136]),cut([0,57],[0,0]),cut([174,0],[174,92]),cut([174,165],[174,207]),cut([174,281],[174,485]),cut([0,189],[174,189]),cut([504,0],[504,155]),cut([504,225],[504,351]),cut([504,424],[504,485]),cut([504,272],[810,272])],
  doors:[cut([0,57],[0,136]),cut([174,92],[174,165]),cut([174,207],[174,281]),cut([504,155],[504,225]),cut([504,351],[504,424])],
  windows:[cut([220,0],[429,0]),cut([574,0],[739,0]),cut([28,485],[129,485])],
  items:[make('entry-lamp','lamp',66,112,0,{name:'玄关灯'}),make('living-lamp','lamp',430,103,0,{name:'客厅灯',power:true}),make('bed-lamp','lamp',748,136,0,{name:'卧室灯',power:true}),make('bath-lamp','lamp',721,397,0,{name:'卫生间灯'}),make('room-lamp','lamp',47,294,0,{name:'次卧灯'}),make('sofa','sofa',370,238,0),make('table','table',330,397),make('bed-f','bed',627,146),make('bed-2','bed',88,405,0,{w:91,h:113}),make('room-ac','ac',385,49,0,{name:'客厅空调'})]
});
function preset(){
  const plan=previewBase(), factor=1.46, scale=([x,y])=>[x*factor,y*factor];
  plan.outline=plan.outline.map(scale);
  for(const r of plan.rooms){r.p=r.p.map(scale);r.tag=scale(r.tag);}
  for(const w of [...plan.walls,...plan.doors,...plan.windows]){w.a=scale(w.a);w.b=scale(w.b);}
  for(const o of plan.items){[o.x,o.y]=scale([o.x,o.y]);}
  plan.items.find(o=>o.id==='sofa').w=175;
  plan.items.find(o=>o.id==='bed-f').h=194;
  return plan;
}
function dot(a,b){return a[0]*b[0]+a[1]*b[1]}
function distance(a,b){return Math.hypot(a[0]-b[0],a[1]-b[1])}
function turn(a,b,c){return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])}
function cross(a,b,c,d){return turn(a,b,c)*turn(a,b,d)<-1e-7 && turn(c,d,a)*turn(c,d,b)<-1e-7}
function onEdge(p,a,b){return Math.abs(turn(a,b,p))<1e-4 && dot([p[0]-a[0],p[1]-a[1]],[p[0]-b[0],p[1]-b[1]])<=1e-5}
function edges(p){return p.map((a,i)=>[a,p[(i+1)%p.length]])}
function inside(q,p){
  if(edges(p).some(([a,b])=>onEdge(q,a,b)))return true;
  let hit=false;
  for(const [[x,y],[u,v]] of edges(p))if((y>q[1])!==(v>q[1]) && q[0] < (u-x)*(q[1]-y)/(v-y)+x)hit=!hit;
  return hit;
}
function corners(o){const a=o.angle*Math.PI/180,c=Math.cos(a),s=Math.sin(a);return rect(-o.w/2,-o.h/2,o.w,o.h).map(([x,y])=>[o.x+x*c-y*s,o.y+x*s+y*c])}
function region(o){return plan.rooms.find(r=>inside([o.x,o.y],r.p))}
function valid(o){
  const p=corners(o), sides=edges(p);
  if(plan.key==='house'&&p.some(q=>!plan.rooms.some(r=>inside(q,r.p))))return false;
  if(p.some(q=>!inside(q,plan.outline))||sides.some(([a,b])=>edges(plan.outline).some(([c,d])=>cross(a,b,c,d))))return false;
  return !plan.walls.some(({a,b})=>{
    const len=distance(a,b); if(len<.1)return false;
    const n=[3*(b[1]-a[1])/len,3*(a[0]-b[0])/len];
    const strip=[[a[0]+n[0],a[1]+n[1]],[b[0]+n[0],b[1]+n[1]],[b[0]-n[0],b[1]-n[1]],[a[0]-n[0],a[1]-n[1]]];
    return strip.some(q=>inside(q,p))||p.some(q=>inside(q,strip))||sides.some(([i,j])=>edges(strip).some(([k,l])=>cross(i,j,k,l)));
  });
}
function decodeRoom(raw,key){
  const checkT=o=>Array.isArray(o?.transform)&&o.transform.length===16&&o.transform.every(Number.isFinite);
  const floors=raw?.floors?.filter(o=>checkT(o)&&Array.isArray(o.polygonCorners)&&o.polygonCorners.length>=3&&o.polygonCorners.every(v=>Array.isArray(v)&&v.length>=2&&v.every(Number.isFinite)));
  if(floors?.length!==1||!Array.isArray(raw.walls)||raw.walls.length<3)throw new Error('需要一个包含地面轮廓和墙体的单房间 RoomPlan JSON。');
  const t=(o,x=0,y=0,z=0)=>[o.transform[12]+x*o.transform[0]+y*o.transform[4]+z*o.transform[8],o.transform[14]+x*o.transform[2]+y*o.transform[6]+z*o.transform[10]];
  const floor=floors[0], a=Math.atan2(floor.transform[2],floor.transform[0]), c=Math.cos(a),s=Math.sin(a);
  const rot=([x,z])=>[(x*c+z*s)*100,(-x*s+z*c)*100];
  const rawOutline=floor.polygonCorners.map(v=>rot(t(floor,v[0],v[1],v[2]??0)));
  const ox=Math.min(...rawOutline.map(p=>p[0])),oy=Math.min(...rawOutline.map(p=>p[1]));
  const project=q=>{const [x,y]=rot(q);return [x-ox,y-oy]};
  const outline=rawOutline.map(([x,y])=>[x-ox,y-oy]);
  const asLine=o=> {
    if(!checkT(o)||!Number.isFinite(o.dimensions?.[0])||o.dimensions[0]<=0)return null;
    const half=o.dimensions[0]/2;
    return {...cut(project(t(o,-half)),project(t(o,half))),id:o.identifier,parent:o.parentIdentifier};
  };
  const lines=list=>Array.isArray(list)?list.map(asLine).filter(Boolean):[];
  const doorLines=[...lines(raw.doors),...lines(raw.openings)], windowLines=lines(raw.windows);
  const walls=lines(raw.walls).flatMap(w=>{
    const dx=w.b[0]-w.a[0],dy=w.b[1]-w.a[1],len=Math.hypot(dx,dy);
    if(len<.1)return [];
    const frac=p=>((p[0]-w.a[0])*dx+(p[1]-w.a[1])*dy)/(len*len);
    const cuts=doorLines.filter(o=>o.parent&&o.parent===w.id)
      .map(o=>[range(Math.min(frac(o.a),frac(o.b)),0,1),range(Math.max(frac(o.a),frac(o.b)),0,1)]).sort((a,b)=>a[0]-b[0]);
    const pos=q=>[w.a[0]+dx*q,w.a[1]+dy*q];
    let last=0,result=[];
    for(const [start,end] of cuts){if(start>last)result.push(cut(pos(last),pos(start)));last=Math.max(last,end)}
    if(last<1)result.push(cut(pos(last),pos(1)));
    return result;
  });
  const area=Math.abs(edges(outline).reduce((sum,[[x,y],[u,v]])=>sum+x*v-u*y,0)/2);
  if(walls.length<1||area<400)throw new Error('扫描数据缺少可用的地面或墙线。');
  const name=labels[raw.sections?.[0]?.label]||'扫描房间';
  const items=(Array.isArray(raw.objects)?raw.objects:[]).filter(o=>checkT(o)&&[o.dimensions?.[0],o.dimensions?.[2]].every(v=>Number.isFinite(v)&&v>0)).slice(0,250).map((o,i)=>{
    const [x,y]=project(t(o)), [u,v]=project(t(o,1)),kind=Object.keys(o.category||{})[0]||'';
    return make('scan-'+i,({sofa:'sofa',bed:'bed',table:'table'})[kind]||'scanned',x,y,Math.atan2(v-y,u-x)*180/Math.PI,{name:labels[kind]||kind||'家具',w:o.dimensions[0]*100,h:o.dimensions[2]*100});
  });
  const maxX=Math.max(...outline.map(o=>o[0])),maxY=Math.max(...outline.map(o=>o[1]));
  return {key,title:key==='apple'?'Apple 样例 · '+name:name,outline,rooms:[{id:'scan-room',name,p:outline,tag:[maxX/2,34]}],walls,doors:doorLines,windows:windowLines,items};
}
const scanProjection=window.ROOMPLAN_PROJECTED;
const livingPlan=()=>{const p=decodeRoom(window.appleLivingRoom,'apple');p.title='客厅平面图';return p;};
let plan=livingPlan(), active=plan.items[0]?.id, scene='normal', occupied={}, place=null, drag=null, dirty=false, stats=[], outcome='ok', messageTimer;
const waiting=new Set(), results=new Map(), offTimers=new Map(), holds=new Map(), holdTimers=new Map();
const STORAGE='smart-home-floorplan-v1', OFF_DELAY=5000, HOLD_DELAY=15000;
try {
  const old=JSON.parse(localStorage.getItem(STORAGE)||'null');
  if(old?.plan?.key===new URLSearchParams(location.search).get('plan') && old.plan.outline?.length && old.plan.items?.length>=0){plan=old.plan;active=plan.items.find(o=>o.id===old.active)?.id??plan.items[0]?.id;}
}catch{}
const drawing=$('#plan'), api=window.homeAPI;
let backend=false, snapshot=null, pending=0, drawKind=null, drawStart=null, drawMouse=null;
let undoGeometry=null, historyId=null, switchGeneration=0;
const blank=()=>({key:'custom',title:'自建户型',outline:rect(0,0,800,520),rooms:[],items:[],walls:[],doors:[],windows:[]});
const editKeys=['outline','rooms','walls','doors','windows'];
function reportErr(error){flash(error.message||'操作没有完成。',true)}
function reflectFresh(next,force=false){
  if(next.plan.key!==plan.key)return;
  if(!force&&snapshot?.seq>=next.seq)return;
  if(force||!dirty){
    plan=next.plan;
    if(!plan.items.some(o=>o.id===active))active=plan.items[0]?.id??null;
    dirty=false;
    snapshot=next;
  }else{
    const byId=new Map(next.plan.items.map(o=>[o.id,o]));
    for(const o of plan.items){
      const live=byId.get(o.id);
      for(const key of Object.keys(defs[o.type]?.caps??{})){
        if(live&&Object.hasOwn(live,key))o[key]=live[key];
      }
    }
    // Keep the geometry revision used when the user began editing.
    snapshot={...next,rev:snapshot?.rev??next.rev};
  }
  scene=next.mode;occupied=next.occupied;stats=next.events.map(v=>({time:v.time,text:v.message}));
  const form=$('#climateForm');
  if(!form.contains(document.activeElement)){
    for(const k of ['season','indoor','outdoor'])form.elements[k].value=next.climate[k];
    form.elements.delay.value=next.delay;
  }
  render();
}
async function saveToServer(){
  if(!dirty)return;
  const current=plan, rev=snapshot?.rev;
  if(!rev)throw new Error('户型尚未加载完成。');
  const next=await api.save(current.key,current,rev);
  if(plan.key===current.key)reflectFresh(next,true);
}
async function withServer(action){
  pending++;
  try{return await action()}catch(err){reportErr(err)}finally{pending--}
}
async function openPlan(key){
  if(!backend){
    load(key==='apple'?livingPlan():key==='house'?clone(scanProjection.house):key==='custom'?blank():preset());
    return;
  }
  if(dirty){flash('先保存当前户型，再切换。',true);return;}
  const gen=++switchGeneration;
  const next=await api.get(key);
  if(gen!==switchGeneration)return;
  load(next.plan);snapshot=null;dirty=false;reflectFresh(next,true);
  const currentUrl=new URL(location.href);currentUrl.searchParams.set('plan',key);window.history.replaceState(null,'',currentUrl);historyId=null;$('#deviceHistory').hidden=true;
}
async function poll(){
  if(!backend||pending||drag||drawKind||waiting.size||document.hidden||$('#inspect').contains(document.activeElement)&&['INPUT','SELECT'].includes(document.activeElement.tagName))return;
  const key=plan.key;
  try{
    const v=await api.get(key);
    if(!pending&&!drag&&plan.key===key)reflectFresh(v);
  }catch{ $('#connection').textContent='暂时不能同步'; }
}
function setDrawing(kind){
  drawKind=kind;drawStart=null;drawMouse=null;
  if(kind)setPlace(null);
  drawing.classList.toggle('drawing',!!kind);
  $('#drawRoom').setAttribute('aria-pressed',String(kind==='room'));
  $('#drawWall').setAttribute('aria-pressed',String(kind==='wall'));
  renderPlan();
}
const snap=p=>[Math.round(p.x/10)*10,Math.round(p.y/10)*10];
function drawAt(q){
  const b=snap(q);
  if(!inside(b,plan.outline)){flash('请在户型边界内选点。',true);return}
  if(!drawStart){
    drawStart=b;drawMouse=b;
    flash(drawKind==='room'?'再点房间对角。':'再点墙线终点。');renderPlan();return;
  }
  if(distance(drawStart,b)<30){flash('两点太近。',true);return}
  const old=Object.fromEntries(editKeys.map(k=>[k,clone(plan[k])]));
  if(drawKind==='wall'){
    plan.walls.push(cut(drawStart,b));
    if(plan.items.some(o=>!o.mount&&region(o)&&!valid(o))){plan.walls=old.walls;flash('墙线与物品相交。',true);return;}
  }else{
    const x=Math.min(drawStart[0],b[0]),y=Math.min(drawStart[1],b[1]),w=Math.abs(drawStart[0]-b[0]),h=Math.abs(drawStart[1]-b[1]);
    if(w<120||h<100){flash('房间至少 1.2 × 1 米。',true);return;}
    const polygon=rect(x,y,w,h);
    if(polygon.some(v=>!inside(v,plan.outline))||edges(polygon).some(([a,b])=>edges(plan.outline).some(([c,d])=>cross(a,b,c,d)))){
      flash('房间不能越过户型边界。',true);return;
    }
    const name=$('#roomName').value.trim()||'房间 '+(plan.rooms.length+1);
    const id='room-'+Date.now().toString(36);
    plan.rooms.push({id,name,p:polygon,tag:[x+w/2,y+26],sleep:$('#quietRoom').checked});
    const doorL=x+Math.round((w-70)/2),doorR=doorL+70;
    plan.walls.push(cut([x,y],[x+w,y]),cut([x+w,y],[x+w,y+h]),cut([x,y+h],[x,y]),cut([x,y+h],[doorL,y+h]),cut([doorR,y+h],[x+w,y+h]));
    plan.doors.push(cut([doorL,y+h],[doorR,y+h]));
  }
  undoGeometry=old;$('#undoDrawing').disabled=false;changed();setDrawing(null);render();
}
async function showDeviceHistory(id){
  const output=$('#deviceHistory');
  if(historyId===id&&!output.hidden){output.hidden=true;historyId=null;return}
  if(!backend){flash('启动本地服务后可查看状态历史。');return}
  const key=plan.key;historyId=id;output.hidden=false;output.textContent='正在读取历史…';
  try{
    const data=await api.history(key,id);
    if(historyId!==id||key!==plan.key||active!==id)return;
    const timeline=data.events.filter(r=>r.state).slice(0,20).reverse();
    const samples=timeline.map(v=>v.state.level??v.state.position??v.state.target??(v.state.power?100:0));
    const graph=samples.length>1?`<svg viewBox="0 0 200 45" role="img" aria-label="设备状态历史曲线"><polyline fill="none" stroke="#355b43" stroke-width="2" points="${samples.map((v,i)=>`${3+194*i/(samples.length-1)},${40-v*.35}`).join(' ')}"/></svg>`:'';
    output.innerHTML=`<strong>状态历史</strong>${graph}${data.events.length?'<ol>'+data.events.slice(0,8).map(e=>`<li>${esc(e.time)} ${esc(e.message)}</li>`).join('')+'</ol>':'<p>还没有设备记录。</p>'}`;
  }catch(err){output.textContent=err.message;}
}

const log=msg=>{stats.unshift({text:msg,time:new Date().toTimeString().slice(0,8)});stats=stats.slice(0,6);renderLog()};
function flash(msg,bad=false){
  const node=$('#notice');node.textContent=msg;node.classList.toggle('bad',bad);node.hidden=false;
  clearTimeout(messageTimer);messageTimer=setTimeout(()=>{node.hidden=true},2400);
}
function changed(){dirty=true;$('#saveState').textContent='布局有未保存的修改'}
function setPlace(type){place=type;renderLists();drawing.classList.toggle('placing',!!type);}
function load(next){
  for(const timer of [...offTimers.values(),...holdTimers.values()])clearTimeout(timer);
  offTimers.clear();holdTimers.clear();holds.clear();waiting.clear();results.clear();
  scene='normal';occupied={};drag=null;plan=next;active=plan.items.find(o=>defs[o.type]?.caps)?.id??plan.items[0]?.id;stats=[];
  undoGeometry=null;$('#undoDrawing').disabled=true;setDrawing(null);setPlace(null);changed();log('已加载 '+next.title);render();
}
function point(ev){const p=drawing.createSVGPoint();p.x=ev.clientX;p.y=ev.clientY;return p.matrixTransform(drawing.getScreenCTM().inverse())}
function pts(p){return p.map(q=>q.join(',')).join(' ')}
function svgLine(w,styles){return `<line x1="${w.a[0]}" y1="${w.a[1]}" x2="${w.b[0]}" y2="${w.b[1]}" ${styles}/>`}
function renderPlan(){
  const coords=plan.outline,minX=Math.min(...coords.map(p=>p[0])),minY=Math.min(...coords.map(p=>p[1])),maxX=Math.max(...coords.map(p=>p[0])),maxY=Math.max(...coords.map(p=>p[1]));
  const home=plan.key==='house', scanned=home||plan.key==='apple';
  const pad=home?38:43;drawing.setAttribute('viewBox',`${minX-pad} ${minY-pad} ${maxX-minX+2*pad} ${maxY-minY+2*pad}`);
  const outside=scanned?'':`<polygon points="${pts(coords)}" fill="#fafbf9" stroke="#a4b3ac" stroke-width="1" stroke-dasharray="5 5" vector-effect="non-scaling-stroke"/>`;
  const isActive=r=>occupied[r.id];
  const rooms=plan.rooms.map(r=>`<polygon points="${pts(r.p)}" fill="${isActive(r)?'#e9f3ed':'#fffffd'}" stroke="#d0d7d1" stroke-width="1" vector-effect="non-scaling-stroke"/>`).join('');
  const roomText=plan.rooms.map(r=>scanned&&!home?'':`<text class="room-label" x="${r.tag[0]}" y="${r.tag[1]-(home?34:0)}" text-anchor="middle" fill="#314841" paint-order="stroke" stroke="#fcfdfb" stroke-width="4" font-size="${home?28:15}" font-weight="600">${esc(r.name)}${occupied[r.id]?' · 有人':''}</text>`).join('');
  const walls=plan.walls.map(w=>svgLine(w,'stroke="#344741" stroke-width="5" vector-effect="non-scaling-stroke" stroke-linecap="butt"')).join('');
  const doors=plan.doors.map(w=>svgLine(w,'stroke="#819991" stroke-width="1.5" stroke-dasharray="4 3" vector-effect="non-scaling-stroke"')).join('');
  const win=plan.windows.map(w=>svgLine(w,'stroke="#83aeb5" stroke-width="2" vector-effect="non-scaling-stroke"')).join('');
  const footprints=scanProjection?.footprints?.[plan.key]||{};
  const materials={sofa:'#dce8ec',storage:'#e5e9df',table:'#ece6db',fireplace:'#ede3de',television:'#dce1e4',bed:'#e7eeec',oven:'#e4e1e7'};
  const drawItem=original=>{
    const o=drag?.id===original.id?{...original,...drag.preview}:original, def=defs[o.type];
    const lamp=['lamp','switch'].includes(o.type), label=o.name, selected=active===o.id;
    const projected=footprints[o.id];
    const shared='class="objectshape" vector-effect="non-scaling-stroke"';
    let shape='';
    if(lamp){
      const r=home?16:9;
      shape=`<circle ${shared} r="${r}" fill="${o.power?'#f7d98b':'#fdfefe'}" stroke="${o.power?'#91692d':'#47685e'}" stroke-width="1.25"/><path d="M-${r*.36},0h${r*.72}M0,-${r*.36}v${r*.72}" stroke="#48675d" stroke-width="1" vector-effect="non-scaling-stroke" pointer-events="none"/>`;
    }else if(projected){
      const tone=materials[projected.kind]||'#e8eeea';
      shape=`<polygon ${shared} points="${pts(projected.p)}" fill="${tone}" stroke="#8b9b93" stroke-width="1"/>`;
    }else{
      const tone=materials[o.type]||'#e8eeea';
      shape=`<rect ${shared} x="${-o.w/2}" y="${-o.h/2}" width="${o.w}" height="${o.h}" rx="2" fill="${tone}" stroke="#83968d" stroke-width="1"/>`;
    }
    return `<g class="object ${o.mount?'mounted':''} ${selected?'selected':''} ${drag?.id===o.id&&!drag.ok?'invalid':''}" data-object="${esc(o.id)}" role="button" aria-label="${esc(label)}" tabindex="0" transform="translate(${o.x} ${o.y}) rotate(${o.angle})"><title>${esc(label)}</title>${shape}</g>`;
  };
  const furniture=plan.items.filter(o=>!defs[o.type]?.caps).map(drawItem).join('');
  const devices=plan.items.filter(o=>!!defs[o.type]?.caps).map(drawItem).join('');
  const clip=scanned?`<defs><clipPath id="scan-interior">${plan.rooms.map(r=>`<polygon points="${pts(r.p)}"/>`).join('')}</clipPath></defs>`:'';
  const items=clip+(scanned?`<g clip-path="url(#scan-interior)">${furniture}</g>`:furniture)+devices;
  const d=home?{x:minX,y:maxY+22,f:21}:{x:minX,y:maxY+20,f:12};
  const scaleMark=`<g aria-hidden="true" stroke="#526a62" fill="#526a62"><path d="M${d.x},${d.y}v-5m0,5h100m0,0v-5" fill="none" vector-effect="non-scaling-stroke" stroke-width="1"/><text x="${d.x+110}" y="${d.y}" stroke="none" font-size="${d.f}">1 m</text></g>`;
  let rubber='';
  if(drawStart&&drawMouse){
    const [x,y]=drawStart,[u,v]=drawMouse;
    rubber=drawKind==='wall'?svgLine({a:drawStart,b:drawMouse},'stroke="#2d705c" stroke-width="3" stroke-dasharray="7 4"'):`<polygon fill="#6da18b35" stroke="#2d705c" stroke-width="2" points="${pts(rect(Math.min(x,u),Math.min(y,v),Math.abs(u-x),Math.abs(v-y)))}"/>`;
  }
  drawing.innerHTML=outside+rooms+items+walls+doors+win+roomText+scaleMark+rubber;
  $('#scale').textContent=`${((maxX-minX)/100).toFixed(2)} m × ${((maxY-minY)/100).toFixed(2)} m`;
}
function renderLists(){
  $('#catalog').innerHTML=Object.entries(defs).map(([k,d])=>`<button aria-pressed="${place===k}" class="${place===k?'on':''}" draggable="true" data-type="${k}"><b>${d.mark}</b>${d.name}</button>`).join('');
  $('#cancelPlace').classList.toggle('hidden',!place);
  $('#rooms').innerHTML=plan.rooms.map(r=>`<button data-room="${r.id}">${esc(r.name)}<small>${plan.items.filter(o=>region(o)?.id===r.id).length} 件</small></button>`).join('');
  document.querySelectorAll('[data-load]').forEach(b=>b.classList.toggle('active',b.dataset.load===plan.key));
}
function scannedFilter(){return ['apple','house'].includes(plan.key)}
function renderInspect(){
  const o=plan.items.find(o=>o.id===active),devices=plan.items.filter(v=>{
    const query=$('#itemSearch').value.trim().toLowerCase(),type=$('#itemType').value;
    return (!type||v.type===type)&&(!query||v.name.toLowerCase().includes(query))&&(!scannedFilter()||!!defs[v.type]?.caps||!!query||!!type);
  });
  let tabs=devices.map(v=>`<button data-select="${esc(v.id)}" class="${v.id===active?'on':''}">${esc(v.name)}</button>`).join('');
  const pick=`<div class="device-tabs">${tabs}</div>`;
  if(!o){$('#inspect').innerHTML=pick+'<p class="hint">选择图上的家具或设备。</p>';return}
  const caps=defs[o.type]?.caps, hasCommands=caps&&Object.keys(caps).length>0, busy=waiting.has(o.id), result=results.get(o.id);
  const chip=hasCommands&&o.type!=='curtain'?`<span class="state">${busy?'等待回执':o.power?'已开启':'已关闭'}</span>`:'';
  const dim=o.type==='lamp'?`<label class="ins-row"><span>亮度</span><input type="range" id="level" min="1" max="100" value="${o.level}" ${busy?'disabled':''} aria-label="亮度"><output id="levelValue">${o.level}%</output></label>`:'';
  const cover=o.type==='curtain'?`<label class="ins-row"><span>开合</span><input id="curtainPosition" aria-label="窗帘开合" type="range" min="0" max="100" value="${o.position}" ${busy?'disabled':''}><output id="curtainValue">${o.position}%</output></label>`:'';
  const ac=o.type==='ac'?`<div class="ins-row"><label>模式 <select id="airMode" ${busy?'disabled':''}>${caps.mode.map(x=>`<option ${x===o.mode?'selected':''}>${x}</option>`).join('')}</select></label><label>目标 <input id="target" type="number" min="16" max="30" value="${o.target}" ${busy?'disabled':''} style="width:48px">°C</label></div>`:'';
  $('#inspect').innerHTML=pick+`<div class="object-title">${esc(o.name)}${chip}</div><div class="meta">${esc(region(o)?.name||'室内')} · ${(o.w/100).toFixed(2)} × ${(o.h/100).toFixed(2)} m</div>
    <label class="item-filter">物品名称<input id="itemName" value="${esc(o.name)}" maxlength="70"></label>
    <div class="control-buttons">${hasCommands&&o.type!=='curtain'?`<button id="power" ${busy?'disabled':''}>${o.power?'关':'开'}${o.type==='ac'?'空调':'灯'}</button>`:''}${o.mount?'':`<button id="rotate">旋转 15°</button>`}<button id="remove" class="danger">移除</button>${hasCommands?`<button id="history">历史</button>`:''}</div>${dim}${ac}${cover}
    ${hasCommands?`<label class="ins-row"><span>回执模拟</span><select id="outcome"><option value="ok">正常</option><option value="offline">设备离线</option><option value="fail">执行失败</option><option value="timeout">响应超时</option></select></label>`:''}
    ${result?`<p class="result ${result.bad?'bad':''}" role="status">${esc(result.text)}</p>`:''}`;
  if($('#outcome'))$('#outcome').value=outcome;
}
function renderSensors(){
  $('#sensors').innerHTML=plan.rooms.map(r=>`<div class="sensor-row"><span>${esc(r.name)}</span>${r.sleep&&scene==='sleep'?'<small>感应暂停</small>':(backend?snapshot?.overrides?.[r.id]:holds.has(r.id))?'<small>手动优先</small>':(backend?snapshot?.due?.[r.id]:offTimers.has(r.id))?`<small>${backend?snapshot.delay:5} 秒后关灯</small>`:''}<button data-sensor="${r.id}" aria-pressed="${!!occupied[r.id]}" class="${occupied[r.id]?'on':''}">${occupied[r.id]?'有人':'无人'}</button></div>`).join('');
  $('#scenarioHelp').textContent=scene==='sleep'?`公共区域有人亮灯，无人 ${backend?snapshot?.delay??5:5} 秒后关灯。`:'打开睡眠场景，再切换公共区域的有人／无人。';
}
function renderLog(){ $('#activity').innerHTML=stats.length?stats.map(o=>`<li><time>${o.time}</time>${esc(o.text)}</li>`).join(''):'<li>暂无操作</li>'; }
function render(){
  $('#sourceName').textContent=({apartment:'旧版教学样例',apple:'扫描模型正投影',house:'扫描模型正投影',custom:'我的户型',upload:'导入的 RoomPlan 扫描'})[plan.key]||'户型';
  $('#planTitle').textContent=plan.key==='apple'?'客厅平面图':plan.title;
  $('#stats').textContent=`${plan.rooms.length} 个区域 · ${plan.items.length} 件物品`;
  $('#saveState').textContent=dirty?'布局有未保存的修改':backend?'布局已存入 SQLite':'布局保存在当前浏览器';
  document.querySelectorAll('[data-mode]').forEach(b=>{b.classList.toggle('on',scene===b.dataset.mode);b.setAttribute('aria-pressed',scene===b.dataset.mode)});
  renderLists();renderPlan();renderInspect();renderSensors();renderLog();
}
function cmd(o,key,value,kind='manual'){
  if(backend){
    if(waiting.has(o.id))return;
    waiting.add(o.id);renderInspect();
    withServer(async()=>{
      try{
        await saveToServer();
        const v=await api.command(plan.key,o.id,key,value,outcome);
        const msg={ok:'收到设备回执：执行成功。',offline:'设备离线，命令未执行。',fail:'设备执行失败，状态未变。',timeout:'响应超时，保留最后确认状态。'}[v.result];
        results.set(o.id,{text:msg,bad:v.result!=='ok'});waiting.delete(o.id);
        reflectFresh(v.snapshot);
      }finally{waiting.delete(o.id);renderInspect();}
    });
    return;
  }
  const caps=defs[o.type]?.caps, allowed=caps?.[key];
  if(!allowed||(typeof allowed[0]==='number' ? !Number.isFinite(value)||value<allowed[0]||value>allowed[1] : !allowed.includes(value))){
    results.set(o.id,{text:'这个设备不支持该操作或数值超范围。',bad:true});renderInspect();return;
  }
  if(waiting.has(o.id))return;
  const failure=kind==='manual'?outcome:'ok';
  const room=region(o), origin=plan;
  if(failure==='offline'){results.set(o.id,{text:'设备离线，命令未发送。',bad:true});log(o.name+' · 离线');renderInspect();return}
  waiting.add(o.id);results.delete(o.id);renderInspect();
  setTimeout(()=>{
    if(plan!==origin)return;
    waiting.delete(o.id);
    if(!plan.items.includes(o))return;
    if(failure==='ok'){
      o[key]=value;changed();
      results.set(o.id,{text:'收到设备回执：执行成功。',bad:false});
      if(kind==='manual'&&scene==='sleep'&&room&&!room.sleep&&o.type==='lamp') hold(room.id);
      log(o.name+' · '+(key==='power'?(value?'已打开':'已关闭'):key==='level'?('亮度 '+value+'%'):key==='target'?(value+'°C'):value));
    }else{
      const msg=failure==='timeout'?'响应超时，保留最后确认状态。':'设备执行失败，状态未变。';
      results.set(o.id,{text:msg,bad:true});log(o.name+' · '+msg);
    }
    renderPlan();renderInspect();renderSensors();
  },failure==='timeout'?1300:285);
}
function stopOff(id){clearTimeout(offTimers.get(id));offTimers.delete(id)}
function hold(id){
  stopOff(id);clearTimeout(holdTimers.get(id));holds.set(id,true);
  holdTimers.set(id,setTimeout(()=>{holds.delete(id);holdTimers.delete(id);auto(id);renderSensors()},HOLD_DELAY));
}
function auto(id){
  stopOff(id);
  if(scene!=='sleep'||holds.has(id)||plan.rooms.find(r=>r.id===id)?.sleep)return;
  const lamps=()=>plan.items.filter(o=>o.type==='lamp'&&region(o)?.id===id);
  if(occupied[id])lamps().filter(o=>!o.power).forEach(o=>cmd(o,'power',true,'scene'));
  else if(lamps().some(o=>o.power))offTimers.set(id,setTimeout(()=>{
    offTimers.delete(id);
    if(scene==='sleep'&&!occupied[id]&&!holds.has(id))lamps().filter(o=>o.power).forEach(o=>cmd(o,'power',false,'scene'));
    renderSensors();
  },OFF_DELAY));
}
function setMode(next){
  if(backend){
    withServer(async()=>{await saveToServer();reflectFresh(await api.scene(plan.key,scene===next?'normal':next));});
    return;
  }
  scene=scene===next?'normal':next;
  for(const id of offTimers.keys())stopOff(id);
  for(const timer of holdTimers.values())clearTimeout(timer);
  holds.clear();holdTimers.clear();
  const lamps=plan.items.filter(o=>o.type==='lamp');
  if(scene==='sleep'){
    lamps.filter(o=>region(o)?.sleep&&o.power).forEach(o=>cmd(o,'power',false,'scene'));
    plan.rooms.forEach(r=>auto(r.id));
  }else if(scene==='away')plan.items.filter(o=>['lamp','ac'].includes(o.type)&&o.power).forEach(o=>cmd(o,'power',false,'scene'));
  else if(scene==='home'){
    const first=lamps.find(o=>region(o)?.id==='entry')||lamps[0];if(first&&!first.power)cmd(first,'power',true,'scene');
  }
  log(({away:'离家',home:'回家',sleep:'睡眠'})[scene]?('已切换到'+({away:'离家',home:'回家',sleep:'睡眠'})[scene]+'场景'):'已退出场景');
  render();
}
function select(id){if(plan.items.some(o=>o.id===id)){if(id!==active){historyId=null;$('#deviceHistory').hidden=true;}active=id;renderPlan();renderInspect()}}
function add(type,x,y){
  if(!defs[type])return;setDrawing(null);
  const id=globalThis.crypto?.randomUUID?.()??('item-'+Date.now()+'-'+Math.random());
  let o=make(id,type,x,y);
  if(!valid(o)){flash('这里放不下：物品不能越出边界或穿墙。',true);return}
  const r=region(o);
  if(type==='lamp'&&r)o.name=r.name+'灯';
  plan.items.push(o);active=id;setPlace(null);changed();log('已摆放 '+o.name);render();
}
$('#modes').addEventListener('click',e=>{const b=e.target.closest('[data-mode]');if(b)setMode(b.dataset.mode)});
$('#sources').addEventListener('click',e=>{
  const b=e.target.closest('[data-load]');if(!b)return;
  withServer(()=>openPlan(b.dataset.load));
});
$('#importFile').addEventListener('change',async e=>{
  const file=e.target.files[0];if(!file)return;
  try{
    if(file.size>20*1024*1024)throw new Error('请选择 20 MB 以内的单房间 JSON。');
    let raw;
    try{raw=JSON.parse(await file.text())}catch{throw new Error('文件不是有效的 JSON。')}
    const imported=raw?.outline?readPlan(raw):decodeRoom(raw,backend?'custom':'upload');
    if(backend){
      if(dirty)throw new Error('请先保存当前布局，再导入。');
      const target=await api.get('custom');
      imported.key='custom';
      const next=await api.save('custom',imported,target.rev,true);
      load(next.plan);snapshot=null;dirty=false;reflectFresh(next,true);
    }else{load(imported);}
    flash('已导入可编辑户型。');
  }catch(err){flash(err.message,true)}
  e.target.value='';
});
$('#catalog').addEventListener('click',e=>{const b=e.target.closest('[data-type]');if(b){setDrawing(null);setPlace(place===b.dataset.type?null:b.dataset.type)}});
$('#catalog').addEventListener('dragstart',e=>{const b=e.target.closest('[data-type]');if(b)e.dataTransfer.setData('text/plain',b.dataset.type)});
$('#rooms').addEventListener('click',e=>{const id=e.target.closest('[data-room]')?.dataset.room;if(id){const o=plan.items.find(o=>region(o)?.id===id);if(o)select(o.id)}});
$('#cancelPlace').addEventListener('click',()=>setPlace(null));
document.addEventListener('keydown',e=>{if(e.key==='Escape'){setDrawing(null);setPlace(null)}});
$('#save').addEventListener('click',()=>{
  if(backend){withServer(async()=>{await saveToServer();flash('布局已保存。');});return;}
  try{localStorage.setItem(STORAGE,JSON.stringify({plan,active}));dirty=false;log('已保存布局');render();flash('布局已保存。')}
  catch{flash('当前浏览器没能保存布局。',true)}
});
$('#inspect').addEventListener('click',e=>{
  const b=e.target.closest('button');if(!b)return;
  if(b.dataset.select){select(b.dataset.select);return}
  const o=plan.items.find(o=>o.id===active);if(!o)return;
  if(b.id==='power')cmd(o,'power',!o.power);
  if(b.id==='history')showDeviceHistory(o.id);
  if(b.id==='rotate'){
    const p={...o,angle:(o.angle+15)%360};
    if(valid(p)){o.angle=p.angle;changed();renderPlan()}
    else flash('旋转后会越界或穿墙。',true);
  }
  if(b.id==='remove'){
    if(backend&&o.mount){withServer(async()=>{await saveToServer();reflectFresh(await api.remove(plan.key,o.id),true)});return;}
    plan.items=plan.items.filter(p=>p!==o);active=null;changed();log('已移除 '+o.name);render();
  }
});
$('#inspect').addEventListener('input',e=>{if(e.target.id==='level')$('#levelValue').textContent=e.target.value+'%';if(e.target.id==='curtainPosition')$('#curtainValue').textContent=e.target.value+'%'});
$('#inspect').addEventListener('change',e=>{
  if(e.target.id==='outcome'){outcome=e.target.value;return}
  const o=plan.items.find(o=>o.id===active);if(!o)return;
  if(e.target.id==='level')cmd(o,'level',Number(e.target.value));
  if(e.target.id==='curtainPosition')cmd(o,'position',Number(e.target.value));
  if(e.target.id==='itemName'){const name=e.target.value.trim();if(name.length){o.name=name;changed();render()}else{e.target.value=o.name;flash('请输入名称。',true)}}
  if(e.target.id==='target')cmd(o,'target',Number(e.target.value));
  if(e.target.id==='airMode')cmd(o,'mode',e.target.value);
});
$('#sensors').addEventListener('click',e=>{
  const id=e.target.closest('[data-sensor]')?.dataset.sensor;
  if(!id)return;
  if(backend){withServer(async()=>{await saveToServer();reflectFresh(await api.environment(plan.key,{room:id,occupied:!occupied[id]}))});return;}
  occupied[id]=!occupied[id];const r=plan.rooms.find(r=>r.id===id);
  log(r.name+' · '+(occupied[id]?'有人':'无人'));auto(id);renderPlan();renderSensors();
});
drawing.addEventListener('pointerdown',e=>{
  if(e.button!==0)return;
  const q=point(e), id=e.target.closest('[data-object]')?.dataset.object;
  if(drawKind){drawAt(q);return}
  if(place){add(place,q.x,q.y);return}
  const o=plan.items.find(o=>o.id===id);if(!o)return;
  if(id!==active){historyId=null;$('#deviceHistory').hidden=true;}
  if(o.mount){select(id);return;}
  active=id;drag={id,offset:[q.x-o.x,q.y-o.y],preview:{x:o.x,y:o.y},pointer:e.pointerId,ok:true,initial:[o.x,o.y]};
  drawing.setPointerCapture(e.pointerId);renderPlan();renderInspect();
});
drawing.addEventListener('pointermove',e=>{
  if(drawKind&&drawStart){drawMouse=snap(point(e));renderPlan();return;}
  if(drag?.pointer!==e.pointerId)return;
  const q=point(e), o=plan.items.find(o=>o.id===drag.id);
  drag.preview={x:q.x-drag.offset[0],y:q.y-drag.offset[1]};drag.ok=valid({...o,...drag.preview});renderPlan();
});
drawing.addEventListener('pointerup',e=>{
  if(drag?.pointer!==e.pointerId)return;
  const o=plan.items.find(o=>o.id===drag.id), moved=distance(drag.initial,[drag.preview.x,drag.preview.y])>1;
  if(moved&&drag.ok){Object.assign(o,drag.preview);changed()}else if(moved)flash('已放回原位：物品不能越出边界或穿墙。',true);
  drag=null;render();
});
drawing.addEventListener('pointercancel',()=>{drag=null;renderPlan()});
drawing.addEventListener('keydown',e=>{const id=e.target.closest('[data-object]')?.dataset.object;if(id&&['Enter',' '].includes(e.key)){e.preventDefault();active=id;renderInspect();drawing.querySelectorAll('.object').forEach(g=>g.classList.toggle('selected',g.dataset.object===active))}});
drawing.addEventListener('dragover',e=>e.preventDefault());
drawing.addEventListener('drop',e=>{e.preventDefault();const q=point(e);add(e.dataTransfer.getData('text/plain'),q.x,q.y)});

function readPlan(raw){
  const pt=p=>Array.isArray(p)&&p.length===2&&p.every(Number.isFinite);
  const poly=p=>Array.isArray(p)&&p.length>=3&&p.length<=100&&p.every(pt);
  const id=x=>typeof x==='string'&&/^[A-Za-z0-9_-]{1,80}$/.test(x);
  const name=x=>typeof x==='string'&&x.trim().length&&x.length<=70;
  if(!poly(raw.outline)||!name(raw.title)||!Array.isArray(raw.rooms)||raw.rooms.length>30||
     raw.rooms.some(r=>!id(r?.id)||!name(r.name)||!poly(r.p)||!pt(r.tag))||
     !['walls','doors','windows'].every(k=>Array.isArray(raw[k])&&raw[k].length<=250&&raw[k].every(w=>pt(w?.a)&&pt(w?.b)))||
     !Array.isArray(raw.items)||raw.items.length>250||
     raw.items.some(o=>!id(o?.id)||!name(o.name)||!(Object.hasOwn(defs,o.type)||o.type==='scanned')||
       !['x','y','w','h','angle'].every(k=>Number.isFinite(o[k]))||o.w<=0||o.h<=0))
    throw new Error('导入文件不是有效的户型。');
  const itemIds=new Set(raw.items.map(o=>o.id)), roomIds=new Set(raw.rooms.map(r=>r.id));
  if(itemIds.size!==raw.items.length||roomIds.size!==raw.rooms.length)throw new Error('房间或物品编号重复。');
  return {...raw,key:'custom',items:raw.items.map(({mount,n,...o})=>{
    const base=make(o.id,o.type,o.x,o.y,o.angle,{name:o.name,w:o.w,h:o.h});
    for(const [k,domain] of Object.entries(defs[o.type]?.caps??{})){
      if(typeof domain[0]==='number'?Number.isFinite(o[k])&&o[k]>=domain[0]&&o[k]<=domain[1]:domain.includes(o[k]))base[k]=o[k];
    }
    return base;
  })};
}
$('#drawRoom').onclick=()=>setDrawing(drawKind==='room'?null:'room');
$('#drawWall').onclick=()=>setDrawing(drawKind==='wall'?null:'wall');
$('#undoDrawing').onclick=()=>{
  if(!undoGeometry)return;Object.assign(plan,undoGeometry);undoGeometry=null;
  $('#undoDrawing').disabled=true;setDrawing(null);changed();render();
};
$('#exportPlan').onclick=()=>{
  const url=URL.createObjectURL(new Blob([JSON.stringify(plan,null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download='floorplan.json';a.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
};
$('#itemSearch').oninput=renderInspect;
$('#itemType').onchange=renderInspect;
$('#climateForm').onsubmit=e=>{
  e.preventDefault();if(!backend)return;
  const f=e.target.elements;
  withServer(async()=>{await saveToServer();reflectFresh(await api.environment(plan.key,{climate:{season:f.season.value,indoor:+f.indoor.value,outdoor:+f.outdoor.value},delay:+f.delay.value}));});
};
function populateTypes(){
  $('#itemType').innerHTML='<option value="">全部</option>'+Object.entries(defs).map(([k,v])=>`<option value="${k}">${esc(v.name)}</option>`).join('')+'<option value="scanned">扫描物品</option>';
}
render();populateTypes();
api?.ready.then(async ready=>{
  if(!ready)return;
  backend=true;
  $('#connection').innerHTML='<i></i>已连接 · 设备模拟';
  $('#climatePanel').hidden=false;
  const defsFromServer=await api.types();Object.assign(defs,defsFromServer);
  populateTypes();
  const requested=new URLSearchParams(location.search).get('plan');
  dirty=false;await openPlan(['apple','house','custom'].includes(requested)?requested:'apple');
  setInterval(poll,850);
}).catch(reportErr);
