'use strict';
(() => {
  const el = id => document.getElementById(id);
  const viewport = el('viewport');
  const names = {living:'客厅',dining:'餐厅',kitchen:'厨房',hall:'走廊一',entry:'走廊二',bed:'卧室一',bed2:'卧室二',bed3:'卧室三',bed4:'卧室四',bath:'卫浴一',bath2:'卫浴二'};
  const categories = {
    sofa:['沙发','#5a8096'], table:['桌几','#c88e58'], storage:['储物柜','#788f73'],
    television:['电视','#4e596a'], oven:['烤箱','#675a86'], fireplace:['壁炉','#a85d51'],
    bed:['床','#8b789d'], chair:['椅子','#a37958'], sink:['洗手台','#69958e'],
    bathtub:['浴缸','#719d9b'], toilet:['坐便器','#8da5ae'], dishwasher:['洗碗机','#676d76']
  };
  try {
    const {THREE:T,SCAN_HOME:source}=window;
    const renderer=new T.WebGLRenderer({antialias:true,alpha:true});
    renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));
    renderer.shadowMap.enabled=true;
    renderer.shadowMap.type=T.PCFSoftShadowMap;
    renderer.toneMapping=T.ACESFilmicToneMapping;
    const canvas=renderer.domElement;
    canvas.tabIndex=0;
    canvas.setAttribute('aria-label','扫描户型。方向键移动视角，正号和负号缩放。');
    const scene=new T.Scene();
    const home=new T.Group(), thresholds=new T.Group(), objects=new T.Group();
    home.add(thresholds,objects);
    scene.add(home);
    const rooms=new Map();
    const counts=new Map();
    const roomOrder=Object.keys(names);
    const mat=(color)=>new T.MeshStandardMaterial({color,roughness:.86,side:T.DoubleSide,flatShading:true});
    const structure={floor:mat('#b8b9a4'),wall:mat('#e4e0d4'),door:mat('#b49f85'),window:mat('#97b1b6'),opening:mat('#e4e0d4')};
    const thresholdMat=mat('#b8b9a4');
    const vector=(p,y=0)=>new T.Vector3(p[0],y,p[1]);
    for(const entry of source.rooms){
      const bounds=new T.Box3();
      for(const part of entry.meshes){
        const geometry=new T.BufferGeometry();
        geometry.setAttribute('position',new T.Float32BufferAttribute(part.p,3));
        geometry.setIndex(part.i);
        geometry.computeVertexNormals();
        geometry.computeBoundingBox();
        const original=new T.Color().setRGB(...part.color,T.SRGBColorSpace);
        const tint=part.furniture&&categories[part.kind]?.[1];
        const mesh=new T.Mesh(geometry,part.furniture?mat(tint||original):structure[part.kind]||mat(original));
        mesh.name=part.name;
        mesh.castShadow=part.kind!=='floor';
        mesh.receiveShadow=true;
        mesh.userData={original,tint};
        if(part.furniture)counts.set(part.kind,(counts.get(part.kind)||0)+1);
        (part.furniture?objects:home).add(mesh);
        if(!part.furniture)bounds.union(geometry.boundingBox);
      }
      const floorBounds=new T.Box3().setFromPoints(entry.outline.map(p=>vector(p)));
      rooms.set(entry.id,{...entry,bounds,floorBounds,neighbors:new Map()});
    }
    const passage=new T.Mesh(new T.PlaneGeometry(1,1),new T.MeshBasicMaterial({color:'#367d69',side:T.DoubleSide,transparent:true,opacity:.83,depthWrite:false}));
    passage.visible=false;
    thresholds.add(passage);
    for(const door of source.portals){
      rooms.get(door.a).neighbors.set(door.b,door);
      rooms.get(door.b).neighbors.set(door.a,door);
      const tangent=vector(door.t);
      const a=vector(door.p,.013), b=vector(door.q,.013);
      const n=new T.Vector3(-tangent.z,0,tangent.x);
      if(n.dot(b.clone().sub(a))<0)n.negate();
      a.addScaledVector(n,-.075);
      b.addScaledVector(n,.075);
      const edge=door.w*.49;
      const corners=[a.clone().addScaledVector(tangent,-edge),a.clone().addScaledVector(tangent,edge),b.clone().addScaledVector(tangent,edge),b.clone().addScaledVector(tangent,-edge)];
      const g=new T.BufferGeometry().setFromPoints(corners);
      g.setIndex([0,1,2,0,2,3]);g.computeVertexNormals();
      const threshold=new T.Mesh(g,thresholdMat);
      threshold.receiveShadow=true;
      thresholds.add(threshold);
      door.mid=a.clone().lerp(b,.5);
      door.depth=a.distanceTo(b);
    }
    const legend=el('legend');
    for(const [kind,[label,color]] of Object.entries(categories)){
      if(!counts.has(kind))continue;
      const item=document.createElement('li');
      item.innerHTML=`<span class="swatch" style="--swatch:${color}" aria-hidden="true"></span><span>${label}</span><span class="count">${counts.get(kind)}</span>`;
      legend.append(item);
    }
    const bounds=new T.Box3();
    for(const r of rooms.values())bounds.union(r.bounds);
    const base=new T.Mesh(new T.PlaneGeometry(180,180),new T.ShadowMaterial({color:'#34444b',opacity:.34}));
    base.rotation.x=-Math.PI/2;base.position.y=-.177;base.receiveShadow=true;
    const sky=new T.HemisphereLight('#f5f6ff','#9c9786',1.5);
    scene.add(base,sky);
    const sun=new T.DirectionalLight('#fff5e5',2);
    sun.position.set(-6,21,10);sun.castShadow=true;
    sun.shadow.mapSize.set(1536,1536);
    Object.assign(sun.shadow.camera,{left:-17,right:17,top:17,bottom:-17,near:.25,far:50});
    sun.shadow.normalBias=.022;sun.shadow.bias=-.00012;
    sun.shadow.autoUpdate=false;sun.shadow.needsUpdate=true;
    scene.add(sun);
    const camera=new T.OrthographicCamera(-1,1,1,-1,.06,125);
    const ANGLE=33*Math.PI/180, YAW=.48;
    const params=new URLSearchParams(location.search);
    let plan=params.get('view')==='2d', selected=rooms.has(params.get('room'))?params.get('room'):null;
    let yaw3=YAW, tilt3=ANGLE, zoom=1, focusPoint=null, motion=null, pointer=null, installing=false;
    let bulbs=null, walker=null, walkMode=false, walkMotion=null, occupied=null, drawFrame=0;
    const reduced=matchMedia('(prefers-reduced-motion: reduce)');
    const liveRay=new T.Raycaster(), floorPlane=new T.Plane(new T.Vector3(0,1,0),0);
    const wrap=a=>Math.atan2(Math.sin(a),Math.cos(a));
    const aspect=()=>viewport.clientWidth/Math.max(1,viewport.clientHeight)||1;
    const logHeight=(w,h)=>Math.log(Math.max(h,w/aspect())/zoom);
    const layout=()=>{const r=rooms.get(selected);return r?.floorBounds||bounds;};
    const desired=()=>{
      const box=layout(), target=box.getCenter(new T.Vector3()), size=box.getSize(new T.Vector3());
      if(focusPoint)return {x:focusPoint.x,y:focusPoint.y,z:focusPoint.z,polar:1.31,yaw:yaw3,scale:logHeight(.35,.34),detail:1};
      const out={x:target.x,y:plan?0:.31,z:target.z,polar:plan?0:tilt3,yaw:plan?0:yaw3,detail:0};
      const pad=selected?2.15:2.55;
      const c=Math.abs(Math.cos(yaw3)),s=Math.abs(Math.sin(yaw3));
      out.scale=plan?logHeight(size.x+pad,size.z+pad):logHeight(size.x*c+size.z*s+pad,
        (size.x*s+size.z*c)*Math.cos(tilt3)+(selected?2.5:bounds.max.y)*Math.sin(tilt3)+pad);
      return out;
    };
    let state=desired();
    const target=new T.Vector3(), dampKeys=Object.keys(state), velocity=Object.fromEntries(dampKeys.map(k=>[k,0]));
    let goal=state, last=null, stiffness=11.5;
    function render(){
      if(drawFrame){cancelAnimationFrame(drawFrame);drawFrame=0;}
      if(!viewport.clientWidth||!viewport.clientHeight)return;
      const ratio=aspect(), half=Math.exp(state.scale)*.5;
      const {yaw,polar}=state, dist=38*Math.exp(state.detail*Math.log(2/38));
      const sin=Math.sin(polar),cos=Math.cos(polar);
      const relief=Math.min(1,Math.max(0,sin/Math.sin(ANGLE)));
      const shift=half*.14*relief*(1-state.detail);
      camera.top=half+shift;camera.bottom=-half+shift;camera.left=-half*ratio;camera.right=half*ratio;
      camera.updateProjectionMatrix();
      target.set(state.x,state.y,state.z);
      camera.position.set(Math.sin(yaw)*sin,cos,Math.cos(yaw)*sin).multiplyScalar(dist).add(target);
      // Orbit-basis up stays perpendicular even at exactly 90° overhead.
      camera.up.set(-Math.sin(yaw)*cos,sin,-Math.cos(yaw)*cos);
      camera.lookAt(target);
      base.material.opacity=.07+.17*relief;
      sun.intensity=.52+1.48*relief;
      sky.intensity=2.45-.95*relief;
      const showHome=state.detail<.92;
      if(home.visible!==showHome)sun.shadow.needsUpdate=true;
      home.visible=showHome;base.visible=showHome;
      bulbs?.updateMarkers(half*2/viewport.clientHeight,polar,state.detail);
      renderer.render(scene,camera);
    }
    function repaint(){if(!drawFrame)drawFrame=requestAnimationFrame(render);}
    function stop(){
      if(motion){cancelAnimationFrame(motion);motion=null;}
      last=null;
      for(const k of dampKeys)velocity[k]=0;
    }
    function tick(now){
      const dt=last===null?1/60:Math.min(.12,(now-last)/1000);
      last=now;
      let remaining=false;
      const decay=Math.exp(-stiffness*dt);
      for(const k of dampKeys){
        const offset=state[k]-goal[k], rate=velocity[k], step=(rate+stiffness*offset)*dt;
        state[k]=goal[k]+(offset+step)*decay;
        velocity[k]=(rate-stiffness*step)*decay;
        if(Math.abs(state[k]-goal[k])>.0006||Math.abs(velocity[k])>.004)remaining=true;
      }
      if(remaining)motion=requestAnimationFrame(tick);
      else{state={...goal};stop();}
      repaint();
    }
    function move({speed=11.5,keepTarget=false,scaleOnly=false}={}){
      const end=desired();
      if(keepTarget)Object.assign(end,{x:state.x,z:state.z});
      if(scaleOnly){
        // Wheel input only changes magnification, not the center of the view.
        const source=motion?goal:state;
        for(const k of dampKeys)if(k!=='scale')end[k]=source[k];
      }
      end.yaw=state.yaw+wrap(end.yaw-state.yaw);
      goal=end;stiffness=speed;
      if(reduced.matches){stop();state={...goal};render();return;}
      if(!motion)motion=requestAnimationFrame(tick);
    }
    function resize(){
      renderer.setSize(viewport.clientWidth,viewport.clientHeight,false);
      if(!motion){state.scale=desired().scale;render();}
      else goal.scale=desired().scale;
    }
    function updateURL(){
      const next=new URL(location.href);
      if(plan)next.searchParams.set('view','2d');else next.searchParams.delete('view');
      if(selected)next.searchParams.set('room',selected);else next.searchParams.delete('room');
      try{history.replaceState(null,'',next);}catch{}
    }
    const roomButtons=new Map();
    function button(id){
      const b=document.createElement('button');b.type='button';b.textContent=names[id];b.dataset.room=id;
      return b;
    }
    roomOrder.forEach(id=>{
      const b=button(id);roomButtons.set(id,b);
      b.onclick=()=>walkMode?walkToRoom(id):lookAtRoom(id);el('roomList').append(b);
    });
    function updateControls(){
      el('orbitView').setAttribute('aria-pressed',String(!plan));
      el('topView').setAttribute('aria-pressed',String(plan));
      el('wholeHome').setAttribute('aria-pressed',String(!selected));
      for(const [id,b] of roomButtons)b.setAttribute('aria-pressed',String(id===selected));
      const neighbors=rooms.get(selected)?.neighbors;
      el('adjacent').hidden=!neighbors?.size;
      el('roomLinks').replaceChildren(...(neighbors?[...neighbors].map(([id,door])=>{
        const b=button(id);b.onclick=()=>walkMode?walkToRoom(id):lookAtRoom(id,door);return b;
      }):[]));
    }
    function lookAtRoom(id,door){
      bulbs.cancel();bulbs.unfocus();
      selected=id;zoom=1;
      passage.visible=Boolean(door);
      if(door){
        passage.rotation.set(-Math.PI/2,0,Math.atan2(-door.t[1],door.t[0]));
        passage.position.copy(door.mid);passage.position.y=.018;
        passage.scale.set(door.w*.94,door.depth+.17,1);
      }
      updateControls();updateURL();
      move({speed:door?8.4:10.4});
    }
    function updatePerson(status){
      const b=el('walkToggle');
      b.setAttribute('aria-pressed',String(walkMode));
      b.textContent=walkMode?'退出行走':walker?.avatar.visible?'继续行走':'进入户型';
      const line=el('walkStatus');
      line.hidden=!walker?.avatar.visible;
      const label=occupied?names[occupied]:'门口';
      const text=status||'人物在'+label;
      if(!line.hidden&&line.textContent!==text)line.textContent=text;
    }
    function syncOccupancy(){
      if(!walker)return;
      const next=walker.room(walker.avatar.position,occupied);
      if(next&&next!==occupied){occupied=next;updatePerson();}
    }
    function stopWalking(){
      if(walkMotion){cancelAnimationFrame(walkMotion);walkMotion=null;}
      walker?.stride(0,0);
    }
    function beginWalk(path){
      if(!path||path.length<2){updatePerson('这里走不过去');return;}
      if(walkMotion)cancelAnimationFrame(walkMotion);
      const person=walker.avatar, segments=path.slice(1).map((p,i)=>p.distanceTo(path[i]));
      const length=segments.reduce((a,b)=>a+b,0);
      if(length<.045){stopWalking();updatePerson();repaint();return;}
      if(reduced.matches){person.position.copy(path.at(-1));stopWalking();syncOccupancy();updatePerson();repaint();return;}
      if(selected){selected=null;zoom=1;passage.visible=false;updateControls();updateURL();move({speed:9});}
      const requested=walker.room(path.at(-1));
      updatePerson(requested?'正在走向'+names[requested]:null);
      const pace=2.2, ramp=.24;
      const duration=length/pace+ramp;
      let lastTime=null, elapsed=0;
      let leg=0, done=0;
      const frame=now=>{
        const dt=lastTime===null?1/60:Math.min(.065,(now-lastTime)/1000);
        elapsed+=dt;lastTime=now;
        const t=Math.min(elapsed,duration), rampTime=Math.min(ramp,duration/2), speed=length/(duration-rampTime);
        const distance=t<rampTime?speed*t*t/(2*rampTime):t>duration-rampTime?
          length-speed*(duration-t)**2/(2*rampTime):speed*(t-rampTime/2);
        while(leg<segments.length-1&&distance>=done+segments[leg])done+=segments[leg++];
        const a=path[leg],b=path[leg+1],n=segments[leg];
        person.position.lerpVectors(a,b,Math.max(0,Math.min(1,n?(distance-done)/n:1)));
        const heading=Math.atan2(b.x-a.x,b.z-a.z);
        person.rotation.y+=wrap(heading-person.rotation.y)*(1-Math.exp(-dt*16));
        walker.stride(distance,Math.min(1,t/rampTime,(duration-t)/rampTime));
        syncOccupancy();
        if(t<duration)walkMotion=requestAnimationFrame(frame);
        else{walkMotion=null;person.position.copy(path.at(-1));syncOccupancy();updatePerson();}
        repaint();
      };
      walkMotion=requestAnimationFrame(frame);
    }
    function walkToRoom(id){
      if(walker&&walkMode)beginWalk(walker.roomPath(walker.avatar.position,id));
    }
    function walkToGround(event){
      const rect=canvas.getBoundingClientRect();
      liveRay.setFromCamera(new T.Vector2((event.clientX-rect.left)/rect.width*2-1,1-(event.clientY-rect.top)/rect.height*2),camera);
      const hit=liveRay.ray.intersectPlane(floorPlane,new T.Vector3());
      if(hit)beginWalk(walker.pointPath(walker.avatar.position,hit));
    }
    function toggleWalk(){
      if(walkMode){walkMode=false;stopWalking();updatePerson();repaint();return;}
      bulbs.cancel();bulbs.unfocus();
      if(!walker)walker=window.createRoomWalker(T,source,home);
      if(!walker.avatar.visible){
        walker.avatar.position.copy(walker.spawn);
        walker.avatar.visible=true;
        occupied=walker.room(walker.spawn);
        lookAtRoom(occupied);
      }
      walkMode=true;updatePerson();repaint();
    }
    function setView(value){
      if(plan===value&&!focusPoint)return;
      bulbs.clearPreview();bulbs.unfocus();
      plan=value;
      updateControls();updateURL();move();
    }
    viewport.prepend(canvas);el('fallback').hidden=true;
    const living=rooms.get('living');
    bulbs=window.createBulbInstaller(T,{scene,renderer,camera,footprint:living.outline,ground:.008,
      ceiling:living.bounds.max.y-.025,render,
      focus(point){if(point&&walkMode)toggleWalk();focusPoint=point;zoom=1;move({speed:11});},
      onPlacement(active){
        installing=active;
        if(active&&walkMode){walkMode=false;stopWalking();updatePerson();}
        if(active){
          selected='living';zoom=1;passage.visible=false;updateControls();updateURL();move({speed:12});
        }
      }
    });
    el('orbitView').onclick=()=>setView(false);
    el('topView').onclick=()=>setView(true);
    el('wholeHome').onclick=()=>lookAtRoom(null);
    el('walkToggle').onclick=toggleWalk;
    el('reset').onclick=()=>{
      bulbs.cancel();bulbs.unfocus();zoom=1;yaw3=YAW;tilt3=ANGLE;passage.visible=false;
      move({speed:12.5});
    };
    function finishes(){
      objects.visible=el('objects').checked;
      sun.shadow.needsUpdate=true;
      const color=el('colors');
      color.disabled=!objects.visible;
      legend.classList.toggle('is-muted',!color.checked||!objects.visible);
      for(const mesh of objects.children){
        const {original,tint}=mesh.userData;
        if(color.checked&&tint)mesh.material.color.set(tint);else mesh.material.color.copy(original);
      }
      render();
    }
    el('objects').onchange=finishes;
    el('colors').onchange=finishes;
    function scale(factor){
      zoom=Math.max(.52,Math.min(4,zoom*factor));
      move({speed:18,scaleOnly:true});
    }
    function drag(dx,dy){
      const wasMoving=!!motion;
      stop();
      if(plan&&!focusPoint){
        const perPixel=Math.exp(state.scale)/viewport.clientHeight;
        state.x-=dx*perPixel;state.z-=dy*perPixel;
        if(wasMoving&&(Math.abs(state.yaw)>.002||state.polar>.002)){
          const center={x:state.x,y:state.y,z:state.z,scale:state.scale};
          goal={...desired(),...center};stiffness=18;motion=requestAnimationFrame(tick);
        }
      }else{
        yaw3=state.yaw-dx*.008;
        state.yaw=yaw3;
        if(!focusPoint){tilt3=Math.max(.03,Math.min(1.42,state.polar-dy*.008));state.polar=tilt3;}
      }
      repaint();
    }
    canvas.addEventListener('pointerdown',e=>{
      if(e.button!==0||!e.isPrimary)return;
      pointer={x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY,id:e.pointerId,dragged:false};
      canvas.setPointerCapture(e.pointerId);
      bulbs.preview(e);
    });
    canvas.addEventListener('pointermove',e=>{
      if(pointer?.id!==e.pointerId){bulbs.preview(e);return;}
      if(!pointer.dragged&&Math.hypot(e.clientX-pointer.startX,e.clientY-pointer.startY)<5){bulbs.preview(e);return;}
      pointer.dragged=true;
      bulbs.clearPreview();
      drag(e.clientX-pointer.x,e.clientY-pointer.y);pointer.x=e.clientX;pointer.y=e.clientY;
    });
    canvas.addEventListener('pointerleave',bulbs.clearPreview);
    canvas.addEventListener('pointerup',e=>{
      if(pointer?.id!==e.pointerId||pointer.dragged||bulbs.place(e))return;
      if(walkMode&&!focusPoint&&!installing)walkToGround(e);else bulbs.pick(e);
    });
    canvas.addEventListener('lostpointercapture',()=>{pointer=null;});
    canvas.addEventListener('wheel',e=>{e.preventDefault();scale(Math.exp(-e.deltaY*.0012));},{passive:false});
    document.addEventListener('keydown',e=>{if(e.key==='Escape'){bulbs.cancel();if(walkMode)toggleWalk();}});
    canvas.addEventListener('keydown',e=>{
      if(bulbs.key(e))return;
      const moves={ArrowLeft:[-18,0],ArrowRight:[18,0],ArrowUp:[0,-18],ArrowDown:[0,18]};
      if(moves[e.key]){e.preventDefault();drag(...moves[e.key]);}
      else if(['+','=','-'].includes(e.key)){e.preventDefault();scale(e.key==='-'?.88:1.14);}
    });
    function fallback(error){
      if(error)console.warn('RoomPlan preview:',error);
      stop();stopWalking();
      canvas.hidden=true;el('fallback').hidden=false;
      viewport.setAttribute('aria-label','客厅模型静态预览');
      el('renderError').hidden=false;
      document.querySelectorAll('.workspace button,.workspace input').forEach(n=>{n.disabled=true;});
    }
    canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();fallback();});
    new ResizeObserver(resize).observe(viewport);
    updateControls();resize();
  }catch(error){
    console.warn('RoomPlan preview:',error);
    viewport.querySelector('canvas')?.remove();
    el('fallback').hidden=false;el('renderError').hidden=false;
    document.querySelectorAll('.workspace button,.workspace input').forEach(n=>{n.disabled=true;});
  }
})();
